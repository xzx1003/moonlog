///|
fn completed_result(
  lines : Array[String],
  config : @cli.Config,
  mode~ : @cli.ContextMode = Spikes,
  signature~ : String? = None,
) -> @cli.ReportResult raise {
  let analyzer = @cli.Analyzer::new(config)
  for raw in lines {
    analyzer.feed(raw)
  }
  let analysis = analyzer.finish()
  let signatures = @cli.SpikeSignatureCollector::new(analysis)
  let contexts = @cli.ContextCollector::new(config)
  let comparison = match signature {
    Some(text) => Some(@cli.SignatureComparisonCollector::new(analysis, text))
    None => None
  }
  for raw in lines {
    ignore(signatures.feed(raw))
    match comparison {
      Some(collector) => collector.feed(raw)
      None => ()
    }
    contexts.feed(raw, analysis.is_target(raw, mode~, signature~))
  }
  @cli.ReportResult::new(
    analysis,
    contexts,
    signatures,
    mode,
    "中文\"\\\n.log",
    selected_signature=signature,
    signature_comparisons=match comparison {
      Some(collector) => collector.comparisons()
      None => []
    },
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
test "selected signature exports comparisons without touching other statistics" {
  let lines = [
    "2026-10-28 08:00:00 [INFO] healthy", "2026-10-28 08:00:00 [ERROR] sig 1", "2026-10-28 08:05:00 [ERROR] sig 2",
    "2026-10-28 08:10:00 [ERROR] sig 3", "2026-10-28 08:10:00 [ERROR] sig 4", "2026-10-28 08:10:00 [ERROR] other 9",
    "2026-10-28 08:20:00 [ERROR] sig 5", "2026-10-28 08:25:00 [ERROR] sig 6", "2026-10-28 08:30:00 [ERROR] sig 7",
    "2026-10-28 08:30:00 [ERROR] sig 8",
  ]
  let config = @cli.Config::new(
    baseline_buckets=2,
    multiplier=2,
    min_errors=2,
    context=0,
  )
  let plain = completed_result(lines, config)
  let picked = completed_result(lines, config, signature=Some("ERROR: sig #"))
  let before = @json.parse(plain.json_report())
  let after = @json.parse(picked.json_report())
  assert_eq(field(before, "selected_signature"), Json::null())
  assert_eq(field(before, "signature_comparisons"), Json::array([]))
  assert_eq(field(after, "selected_signature"), Json("ERROR: sig #"))
  for key in ["spikes", "signatures", "level_counts", "buckets"] {
    assert_eq(field(before, key).stringify(), field(after, key).stringify())
  }
  for
    key in [
      "log_error_ratio", "total", "matched", "untimed", "errors", "spike_count",
      "omitted_targets", "omitted_global_signature_occurrences",
    ] {
    assert_eq(
      field(field(before, "summary"), key).stringify(),
      field(field(after, "summary"), key).stringify(),
    )
  }
  let comparisons = items(field(after, "signature_comparisons"))
  assert_eq(comparisons.length(), 1)
  let first = comparisons[0]
  assert_eq(field(first, "signature"), Json("ERROR: sig #"))
  assert_eq(field(first, "before_start"), Json("2026-10-28 08:00:00Z"))
  assert_eq(field(first, "spike_start"), Json("2026-10-28 08:10:00Z"))
  assert_eq(field(first, "spike_end_exclusive"), Json("2026-10-28 08:15:00Z"))
  assert_eq(field(first, "before_minutes"), Json("10"))
  assert_eq(field(first, "spike_minutes"), Json("5"))
  assert_eq(field(first, "before_count"), Json("2"))
  assert_eq(field(first, "spike_count"), Json("2"))
  assert_eq(field(first, "before_per_minute"), Json(0.2))
  assert_eq(field(first, "spike_per_minute"), Json(0.4))
  assert_eq(field(first, "rate_multiplier"), Json(2.0))
  let summary = picked.summary()
  assert_eq(summary.selected_signature, Some("ERROR: sig #"))
  assert_eq(summary.signature_comparisons.length(), 1)
  assert_eq(summary.spikes.length(), 1)
  assert_eq(summary.spikes.length(), plain.summary().spikes.length())
  assert_eq(plain.summary().selected_signature, None)
  assert_eq(plain.summary().signature_comparisons.length(), 0)
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
