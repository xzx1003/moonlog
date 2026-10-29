///|
// Deterministic output-only redaction. The source bytes and all analysis
// counters remain untouched; callers apply this to rendered text fields.
pub(all) struct RedactionRule {
  needle : String
  replacement : String
}

///|
pub struct Redactor {
  rules : Array[RedactionRule]
}

///|
pub fn Redactor::new(rules : Array[RedactionRule]) -> Redactor raise {
  for rule in rules {
    guard rule.needle != "" else { fail("redaction text must not be empty") }
    guard !rule.needle.contains_char('\n') && !rule.needle.contains_char('\r') else {
      fail("redaction text must not contain newlines")
    }
    guard rule.replacement != rule.needle else {
      fail("redaction replacement must differ")
    }
  }
  { rules: rules.copy(), }
}

///|
pub fn Redactor::none() -> Redactor {
  { rules: [], }
}

///|
pub fn Redactor::apply(self : Redactor, text : String) -> String {
  let mut result = text
  for rule in self.rules {
    result = result
      .split(rule.needle)
      .map(part => part.to_owned())
      .to_array()
      .join(rule.replacement)
  }
  result
}

///|
pub fn Redactor::enabled(self : Redactor) -> Bool {
  self.rules.length() > 0
}

///|
pub fn Redactor::rule_count(self : Redactor) -> Int32 {
  self.rules.length()
}

///|
// Redact named keys recursively in a JSON value, replacing the entire value.
// Keys are exact, case-sensitive literal keys, never dotted paths. Invalid
// JSON is preserved except for literal replacements; no false safety claim.
pub fn Redactor::json_line(
  self : Redactor,
  raw : String,
  keys : Array[String],
) -> String {
  let parsed = @json.parse(
    raw,
    max_nesting_depth=32,
    reject_duplicate_keys=true,
  ) catch {
    _ => return self.apply(raw)
  }
  fn visit(value : Json) -> Json {
    match value {
      Object(fields) => {
        let result : Map[String, Json] = Map([])
        for key, item in fields {
          result[key] = if keys.contains(key) {
            Json("[REDACTED]")
          } else {
            visit(item)
          }
        }
        Json::object(result)
      }
      Array(items) => Json::array(items.map(visit))
      String(text) => Json(self.apply(text))
      _ => value
    }
  }
  if keys.is_empty() {
    return self.apply(raw)
  }
  self.apply(visit(parsed).stringify())
}

///|
// Metadata deliberately omits needles, keys and replacement values: rules
// themselves can contain credentials. Do not serialize a RedactionRule.
pub fn Redactor::metadata(self : Redactor, field_count : Int32) -> Json {
  Json::object({
    "literal_rule_count": Json(self.rule_count()),
    "json_field_rule_count": Json(field_count),
    "notice": Json(
      "Output-only best-effort redaction; not a guarantee that all sensitive data was removed. Malformed JSON uses literal rules only. Statistics use original input.",
    ),
  })
}
