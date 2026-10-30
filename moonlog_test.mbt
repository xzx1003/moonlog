///|
test "standard text and JSONL parse to normalized records" {
  let text = @cli.parse_line(
    "2026-10-28 08:15:30 [ERROR] database timeout retry=2",
  )
  assert_eq(text.level, Error)
  assert_eq(text.message, "database timeout retry=2")
  assert_eq(text.minute, @cli.parse_time("2026-10-28 08:15:00Z"))
  let json = @cli.parse_line(
    "{\"ts\":\"2026-10-28T08:15:30.123+00:00\",\"level\":\"FATAL\",\"msg\":\"write failed\"}",
  )
  assert_eq(json.level, Fatal)
  assert_eq(json.message, "write failed")
  assert_eq(json.minute, text.minute)
  assert_eq(@cli.parse_line("{bad json"), {
    minute: None,
    level: Other,
    message: "{bad json",
  })
  assert_eq(@cli.parse_line("stack frame at app.js:22").level, Other)
}

///|
test "time parser validates dates, fractions and offsets" {
  assert_eq(@cli.parse_time("2026-02-29 12:00:00"), None)
  assert_eq(
    @cli.parse_time("2024-02-29 12:00:00"),
    @cli.parse_time("2024-02-29T17:30:59+05:30"),
  )
  assert_eq(
    @cli.parse_time("2026-10-28 23:59:59Z").unwrap() + 1L,
    @cli.parse_time("2026-10-29 00:00:00+00:00").unwrap(),
  )
  assert_eq(
    @cli.format_time(@cli.parse_time("2026-10-28 23:59:00Z").unwrap()),
    "2026-10-28 23:59:00Z",
  )
  assert_eq(@cli.parse_time("2026-10-28 24:00:00"), None)
  assert_eq(@cli.parse_time("2026-10-28 10:00:00+99:00"), None)
  assert_eq(@cli.parse_time("2026-10-28 10:00:00+14:01"), None)
  assert_eq(
    @cli.parse_line("nonsense but with a timestamp-like area     [ERROR] boom").level,
    Other,
  )
}

///|
test "10,000 lines aggregate exactly into UTC five-minute buckets" {
  let base = @cli.parse_time("2026-10-28 00:00:00Z").unwrap()
  let analyzer = @cli.Analyzer::new(@cli.Config::new() catch { _ => panic() })
  for i in 0..<10000 {
    let minute = base + (i % 288 * 5).to_int64()
    let level = if i % 100 == 0 { "ERROR" } else { "INFO" }
    analyzer.feed("\{@cli.format_time(minute)} [\{level}] event-\{i}")
  }
  let result = analyzer.finish()
  assert_eq(result.total, 10000)
  assert_eq(result.matched, 10000)
  assert_eq(result.buckets.length(), 288)
  assert_eq(
    result.buckets.map(fn(b) { b.total }).fold(init=0L, fn(sum, n) { sum + n }),
    10000,
  )
  assert_eq(
    result.buckets.map(fn(b) { b.errors }).fold(init=0L, fn(sum, n) { sum + n }),
    100,
  )
  assert_eq(result.counts.get_or_default("ERROR", 0), 100)
  assert_eq(result.counts.get_or_default("INFO", 0), 9900)
}

///|
test "spikes use the previous complete rolling baseline and merge buckets" {
  let base = @cli.parse_time("2026-10-28 08:00:00Z").unwrap()
  let analyzer = @cli.Analyzer::new(
    @cli.Config::new(min_errors=3) catch {
      _ => panic()
    },
  )
  for
    (bucket, count) in [
      (0, 1),
      (1, 1),
      (2, 1),
      (3, 1),
      (4, 1),
      (5, 1),
      (6, 4),
      (7, 5),
      (8, 1),
    ] {
    for j in 0..<count {
      analyzer.feed(
        "\{@cli.format_time(base + (bucket * 5).to_int64())} [ERROR] database timeout retry=\{j}",
      )
    }
  }
  let result = analyzer.finish()
  assert_eq(result.spikes.length(), 1)
  let spike = result.spikes[0]
  assert_eq(spike.start, base + 30L)
  assert_eq(spike.end, base + 40L)
  assert_eq(spike.errors, 9)
  assert_eq(spike.peak_errors, 5)
  assert_eq(spike.baseline, 1.0)
  assert_true(
    result.is_target("\{@cli.format_time(base + 35L)} [ERROR] another failure"),
  )
  assert_false(
    result.is_target("\{@cli.format_time(base + 40L)} [ERROR] after incident"),
  )
}

///|
test "zero baseline requires the configured minimum and warmup is respected" {
  let base = @cli.parse_time("2026-10-28 08:00:00Z").unwrap()
  let analyzer = @cli.Analyzer::new(@cli.Config::new() catch { _ => panic() })
  for
    (bucket, count) in [
      (0, 2),
      (1, 0),
      (2, 0),
      (3, 0),
      (4, 0),
      (5, 0),
      (6, 2),
      (7, 3),
    ] {
    for _ in 0..<count {
      analyzer.feed(
        "\{@cli.format_time(base + (bucket * 5).to_int64())} [ERROR] outage",
      )
    }
  }
  let result = analyzer.finish()
  assert_eq(result.spikes.length(), 1)
  assert_eq(result.spikes[0].start, base + 35L)
  assert_eq(result.spikes[0].errors, 3)
}

///|
test "ring buffer returns exact previous ten lines" {
  let ring = @cli.RingBuffer::new(10)
  for i in 1..<=15 {
    ring.push({ number: i.to_int64(), text: "line-\{i}", })
  }
  let before = ring.snapshot()
  assert_eq(before.length(), 10)
  assert_eq(before[0], { number: 6, text: "line-6", })
  assert_eq(before[9], { number: 15, text: "line-15", })
}

///|
test "context includes target and ten following lines at EOF" {
  let config = @cli.Config::new() catch { _ => panic() }
  let collector = @cli.ContextCollector::new(config)
  for i in 1..<=20 {
    collector.feed("line-\{i}", i == 12)
  }
  assert_eq(collector.sampled(), 1)
  let windows = collector.windows()
  assert_eq(windows.length(), 1)
  assert_eq(windows[0].lines.length(), 19)
  assert_eq(windows[0].lines[0].number, 2)
  assert_eq(windows[0].lines[18].number, 20)
  assert_eq(windows[0].targets, [12])
}

///|
test "overlapping error windows merge while targets remain marked" {
  let collector = @cli.ContextCollector::new(
    @cli.Config::new(context=3) catch {
      _ => panic()
    },
  )
  for i in 1..<=30 {
    collector.feed("line-\{i}", i == 12 || i == 15)
  }
  let windows = collector.windows()
  assert_eq(windows.length(), 1)
  assert_eq(windows[0].lines[0].number, 9)
  assert_eq(windows[0].lines.last().unwrap().number, 18)
  assert_eq(windows[0].targets, [12, 15])
}

///|
test "filters apply to summary and include explicit timestamp rules" {
  let start = @cli.parse_time("2026-10-28 08:00:00Z").unwrap()
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "timeout",
    from: Some(start),
    to: Some(start + 5L),
  }
  let analyzer = @cli.Analyzer::new(
    @cli.Config::new() catch {
      _ => panic()
    },
    filter~,
  )
  analyzer.feed("2026-10-28 08:01:00Z [ERROR] timeout")
  analyzer.feed("2026-10-28 08:02:00Z [ERROR] other")
  analyzer.feed("2026-10-28 08:03:00Z [INFO] timeout")
  analyzer.feed("2026-10-28 08:06:00Z [ERROR] timeout outside")
  let result = analyzer.finish()
  assert_eq(result.total, 4)
  assert_eq(result.matched, 1)
  assert_eq(result.counts.get_or_default("ERROR", 0), 1)
}

///|
test "context sample cap stays bounded and counts omitted targets" {
  let collector = @cli.ContextCollector::new(
    @cli.Config::new(max_samples=2, context=1) catch {
      _ => panic()
    },
  )
  for i in 1..<=50 {
    collector.feed("line-\{i}", i % 2 == 0)
  }
  assert_eq(collector.sampled(), 2)
  assert_eq(collector.omitted(), 23)
  assert_eq(collector.windows().length(), 1)
  assert_eq(collector.windows()[0].targets, [2, 4])
}

///|
test "context gives exactly 21 lines with target excluded from radius" {
  let c = @cli.ContextCollector::new(@cli.Config::new())
  for i in 1..<=50 {
    c.feed("line-\{i}", i == 25)
  }
  let w = c.windows()[0]
  assert_eq(w.lines.length(), 21)
  assert_eq(w.lines[0].number, 15)
  assert_eq(w.lines[10].number, 25)
  assert_eq(w.lines[20].number, 35)
}

///|
test "file start truncates context and zero radius keeps only target" {
  let c = @cli.ContextCollector::new(@cli.Config::new())
  c.feed("first", true)
  c.feed("second", false)
  assert_eq(c.windows()[0].lines.length(), 2)
  assert_eq(c.windows()[0].lines[0].number, 1)
  let zero = @cli.ContextCollector::new(@cli.Config::new(context=0))
  for i in 1..<=20 {
    zero.feed("x", i == 10)
  }
  assert_eq(zero.windows()[0].lines.length(), 1)
  assert_eq(zero.windows()[0].lines[0].number, 10)
  let disabled = @cli.ContextCollector::new(@cli.Config::new(max_samples=0))
  disabled.feed("error", true)
  assert_eq(disabled.windows().length(), 0)
  assert_eq(disabled.omitted(), 1)
}

///|
test "context merges windows bridged by a later target without duplicating lines" {
  let c = @cli.ContextCollector::new(@cli.Config::new(context=2))
  for i in 1..<=30 {
    c.feed("line-\{i}", i == 10 || i == 15 || i == 25)
  }
  assert_eq(c.windows().length(), 2)
  assert_eq(c.windows()[0].lines.map(fn(l) { l.number }), [
    8, 9, 10, 11, 12, 13, 14, 15, 16, 17,
  ])
  assert_eq(c.windows()[1].lines.map(fn(l) { l.number }), [23, 24, 25, 26, 27])
}

///|
test "strictly three times baseline does not trigger" {
  let c = @cli.Config::new(baseline_buckets=2)
  let buckets : Array[@cli.Bucket] = [
    { start: 0L, total: 1, errors: 1, },
    { start: 5L, total: 1, errors: 1, },
    { start: 10L, total: 3, errors: 3, },
    { start: 15L, total: 7, errors: 7, },
  ]
  let spikes = @cli.detect_spikes(buckets, c)
  assert_eq(spikes.length(), 1)
  assert_eq(spikes[0].start, 15L)
  assert_eq(spikes[0].end, 20L)
  assert_eq(spikes[0].baseline, 2.0)
}

///|
test "out-of-order logs, empty buckets and exact bucket boundaries" {
  let a = @cli.Analyzer::new(@cli.Config::new(baseline_buckets=2))
  a.feed("2026-10-29 00:05:00 [ERROR] x")
  a.feed("2026-10-28 23:55:00 [INFO] x")
  a.feed("2026-10-29 00:04:59 [ERROR] x")
  let r = a.finish()
  assert_eq(r.buckets.length(), 3)
  assert_eq(r.buckets.map(fn(b) { b.total }), [1, 1, 1])
  let b = @cli.Analyzer::new(@cli.Config::new())
  b.feed("2026-10-28 08:00:00 [INFO] start")
  b.feed("2026-10-28 08:30:00 [ERROR] x")
  let filled = b.finish()
  assert_eq(filled.buckets.length(), 7)
  assert_eq(filled.buckets[1].total, 0)
  assert_eq(filled.buckets[5].errors, 0)
  assert_eq(filled.spikes.length(), 0)
  b.feed("2026-10-28 08:30:01 [FATAL] x")
  b.feed("2026-10-28 08:30:02 [ERROR] x")
  let high = b.finish()
  assert_eq(high.spikes.length(), 1)
  assert_eq(high.spikes[0].baseline, 0.0)
  assert_eq(high.spikes[0].errors, 3)
}

///|
test "empty input and unrecognized lines have honest counts" {
  let a = @cli.Analyzer::new(@cli.Config::new())
  let empty = a.finish()
  assert_eq(empty.total, 0)
  assert_eq(empty.spikes.length(), 0)
  a.feed("")
  a.feed("stack trace")
  a.feed("{bad json}")
  a.feed("{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"x\"}")
  let r = a.finish()
  assert_eq(r.total, 4)
  assert_eq(r.matched, 4)
  assert_eq(r.untimed, 4)
  assert_eq(r.counts.get_or_default("OTHER", 0), 3)
  assert_eq(r.counts.get_or_default("ERROR", 0), 1)
  assert_eq(r.buckets.length(), 0)
}

///|
test "level comes only from the declared field, JSON message may contain level tokens" {
  assert_eq(
    @cli.parse_line("2026-10-28 08:00:00 [ERROR] turn DEBUG off").level,
    Error,
  )
  assert_eq(
    @cli.parse_line(
      "{\"ts\":\"2026-10-28T08:00:00Z\",\"level\":\"ERROR\",\"msg\":\" [DEBUG] text\"}",
    ).level,
    Error,
  )
  assert_eq(
    @cli.parse_line(
      "{\"ts\":\"2026-10-28T08:00:00Z\",\"level\":\"INFO\",\"level\":\"ERROR\",\"msg\":\"x\"}",
    ).level,
    Other,
  )
  assert_eq(@cli.parse_line("2026-10-28 08:00:00 [ERROR]x").level, Other)
}

///|
test "signature and bucket caps fail or count overflow instead of growing indefinitely" {
  let a = @cli.Analyzer::new(@cli.Config::new(max_signatures=1, max_buckets=2))
  a.feed("2026-10-28 08:00:00 [ERROR] timeout 123")
  a.feed("2026-10-28 08:00:00 [ERROR] timeout 456")
  a.feed("2026-10-28 08:00:00 [ERROR] disk full")
  let r = a.finish()
  assert_eq(r.signatures.length(), 1)
  assert_eq(r.signatures[0].text, "ERROR: timeout #")
  assert_eq(r.signatures[0].count, 2)
  assert_eq(r.overflow_signatures, 1)
  let mut rejected = false
  a.feed("2026-10-28 08:10:00 [INFO] far") catch {
    _ => rejected = true
  }
  assert_true(rejected)
}

///|
test "configuration rejects invalid ranges" {
  let mut rejected = false
  ignore(@cli.Config::new(bucket_minutes=0)) catch {
    _ => rejected = true
  }
  assert_true(rejected)
  rejected = false
  ignore(@cli.Config::new(baseline_buckets=0)) catch {
    _ => rejected = true
  }
  assert_true(rejected)
  rejected = false
  ignore(@cli.Config::new(context=101)) catch {
    _ => rejected = true
  }
  assert_true(rejected)
}

///|
test "filter preserves untimed lines only without a time filter" {
  let untimed : @cli.Record = {
    minute: None,
    level: Error,
    message: "timeout",
  }
  assert_true(@cli.Filter::new().accepts(untimed))
  let f : @cli.Filter = {
    level: None,
    keyword: "time",
    from: Some(0L),
    to: None,
  }
  assert_false(f.accepts(untimed))
}

///|
test "report is deterministic and raw backticks cannot close context fences" {
  let cfg = @cli.Config::new(baseline_buckets=1)
  let a = @cli.Analyzer::new(cfg)
  a.feed("2026-10-28 08:00:00 [INFO] ready")
  for _ in 0..<3 {
    a.feed("2026-10-28 08:05:00 [ERROR] `<script>|` 123")
  }
  let analysis = a.finish()
  let contexts = @cli.ContextCollector::new(cfg)
  contexts.feed("```", true)
  contexts.feed("<script>alert(1)</script>", false)
  let spike_signatures = @cli.SpikeSignatureCollector::new(analysis)
  for _ in 0..<3 {
    ignore(spike_signatures.feed("2026-10-28 08:05:00 [ERROR] `<script>|` 123"))
  }
  let windows = contexts
    .windows()
    .map(w => ({ source: "file[1].log", window: w, } : @cli.FileContextWindow))
  let first = @cli.markdown_report(
    analysis,
    windows,
    contexts.sampled(),
    contexts.omitted(),
    spike_signatures,
    @cli.ContextMode::Spikes,
    ["file[1].log"],
  )
  assert_eq(
    first,
    @cli.markdown_report(
      analysis,
      windows,
      contexts.sampled(),
      contexts.omitted(),
      spike_signatures,
      @cli.ContextMode::Spikes,
      ["file[1].log"],
    ),
  )
  assert_true(first.contains("````text"))
  assert_true(first.contains("&lt;script&gt;&#124;"))
  assert_true(first.contains("Target source lines: 1"))
  assert_true(first.contains("## Error signatures by spike"))
  assert_true(first.contains("### Spike 1:"))
  assert_true(first.contains("- Context mode: spikes"))
}

///|
test "level and keyword filters retain the observed healthy time baseline" {
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "timeout",
    from: None,
    to: None,
  }
  let a = @cli.Analyzer::new(@cli.Config::new(), filter~)
  a.feed("2026-10-28 08:00:00 [INFO] ready")
  for _ in 0..<3 {
    a.feed("2026-10-28 08:30:00 [ERROR] timeout")
  }
  let r = a.finish()
  assert_eq(r.matched, 3)
  assert_eq(r.buckets.length(), 7)
  assert_eq(r.buckets[0].total, 0)
  assert_eq(r.spikes.length(), 1)
  assert_eq(r.spikes[0].baseline, 0.0)
}

///|
test "spike signatures separate incidents and exclude baseline and end boundary" {
  let config = @cli.Config::new(baseline_buckets=1, min_errors=3)
  let analyzer = @cli.Analyzer::new(config)
  let lines = [
    "2026-10-28 00:00:00 [INFO] healthy", "2026-10-28 00:05:00 [ERROR] timeout 1",
    "2026-10-28 00:05:00 [ERROR] timeout 2", "2026-10-28 00:05:00 [FATAL] crashed",
    "2026-10-28 00:10:00 [ERROR] baseline noise", "2026-10-28 00:15:00 [ERROR] payment",
    "2026-10-28 00:15:00 [ERROR] payment", "2026-10-28 00:15:00 [ERROR] payment",
    "2026-10-28 00:15:00 [ERROR] payment",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  assert_eq(analysis.spikes.length(), 2)
  let collector = @cli.SpikeSignatureCollector::new(analysis)
  // Feed in reverse order to check that lookup does not assume sorted input.
  for i = lines.length() - 1; i >= 0; i = i - 1 {
    assert_eq(collector.feed(lines[i]), analysis.is_target(lines[i]))
  }
  let first = collector.signatures(0)
  assert_eq(first.length(), 2)
  assert_eq(first[0].text, "ERROR: timeout #")
  assert_eq(first[0].count, 2)
  assert_eq(first[1].text, "FATAL: crashed")
  assert_eq(collector.signatures(1)[0].text, "ERROR: payment")
  assert_eq(collector.signatures(1)[0].count, 4)
  assert_eq(collector.omitted(0), 0)
  assert_eq(collector.omitted(1), 0)
}

///|
test "spike signature shared budget counts omissions and retained repeats" {
  let config = @cli.Config::new(baseline_buckets=1, max_signatures=1)
  let analyzer = @cli.Analyzer::new(config)
  let lines = [
    "2026-10-28 00:00:00 [INFO] healthy", "2026-10-28 00:05:00 [ERROR] a", "2026-10-28 00:05:00 [ERROR] b",
    "2026-10-28 00:05:00 [ERROR] a", "2026-10-28 00:10:00 [INFO] healthy", "2026-10-28 00:15:00 [ERROR] a",
    "2026-10-28 00:15:00 [ERROR] a", "2026-10-28 00:15:00 [ERROR] a",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  let collector = @cli.SpikeSignatureCollector::new(analysis)
  for raw in lines {
    ignore(collector.feed(raw))
  }
  assert_eq(collector.signatures(0).length(), 1)
  assert_eq(collector.signatures(0)[0].count, 2)
  assert_eq(collector.omitted(0), 1)
  assert_eq(collector.signatures(1).length(), 0)
  assert_eq(collector.omitted(1), 3)
}

///|
test "spike signatures apply filters and deterministic tie ordering" {
  let config = @cli.Config::new(baseline_buckets=1)
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "keep",
    from: None,
    to: None,
  }
  let analyzer = @cli.Analyzer::new(config, filter~)
  let lines = [
    "2026-10-28 00:00:00 [INFO] healthy", "2026-10-28 00:05:00 [ERROR] keep z", "2026-10-28 00:05:00 [ERROR] keep a",
    "2026-10-28 00:05:00 [ERROR] keep b", "2026-10-28 00:05:00 [ERROR] discard",
    "2026-10-28 00:05:00 [FATAL] keep fatal",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  let collector = @cli.SpikeSignatureCollector::new(analysis)
  for raw in lines {
    ignore(collector.feed(raw))
  }
  let signatures = collector.signatures(0)
  assert_eq(signatures.length(), 3)
  assert_eq(signatures[0].text, "ERROR: keep a")
  assert_eq(signatures[1].text, "ERROR: keep b")
  assert_eq(signatures[2].text, "ERROR: keep z")
  assert_eq(collector.feed("stack trace without timestamp"), false)
  let empty = @cli.SpikeSignatureCollector::new(
    @cli.Analyzer::new(config).finish(),
  )
  assert_eq(empty.feed(lines[1]), false)
}

///|
test "errors context mode works without spikes and keeps physical neighbors" {
  let config = @cli.Config::new(context=1, max_samples=1)
  let analyzer = @cli.Analyzer::new(config)
  let lines = [
    "2026-10-28 08:00:00 [INFO] before", "2026-10-28 08:01:00 [ERROR] failed", "stack frame without timestamp",
    "2026-10-28 08:02:00 [FATAL] crashed",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  assert_eq(analysis.spikes.length(), 0)
  let contexts = @cli.ContextCollector::new(config)
  for raw in lines {
    assert_eq(analysis.is_target(raw), false)
    contexts.feed(raw, analysis.is_target(raw, mode=Errors))
  }
  assert_eq(contexts.sampled(), 1)
  assert_eq(contexts.omitted(), 1)
  assert_eq(contexts.windows().length(), 1)
  assert_eq(contexts.windows()[0].targets, [2])
  assert_eq(contexts.windows()[0].lines.map(line => line.number), [1, 2, 3])
  assert_eq(contexts.windows()[0].lines[2].text, lines[2])
}

///|
test "errors context mode honors level keyword and inclusive time bounds" {
  let config = @cli.Config::new()
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "keep",
    from: @cli.parse_time("2026-10-28 08:00:00Z"),
    to: @cli.parse_time("2026-10-28 08:05:00Z"),
  }
  let analysis = @cli.Analyzer::new(config, filter~).finish()
  for
    raw in [
      "2026-10-28 08:00:00 [ERROR] keep", "2026-10-28 08:05:00 [ERROR] keep",
    ] {
    assert_true(analysis.is_target(raw, mode=Errors))
  }
  for
    raw in [
      "2026-10-28 07:59:00 [ERROR] keep", "2026-10-28 08:06:00 [ERROR] keep", "2026-10-28 08:01:00 [FATAL] keep",
      "2026-10-28 08:01:00 [INFO] keep", "2026-10-28 08:01:00 [ERROR] discard", "{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"keep\"}",
    ] {
    assert_eq(analysis.is_target(raw, mode=Errors), false)
  }
}

///|
test "errors context accepts untimed JSON errors without time bounds" {
  let analysis = @cli.Analyzer::new(@cli.Config::new()).finish()
  let raw = "{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"failed\"}"
  assert_true(analysis.is_target(raw, mode=Errors))
  assert_eq(analysis.is_target(raw), false)
  assert_eq(analysis.is_target("stack frame", mode=Errors), false)
  assert_eq(@cli.ContextMode::Spikes.label(), "spikes")
  assert_eq(@cli.ContextMode::Errors.label(), "errors")
}
