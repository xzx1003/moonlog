///|
#external
priv type Handle

///|
#borrow(path)
extern "C" fn open_file(path : Bytes, output : Int32) -> Handle = "moonlog_open"

///|
extern "C" fn is_null(file : Handle) -> Int32 = "moonlog_null"

///|
#borrow(buffer)
extern "C" fn read_chunk(file : Handle, buffer : Bytes, size : Int32) -> Int32 = "moonlog_read"

///|
#borrow(bytes)
extern "C" fn write_chunk(file : Handle, bytes : Bytes, size : Int32) -> Int32 = "moonlog_write"

///|
#borrow(path)
extern "C" fn stat_file(path : Bytes) -> Bytes = "moonlog_stat"

///|
#borrow(a, b)
extern "C" fn same_file_ffi(a : Bytes, b : Bytes) -> Int32 = "moonlog_same_file"

///|
extern "C" fn close(file : Handle) -> Int32 = "moonlog_close"

///|
extern "C" fn error_bytes() -> Bytes = "moonlog_error"

///|
#borrow(bytes)
extern "C" fn stderr_bytes(bytes : Bytes, size : Int32) = "moonlog_stderr"

///|
pub extern "C" fn exit(code : Int32) = "exit"

///|
pub fn stderr(message : String) -> Unit {
  let bytes = @utf8.encode(message + "\n")
  stderr_bytes(bytes, bytes.length())
}

///|
fn c_path(path : String) -> Bytes raise {
  if path.contains_char('\u0000') {
    fail("path contains NUL")
  }
  @utf8.encode(path) + b"\x00"
}

///|
fn io_error(action : String, path : String) -> Unit raise {
  let detail = @utf8.decode_lossy(error_bytes())
  fail("\{action} '\{path}': \{detail}")
}

///|
pub fn same_file(a : String, b : String) -> Bool raise {
  same_file_ffi(c_path(a), c_path(b)) != 0
}

///|
pub fn path_exists(path : String) -> Bool raise {
  let identity = stat_file(c_path(path))
  identity.length() != 0
}

///|
pub fn ensure_distinct_output(
  output : String,
  inputs : Array[String],
) -> Unit raise {
  if path_exists(output) {
    for input in inputs {
      if same_file(output, input) {
        fail("report path aliases an input file: \{output}")
      }
    }
  }
}

///|
pub fn stat_identity(path : String) -> String raise {
  let raw = stat_file(c_path(path))
  if raw.length() == 0 {
    let detail = @utf8.decode_lossy(error_bytes())
    if detail != "" {
      fail("cannot stat input '\{path}': \{detail}")
    }
    fail("not a regular file '\{path}'")
  }
  @utf8.decode_lossy(raw)
}

///|
// 64 KiB chunks; UTF-8 is decoded only after a full bounded line is available.
// Fail explicitly instead of allocating without bound on a pathological line.
// observe_chunk sees a whole chunk before any line from it is consumed; observe,
// when given, receives the same raw bytes one by one. Neither may retain a view.
pub fn each_line(
  path : String,
  consume : (String) -> Unit raise,
  max_line_bytes~ : Int32 = 65536,
  observe~ : ((Byte) -> Unit)? = None,
  observe_chunk~ : (BytesView) -> Unit = fn(_) { () },
) -> Unit raise {
  guard max_line_bytes > 0 && max_line_bytes <= 1048576 else {
    fail("max line bytes must be 1..1048576")
  }
  let file = open_file(c_path(path), 0)
  if is_null(file) != 0 {
    io_error("cannot open input", path)
    return
  }
  defer ignore(close(file))
  let bytes = Bytes::make(65536, 0)
  let pending = @buffer.Buffer()
  let mut line = 1L
  fn emit() -> Unit raise {
    let data = pending.to_bytes()
    let end = if data.length() > 0 && data[data.length() - 1] == 13 {
      data.length() - 1
    } else {
      data.length()
    }
    let text = @utf8.decode(data[:end], ignore_bom=line == 1) catch {
      _ => fail("invalid UTF-8 at line \{line}")
    }
    consume(text)
    pending.reset()
    line += 1
  }
  while true {
    let size = read_chunk(file, bytes, bytes.length())
    if size < 0 {
      io_error("cannot read input", path)
    }
    if size == 0 {
      break
    }
    // Borrowed view is valid only during this synchronous callback.
    observe_chunk(bytes[:size])
    if observe is Some(callback) {
      for i in 0..<size {
        callback(bytes[i])
      }
    }
    let mut start = 0
    for i in 0..<size {
      if bytes[i] == 10 {
        if pending.length() + i - start > max_line_bytes {
          fail("line \{line} exceeds --max-line-bytes (\{max_line_bytes})")
        }
        pending.write_bytes(bytes[start:i])
        emit()
        start = i + 1
      }
    }
    if pending.length() + size - start > max_line_bytes {
      fail("line \{line} exceeds --max-line-bytes (\{max_line_bytes})")
    }
    pending.write_bytes(bytes[start:size])
  }
  if pending.length() > 0 {
    emit()
  }
}

///|
// Exclusive creation protects existing reports, the input and hard/symbolic aliases.
pub fn write_report(path : String, content : String) -> Unit raise {
  let file = open_file(c_path(path), 1)
  if is_null(file) != 0 {
    io_error(
      "cannot create report (existing files are never overwritten)", path,
    )
    return
  }
  let bytes = @utf8.encode(content)
  let result = write_chunk(file, bytes, bytes.length())
  let closed = close(file)
  if result != 0 || closed != 0 {
    io_error("cannot finish report", path)
  }
}
