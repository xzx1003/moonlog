///|
test "record counters cross Int32 boundary without wrapping" {
  let a = Analyzer::new(Config::new())
  a.total = 2147483647L
  a.matched = 2147483647L
  a.untimed = 2147483647L
  a.counts["ERROR"] = 2147483647L
  a.feed("{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"timeout\"}")
  let result = a.finish()
  assert_eq(result.total, 2147483648L)
  assert_eq(result.matched, 2147483648L)
  assert_eq(result.untimed, 2147483648L)
  assert_eq(result.counts["ERROR"], 2147483648L)
}

///|
test "bucket spike and signature counts support more than Int32" {
  let a = Analyzer::new(Config::new())
  let start = parse_time("2026-10-28 08:30:00").unwrap()
  a.feed("2026-10-28 08:00:00 [INFO] baseline")
  a.feed("2026-10-28 08:30:00 [ERROR] timeout")
  a.buckets[start].total = 2147483647L
  a.buckets[start].errors = 2147483647L
  a.observation[start].total = 2147483647L
  a.observation[start].errors = 2147483647L
  a.signatures["ERROR: timeout"] = 2147483647L
  a.feed("2026-10-28 08:30:00 [ERROR] timeout")
  let result = a.finish()
  assert_eq(result.buckets.last().unwrap().errors, 2147483648L)
  assert_eq(result.signatures[0].count, 2147483648L)
  assert_eq(result.spikes[0].errors, 2147483648L)
}

///|
test "record safety ceiling fails before changing counters" {
  let a = Analyzer::new(Config::new())
  a.total = 9000000000000L
  let rejected = try {
    a.feed("x")
    false
  } catch {
    _ => true
  }
  assert_true(rejected)
  assert_eq(a.total, 9000000000000L)
}
