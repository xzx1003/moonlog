///|
// One analysis at a time. The host creates a fresh Web Worker per run and
// terminates it on cancel, so no session handle ever crosses the JS boundary.
// MoonBit has no top-level mut bindings; one-element arrays hold the singleton.
let session_holder : Array[@browser.Session?] = [None]

///|
let error_holder : Array[String] = [""]

///|
fn set_error(message : String) -> Unit {
  error_holder[0] = message
}

///|
fn bridge_failure_message(message : String) -> String {
  match message.split_once(" FAILED: ") {
    Some((_, detail)) => detail.to_owned()
    None => message
  }
}

///|
fn record_error(message : String) -> Int32 {
  set_error(message)
  -1
}

///|
fn drop_session() -> Unit {
  match session_holder[0] {
    Some(s) => s.cancel()
    None => ()
  }
  session_holder[0] = None
}

///|
// 0 on success, -1 on error; read moonlog_last_error for the message.
// Only the parameters exposed by the web page are accepted. max_buckets and
// max_signatures keep their CLI defaults because the page does not surface them.
pub fn moonlog_start(
  source : String,
  bucket_minutes : Int32,
  baseline_buckets : Int32,
  multiplier : Int32,
  min_errors : Int32,
  context : Int32,
  max_samples : Int32,
  level : String,
  keyword : String,
  from : String,
  to : String,
) -> Int32 {
  set_error("")
  drop_session()
  let config = @engine.Config::new(
    bucket_minutes~,
    baseline_buckets~,
    multiplier~,
    min_errors~,
    context~,
    max_samples~,
  ) catch {
    Failure(message) => return record_error(bridge_failure_message(message))
    _ => return record_error("invalid analysis parameters")
  }
  let level_filter : @engine.Level? = if level == "" {
    None
  } else {
    let parsed = @engine.parse_level(level)
    if parsed == @engine.Other && level != "OTHER" {
      return record_error("unknown log level: \{level}")
    }
    Some(parsed)
  }
  let from_time : Int64? = if from == "" {
    None
  } else {
    match @engine.parse_time(from) {
      Some(t) => Some(t)
      None => return record_error("invalid from timestamp: \{from}")
    }
  }
  let to_time : Int64? = if to == "" {
    None
  } else {
    match @engine.parse_time(to) {
      Some(t) => Some(t)
      None => return record_error("invalid to timestamp: \{to}")
    }
  }
  if from_time is Some(a) && to_time is Some(b) && a > b {
    return record_error("from must not be after to")
  }
  let filter : @engine.Filter = {
    level: level_filter,
    keyword,
    from: from_time,
    to: to_time,
  }
  session_holder[0] = Some(@browser.Session::new(source, config, filter~))
  0
}

///|
// Base64 keeps chunk bytes exact across the JS boundary, including split
// multi-byte sequences. 65,536 bytes encode to 87,384 characters.
pub fn moonlog_feed_base64(chunk : String) -> Int32 {
  match session_holder[0] {
    Some(s) => {
      if chunk.length() > 87384 {
        drop_session()
        return record_error("chunk exceeds 64 KiB")
      }
      let bytes = @base64.decode(chunk) catch {
        _ => {
          drop_session()
          return record_error("invalid base64 chunk")
        }
      }
      s.feed(bytes) catch {
        Failure(message) => {
          drop_session()
          return record_error(bridge_failure_message(message))
        }
        _ => {
          drop_session()
          return record_error("failed to feed input")
        }
      }
      0
    }
    None => record_error("analysis has not started")
  }
}

///|
// 2 means rewind the file and feed pass two; 3 means the report is ready.
pub fn moonlog_end_pass() -> Int32 {
  match session_holder[0] {
    Some(s) => {
      let next = s.end_pass() catch {
        Failure(message) => {
          drop_session()
          return record_error(bridge_failure_message(message))
        }
        _ => {
          drop_session()
          return record_error("failed to finish scan pass")
        }
      }
      if next == 2 || next == 3 {
        next
      } else {
        drop_session()
        record_error("unexpected session state")
      }
    }
    None => record_error("analysis has not started")
  }
}

///|
pub fn moonlog_phase() -> Int32 {
  match session_holder[0] {
    Some(s) => s.phase()
    None => -1
  }
}

///|
pub fn moonlog_bytes_processed() -> Double {
  match session_holder[0] {
    Some(s) => s.bytes_processed().to_double()
    None => 0.0
  }
}

///|
pub fn moonlog_cancel() -> Unit {
  drop_session()
}

///|
pub fn moonlog_result_json() -> String {
  match session_holder[0] {
    Some(s) => {
      guard s.phase() == 3 else {
        set_error("report is not ready")
        return ""
      }
      let result = s.result() catch {
        Failure(message) => {
          set_error(bridge_failure_message(message))
          return ""
        }
        _ => {
          set_error("failed to build report")
          return ""
        }
      }
      set_error("")
      result.json_report()
    }
    None => {
      set_error("analysis has not started")
      ""
    }
  }
}

///|
pub fn moonlog_last_error() -> String {
  error_holder[0]
}

///|
fn main {

}
