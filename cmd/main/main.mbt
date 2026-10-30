///|
const Usage : String =
  #|MoonLog 0.1.0 - offline incident troubleshooting
  #|
  #|Usage: moonlog analyze <input.log> [<input2.log> ...] --report <incident.md> [options]
  #|
  #|  --config PATH        Explicit JSON defaults; CLI options override
  #|  --format FORMAT      Report format: markdown or json (default markdown)
  #|  --sampling MODE      Target selection: first or distributed (default first)
  #|  --bucket-minutes N   Time bucket width (default 5)
  #|  --baseline-buckets N Previous buckets in baseline (default 6)
  #|  --multiplier N       Strict spike multiplier (default 3)
  #|  --min-errors N       Minimum errors per spike bucket (default 3)
  #|  --context N          Physical lines before/after each target (default 10)
  #|  --context-mode MODE  Context targets: spikes or errors (default spikes)
  #|  --max-samples N      Maximum context targets (default 20)
  #|  --max-buckets N      Maximum bucket span (default 100000)
  #|  --max-signatures N   Maximum retained signatures (default 1000)
  #|  --max-line-bytes N   Maximum physical line bytes (default 65536)
  #|  --json-time-field K  Exact top-level JSON time key (default ts)
  #|  --json-level-field K Exact top-level JSON level key (default level)
  #|  --json-message-field K
  #|                       Exact top-level JSON message key (default msg)
  #|  --level LEVEL        DEBUG/INFO/WARN/ERROR/FATAL/OTHER
  #|  --keyword TEXT       Case-sensitive substring of the message
  #|  --signature SIG      Exact full signature for context and comparison,
  #|                       e.g. "ERROR: database timeout retry=#"
  #|  --from TIMESTAMP     Inclusive UTC minute, e.g. "2026-10-28 08:00:00"
  #|  --to TIMESTAMP       Inclusive UTC minute
  #|  --help               Show this help
  #|
  #|JSON fields are exact top-level string keys; "a.b" is a literal key, not a
  #|nested path. There is no fallback to ts/level/msg, no numeric conversion and
  #|no level lowercasing. Text log lines are parsed independently of this map.
  #|
  #|Redaction is config-file only: redact-text and redact-fields. Rules are
  #|never accepted on the command line, so they stay out of shell history.
  #|Redaction affects output only; statistics still use the original logs.
  #|JSON field rules cover raw JSON context lines. Parsed messages, signatures,
  #|paths, keywords and report hints need literal redact-text rules.
  #|Redaction is not a guarantee that all sensitive data was removed.
  #|
  #|Inputs must be stable, regular UTF-8 files. One file is scanned twice;
  #|multiple files, or --sampling distributed, are scanned three times.
  #|Duplicate and hard/symbolic-link aliased inputs are rejected.
  #|Existing report files are never overwritten. No network or AI calls.
  #|
  #|Both formats write the file first, then print a terminal summary on stdout.
  #|Only the file holds the report; the JSON file is valid JSON alone.
  #|JSON keeps raw context lines. --max-line-bytes is a host read limit and is
  #|not part of the core result config, so JSON config is not every CLI option.

///|
fn positive_or_zero(value : String, flag : String) -> Int32 raise {
  let n = @string.parse_int(value) catch {
    _ => fail("\{flag} expects an integer")
  }
  if n < 0 {
    fail("\{flag} must not be negative")
  }
  n
}

///|
fn timestamp(value : String, flag : String) -> Int64 raise {
  match @engine.parse_time(value) {
    Some(t) => t
    None => fail("\{flag}: invalid timestamp '\{value}'")
  }
}

///|
// A per-file stable identity captured during a scan: line count and raw-byte SHA-256
// digest. Each file must match across every pass, not just the aggregate total.
struct FileSnapshot {
  lines : Int64
  digest : String
}

///|
// Read one file and apply consume to every physical line. Returns the file's
// line count and raw-byte SHA-256 digest so the caller can verify it did not change.
fn scan_file(
  path : String,
  max_line_bytes : Int32,
  consume : (String) -> Unit raise,
  begin~ : () -> Unit raise = fn() { () },
) -> FileSnapshot raise {
  let digest = @engine.Sha256::new()
  let mut lines = 0L
  begin()
  @io.each_line(
    path,
    raw => {
      lines += 1
      consume(raw)
    },
    max_line_bytes~,
    observe=fn(byte) { digest.feed_byte(byte) },
  )
  { lines, digest: digest.hex(), }
}

///|
// Verify every file matches its earlier snapshot before proceeding.
fn verify_snapshots(
  files : Array[String],
  before : Array[FileSnapshot],
  after : Array[FileSnapshot],
) -> Unit raise {
  for i in 0..<files.length() {
    if before[i].lines != after[i].lines || before[i].digest != after[i].digest {
      fail("input changed between passes; analyze a stable snapshot instead")
    }
  }
}

///|
fn run(prepared : PreparedArgs) -> Unit raise {
  let args = prepared.args
  if args.length() < 2 {
    fail("expected analyze <input.log> --report <incident.md>; use --help")
  }
  if args[1] == "--help" || args[1] == "-h" {
    println(Usage)
    return
  }
  if args[1] == "--version" {
    println("MoonLog 0.1.0")
    return
  }
  if args[1] != "analyze" || args.length() < 3 {
    fail("expected analyze <input.log> --report <incident.md>; use --help")
  }
  if args[2] == "--help" || args[2] == "-h" {
    println(Usage)
    return
  }
  // Positional arguments before the first option are input files; the rest are
  // --flag value pairs. Input order is preserved and never re-sorted.
  let sources : Array[String] = []
  let mut i = 2
  while i < args.length() && !args[i].has_prefix("--") {
    sources.push(args[i])
    i += 1
  }
  if sources.is_empty() {
    fail("expected at least one input file; use --help")
  }
  let mut report = ""
  let mut format = "markdown"
  let mut sampling = @engine.SamplingMode::First
  let mut bucket_minutes = 5
  let mut baseline_buckets = 6
  let mut multiplier = 3
  let mut min_errors = 3
  let mut context = 10
  let mut context_mode = @engine.ContextMode::Spikes
  let mut max_samples = 20
  let mut max_buckets = 100000
  let mut max_signatures = 1000
  let mut max_line_bytes = 65536
  let mut json_time_field = "ts"
  let mut json_level_field = "level"
  let mut json_message_field = "msg"
  let mut level : @engine.Level? = None
  let mut keyword = ""
  let mut selected_signature : String? = None
  let mut from : Int64? = None
  let mut to : Int64? = None
  let seen : Map[String, Bool] = Map([])
  while i < args.length() {
    let flag = args[i]
    if flag == "--help" {
      println(Usage)
      return
    }
    if seen.contains(flag) {
      fail("duplicate option: \{flag}")
    }
    seen[flag] = true
    if i + 1 >= args.length() {
      fail("missing value for \{flag}")
    }
    let value = args[i + 1]
    match flag {
      "--report" => report = value
      "--format" =>
        match value {
          "markdown" => format = "markdown"
          "json" => format = "json"
          _ => fail("unknown format: \{value}; expected markdown or json")
        }
      "--sampling" =>
        match value {
          "first" => sampling = @engine.SamplingMode::First
          "distributed" => sampling = @engine.SamplingMode::Distributed
          _ =>
            fail(
              "unknown sampling mode: \{value}; expected first or distributed",
            )
        }
      "--bucket-minutes" => bucket_minutes = positive_or_zero(value, flag)
      "--baseline-buckets" => baseline_buckets = positive_or_zero(value, flag)
      "--multiplier" => multiplier = positive_or_zero(value, flag)
      "--min-errors" => min_errors = positive_or_zero(value, flag)
      "--context" => context = positive_or_zero(value, flag)
      "--context-mode" =>
        match value {
          "spikes" => context_mode = @engine.ContextMode::Spikes
          "errors" => context_mode = @engine.ContextMode::Errors
          _ => fail("unknown context mode: \{value}")
        }
      "--max-samples" => max_samples = positive_or_zero(value, flag)
      "--max-buckets" => max_buckets = positive_or_zero(value, flag)
      "--max-signatures" => max_signatures = positive_or_zero(value, flag)
      "--max-line-bytes" => max_line_bytes = positive_or_zero(value, flag)
      "--json-time-field" => json_time_field = value
      "--json-level-field" => json_level_field = value
      "--json-message-field" => json_message_field = value
      "--keyword" => keyword = value
      "--signature" => {
        // The value is a complete normalized signature. Reject an empty one
        // instead of silently normalizing or repairing user input.
        if value.trim() == "" {
          fail("--signature must not be empty")
        }
        selected_signature = Some(value)
      }
      "--level" => {
        let parsed = @engine.parse_level(value)
        if parsed == @engine.Other && value != "OTHER" {
          fail("unknown log level: \{value}")
        }
        level = Some(parsed)
      }
      "--from" => from = Some(timestamp(value, flag))
      "--to" => to = Some(timestamp(value, flag))
      _ => fail("unknown option: \{flag}")
    }
    i += 2
  }
  if report == "" {
    fail("--report <incident.md> is required")
  }
  for source in sources {
    if source == report {
      fail("input and report must be different paths")
    }
  }
  if from is Some(a) && to is Some(b) && a > b {
    fail("--from must not be after --to")
  }
  // Validate the complete mapping only after every field source (defaults,
  // config, CLI) has been applied, so partial overrides are checked together.
  let json_fields = @engine.JsonFields::new(
    time=json_time_field,
    level=json_level_field,
    message=json_message_field,
  )
  @io.ensure_distinct_output(report, sources)
  // Reject duplicate paths and hard/symbolic-link aliases using POSIX device
  // number and inode, never string comparison of paths or log content.
  let identities : Map[String, Bool] = Map([])
  for source in sources {
    let id = @io.stat_identity(source)
    if identities.contains(id) {
      fail("duplicate input file (same device and inode): \{source}")
    }
    identities[id] = true
  }
  let config = @engine.Config::new(
    bucket_minutes~,
    baseline_buckets~,
    multiplier~,
    min_errors~,
    context~,
    max_samples~,
    max_buckets~,
    max_signatures~,
  )
  let filter : @engine.Filter = { level, keyword, from, to, }
  // One analyzer sees every file in caller order, so time buckets and spikes
  // are shared across all inputs. File order only affects sampling and the
  // order in which signatures are retained under capacity pressure.
  let analyzer = @engine.Analyzer::new(config, filter~, json_fields~)

  // Pass 1: aggregate statistics across every file.
  let snapshots = Array::makei(sources.length(), i => {
    scan_file(sources[i], max_line_bytes, raw => analyzer.feed(raw))
  })
  let analysis = analyzer.finish()

  // The comparison collector exists only when a signature was requested; the
  // spike signature collector stays unconditional.
  let spike_signatures = @engine.SpikeSignatureCollector::new(analysis)
  let comparison = match selected_signature {
    Some(signature) =>
      Some(@engine.SignatureComparisonCollector::new(analysis, signature))
    None => None
  }

  let three_pass = sources.length() > 1 ||
    (match sampling {
      @engine.SamplingMode::Distributed => true
      @engine.SamplingMode::First => false
    })
  let first_contexts = @engine.ContextCollector::new(config)
  // Pass 2: count signatures, comparison windows and target occurrences.
  let mut target_total : Int64 = 0L
  let pass2 = Array::makei(sources.length(), i => {
    scan_file(sources[i], max_line_bytes, raw => {
      ignore(spike_signatures.feed(raw))
      if comparison is Some(collector) {
        collector.feed(raw)
      }
      let target = analysis.is_target(
        raw,
        mode=context_mode,
        signature=selected_signature,
      )
      if target {
        target_total += 1L
      }
      if !three_pass {
        first_contexts.feed(raw, target)
      }
    })
  })
  verify_snapshots(sources, snapshots, pass2)

  // Single file with the default first sampling keeps the two-pass path.
  // Multi-file and distributed sampling use a third pass to extract context.
  let file_windows : Array[@engine.FileContextWindow] = []
  let mut sampled : Int32 = 0
  let mut omitted : Int64 = 0L
  if !three_pass {
    // Two-pass single-file first sampling.
    let contexts = first_contexts
    sampled = contexts.sampled()
    omitted = contexts.omitted()
    for window in contexts.windows() {
      file_windows.push({ source: sources[0], window, })
    }
  } else {
    // Three-pass: sample context with a shared budget and per-file windows.
    let plan = @engine.SamplingPlan::new(target_total, max_samples, sampling)
    let collector = @engine.MultiFileContextCollector::new(config, plan)
    let pass3 = Array::makei(sources.length(), i => {
      let source = sources[i]
      scan_file(
        source,
        max_line_bytes,
        raw => {
          collector.feed(
            raw,
            analysis.is_target(
              raw,
              mode=context_mode,
              signature=selected_signature,
            ),
          )
        },
        begin=fn() { collector.begin_file(source) },
      )
    })
    verify_snapshots(sources, snapshots, pass3)
    sampled = collector.sampled()
    omitted = collector.omitted()
    for file_window in collector.finish() {
      file_windows.push(file_window)
    }
  }

  let signature_comparisons = match comparison {
    Some(collector) => collector.comparisons()
    None => []
  }
  let result = @engine.ReportResult::new(
    analysis,
    file_windows,
    sampled,
    omitted,
    spike_signatures,
    context_mode,
    sources,
    sampling~,
    scans=if three_pass { 3 } else { 2 },
    sample_limit=max_samples,
    selected_signature~,
    signature_comparisons~,
    redactor=prepared.redactor,
    redact_fields=prepared.redact_fields,
  )
  let content = if format == "json" {
    result.json_report()
  } else {
    @engine.markdown_report(
      analysis,
      file_windows,
      sampled,
      omitted,
      spike_signatures,
      context_mode,
      sources,
      sampling~,
      scans=if three_pass { 3 } else { 2 },
      selected_signature~,
      signature_comparisons~,
      redactor=prepared.redactor,
      redact_fields=prepared.redact_fields,
    )
  }
  @io.write_report(report, content)
  let label = if format == "json" { "JSON" } else { "Markdown" }
  println(terminal_summary(result.summary(), label, report))
}

///|
fn failure_message(message : String) -> String {
  match message.split_once(" FAILED: ") {
    Some((_, detail)) => detail.to_owned()
    None => message
  }
}

///|
fn print_failure(message : String, redactor : @engine.Redactor) -> Unit {
  @io.stderr("moonlog: \{terminal_escape(redactor.apply(message))}")
  @io.exit(1)
}

///|
fn main {
  let outcome : Result[PreparedArgs, String] = Ok(config_args(@env.args())) catch {
    Failure(message) => Err(failure_message(message))
    error => Err("\{error}")
  }
  match outcome {
    Ok(prepared) =>
      run(prepared) catch {
        Failure(message) =>
          print_failure(failure_message(message), prepared.diagnostic_redactor)
        error => print_failure("\{error}", prepared.diagnostic_redactor)
      }
    Err(message) => print_failure(message, @engine.Redactor::none())
  }
}
