///|
// A view of the completed two-pass analysis. Construct only after verifying
// that the input did not change; do not feed collectors after construction.
pub struct ReportResult {
  analysis : Analysis
  contexts : ContextCollector
  spike_signatures : SpikeSignatureCollector
  context_mode : ContextMode
  source : String
}

///|
pub fn ReportResult::new(
  analysis : Analysis,
  contexts : ContextCollector,
  spike_signatures : SpikeSignatureCollector,
  context_mode : ContextMode,
  source : String,
) -> ReportResult {
  { analysis, contexts, spike_signatures, context_mode, source, }
}

///|
pub(all) struct SpikeSummary {
  start : String
  end_exclusive : String
  errors : Int32
  top_signatures : Array[Signature]
  retained_signature_count : Int32
  omitted_signature_occurrences : Int32
}

///|
pub(all) struct TerminalSummary {
  source : String
  total : Int32
  matched : Int32
  untimed : Int32
  errors : Int32
  context_mode : ContextMode
  sampled_targets : Int32
  omitted_targets : Int32
  omitted_global_signature_occurrences : Int32
  spikes : Array[SpikeSummary]
}

///|
pub fn ReportResult::summary(self : ReportResult) -> TerminalSummary {
  let a = self.analysis
  let spikes = Array::makei(a.spikes.length(), fn(i) {
    let s = a.spikes[i]
    let signatures = self.spike_signatures.signatures(i)
    let top : Array[Signature] = []
    for j in 0..<signatures.length() {
      if j >= 3 {
        break
      }
      top.push(signatures[j])
    }
    {
      start: format_time(s.start),
      end_exclusive: format_time(s.end),
      errors: s.errors,
      top_signatures: top,
      retained_signature_count: signatures.length(),
      omitted_signature_occurrences: self.spike_signatures.omitted(i),
    }
  })
  {
    source: self.source,
    total: a.total,
    matched: a.matched,
    untimed: a.untimed,
    errors: a.counts.get_or_default("ERROR", 0) +
    a.counts.get_or_default("FATAL", 0),
    context_mode: self.context_mode,
    sampled_targets: self.contexts.sampled(),
    omitted_targets: self.contexts.omitted(),
    omitted_global_signature_occurrences: a.overflow_signatures,
    spikes,
  }
}

///|
fn result_time(value : Int64?) -> Json {
  match value {
    Some(t) => Json(format_time(t))
    None => Json::null()
  }
}

///|
fn result_signatures(signatures : Array[Signature]) -> Json {
  Json::array(
    signatures.map(s => {
      Json::object({ "text": Json(s.text), "count": Json(s.count) })
    }),
  )
}

///|
// All retained signatures are exported, not just Markdown's top ten.
// Arrays have stable source/time/ranking order. Object key order is not a contract.
pub fn ReportResult::to_json(self : ReportResult) -> Json {
  let a = self.analysis
  let c = a.config
  let f = a.filter
  let counts : Map[String, Json] = Map([])
  for level in ["DEBUG", "INFO", "WARN", "ERROR", "FATAL", "OTHER"] {
    counts[level] = Json(a.counts.get_or_default(level, 0))
  }
  let spikes = Array::makei(a.spikes.length(), fn(i) {
    let s = a.spikes[i]
    Json::object({
      "start": Json(format_time(s.start)),
      "end_exclusive": Json(format_time(s.end)),
      "errors": Json(s.errors),
      "peak_errors": Json(s.peak_errors),
      "baseline": Json(s.baseline),
      "signatures": result_signatures(self.spike_signatures.signatures(i)),
      "omitted_signature_occurrences": Json(self.spike_signatures.omitted(i)),
    })
  })
  let windows = self.contexts
    .windows()
    .map(w => {
      Json::object({
        "targets": Json(w.targets),
        "lines": Json::array(
          w.lines.map(line => {
            Json::object({
              "number": Json(line.number),
              "text": Json(line.text),
            })
          }),
        ),
      })
    })
  Json::object({
    "schema_version": Json(1),
    "engine_version": Json("0.1.0"),
    "source": Json(self.source),
    "config": Json::object({
      "bucket_minutes": Json(c.bucket_minutes),
      "baseline_buckets": Json(c.baseline_buckets),
      "multiplier": Json(c.multiplier),
      "min_errors": Json(c.min_errors),
      "context": Json(c.context),
      "context_mode": Json(self.context_mode.label()),
      "max_samples": Json(c.max_samples),
      "max_buckets": Json(c.max_buckets),
      "max_signatures": Json(c.max_signatures),
    }),
    "filter": Json::object({
      "level": match f.level {
        Some(l) => Json(l.label())
        None => Json::null()
      },
      "keyword": Json(f.keyword),
      "from_inclusive": result_time(f.from),
      "to_inclusive": result_time(f.to),
    }),
    "time_semantics": Json(
      "UTC; seconds floored to minutes; filters inclusive; spike ends exclusive",
    ),
    "summary": Json::object({
      "total": Json(a.total),
      "matched": Json(a.matched),
      "untimed": Json(a.untimed),
      "errors": Json(
        a.counts.get_or_default("ERROR", 0) +
        a.counts.get_or_default("FATAL", 0),
      ),
      "spike_count": Json(a.spikes.length()),
      "sampled_targets": Json(self.contexts.sampled()),
      "omitted_targets": Json(self.contexts.omitted()),
      "omitted_global_signature_occurrences": Json(a.overflow_signatures),
    }),
    "level_counts": Json::object(counts),
    "buckets": Json::array(
      a.buckets.map(b => {
        Json::object({
          "start": Json(format_time(b.start)),
          "end_exclusive": Json(
            format_time(b.start + c.bucket_minutes.to_int64()),
          ),
          "total": Json(b.total),
          "errors": Json(b.errors),
        })
      }),
    ),
    "spikes": Json::array(spikes),
    "signatures": result_signatures(a.signatures),
    "context_windows": Json::array(windows),
    "diagnostic_note": Json(
      "Rule-based evidence; spikes do not establish a root cause. Signature counts cover retained signatures only; context contains unfiltered original lines.",
    ),
  })
}

///|
pub fn ReportResult::json_report(self : ReportResult) -> String {
  self.to_json().stringify(indent=2) + "\n"
}
