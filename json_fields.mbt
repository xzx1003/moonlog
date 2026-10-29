///|
// Exact top-level JSON keys only. Private fields keep validation mandatory.
pub struct JsonFields {
  time : String
  level : String
  message : String
}

///|
pub fn JsonFields::new(
  time~ : String = "ts",
  level~ : String = "level",
  message~ : String = "msg",
) -> JsonFields raise {
  for key in [time, level, message] {
    guard key.trim() != "" && key.length() <= 256 else {
      fail(
        "JSON field names must be nonblank and at most 256 UTF-16 code units",
      )
    }
    for ch in key.iter() {
      if ch.to_int() < 32 || ch.to_int() == 127 {
        fail("JSON field names must not contain control characters")
      }
    }
  }
  guard time != level && time != message && level != message else {
    fail("JSON time, level and message field names must be distinct")
  }
  { time, level, message, }
}

///|
pub fn JsonFields::default() -> JsonFields {
  { time: "ts", level: "level", message: "msg", }
}

///|
pub fn JsonFields::label(self : JsonFields) -> String {
  "time=\{self.time}; level=\{self.level}; message=\{self.message}"
}

///|
pub fn JsonFields::to_json(self : JsonFields) -> Json {
  Json::object({
    "time": Json(self.time),
    "level": Json(self.level),
    "message": Json(self.message),
  })
}
