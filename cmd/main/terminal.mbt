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
fn spike_summary_lines(summary : @engine.SpikeSummary) -> Array[String] {
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
    "\{terminal_escape(s.text)} (\{s.count})"
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
  line("Source: \{terminal_escape(summary.source)}")
  line(
    "Scanned \{summary.total} lines; matched \{summary.matched}; untimed \{summary.untimed}; errors \{summary.errors}; spikes \{summary.spikes.length()}.",
  )
  if summary.spikes.is_empty() {
    line("No spikes met the rule; this does not imply the service was healthy.")
  } else {
    for i in 0..<summary.spikes.length() {
      let spike = summary.spikes[i]
      line(
        "Spike \{i + 1}: \{terminal_escape(spike.start)} to \{terminal_escape(spike.end_exclusive)} (end exclusive); errors \{spike.errors}.",
      )
      for text in spike_summary_lines(spike) {
        line(text)
      }
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
  line("\{format} report written to \{terminal_escape(report)}.")
  lines.join("\n")
}
