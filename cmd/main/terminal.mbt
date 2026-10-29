///|
// Log text and paths come from user input, so they can contain newlines, ESC and
// other control characters. Escape them before printing: a crafted signature
// must not be able to drive the terminal (CSI sequences, cursor movement, spoofed
// lines). This applies to terminal output only; JSON reports keep raw content.
fn hex_pad(value : Int32, width : Int32) -> String {
  let text = value.to_string(radix=16)
  let padding = if text.length() >= width {
    ""
  } else {
    "0".repeat(width - text.length())
  }
  padding + text
}

///|
fn terminal_escape(text : String) -> String {
  let out = StringBuilder()
  for ch in text.iter() {
    match ch {
      '\\' => out.write_string("\\\\")
      '\n' => out.write_string("\\n")
      '\r' => out.write_string("\\r")
      '\t' => out.write_string("\\t")
      _ => {
        let code = ch.to_int()
        if code < 32 || code == 127 {
          out.write_string("\\x" + hex_pad(code, 2))
        } else if code == 0x85 || code == 0x2028 || code == 0x2029 {
          out.write_string("\\u" + hex_pad(code, 4))
        } else {
          out.write_char(ch)
        }
      }
    }
  }
  out.to_string()
}

///|
fn spike_summary_lines(
  redactor : @engine.Redactor,
  summary : @engine.SpikeSummary,
) -> Array[String] {
  let lines : Array[String] = []
  let shown = summary.top_signatures.length()
  if shown == 0 {
    if summary.omitted_signature_occurrences > 0 {
      lines.push(
        "  No signature retained; all \{summary.omitted_signature_occurrences} error occurrence(s) were dropped after the shared signature capacity limit, so this spike is not error-free.",
      )
    } else {
      lines.push("  No signature retained for this spike.")
    }
    return lines
  }
  let ranked = summary.top_signatures.map(s => {
    "\{terminal_escape(redactor.apply(s.text))} (\{s.count})"
  })
  lines.push("  Top signatures (\{shown}): \{ranked.join(", ")}")
  if summary.retained_signature_count > shown {
    lines.push(
      "  Showing the top \{shown} of \{summary.retained_signature_count} retained signatures; the other \{summary.retained_signature_count - shown} are hidden by this display limit, not by capacity omissions.",
    )
  }
  if summary.omitted_signature_occurrences > 0 {
    lines.push(
      "  \{summary.omitted_signature_occurrences} occurrence(s) were omitted after the shared signature capacity limit; the spike error total still includes them.",
    )
  }
  lines
}

///|
// Comparison lines for the selected signature. Timestamps and counts come from
// the same values the Markdown and JSON reports print.
fn signature_comparison_lines(
  signature : String,
  comparisons : Array[@engine.SignatureComparison],
  redactor : @engine.Redactor,
) -> Array[String] {
  let lines : Array[String] = []
  fn line(text : String) -> Unit {
    lines.push(text)
  }
  line("Selected signature: \{terminal_escape(redactor.apply(signature))}")
  line(
    "  Exact match on the complete normalized signature; counts apply the level/keyword/time filters; the pre-spike window can contain earlier incidents and is not a healthy window.",
  )
  if comparisons.is_empty() {
    line(
      "  No spikes met the rule, so there is no comparison window; this does not mean the selected signature never occurred.",
    )
    return lines
  }
  let mut counted = 0L
  for i in 0..<comparisons.length() {
    let c = comparisons[i]
    let label = "  Spike \{i + 1}"
    counted += c.before_count + c.spike_count
    line(
      "\{label} baseline: \{terminal_escape(@engine.format_time(c.before_start))} to \{terminal_escape(@engine.format_time(c.spike_start))} (end exclusive); \{c.before_minutes} min; \{c.before_count} occurrence(s); \{@engine.format_per_minute(c.before_per_minute)} per minute.",
    )
    line(
      "\{label} spike: \{terminal_escape(@engine.format_time(c.spike_start))} to \{terminal_escape(@engine.format_time(c.spike_end))} (end exclusive); \{c.spike_minutes} min; \{c.spike_count} occurrence(s); \{@engine.format_per_minute(c.spike_per_minute)} per minute.",
    )
    match c.rate_multiplier {
      Some(value) =>
        line("\{label} rate multiplier: \{@engine.format_multiplier(value)}.")
      None =>
        line(
          "\{label} rate multiplier: N/A (zero baseline: \{c.before_count} occurrence(s) over \{c.before_minutes} min; spike \{c.spike_count} over \{c.spike_minutes} min).",
        )
    }
  }
  if counted == 0L {
    line(
      "  The selected signature was not counted inside these windows; it can still appear elsewhere in the log.",
    )
  }
  lines
}

///|
// Terminal evidence after a successful write. Used by both formats so the
// numbers cannot drift between the file and the console.
fn terminal_summary(
  summary : @engine.TerminalSummary,
  format : String,
  report : String,
) -> String {
  let lines : Array[String] = []
  fn line(text : String) -> Unit {
    lines.push(text)
  }
  if summary.sources.length() == 1 {
    line("Source: \{terminal_escape(summary.redactor.apply(summary.source))}")
  } else {
    line(
      "Sources: \{summary.sources.map(s => terminal_escape(summary.redactor.apply(s))).join(", ")}",
    )
  }
  line(
    "JSON fields: \{terminal_escape(summary.json_fields.label())} (exact top-level string keys; text logs unaffected).",
  )
  if summary.redactor.enabled() || !summary.redact_fields.is_empty() {
    line(
      "Redaction: output-only best-effort; \{summary.redactor.rule_count()} literal rule(s), \{summary.redact_fields.length()} JSON field rule(s) (raw JSON context lines only); not a guarantee that all sensitive data was removed.",
    )
  }
  line(
    "Scanned \{summary.total} lines; matched \{summary.matched}; untimed \{summary.untimed}; errors \{summary.errors}; spikes \{summary.spikes.length()}.",
  )
  line(
    "Sampling: \{summary.sampling.label()} (limit \{summary.sample_limit}); scans \{summary.scans}.",
  )
  line(
    "Log error ratio (all observed lines): \{@engine.format_ratio(summary.log_error_ratio)} (\{summary.log_error_ratio.errors}/\{summary.log_error_ratio.total}).",
  )
  line(
    "Ratio scope: time-valid lines only, OTHER included; level/keyword filters do not apply; untimed lines are excluded; a log-line share, not a request failure rate.",
  )
  if summary.spikes.is_empty() {
    line("No spikes met the rule; this does not imply the service was healthy.")
  } else {
    for i in 0..<summary.spikes.length() {
      let spike = summary.spikes[i]
      line(
        "Spike \{i + 1}: \{terminal_escape(spike.start)} to \{terminal_escape(spike.end_exclusive)} (end exclusive); errors \{spike.errors}.",
      )
      line(
        "  Log error ratio: \{@engine.format_ratio(spike.log_error_ratio)} (\{spike.log_error_ratio.errors}/\{spike.log_error_ratio.total}).",
      )
      for text in spike_summary_lines(summary.redactor, spike) {
        line(text)
      }
    }
  }
  if summary.selected_signature is Some(signature) {
    for
      text in signature_comparison_lines(
        signature,
        summary.signature_comparisons,
        summary.redactor,
      ) {
      line(text)
    }
  }
  line(
    "Context mode: \{summary.context_mode.label()}; sampled \{summary.sampled_targets}; omitted \{summary.omitted_targets}.",
  )
  if summary.omitted_global_signature_occurrences > 0 {
    line(
      "Signature capacity: \{summary.omitted_global_signature_occurrences} occurrence(s) were omitted from the global ranking after max_signatures was reached.",
    )
  }
  line(
    "\{format} report written to \{terminal_escape(summary.redactor.apply(report))}.",
  )
  lines.join("\n")
}
