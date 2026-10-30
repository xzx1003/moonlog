///|
fn prepare_fixture(path : String, content : String) -> Unit raise {
  @io.write_report(path, content) catch {
    _ => ()
  }
  if !@io.path_exists(path) {
    fail("cannot prepare acceptance fixture \{path}")
  }
}

///|
// Same decoded lines with CRLF/no final newline and LF/trailing newline.
// Expected digests come from Python hashlib over the raw file bytes.
test "scan_file keeps per-file digests and verify_snapshots compares each file" {
  let a = "/tmp/moonlog-scan-36c2dbc5.log"
  let b = "/tmp/moonlog-scan-8bab7289.log"
  prepare_fixture(
    a, "2026-10-28 08:00:00 [INFO] ok\r\n2026-10-28 08:05:00 [ERROR] boom",
  )
  prepare_fixture(
    b, "2026-10-28 08:00:00 [INFO] ok\n2026-10-28 08:05:00 [ERROR] boom\n",
  )
  let sa = scan_file(a, 65536, fn(_) { () })
  let sb = scan_file(b, 65536, fn(_) { () })
  assert_eq(sa.lines, 2L)
  assert_eq(sb.lines, 2L)
  assert_eq(
    sa.digest,
    "36c2dbc51bfc5536da01cd7e657f5abf35ae8e79ecdb20f446f32d50833e5eb6",
  )
  assert_eq(
    sb.digest,
    "8bab72898f1c8576747200b424b3655ae1a739a8c1d742c8444be35c1e4404f2",
  )
  assert_true(sa.digest != sb.digest)
  verify_snapshots([a, b], [sa, sb], [sa, sb])
  let mismatch = try {
    verify_snapshots([a, b], [sa, sb], [sb, sa])
    false
  } catch {
    _ => true
  }
  assert_true(mismatch)
}
