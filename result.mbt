///|
// A view of the completed analysis. Construct only after verifying that every
// input file's line count and digest stayed stable across the scans; do not
// feed collectors after construction. Windows are per-file (FileContextWindow),
// each carrying its own source and file-local line numbers.
pub struct ReportResult {
  analysis : Analysis
  file_windows : Array[FileContextWindow]
  sampled : Int32
  omitted : Int64
  spike_signatures : SpikeSignatureCollector
  context_mode : ContextMode
  sources : Array[String]
  sampling : SamplingMode
  scans : Int32
  sample_limit : Int32
  selected_signature : String?
  signature_comparisons : Array[SignatureComparison]
  redactor : Redactor
  redact_fields : Array[String]
}

///|
pub fn ReportResult::new(
  analysis : Analysis,
  file_windows : Array[FileContextWindow],
  sampled : Int32,
  omitted : Int64,
  spike_signatures : SpikeSignatureCollector,
  context_mode : ContextMode,
  sources : Array[String],
  sampling~ : SamplingMode = First,
  scans~ : Int32 = 2,
  sample_limit~ : Int32 = 20,
  selected_signature~ : String? = None,
  signature_comparisons~ : Array[SignatureComparison] = [],
  redactor~ : Redactor = Redactor::none(),
  redact_fields~ : Array[String] = [],
) -> ReportResult {
  {
    analysis,
    file_windows,
    sampled,
    omitted,
    spike_signatures,
    context_mode,
    sources,
    sampling,
    scans,
    sample_limit,
    selected_signature,
    signature_comparisons,
    redactor,
    redact_fields: redact_fields.copy(),
  }
}

///|
pub(all) struct SpikeSummary {
  log_error_ratio : LogErrorRatio
  start : String
  end_exclusive : String
  errors : Int64
  top_signatures : Array[Signature]
  retained_signature_count : Int32
  omitted_signature_occurrences : Int64
}

///|
pub(all) struct TerminalSummary {
  log_error_ratio : LogErrorRatio
  source : String
  sources : Array[String]
  sampling : SamplingMode
  scans : Int32
  sample_limit : Int32
  json_fields : JsonFields
  total : Int64
  matched : Int64
  untimed : Int64
  errors : Int64
  context_mode : ContextMode
  sampled_targets : Int32
  omitted_targets : Int64
  omitted_global_signature_occurrences : Int64
  spikes : Array[SpikeSummary]
  selected_signature : String?
  signature_comparisons : Array[SignatureComparison]
  redactor : Redactor
  redact_fields : Array[String]
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
      log_error_ratio: a.log_error_ratio(start=Some(s.start), end=Some(s.end)),
      start: format_time(s.start),
      end_exclusive: format_time(s.end),
      errors: s.errors,
      top_signatures: top,
      retained_signature_count: signatures.length(),
      omitted_signature_occurrences: self.spike_signatures.omitted(i),
    }
  })
  {
    log_error_ratio: a.log_error_ratio(),
    source: if self.sources.length() == 1 {
      self.sources[0]
    } else {
      ""
    },
    sources: self.sources.copy(),
    sampling: self.sampling,
    scans: self.scans,
    sample_limit: self.sample_limit,
    json_fields: a.json_fields,
    total: a.total,
    matched: a.matched,
    untimed: a.untimed,
    errors: a.counts.get_or_default("ERROR", 0) +
    a.counts.get_or_default("FATAL", 0),
    context_mode: self.context_mode,
    sampled_targets: self.sampled,
    omitted_targets: self.omitted,
    omitted_global_signature_occurrences: a.overflow_signatures,
    spikes,
    selected_signature: self.selected_signature,
    signature_comparisons: self.signature_comparisons,
    redactor: self.redactor,
    redact_fields: self.redact_fields.copy(),
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
fn result_signatures(
  signatures : Array[Signature],
  redactor : Redactor,
) -> Json {
  Json::array(
    signatures.map(s => {
      Json::object({
        "text": Json(redactor.apply(s.text)),
        "count": Json(s.count.to_double()),
      })
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
    counts[level] = Json(a.counts.get_or_default(level, 0L).to_double())
  }
  let spikes = Array::makei(a.spikes.length(), fn(i) {
    let s = a.spikes[i]
    Json::object({
      "log_error_ratio": a
      .log_error_ratio(start=Some(s.start), end=Some(s.end))
      .to_json(),
      "start": Json(format_time(s.start)),
      "end_exclusive": Json(format_time(s.end)),
      "errors": Json(s.errors.to_double()),
      "peak_errors": Json(s.peak_errors.to_double()),
      "baseline": Json(s.baseline),
      "signatures": result_signatures(
        self.spike_signatures.signatures(i),
        self.redactor,
      ),
      "omitted_signature_occurrences": Json(
        self.spike_signatures.omitted(i).to_double(),
      ),
    })
  })
  let windows = self.file_windows.map(fw => {
    Json::object({
      "source": Json(self.redactor.apply(fw.source)),
      "targets": Json::array(fw.window.targets.map(n => Json(n.to_double()))),
      "lines": Json::array(
        fw.window.lines.map(line => {
          Json::object({
            "number": Json(line.number.to_double()),
            "text": Json(
              redact_raw_line(self.redactor, self.redact_fields, line.text),
            ),
          })
        }),
      ),
    })
  })
  let document = Json::object({
    "selected_signature": match self.selected_signature {
      Some(s) => Json(self.redactor.apply(s))
      None => Json::null()
    },
    "signature_comparisons": Json::array(
      self.signature_comparisons.map(c => c.to_json(redactor=self.redactor)),
    ),
    "json_fields": a.json_fields.to_json(),
    "schema_version": Json(1),
    "engine_version": Json("0.1.0"),
    "source": match self.sources.length() {
      1 => Json(self.redactor.apply(self.sources[0]))
      _ => Json::null()
    },
    "sources": Json::array(self.sources.map(s => Json(self.redactor.apply(s)))),
    "sampling": Json(self.sampling.label()),
    "scans": Json(self.scans),
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
      "keyword": Json(self.redactor.apply(f.keyword)),
      "from_inclusive": result_time(f.from),
      "to_inclusive": result_time(f.to),
    }),
    "time_semantics": Json(
      "UTC; seconds floored to minutes; filters inclusive; spike ends exclusive",
    ),
    "log_error_ratio_semantics": Json(
      "Time-valid physical log lines within inclusive time filters; independent of level and keyword; ERROR/FATAL divided by all levels; fraction 0..1, null for zero denominator; not a request failure rate",
    ),
    "summary": Json::object({
      "log_error_ratio": a.log_error_ratio().to_json(),
      "total": Json(a.total.to_double()),
      "matched": Json(a.matched.to_double()),
      "untimed": Json(a.untimed.to_double()),
      "errors": Json(
        (a.counts.get_or_default("ERROR", 0L) +
        a.counts.get_or_default("FATAL", 0L)).to_double(),
      ),
      "spike_count": Json(a.spikes.length()),
      "sampled_targets": Json(self.sampled),
      "omitted_targets": Json(self.omitted.to_double()),
      "omitted_global_signature_occurrences": Json(
        a.overflow_signatures.to_double(),
      ),
    }),
    "level_counts": Json::object(counts),
    "buckets": Json::array(
      a.buckets.map(b => {
        Json::object({
          "start": Json(format_time(b.start)),
          "end_exclusive": Json(
            format_time(b.start + c.bucket_minutes.to_int64()),
          ),
          "total": Json(b.total.to_double()),
          "errors": Json(b.errors.to_double()),
        })
      }),
    ),
    "observation_buckets": Json::array(
      a.observation_buckets.map(b => {
        Json::object({
          "start": Json(format_time(b.start)),
          "end_exclusive": Json(
            format_time(b.start + c.bucket_minutes.to_int64()),
          ),
          "log_error_ratio": b.log_error_ratio().to_json(),
        })
      }),
    ),
    "spikes": Json::array(spikes),
    "signatures": result_signatures(a.signatures, self.redactor),
    "context_windows": Json::array(windows),
    "diagnostic_note": Json(
      "Rule-based evidence; spikes do not establish a root cause. Signature counts cover retained signatures only; context contains unfiltered original lines.",
    ),
  })
  if redaction_enabled(self.redactor, self.redact_fields) {
    match document {
      Object(fields) =>
        fields["redaction"] = self.redactor.metadata(
          self.redact_fields.length(),
        )
      _ => ()
    }
  }
  document
}

///|
pub fn ReportResult::json_report(self : ReportResult) -> String {
  self.to_json().stringify(indent=2) + "\n"
}
