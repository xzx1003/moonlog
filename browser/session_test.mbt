///|
fn bytes(text : String) -> Bytes {
  @utf8.encode(text)
}

///|
test "wasm session handles chunk boundaries CRLF BOM and two passes" {
  let config = @engine.Config::new(context=1)
  let session = @browser.Session::new("input.log", config)
  session.feed(
    bytes("\u{feff}2026-10-28 08:00:00 [INFO] ok\r\n2026-10-28 08:05"),
  )
  session.feed(
    bytes(
      ":00 [ERROR] failed 1\r\n2026-10-28 08:05:00 [ERROR] failed 2\r\n2026-10-28 08:05:00 [ERROR] failed 3",
    ),
  )
  assert_eq(session.end_pass(), 2)
  assert_eq(session.phase(), 2)
  session.feed(
    bytes(
      "\u{feff}2026-10-28 08:00:00 [INFO] ok\r\n2026-10-28 08:05:00 [ERROR] failed 1\r\n2026-10-28 08:05:00 [ERROR] failed 2\r\n2026-10-28 08:05:00 [ERROR] failed 3",
    ),
  )
  assert_eq(session.end_pass(), 3)
  let result = session.result()
  assert_eq(result.json_report().contains("\"total\": 4"), true)
  assert_eq(session.bytes_processed(), 146L)
}

///|
test "wasm session rejects oversized chunks and changed second pass" {
  let session = @browser.Session::new("input.log", @engine.Config::new())
  let huge = Bytes::make(65537, 65)
  let failed = try {
    session.feed(huge)
    false
  } catch {
    _ => true
  }
  assert_true(failed)
  assert_eq(session.phase(), -1)
  let changed = @browser.Session::new("input.log", @engine.Config::new())
  changed.feed(bytes("2026-10-28 08:00:00 [INFO] ok\n"))
  assert_eq(changed.end_pass(), 2)
  changed.feed(bytes("2026-10-28 08:00:00 [ERROR] changed\n"))
  let mismatch = try {
    ignore(changed.end_pass())
    false
  } catch {
    _ => true
  }
  assert_true(mismatch)
  assert_eq(changed.phase(), -1)
}

///|
test "wasm session cancel prevents further input and report" {
  let session = @browser.Session::new("input.log", @engine.Config::new())
  session.cancel()
  assert_eq(session.phase(), -1)
  let failed = try {
    session.feed(bytes("x"))
    false
  } catch {
    _ => true
  }
  assert_true(failed)
  let report = try {
    ignore(session.result())
    false
  } catch {
    _ => true
  }
  assert_true(report)
}

///|
test "byte digest rejects identical decoded lines with changed line endings" {
  let session = @browser.Session::new("input.log", @engine.Config::new())
  session.feed(bytes("2026-10-28 08:00:00 [INFO] ok\r\n"))
  assert_eq(session.end_pass(), 2)
  session.feed(bytes("2026-10-28 08:00:00 [INFO] ok\n"))
  let rejected = try {
    ignore(session.end_pass())
    false
  } catch {
    _ => true
  }
  assert_true(rejected)
  assert_eq(session.phase(), -1)
}
