///|
test "signature comparison uses full baseline duration and exclusive boundaries" {
  let config = @cli.Config::new(baseline_buckets=2)
  let analyzer = @cli.Analyzer::new(config)
  let lines = [
    "2026-10-28 08:00:00 [ERROR] timeout 1", "2026-10-28 08:05:00 [INFO] healthy",
    "2026-10-28 08:10:00 [ERROR] timeout 2", "2026-10-28 08:10:00 [ERROR] timeout 3",
    "2026-10-28 08:10:00 [ERROR] timeout 4", "2026-10-28 08:15:00 [ERROR] timeout 5",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  assert_eq(analysis.spikes.length(), 1)
  let c = @cli.SignatureComparisonCollector::new(analysis, "ERROR: timeout #")
  for i = lines.length() - 1; i >= 0; i = i - 1 {
    c.feed(lines[i])
  }
  let comparison = c.comparisons()[0]
  assert_eq(comparison.before_minutes, 10L)
  assert_eq(comparison.spike_minutes, 5L)
  assert_eq(comparison.before_count, 1L)
  assert_eq(comparison.spike_count, 3L)
  assert_eq(comparison.before_per_minute, 0.1)
  assert_eq(comparison.spike_per_minute, 0.6)
  assert_true(comparison.rate_multiplier.unwrap() > 5.99)
  assert_true(@json.valid(comparison.to_json().stringify()))
}

///|
test "exact signature context filtering preserves error mode and level prefix" {
  let a = @cli.Analyzer::new(@cli.Config::new()).finish()
  let raw = "2026-10-28 08:00:00 [ERROR] timeout 123"
  assert_true(a.is_target(raw, mode=Errors, signature=Some("ERROR: timeout #")))
  assert_eq(a.is_target(raw, mode=Errors, signature=Some("timeout")), false)
  assert_eq(a.is_target(raw, signature=Some("ERROR: timeout #")), false)
  assert_eq(
    a.is_target(
      "2026-10-28 08:00:00 [FATAL] timeout 123",
      mode=Errors,
      signature=Some("ERROR: timeout #"),
    ),
    false,
  )
  let contexts = @cli.ContextCollector::new(@cli.Config::new(context=1))
  let lines = ["before", raw, "other error as unfiltered neighbor"]
  for line in lines {
    contexts.feed(
      line,
      a.is_target(line, mode=Errors, signature=Some("ERROR: timeout #")),
    )
  }
  assert_eq(contexts.sampled(), 1)
  assert_eq(contexts.windows()[0].lines.length(), 3)
}

///|
test "comparison windows are left-closed and right-open on minute boundaries" {
  let config = @cli.Config::new(
    bucket_minutes=1,
    baseline_buckets=5,
    min_errors=2,
  )
  let lines = [
    "2026-10-28 07:59:00 [ERROR] sig 9", "2026-10-28 08:00:00 [ERROR] sig 1", "2026-10-28 08:04:00 [ERROR] sig 2",
    "2026-10-28 08:05:00 [ERROR] sig 3", "2026-10-28 08:05:00 [ERROR] sig 4", "2026-10-28 08:06:00 [ERROR] sig 5",
    "2026-10-28 08:07:00 [INFO] end",
  ]
  let analyzer = @cli.Analyzer::new(config)
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  assert_eq(analysis.spikes.length(), 1)
  let collector = @cli.SignatureComparisonCollector::new(
    analysis, "ERROR: sig #",
  )
  for raw in lines {
    collector.feed(raw)
  }
  let comparison = collector.comparisons()[0]
  // 07:59 sits before the window and 08:06 sits on the exclusive spike end.
  assert_eq(
    comparison.before_start,
    @cli.parse_time("2026-10-28 08:00:00Z").unwrap(),
  )
  assert_eq(
    comparison.spike_start,
    @cli.parse_time("2026-10-28 08:05:00Z").unwrap(),
  )
  assert_eq(
    comparison.spike_end,
    @cli.parse_time("2026-10-28 08:06:00Z").unwrap(),
  )
  assert_eq(comparison.before_minutes, 5L)
  assert_eq(comparison.spike_minutes, 1L)
  assert_eq(comparison.before_count, 2L)
  assert_eq(comparison.spike_count, 2L)
  assert_eq(comparison.before_per_minute, 0.4)
  assert_eq(comparison.spike_per_minute, 2.0)
  let multiplier = comparison.rate_multiplier.unwrap()
  assert_true(multiplier > 4.99 && multiplier < 5.01)
}

///|
test "window length follows bucket size and baseline buckets" {
  let lines = [
    "2026-10-28 07:59:00 [ERROR] sig 9", "2026-10-28 08:00:00 [ERROR] sig 1", "2026-10-28 08:04:00 [ERROR] sig 2",
    "2026-10-28 08:05:00 [ERROR] sig 3", "2026-10-28 08:05:00 [ERROR] sig 4", "2026-10-28 08:06:00 [ERROR] sig 5",
  ]
  let short = @cli.Config::new(
    bucket_minutes=1,
    baseline_buckets=3,
    min_errors=2,
  )
  let analyzer = @cli.Analyzer::new(short)
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  assert_eq(analysis.spikes.length(), 1)
  let collector = @cli.SignatureComparisonCollector::new(
    analysis, "ERROR: sig #",
  )
  for raw in lines {
    collector.feed(raw)
  }
  let comparison = collector.comparisons()[0]
  assert_eq(comparison.before_minutes, 3L)
  assert_eq(comparison.spike_minutes, 1L)
  assert_eq(comparison.before_count, 1L)
  assert_eq(comparison.spike_count, 2L)
  assert_eq(
    comparison.before_start,
    @cli.parse_time("2026-10-28 08:02:00Z").unwrap(),
  )
  let multiplier = comparison.rate_multiplier.unwrap()
  assert_true(multiplier > 5.99 && multiplier < 6.01)
}

///|
test "time filter removes pre-spike occurrences from the comparison only" {
  let lines = [
    "2026-10-28 08:00:00 [ERROR] sig 1", "2026-10-28 08:04:00 [INFO] keep", "2026-10-28 08:05:00 [ERROR] sig 2",
    "2026-10-28 08:05:00 [ERROR] sig 3", "2026-10-28 08:05:00 [ERROR] other 7", "2026-10-28 08:06:00 [INFO] end",
  ]
  let config = @cli.Config::new(baseline_buckets=1, multiplier=2, min_errors=2)
  let unfiltered = @cli.Analyzer::new(config)
  for raw in lines {
    unfiltered.feed(raw)
  }
  let open = unfiltered.finish()
  assert_eq(open.spikes.length(), 1)
  let all = @cli.SignatureComparisonCollector::new(open, "ERROR: sig #")
  for raw in lines {
    all.feed(raw)
  }
  assert_eq(all.comparisons()[0].before_count, 1L)
  assert_eq(all.comparisons()[0].spike_count, 2L)
  assert_true(all.comparisons()[0].rate_multiplier is Some(_))
  let filter : @cli.Filter = {
    level: None,
    keyword: "",
    from: @cli.parse_time("2026-10-28 08:03:00Z"),
    to: None,
  }
  let filtered = @cli.Analyzer::new(config, filter~)
  for raw in lines {
    filtered.feed(raw)
  }
  let bounded = filtered.finish()
  assert_eq(bounded.spikes.length(), 1)
  assert_eq(bounded.spikes[0].start, open.spikes[0].start)
  assert_eq(bounded.spikes[0].end, open.spikes[0].end)
  let scoped = @cli.SignatureComparisonCollector::new(bounded, "ERROR: sig #")
  for raw in lines {
    scoped.feed(raw)
  }
  let comparison = scoped.comparisons()[0]
  // The 08:00 occurrence is inside the window but outside the time filter.
  assert_eq(comparison.before_count, 0L)
  assert_eq(comparison.spike_count, 2L)
  assert_eq(comparison.rate_multiplier, None)
}

///|
test "report shows the selection, escapes it and states a zero baseline" {
  let lines = [
    "2026-10-28 08:00:00 [INFO] healthy", "2026-10-28 08:05:00 [ERROR] `<x>`|sig 1",
    "2026-10-28 08:05:00 [ERROR] `<x>`|sig 2",
  ]
  let config = @cli.Config::new(baseline_buckets=1, context=0, min_errors=2)
  let signature = "ERROR: `<x>`|sig #"
  let result = completed_result(lines, config, signature=Some(signature))
  let analysis = @cli.Analyzer::new(config)
  for raw in lines {
    analysis.feed(raw)
  }
  let report = @cli.markdown_report(
    analysis.finish(),
    [],
    0,
    0,
    @cli.SpikeSignatureCollector::new(analysis.finish()),
    @cli.ContextMode::Spikes,
    ["input.log"],
    selected_signature=Some(signature),
    signature_comparisons=result.signature_comparisons,
  )
  assert_true(report.contains("## Selected signature comparison"))
  assert_true(
    report.contains(
      "Selected signature: `ERROR: &#96;&lt;x&gt;&#96;&#124;sig \\#`",
    ),
  )
  assert_true(report.contains("left-closed and right-open"))
  assert_true(report.contains("not a healthy window"))
  assert_true(
    report.contains(
      "| Pre-spike baseline | 2026-10-28 08:00:00Z | 2026-10-28 08:05:00Z | 5 | 0 | 0.000 |",
    ),
  )
  assert_true(
    report.contains(
      "| Spike | 2026-10-28 08:05:00Z | 2026-10-28 08:10:00Z | 5 | 2 | 0.400 |",
    ),
  )
  assert_true(report.contains("Rate multiplier: N/A"))
  assert_true(report.contains("undefined, not zero"))
  assert_false(
    report.contains("No spikes met the rule, so there is no comparison window"),
  )
  let plain = @cli.markdown_report(
    analysis.finish(),
    [],
    0,
    0,
    @cli.SpikeSignatureCollector::new(analysis.finish()),
    @cli.ContextMode::Spikes,
    ["input.log"],
  )
  assert_false(plain.contains("## Selected signature comparison"))
}

///|
test "spikeless selection explains the absence without denying failures" {
  let config = @cli.Config::new()
  let result = completed_result(
    ["2026-10-28 08:00:00 [ERROR] other 1"],
    config,
    signature=Some("ERROR: sig #"),
  )
  assert_eq(result.signature_comparisons.length(), 0)
  assert_eq(result.summary().selected_signature, Some("ERROR: sig #"))
  let analysis = @cli.Analyzer::new(config)
  analysis.feed("2026-10-28 08:00:00 [ERROR] other 1")
  let contexts = @cli.ContextCollector::new(config)
  let windows = contexts
    .windows()
    .map(w => ({ source: "input.log", window: w, } : @cli.FileContextWindow))
  let report = @cli.markdown_report(
    analysis.finish(),
    windows,
    contexts.sampled(),
    contexts.omitted(),
    @cli.SpikeSignatureCollector::new(analysis.finish()),
    @cli.ContextMode::Errors,
    ["input.log"],
    selected_signature=Some("ERROR: sig #"),
    signature_comparisons=result.signature_comparisons,
  )
  assert_true(report.contains("there is no comparison window"))
  assert_true(
    report.contains("does not mean the selected signature never occurred"),
  )
  assert_true(report.contains("No context matched the selected signature"))
  assert_true(report.contains("This does not imply the service was healthy"))
  assert_false(report.contains("no faults"))
}

///|
test "comparison applies filters and zero baseline has undefined multiplier" {
  let config = @cli.Config::new(baseline_buckets=1, max_signatures=1)
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "keep",
    from: None,
    to: None,
  }
  let analyzer = @cli.Analyzer::new(config, filter~)
  let lines = [
    "2026-10-28 08:00:00 [INFO] healthy", "2026-10-28 08:00:00 [ERROR] discard",
    "2026-10-28 08:05:00 [ERROR] keep 1", "2026-10-28 08:05:00 [ERROR] keep 2", "2026-10-28 08:05:00 [ERROR] keep 3",
    "2026-10-28 08:05:00 [FATAL] keep 4", "{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"keep 5\"}",
  ]
  for raw in lines {
    analyzer.feed(raw)
  }
  let a = analyzer.finish()
  let c = @cli.SignatureComparisonCollector::new(a, "ERROR: keep #")
  for raw in lines {
    c.feed(raw)
  }
  let comparison = c.comparisons()[0]
  assert_eq(comparison.before_count, 0L)
  assert_eq(comparison.spike_count, 3L)
  assert_eq(comparison.rate_multiplier, None)
  let missing = @cli.SignatureComparisonCollector::new(a, "ERROR: absent")
  for raw in lines {
    missing.feed(raw)
  }
  assert_eq(missing.comparisons()[0].spike_count, 0L)
  let empty = @cli.SignatureComparisonCollector::new(
    @cli.Analyzer::new(config).finish(),
    "ERROR: keep #",
  )
  empty.feed(lines[2])
  assert_eq(empty.comparisons().length(), 0)
}

///|
test "large frequency and multiplier formatting does not overflow Int32" {
  assert_eq(@cli.format_per_minute(3000000.125), "3000000.125")
  assert_eq(@cli.format_multiplier(30000000.25), "30000000.25x")
}
