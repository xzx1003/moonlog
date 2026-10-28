///|
fn completed_result(
  lines : Array[String],
  config : @cli.Config,
  mode~ : @cli.ContextMode = Spikes,
) -> @cli.ReportResult raise {
  let analyzer = @cli.Analyzer::new(config)
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  let signatures = @cli.SpikeSignatureCollector::new(analysis)
  let contexts = @cli.ContextCollector::new(config)
  for raw in lines {
    ignore(signatures.feed(raw))
    contexts.feed(raw, analysis.is_target(raw, mode~))
  }
  @cli.ReportResult::new(
    analysis, contexts, signatures, mode, "中文\"\\\n.log",
  )
}

///|
fn field(json : Json, key : String) -> Json {
  match json {
    Object(fields) => fields.get(key).unwrap()
    _ => panic()
  }
}

///|
fn items(json : Json) -> Array[Json] {
  match json {
    Array(values) => values
    _ => panic()
  }
}

///|
test "JSON roundtrip preserves raw unicode controls and empty result semantics" {
  let empty = completed_result([], @cli.Config::new())
  let json = @json.parse(empty.json_report())
  assert_eq(field(json, "schema_version"), Json(1))
  assert_eq(field(json, "source"), Json("中文\"\\\n.log"))
  assert_eq(field(field(json, "filter"), "from_inclusive"), Json::null())
  assert_eq(items(field(json, "spikes")).length(), 0)
  assert_eq(items(field(json, "buckets")).length(), 0)
  assert_eq(items(field(json, "context_windows")).length(), 0)
  assert_eq(field(field(json, "level_counts"), "OTHER"), Json(0))
  let raw = "{\"ts\":\"bad\",\"level\":\"ERROR\",\"msg\":\"中文\\n\\t\\u0000\\\"\\\\\"}"
  let result = completed_result([raw], @cli.Config::new(context=0), mode=Errors)
  let doc = @json.parse(result.json_report())
  let window = items(field(doc, "context_windows"))[0]
  assert_eq(field(items(field(window, "lines"))[0], "text"), Json(raw))
  assert_eq(
    field(items(field(doc, "signatures"))[0], "text"),
    Json("ERROR: 中文\n\t\u0000\"\\"),
  )
  assert_eq(field(field(doc, "summary"), "untimed"), Json(1))
  assert_eq(field(field(doc, "config"), "context_mode"), Json("errors"))
}

///|
test "structured output includes full rankings while terminal summary takes three" {
  let lines = ["2026-10-28 08:00:00 [INFO] healthy"]
  for name in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"] {
    lines.push("2026-10-28 08:05:00 [ERROR] " + name)
  }
  let result = completed_result(
    lines,
    @cli.Config::new(baseline_buckets=1, context=0),
  )
  let doc = @json.parse(result.json_report())
  let spike = items(field(doc, "spikes"))[0]
  assert_eq(field(spike, "start"), Json("2026-10-28 08:05:00Z"))
  assert_eq(field(spike, "end_exclusive"), Json("2026-10-28 08:10:00Z"))
  assert_eq(items(field(spike, "signatures")).length(), 12)
  assert_eq(items(field(doc, "signatures")).length(), 12)
  assert_eq(field(field(doc, "summary"), "errors"), Json(12))
  let summary = result.summary()
  assert_eq(summary.total, 13)
  assert_eq(summary.matched, 13)
  assert_eq(summary.errors, 12)
  assert_eq(summary.spikes.length(), 1)
  assert_eq(summary.spikes[0].retained_signature_count, 12)
  assert_eq(summary.spikes[0].top_signatures.length(), 3)
  assert_eq(summary.spikes[0].top_signatures[0].text, "ERROR: a")
  assert_eq(summary.spikes[0].omitted_signature_occurrences, 0)
}

///|
test "structured output preserves signature and context capacity omissions" {
  let result = completed_result(
    [
      "2026-10-28 08:00:00 [INFO] healthy", "2026-10-28 08:05:00 [ERROR] a", "2026-10-28 08:05:00 [ERROR] b",
      "2026-10-28 08:05:00 [ERROR] a",
    ],
    @cli.Config::new(baseline_buckets=1, max_signatures=1, max_samples=0),
  )
  let doc = @json.parse(result.json_report())
  let spike = items(field(doc, "spikes"))[0]
  assert_eq(field(spike, "errors"), Json(3))
  assert_eq(field(spike, "omitted_signature_occurrences"), Json(1))
  assert_eq(field(items(field(spike, "signatures"))[0], "count"), Json(2))
  assert_eq(items(field(doc, "context_windows")).length(), 0)
  let summary = result.summary()
  assert_eq(summary.sampled_targets, 0)
  assert_eq(summary.omitted_targets, 3)
  assert_eq(summary.omitted_global_signature_occurrences, 1)
  assert_eq(summary.spikes[0].omitted_signature_occurrences, 1)
}
