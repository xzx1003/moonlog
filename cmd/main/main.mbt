///|
const Usage : String =
  #|MoonLog 0.1.0 - offline incident troubleshooting
  #|
  #|Usage: moonlog analyze <input.log> --report <incident.md> [options]
  #|
  #|  --format FORMAT      Report format: markdown or json (default markdown)
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
  #|  --level LEVEL        DEBUG/INFO/WARN/ERROR/FATAL/OTHER
  #|  --keyword TEXT       Case-sensitive substring of the message
  #|  --signature SIG      Exact full signature for context and comparison,
  #|                       e.g. "ERROR: database timeout retry=#"
  #|  --from TIMESTAMP     Inclusive UTC minute, e.g. "2026-10-28 08:00:00"
  #|  --to TIMESTAMP       Inclusive UTC minute
  #|  --help               Show this help
  #|
  #|Input must be a stable, regular UTF-8 file; it is scanned twice.
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
fn update_digest(digest : UInt64, raw : String) -> UInt64 {
  (digest * 1099511628211UL) ^ raw.hash().reinterpret_as_uint().to_uint64()
}

///|
fn run(args : Array[String]) -> Unit raise {
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
  let source = args[2]
  let mut report = ""
  let mut format = "markdown"
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
  let mut level : @engine.Level? = None
  let mut keyword = ""
  let mut selected_signature : String? = None
  let mut from : Int64? = None
  let mut to : Int64? = None
  let seen : Map[String, Bool] = Map([])
  let mut i = 3
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
  if source == report {
    fail("input and report must be different paths")
  }
  if from is Some(a) && to is Some(b) && a > b {
    fail("--from must not be after --to")
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
  let analyzer = @engine.Analyzer::new(config, filter~)
  let mut first_digest = 14695981039346656037UL
  @io.each_line(
    source,
    raw => {
      first_digest = update_digest(first_digest, raw)
      analyzer.feed(raw)
    },
    max_line_bytes~,
  )
  let analysis = analyzer.finish()
  let contexts = @engine.ContextCollector::new(config)
  let spike_signatures = @engine.SpikeSignatureCollector::new(analysis)
  // The comparison collector exists only when a signature was requested; the
  // spike signature collector stays unconditional.
  let comparison = match selected_signature {
    Some(signature) =>
      Some(@engine.SignatureComparisonCollector::new(analysis, signature))
    None => None
  }
  let mut second_digest = 14695981039346656037UL
  let mut second_lines = 0
  @io.each_line(
    source,
    raw => {
      second_digest = update_digest(second_digest, raw)
      second_lines += 1
      ignore(spike_signatures.feed(raw))
      if comparison is Some(collector) {
        collector.feed(raw)
      }
      contexts.feed(
        raw,
        analysis.is_target(raw, mode=context_mode, signature=selected_signature),
      )
    },
    max_line_bytes~,
  )
  if first_digest != second_digest || second_lines != analysis.total {
    fail("input changed between passes; analyze a stable snapshot instead")
  }
  let signature_comparisons = match comparison {
    Some(collector) => collector.comparisons()
    None => []
  }
  let result = @engine.ReportResult::new(
    analysis,
    contexts,
    spike_signatures,
    context_mode,
    source,
    selected_signature~,
    signature_comparisons~,
  )
  let content = if format == "json" {
    result.json_report()
  } else {
    @engine.markdown_report(
      analysis,
      contexts,
      spike_signatures,
      context_mode,
      source,
      selected_signature~,
      signature_comparisons~,
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
fn main {
  run(@env.args()) catch {
    Failure(message) => {
      @io.stderr("moonlog: \{terminal_escape(failure_message(message))}")
      @io.exit(1)
    }
    error => {
      @io.stderr("moonlog: \{terminal_escape("\{error}")}")
      @io.exit(1)
    }
  }
}
