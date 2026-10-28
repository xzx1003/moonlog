///|
test "observation ratio ignores level keyword but respects time and unknown levels" {
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "keep",
    from: @cli.parse_time("2026-10-28 08:00:00Z"),
    to: @cli.parse_time("2026-10-28 08:05:00Z"),
  }
  let analyzer = @cli.Analyzer::new(@cli.Config::new(), filter~)
  for
    line in [
      "2026-10-28 07:59:00 [ERROR] keep", "2026-10-28 08:00:00 [INFO] healthy", "2026-10-28 08:00:00 [OTHER] unknown",
      "2026-10-28 08:00:00 [ERROR] keep", "2026-10-28 08:05:00 [FATAL] discard",
      "2026-10-28 08:06:00 [ERROR] keep", "{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"keep\"}",
      "stack frame",
    ] {
    analyzer.feed(line)
  }
  let a = analyzer.finish()
  assert_eq(a.matched, 1)
  assert_eq(a.buckets[0].total, 1)
  let ratio = a.log_error_ratio()
  assert_eq(ratio.total, 4L)
  assert_eq(ratio.errors, 2L)
  assert_eq(ratio.fraction, Some(0.5))
  assert_eq(a.observation_buckets[0].log_error_ratio().total, 3L)
  assert_eq(a.observation_buckets[1].log_error_ratio().fraction, Some(1.0))
}

///|
test "ratio empty buckets undefined and spike ranges end exclusive with disorder" {
  let analyzer = @cli.Analyzer::new(@cli.Config::new(baseline_buckets=1))
  for
    line in [
      "2026-10-28 08:10:00 [INFO] end boundary", "2026-10-28 08:05:00 [ERROR] a",
      "2026-10-28 07:55:00 [INFO] healthy", "2026-10-28 08:05:00 [FATAL] b", "2026-10-28 08:05:00 [ERROR] c",
      "2026-10-28 08:05:00 [INFO] healthy",
    ] {
    analyzer.feed(line)
  }
  let a = analyzer.finish()
  assert_eq(a.observation_buckets[1].log_error_ratio().fraction, None)
  assert_eq(a.spikes.length(), 1)
  let spike = a.spikes[0]
  let ratio = a.log_error_ratio(start=Some(spike.start), end=Some(spike.end))
  assert_eq(ratio.total, 4L)
  assert_eq(ratio.errors, 3L)
  assert_eq(ratio.fraction, Some(0.75))
  assert_eq(a.log_error_ratio().fraction, Some(0.5))
  let empty = @cli.Analyzer::new(@cli.Config::new()).finish().log_error_ratio()
  assert_eq(empty.total, 0L)
  assert_eq(empty.fraction, None)
  assert_true(empty.to_json().stringify().contains("null"))
}

///|
test "10k observations keep ratio invariant under error-only filter" {
  let config = @cli.Config::new()
  let all = @cli.Analyzer::new(config)
  let filter : @cli.Filter = {
    level: Some(Error),
    keyword: "",
    from: None,
    to: None,
  }
  let errors = @cli.Analyzer::new(config, filter~)
  for i in 0..<10000 {
    let level = if i % 10 == 0 { "ERROR" } else { "INFO" }
    let raw = "2026-10-28 08:00:00 [\{level}] event"
    all.feed(raw)
    errors.feed(raw)
  }
  let a = all.finish()
  let b = errors.finish()
  assert_eq(a.log_error_ratio().fraction, Some(0.1))
  assert_eq(b.log_error_ratio().fraction, Some(0.1))
  assert_eq(b.matched, 1000)
  assert_eq(b.log_error_ratio().total, 10000L)
}
