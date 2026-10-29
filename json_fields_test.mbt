///|
test "JSON fields exact top-level mapping no fallback or nesting" {
  let fields = @cli.JsonFields::new(
    time="timestamp",
    level="severity",
    message="message",
  )
  let raw = "{\"timestamp\":\"2026-10-28T08:05:00Z\",\"severity\":\"ERROR\",\"message\":\"failed 42\",\"ts\":\"bad\",\"level\":\"INFO\",\"msg\":\"wrong\"}"
  let record = @cli.parse_line(raw, fields~)
  assert_eq(record.level, Error)
  assert_eq(record.message, "failed 42")
  assert_eq(record.minute, @cli.parse_time("2026-10-28 08:05:00Z"))
  assert_eq(@cli.parse_line(raw).level, Info)
  for
    invalid in [
      "{\"timestamp\":\"2026-10-28T08:05:00Z\",\"severity\":3,\"message\":\"x\"}",
      "{\"timestamp\":\"a\",\"timestamp\":\"b\",\"severity\":\"ERROR\",\"message\":\"x\"}",
      "{\"ts\":\"2026-10-28T08:05:00Z\",\"level\":\"ERROR\",\"msg\":\"x\"}", "{\"outer\":{\"timestamp\":\"x\",\"severity\":\"ERROR\",\"message\":\"x\"}}",
    ] {
    assert_eq(@cli.parse_line(invalid, fields~).level, Other)
  }
  let literal = @cli.JsonFields::new(
    time="a.b",
    level="级别",
    message="内容",
  )
  assert_eq(
    @cli.parse_line(
      "{\"a.b\":\"bad\",\"级别\":\"FATAL\",\"内容\":\"中文\"}",
      fields=literal,
    ).level,
    Fatal,
  )
  assert_eq(
    @cli.parse_line("2026-10-28 08:05:00 [ERROR] text", fields~).message,
    "text",
  )
}

///|
test "mapped JSON flows through aggregation ranking comparison and context" {
  let fields = @cli.JsonFields::new(
    time="timestamp",
    level="severity",
    message="message",
  )
  let config = @cli.Config::new(baseline_buckets=1, context=0)
  let analyzer = @cli.Analyzer::new(config, json_fields=fields)
  let lines = [
    "{\"timestamp\":\"2026-10-28T08:00:00Z\",\"severity\":\"INFO\",\"message\":\"healthy\"}",
    "{\"timestamp\":\"2026-10-28T08:05:00Z\",\"severity\":\"ERROR\",\"message\":\"failed 1\"}",
    "{\"timestamp\":\"2026-10-28T08:05:00Z\",\"severity\":\"ERROR\",\"message\":\"failed 2\"}",
    "{\"timestamp\":\"2026-10-28T08:05:00Z\",\"severity\":\"ERROR\",\"message\":\"failed 3\"}",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let a = analyzer.finish()
  assert_eq(a.spikes.length(), 1)
  assert_eq(a.log_error_ratio().fraction, Some(0.75))
  let signatures = @cli.SpikeSignatureCollector::new(a)
  let comparison = @cli.SignatureComparisonCollector::new(a, "ERROR: failed #")
  let contexts = @cli.ContextCollector::new(config)
  for raw in lines {
    ignore(signatures.feed(raw))
    comparison.feed(raw)
    contexts.feed(raw, a.is_target(raw, signature=Some("ERROR: failed #")))
  }
  assert_eq(signatures.signatures(0)[0].count, 3)
  assert_eq(comparison.comparisons()[0].spike_count, 3L)
  assert_eq(contexts.sampled(), 3)
  let windows = contexts
    .windows()
    .map(window => @cli.FileContextWindow::{ source: "input.jsonl", window, })
  let result = @cli.ReportResult::new(
    a,
    windows,
    contexts.sampled(),
    contexts.omitted(),
    signatures,
    Spikes,
    ["input.jsonl"],
  )
  let json = @json.parse(result.json_report())
  guard json is Object(object) else { fail("expected object") }
  assert_eq(object.get("json_fields"), Some(fields.to_json()))
  let untimed = "{\"timestamp\":\"bad\",\"severity\":\"ERROR\",\"message\":\"failed 4\"}"
  assert_true(a.is_target(untimed, mode=Errors))
  assert_eq(a.is_target(untimed), false)
}

///|
test "JSON field names reject duplicates blank control and excessive length" {
  for key in ["", "  ", "a\n", "x".repeat(257)] {
    let invalid = try {
      ignore(@cli.JsonFields::new(time=key))
      false
    } catch {
      _ => true
    }
    assert_true(invalid)
  }
  let duplicate = try {
    ignore(@cli.JsonFields::new(time="level"))
    false
  } catch {
    _ => true
  }
  assert_true(duplicate)
}
