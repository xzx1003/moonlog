///|
pub fn parse_level(text : String) -> Level {
  match text {
    "DEBUG" => Debug
    "INFO" => Info
    "WARN" => Warn
    "ERROR" => Error
    "FATAL" => Fatal
    _ => Other
  }
}

///|
fn digits(s : String, start : Int32, count : Int32) -> Int32? {
  if start + count > s.length() {
    return None
  }
  let mut n = 0
  for i in start..<(start + count) {
    let c = s[i].to_int()
    if c < 48 || c > 57 {
      return None
    }
    n = n * 10 + c - 48
  }
  Some(n)
}

///|
fn leap(year : Int32) -> Bool {
  year % 4 == 0 && (year % 100 != 0 || year % 400 == 0)
}

///|
// Minutes since 0001-01-01, interpreted as UTC. No host timezone dependency.
pub fn parse_time(s : String) -> Int64? {
  if s.length() < 19 {
    return None
  }
  if s[4] != 45 ||
    s[7] != 45 ||
    (s[10] != 32 && s[10] != 84) ||
    s[13] != 58 ||
    s[16] != 58 {
    return None
  }
  guard digits(s, 0, 4) is Some(y) && y > 0 else { return None }
  guard digits(s, 5, 2) is Some(m) && m >= 1 && m <= 12 else { return None }
  guard digits(s, 8, 2) is Some(d) else { return None }
  guard digits(s, 11, 2) is Some(h) && h < 24 else { return None }
  guard digits(s, 14, 2) is Some(minute) && minute < 60 else { return None }
  guard digits(s, 17, 2) is Some(second) && second < 60 else { return None }
  let month_days = [
    31,
    if leap(y) {
      29
    } else {
      28
    },
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ]
  if d < 1 || d > month_days[m - 1] {
    return None
  }
  let prior = y - 1
  let mut days = prior * 365 + prior / 4 - prior / 100 + prior / 400 + d - 1
  for i in 0..<(m - 1) {
    days += month_days[i]
  }
  let mut offset = 0
  let mut pos = 19
  if pos < s.length() && s[pos] == 46 {
    pos += 1
    let first = pos
    while pos < s.length() && s[pos] >= 48 && s[pos] <= 57 {
      pos += 1
    }
    if first == pos {
      return None
    }
  }
  if pos < s.length() {
    if s[pos] == 90 && pos + 1 == s.length() {
      pos += 1
    } else if (s[pos] == 43 || s[pos] == 45) &&
      pos + 6 == s.length() &&
      s[pos + 3] == 58 {
      guard digits(s, pos + 1, 2) is Some(oh) && oh <= 14 else { return None }
      guard digits(s, pos + 4, 2) is Some(om) && om < 60 else { return None }
      if oh == 14 && om != 0 {
        return None
      }
      offset = (oh * 60 + om) * (if s[pos] == 43 { 1 } else { -1 })
      pos += 6
    } else {
      return None
    }
  }
  if pos != s.length() {
    return None
  }
  let result = days.to_int64() * 1440L + (h * 60 + minute - offset).to_int64()
  if result < 0L {
    None
  } else {
    Some(result)
  }
}

///|
fn pad(n : Int32, width : Int32) -> String {
  n.to_string().pad_start(width, '0')
}

///|
pub fn format_time(minute : Int64) -> String {
  let day = (minute / 1440L).to_int()
  let mut y = day / 366 + 1
  while ({
          let p = y
          p * 365 + p / 4 - p / 100 + p / 400 <= day
        }) {
    y += 1
  }
  let p = y - 1
  let mut remaining = day - (p * 365 + p / 4 - p / 100 + p / 400)
  let md = [
    31,
    if leap(y) {
      29
    } else {
      28
    },
    31,
    30,
    31,
    30,
    31,
    31,
    30,
    31,
    30,
    31,
  ]
  let mut m = 0
  while remaining >= md[m] {
    remaining -= md[m]
    m += 1
  }
  let clock = (minute % 1440L).to_int()
  "\{pad(y,4)}-\{pad(m+1,2)}-\{pad(remaining+1,2)} \{pad(clock/60,2)}:\{pad(clock%60,2)}:00Z"
}

///|
pub fn parse_line(
  raw : String,
  fields~ : JsonFields = JsonFields::default(),
) -> Record {
  let text = raw.trim().to_owned()
  let unknown = { minute: None, level: Other, message: raw, }
  if text.has_prefix("{") {
    let json = @json.parse(
      text,
      max_nesting_depth=32,
      reject_duplicate_keys=true,
    ) catch {
      _ => return unknown
    }
    if json is Object(object) &&
      object.get(fields.time) is Some(String(ts)) &&
      object.get(fields.level) is Some(String(level)) &&
      object.get(fields.message) is Some(String(message)) {
      return { minute: parse_time(ts), level: parse_level(level), message, }
    }
    return unknown
  }
  guard text.find(" [") is Some(prefix) && prefix >= 19 && prefix <= 35 else {
    return unknown
  }
  let tail = text[prefix + 2:].to_owned()
  guard tail.find("]") is Some(close) && close > 0 else { return unknown }
  if close + 1 < tail.length() && tail[close + 1] != 32 {
    return unknown
  }
  let level = parse_level(tail[:close].to_owned())
  let message = tail[close + 1:].trim_start().to_owned()
  guard parse_time(text[:prefix].to_owned()) is Some(minute) else {
    return unknown
  }
  { minute: Some(minute), level, message, }
}

///|
// Normalize only decimal runs. Deliberately no unbounded regex or semantic inference.
pub fn error_signature(record : Record) -> String {
  let out = StringBuilder()
  out.write_string(record.level.label() + ": ")
  let mut in_digits = false
  let mut length = 0
  for ch in record.message.iter() {
    if length >= 512 {
      break
    }
    if ch >= '0' && ch <= '9' {
      if !in_digits {
        out.write_char('#')
        length += 1
      }
      in_digits = true
    } else {
      out.write_char(ch)
      length += 1
      in_digits = false
    }
  }
  out.to_string()
}
