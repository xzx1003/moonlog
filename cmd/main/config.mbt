///|
// Config-derived state that must never become a command-line argument:
// redaction rules can contain credentials and shell history is not private.
struct PreparedArgs {
  args : Array[String]
  redactor : @engine.Redactor
  diagnostic_redactor : @engine.Redactor
  redact_fields : Array[String]
}

///|
struct RedactionConfig {
  redactor : @engine.Redactor
  diagnostic_redactor : @engine.Redactor
  fields : Array[String]
}

///|
const MAX_REDACTION_RULES : Int32 = 100

///|
const MAX_REDACT_FIELDS : Int32 = 100

///|
const MAX_REDACTION_TEXT : Int32 = 1024

///|
const MAX_REDACT_FIELD_NAME : Int32 = 256

///|
fn has_control_character(text : String) -> Bool {
  for ch in text.iter() {
    let code = ch.to_int()
    if code < 32 || code == 127 {
      return true
    }
  }
  false
}

///|
fn has_output_control_character(text : String) -> Bool {
  for ch in text.iter() {
    let code = ch.to_int()
    if code < 32 ||
      code == 127 ||
      code == 0x85 ||
      code == 0x2028 ||
      code == 0x2029 {
      return true
    }
  }
  false
}

///|
// Parse redaction settings first so later config errors can be rendered through
// the rules. Every message names only a position, never a needle, replacement
// or field value.
fn redaction_config(fields : Map[String, Json]) -> RedactionConfig raise {
  let rules : Array[@engine.RedactionRule] = []
  // Diagnostics keep the needles but never the configured replacement, which is
  // itself rule content. A neutral token keeps stderr free of both.
  let diagnostic_rules : Array[@engine.RedactionRule] = []
  match fields.get("redact-text") {
    None => ()
    Some(value) =>
      match value {
        Array(items) => {
          if items.length() > MAX_REDACTION_RULES {
            fail(
              "config redact-text must contain at most \{MAX_REDACTION_RULES} rules",
            )
          }
          for i, item in items {
            let rule = match item {
              Object(rule) => rule
              _ => fail("config redact-text[\{i}] must be an object")
            }
            if rule.length() != 2 ||
              !rule.contains("needle") ||
              !rule.contains("replacement") {
              fail(
                "config redact-text[\{i}] must contain exactly needle and replacement",
              )
            }
            let needle = match rule.get("needle") {
              Some(String(text)) => text
              _ => fail("config redact-text[\{i}].needle must be a string")
            }
            let replacement = match rule.get("replacement") {
              Some(String(text)) => text
              _ => fail("config redact-text[\{i}].replacement must be a string")
            }
            if needle == "" {
              fail("config redact-text[\{i}].needle must not be empty")
            }
            if needle.contains_char('\n') || needle.contains_char('\r') {
              fail("config redact-text[\{i}].needle must not contain newlines")
            }
            if needle.length() > MAX_REDACTION_TEXT {
              fail(
                "config redact-text[\{i}].needle must be at most \{MAX_REDACTION_TEXT} UTF-16 code units",
              )
            }
            if replacement.length() > MAX_REDACTION_TEXT {
              fail(
                "config redact-text[\{i}].replacement must be at most \{MAX_REDACTION_TEXT} UTF-16 code units",
              )
            }
            if has_output_control_character(replacement) {
              fail(
                "config redact-text[\{i}].replacement must not contain control characters",
              )
            }
            if replacement == needle {
              fail(
                "config redact-text[\{i}].replacement must differ from needle",
              )
            }
            for existing in rules {
              if existing.needle == needle {
                fail(
                  "config redact-text[\{i}].needle duplicates an earlier rule",
                )
              }
            }
            rules.push({ needle, replacement, })
            let neutral = if needle == "[REDACTED]" {
              "[MASKED]"
            } else {
              "[REDACTED]"
            }
            diagnostic_rules.push({ needle, replacement: neutral, })
          }
        }
        _ => fail("config redact-text must be an array")
      }
  }
  let redact_fields : Array[String] = []
  match fields.get("redact-fields") {
    None => ()
    Some(value) =>
      match value {
        Array(items) => {
          if items.length() > MAX_REDACT_FIELDS {
            fail(
              "config redact-fields must contain at most \{MAX_REDACT_FIELDS} fields",
            )
          }
          for i, item in items {
            let name = match item {
              String(text) => text
              _ => fail("config redact-fields[\{i}] must be a string")
            }
            if name.trim() == "" {
              fail("config redact-fields[\{i}] must be nonblank")
            }
            if name.length() > MAX_REDACT_FIELD_NAME {
              fail(
                "config redact-fields[\{i}] must be at most \{MAX_REDACT_FIELD_NAME} UTF-16 code units",
              )
            }
            if has_control_character(name) {
              fail(
                "config redact-fields[\{i}] must not contain control characters",
              )
            }
            if redact_fields.contains(name) {
              fail("config redact-fields[\{i}] duplicates an earlier field")
            }
            redact_fields.push(name)
          }
        }
        _ => fail("config redact-fields must be an array")
      }
  }
  let redactor = @engine.Redactor::new(rules) catch {
    Failure(message) =>
      fail("config redact-text is invalid: \{failure_message(message)}")
    _ => fail("config redact-text is invalid")
  }
  let diagnostic_redactor = @engine.Redactor::new(diagnostic_rules) catch {
    _ => fail("config redact-text is invalid")
  }
  { redactor, diagnostic_redactor, fields: redact_fields, }
}

///|
// Explicit config only: never discover files or accept input/output paths.
// Precedence: built-in defaults < config file < command line. Config keys use
// the long CLI option spelling without the leading `--`.
fn config_args(args : Array[String]) -> PreparedArgs raise {
  let mut path : String? = None
  let cleaned : Array[String] = []
  let mut i = 0
  // Only recognize --config in option positions, never inside a keyword or
  // signature value. Positional inputs precede options, as in the main parser.
  while i < args.length() && (i < 2 || !args[i].has_prefix("--")) {
    cleaned.push(args[i])
    i += 1
  }
  while i < args.length() {
    let flag = args[i]
    if flag == "--config" {
      if path is Some(_) {
        fail("duplicate option: --config")
      }
      if i + 1 >= args.length() {
        fail("missing value for --config")
      }
      path = Some(args[i + 1])
    } else {
      cleaned.push(flag)
      if i + 1 < args.length() {
        cleaned.push(args[i + 1])
      }
    }
    i += 2
  }
  guard path is Some(config_path) else {
    return {
      args: cleaned,
      redactor: @engine.Redactor::none(),
      diagnostic_redactor: @engine.Redactor::none(),
      redact_fields: [],
    }
  }
  let text = StringBuilder()
  let mut size = 0
  @io.each_line(config_path, line => {
    size += line.length() + 1
    if size > 65536 {
      fail("config exceeds 64 KiB text limit")
    }
    text.write_string(line)
    text.write_char('\n')
  })
  let json = @json.parse(
    text.to_string(),
    reject_duplicate_keys=true,
    max_nesting_depth=4,
  ) catch {
    _ => fail("config must be a JSON object with unique keys")
  }
  guard json is Object(fields) else { fail("config must be a JSON object") }
  let redaction = redaction_config(fields)
  let defaults : Array[String] = []
  let json_config_fields : Map[String, String] = Map([])
  try {
    for key, value in fields {
      let flag = "--" + key
      let rendered : String? = match key {
        "redact-text" | "redact-fields" => None
        "detector" => {
          guard value is String(v) else {
            fail("config detector must be a string")
          }
          ignore(detector_value(v))
          Some(v)
        }
        "ewma-alpha" | "mad-threshold" => {
          let raw = value.stringify()
          ignore(detector_number(raw, flag))
          Some(raw)
        }
        "bucket-minutes"
        | "baseline-buckets"
        | "multiplier"
        | "min-errors"
        | "context"
        | "max-samples"
        | "max-buckets"
        | "max-signatures"
        | "max-line-bytes" => {
          let raw = value.stringify()
          let n = positive_or_zero(raw, flag)
          let (low, high) = match key {
            "bucket-minutes" => (1, 1440)
            "baseline-buckets" => (1, 1000)
            "multiplier" => (2, 1000)
            "context" => (0, 100)
            "max-samples" => (0, 100)
            "max-buckets" => (1, 1000000)
            "max-signatures" => (1, 10000)
            "max-line-bytes" => (1, 1048576)
            _ => (1, 2147483647)
          }
          if n < low || n > high {
            fail("config \{key} must be \{low}..\{high}")
          }
          Some(raw)
        }
        "format" | "sampling" | "context-mode" => {
          guard value is String(v) else {
            fail("config \{key} must be a string")
          }
          let valid = match key {
            "format" => v == "markdown" || v == "json"
            "sampling" => v == "first" || v == "distributed"
            _ => v == "spikes" || v == "errors"
          }
          if !valid {
            fail("invalid config \{key}: \{v}")
          }
          Some(v)
        }
        "json-time-field" | "json-level-field" | "json-message-field" => {
          guard value is String(v) else {
            fail("config \{key} must be a string")
          }
          json_config_fields[key] = v
          Some(v)
        }
        _ => fail("unknown or forbidden config key: \{key}")
      }
      match rendered {
        Some(text) => {
          // An explicit CLI flag wins over this config key.
          let mut option = 2
          while option < cleaned.length() && !cleaned[option].has_prefix("--") {
            option += 1
          }
          let mut overridden = false
          while option < cleaned.length() {
            if cleaned[option] == flag {
              overridden = true
            }
            option += 2
          }
          if !overridden {
            defaults.push(flag)
            defaults.push(text)
          }
        }
        None => ()
      }
    }
    // Validate the config layer as a complete mapping even when a CLI flag later
    // overrides one of its keys. The merged mapping is validated again in run().
  } catch {
    Failure(message) =>
      fail(redaction.diagnostic_redactor.apply(failure_message(message)))
    error => fail(redaction.diagnostic_redactor.apply("\{error}"))
  }
  ignore(
    @engine.JsonFields::new(
      time=json_config_fields.get_or_default("json-time-field", "ts"),
      level=json_config_fields.get_or_default("json-level-field", "level"),
      message=json_config_fields.get_or_default("json-message-field", "msg"),
    ),
  ) catch {
    Failure(message) =>
      fail(
        "config JSON field mapping is invalid: \{redaction.diagnostic_redactor.apply(failure_message(message))}",
      )
    error =>
      fail(
        "config JSON field mapping is invalid: \{redaction.diagnostic_redactor.apply("\{error}")}",
      )
  }
  // Insert config values after positional inputs but before CLI options. This
  // gives CLI settings precedence without triggering duplicate-option errors.
  let mut first_option = if cleaned.length() < 2 { cleaned.length() } else { 2 }
  while first_option < cleaned.length() &&
        !cleaned[first_option].has_prefix("--") {
    first_option += 1
  }
  let result : Array[String] = []
  for j in 0..<first_option {
    result.push(cleaned[j])
  }
  for item in defaults {
    result.push(item)
  }
  for j in first_option..<cleaned.length() {
    result.push(cleaned[j])
  }
  {
    args: result,
    redactor: redaction.redactor,
    diagnostic_redactor: redaction.diagnostic_redactor,
    redact_fields: redaction.fields,
  }
}
