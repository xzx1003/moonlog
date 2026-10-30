///|
test "year limits and UTC conversion across calendar boundaries" {
  assert_eq(@cli.parse_time("0001-01-01 00:00:00Z"), Some(0L))
  assert_eq(@cli.parse_time("9999-12-31 23:59:59Z"), Some(5258964959L))
  assert_eq(@cli.parse_time("0000-01-01 00:00:00Z"), None)
  assert_eq(@cli.parse_time("0001-01-01 00:30:00+01:00"), None)
  assert_eq(@cli.parse_time("9999-12-31 23:30:00-00:30"), None)
  assert_eq(
    @cli.parse_time("2026-01-01 00:30:00+01:00"),
    @cli.parse_time("2025-12-31 23:30:00Z"),
  )
  assert_eq(
    @cli.parse_time("2025-12-31 23:30:00-01:00"),
    @cli.parse_time("2026-01-01 00:30:00Z"),
  )
}

///|
test "leap day fractions and timezone limits" {
  for fraction in ["", ".1", ".123", ".123456789012"] {
    assert_eq(
      @cli.parse_time("2024-03-01T00:30:59\{fraction}+01:00"),
      @cli.parse_time("2024-02-29 23:30:00Z"),
    )
  }
  assert_eq(
    @cli.parse_time("2024-02-29T23:30:00-01:00"),
    @cli.parse_time("2024-03-01 00:30:00Z"),
  )
  assert_true(@cli.parse_time("2024-02-29 23:59:59+14:00") is Some(_))
  assert_true(@cli.parse_time("2024-02-29 23:59:59-14:00") is Some(_))
  for
    suffix in [
      "+14:01", "-14:01", "+15:00", "+01:60", "+1:00", ".Z", ".xZ", "+00:00junk",
    ] {
    assert_eq(@cli.parse_time("2024-02-29T12:00:00\{suffix}"), None)
  }
}
