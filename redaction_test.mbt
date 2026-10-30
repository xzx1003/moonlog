///|
test "redactor applies ordered literal replacements without changing counts" {
  let redactor = @cli.Redactor::new([
    { needle: "token=abc", replacement: "token=[REDACTED]", },
    { needle: "alice@example.com", replacement: "[EMAIL]", },
  ])
  assert_true(redactor.enabled())
  assert_eq(redactor.rule_count(), 2)
  assert_eq(
    redactor.apply("token=abc alice@example.com token=abc"),
    "token=[REDACTED] [EMAIL] token=[REDACTED]",
  )
  assert_eq(redactor.apply("unchanged"), "unchanged")
  assert_eq(@cli.Redactor::none().apply("raw"), "raw")
}

///|
test "redactor rejects ambiguous or unsafe rules" {
  let rules : Array[@cli.RedactionRule] = [
    { needle: "", replacement: "x", },
    { needle: "x\n", replacement: "y", },
    { needle: "x", replacement: "x", },
  ]
  for rule in rules {
    let invalid = try {
      ignore(@cli.Redactor::new([rule]))
      false
    } catch {
      _ => true
    }
    assert_true(invalid)
  }
}

///|
test "JSON fields replace whole values recursively and keep invalid input visible" {
  let r = @cli.Redactor::new([{ needle: "secret", replacement: "[HIDDEN]", }])
  let output = r.json_line(
    "{\"token\":{\"a\":1},\"nested\":[{\"token\":42}],\"msg\":\"secret\"}",
    ["token"],
  )
  assert_true(@json.valid(output))
  assert_eq(output.contains("secret"), false)
  assert_eq(output.contains("42"), false)
  assert_true(output.contains("REDACTED"))
  assert_eq(
    r.json_line("broken token=secret", ["token"]),
    "broken token=[HIDDEN]",
  )
  assert_eq(r.metadata(1).stringify().contains("secret"), false)
}

///|
test "field-only redaction leaves message copies visible; explicit literal rules cover them" {
  let line = "{\"token\":\"abc123\",\"message\":\"authentication failed: abc123\"}"
  let field_only = @cli.Redactor::none().json_line(line, ["token"])
  assert_true(field_only.contains("authentication failed: abc123"))
  assert_true(field_only.contains("[REDACTED]"))
  let explicit = @cli.Redactor::new([
    { needle: "abc123", replacement: "[HIDDEN]", },
  ])
  assert_eq(explicit.json_line(line, ["token"]).contains("abc123"), false)
}
