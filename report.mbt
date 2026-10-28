///|
fn safe_markdown(text : String) -> String {
  let out = StringBuilder()
  for ch in text.iter() {
    if ch == '\n' || ch == '\r' {
      out.write_char(' ')
    } else if ch < ' ' {
      out.write_string("?")
    } else if ch == '<' {
      out.write_string("&lt;")
    } else if ch == '>' {
      out.write_string("&gt;")
    } else if ch == '&' {
      out.write_string("&amp;")
    } else if ch == '|' {
      out.write_string("&#124;")
    } else if ch == '`' {
      out.write_string("&#96;")
    } else if ch == '[' ||
      ch == ']' ||
      ch == '*' ||
      ch == '_' ||
      ch == '\\' ||
      ch == '#' {
      out.write_char('\\')
      out.write_char(ch)
    } else {
      out.write_char(ch)
    }
  }
  out.to_string()
}

///|
fn code_fence(windows : Array[ContextWindow]) -> String {
  let mut longest = 2
  for window in windows {
    for line in window.lines {
      let mut run = 0
      for ch in line.text.iter() {
        if ch == '`' {
          run += 1
          if run > longest {
            longest = run
          }
        } else {
          run = 0
        }
      }
    }
  }
  "`".repeat(longest + 1)
}

///|
pub fn markdown_report(
  analysis : Analysis,
  contexts : ContextCollector,
  source : String,
) -> String {
  let out = StringBuilder()
  fn line(text : String) -> Unit {
    out.write_string(text)
    out.write_char('\n')
  }
  let c = analysis.config
  line("# MoonLog Incident Report")
  line("")
  line(
    "Deterministic log evidence; spike detection does not establish a root cause.",
  )
  line("")
  line("## Summary")
  line("")
  line("- Source: \{safe_markdown(source)}")
  line("- Engine: MoonLog 0.1.0 / native MoonBit")
  line("- Lines scanned: \{analysis.total}")
  line("- Lines matching filters: \{analysis.matched}")
  line("- Matched lines without a valid timestamp: \{analysis.untimed}")
  let errors = analysis.counts.get_or_default("ERROR", 0) +
    analysis.counts.get_or_default("FATAL", 0)
  line("- ERROR + FATAL: \{errors}")
  line("- Detected spikes: \{analysis.spikes.length()}")
  line(
    "- Context targets sampled: \{contexts.sampled()} (limit \{c.max_samples}); omitted: \{contexts.omitted()}",
  )
  line(
    "- Untracked signature occurrences after capacity limit: \{analysis.overflow_signatures}",
  )
  if analysis.buckets.get(0) is Some(first) &&
    analysis.buckets.last() is Some(last) {
    line(
      "- Bucket coverage (end exclusive): \{format_time(first.start)} to \{format_time(last.start + c.bucket_minutes.to_int64())}",
    )
  }
  line("")
  line("## Rules and filters")
  line("")
  line(
    "- Bucket size: \{c.bucket_minutes} minutes, UTC-aligned; empty buckets count as zero.",
  )
  line(
    "- Baseline: previous \{c.baseline_buckets} complete buckets, excluding the current bucket.",
  )
  line(
    "- Spike: ERROR + FATAL strictly greater than \{c.multiplier} times baseline, with at least \{c.min_errors} errors.",
  )
  line(
    "- Zero baseline: trigger at minimum error count. Warm-up: no detection until a full baseline exists.",
  )
  line(
    "- Adjacent flagged buckets merge; incident end is the exclusive bucket boundary.",
  )
  line(
    "- Timestamps without offsets are interpreted as UTC; seconds/fractions are floored to minutes.",
  )
  line(
    "- Context: up to \{c.context} physical lines on either side; overlapping/adjacent windows merge. Context includes unfiltered evidence.",
  )
  line(
    "- Level: \{match analysis.filter.level {Some(l) => l.label(); None => "all"}}",
  )
  line(
    "- Message keyword (case-sensitive): \{safe_markdown(analysis.filter.keyword)}",
  )
  line(
    "- From (inclusive minute): \{match analysis.filter.from {Some(t) => format_time(t); None => "unbounded"}}",
  )
  line(
    "- To (inclusive minute): \{match analysis.filter.to {Some(t) => format_time(t); None => "unbounded"}}",
  )
  line("")
  line("## Level counts (matching filters)")
  line("")
  line("| Level | Count |")
  line("| --- | ---: |")
  for level in ["DEBUG", "INFO", "WARN", "ERROR", "FATAL", "OTHER"] {
    line("| \{level} | \{analysis.counts.get_or_default(level,0)} |")
  }
  line("")
  line("## Detected spikes")
  line("")
  if analysis.spikes.is_empty() {
    line("No spikes met the rule. This does not imply the service was healthy.")
  } else {
    line(
      "| Start UTC | End UTC (exclusive) | Errors | Peak per bucket | Baseline at start |",
    )
    line("| --- | --- | ---: | ---: | ---: |")
    for spike in analysis.spikes {
      line(
        "| \{format_time(spike.start)} | \{format_time(spike.end)} | \{spike.errors} | \{spike.peak_errors} | \{spike.baseline} |",
      )
    }
  }
  line("")
  line("## Top error signatures (matching filters)")
  line("")
  line(
    "Decimal runs become #; the message portion is capped at 512 characters (the level prefix is outside the cap). Counts cover retained signatures only.",
  )
  line("")
  line("| Signature | Occurrences |")
  line("| --- | ---: |")
  for i in 0..<analysis.signatures.length() {
    if i >= 10 {
      break
    }
    let s = analysis.signatures[i]
    line("| \{safe_markdown(s.text)} | \{s.count} |")
  }
  line("")
  line("## Context evidence")
  line("")
  let windows = contexts.windows()
  if windows.is_empty() {
    line(
      "No sampled spike context. Raw stack/unknown lines are preserved only as surrounding evidence.",
    )
  }
  let fence = code_fence(windows)
  for i in 0..<windows.length() {
    let window = windows[i]
    line("### Window \{i+1}")
    line("")
    line(
      "Target source lines: \{window.targets.map(fn(n){n.to_string()}).join(", ")}. `>` marks sampled targets.",
    )
    line("")
    line(fence + "text")
    for source_line in window.lines {
      let mark = if window.targets.contains(source_line.number) {
        ">"
      } else {
        " "
      }
      line("\{mark} \{source_line.number}: \{source_line.text}")
    }
    line(fence)
    line("")
  }
  out.to_string()
}
