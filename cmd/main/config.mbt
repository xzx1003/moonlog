///|
// Explicit config only: never discover files or accept input/output paths.
// Precedence: built-in defaults < config file < command line. Config keys use
// the long CLI option spelling without the leading `--`.
fn config_args(args : Array[String]) -> Array[String] raise {
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
  guard path is Some(config_path) else { return cleaned }
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
  let defaults : Array[String] = []
  let json_config_fields : Map[String, String] = Map([])
  for key, value in fields {
    let flag = "--" + key
    let rendered = match key {
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
        raw
      }
      "format" | "sampling" | "context-mode" => {
        guard value is String(v) else { fail("config \{key} must be a string") }
        let valid = match key {
          "format" => v == "markdown" || v == "json"
          "sampling" => v == "first" || v == "distributed"
          _ => v == "spikes" || v == "errors"
        }
        if !valid {
          fail("invalid config \{key}: \{v}")
        }
        v
      }
      "json-time-field" | "json-level-field" | "json-message-field" => {
        guard value is String(v) else { fail("config \{key} must be a string") }
        json_config_fields[key] = v
        v
      }
      _ => fail("unknown or forbidden config key: \{key}")
    }
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
      defaults.push(rendered)
    }
  }
  // Validate the config layer as a complete mapping even when a CLI flag later
  // overrides one of its keys. The merged mapping is validated again in run().
  ignore(
    @engine.JsonFields::new(
      time=json_config_fields.get_or_default("json-time-field", "ts"),
      level=json_config_fields.get_or_default("json-level-field", "level"),
      message=json_config_fields.get_or_default("json-message-field", "msg"),
    ) catch {
      Failure(message) =>
        fail(
          "config JSON field mapping is invalid: \{failure_message(message)}",
        )
      _ => fail("config JSON field mapping is invalid")
    },
  )
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
  result
}
