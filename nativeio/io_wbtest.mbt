///|
// Cross-platform temporary directory: use .tmp in current directory
fn temp_dir() -> String {
  ".tmp"
}

///|
// Ensure temp directory exists
fn ensure_temp_dir() -> Unit raise {
  let tmp = temp_dir()
  if !path_exists(tmp) {
    ignore(write_report(tmp + "/.keep", "") catch { _ => () })
  }
}

///|
// write_report never overwrites, so fixture paths are content-addressed and
// may be reused after a previous test run.
fn prepare_fixture(path : String, content : String) -> Unit raise {
  ensure_temp_dir()
  write_report(path, content) catch {
    _ => ()
  }
  if !path_exists(path) {
    fail("cannot prepare acceptance fixture \{path}")
  }
}

///|
// 65,572 bytes: BOM, a complete line, then a line whose multibyte character is
// split by the 64 KiB read boundary, CRLF, and a final line without newline.
fn acceptance_chunked_log() -> String {
  "\u{feff}2026-10-28 08:00:00 [INFO] start\n" +
  "a".repeat(65499) +
  "中\r\n" +
  "2026-10-28 08:05:00 [ERROR] boom"
}

///|
test "each_line observes raw chunks before decoding lines across the 64 KiB boundary" {
  let path = ".tmp/moonlog-each-line-a31079f2.log"
  let content = acceptance_chunked_log()
  prepare_fixture(path, content)
  let lines : Array[String] = []
  let events : Array[String] = []
  each_line(
    path,
    raw => {
      events.push("line")
      lines.push(raw)
    },
    observe_chunk=view => events.push("chunk:\{view.length()}"),
  )
  assert_eq(lines.length(), 3)
  assert_eq(events.join(","), "chunk:65536,line,chunk:36,line,line")
  assert_eq(lines[0], "2026-10-28 08:00:00 [INFO] start")
  assert_eq(lines[1], "a".repeat(65499) + "中")
  assert_eq(lines[2], "2026-10-28 08:05:00 [ERROR] boom")
  let chunked = @buffer.Buffer()
  each_line(path, _ => (), observe_chunk=view => chunked.write_bytes(view))
  assert_eq(chunked.to_bytes(), @utf8.encode(content))
  let bytewise = @buffer.Buffer()
  each_line(path, _ => (), observe=Some(byte => bytewise.write_byte(byte)))
  assert_eq(bytewise.to_bytes(), @utf8.encode(content))
}

///|
test "each_line observes a failing chunk before rejecting an overlong line" {
  let path = ".tmp/moonlog-each-line-a6095d81.log"
  let content = "abc\n" + "x".repeat(65536) + "y\n"
  prepare_fixture(path, content)
  let lines : Array[String] = []
  let observed = @buffer.Buffer()
  let message = try {
    each_line(path, raw => lines.push(raw), observe_chunk=view => {
      observed.write_bytes(view)
    })
    ""
  } catch {
    Failure(message) => message
    _ => "unexpected error"
  }
  assert_true(message.contains("line 2 exceeds --max-line-bytes (65536)"))
  assert_eq(lines.join(","), "abc")
  assert_eq(observed.to_bytes(), @utf8.encode(content))
}
