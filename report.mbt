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
fn code_fence(file_windows : Array[FileContextWindow]) -> String {
  let mut longest = 2
  for file_window in file_windows {
    for line in file_window.window.lines {
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
// Ratios are shares of log lines. "N/A" marks an empty denominator (no
// time-valid line in the range), which is not the same as 0%.
pub fn format_ratio(ratio : LogErrorRatio) -> String {
  match ratio.fraction {
    None => "N/A"
    Some(fraction) => {
      let tenths = (fraction * 1000.0 + 0.5).to_int()
      "\{tenths / 10}.\{tenths % 10}%"
    }
  }
}

///|
// Rates are per-minute shares of a compared window. Three decimals keep small
// baselines readable without implying precision the integer counts do not have.
pub fn format_per_minute(value : Double) -> String {
  let thousandths = (value * 1000.0 + 0.5).to_int64()
  "\{thousandths / 1000L}.\{(thousandths % 1000L).to_string().pad_start(3, '0')}"
}

///|
// Only call this for a defined multiplier: a zero baseline has no ratio.
pub fn format_multiplier(value : Double) -> String {
  let hundredths = (value * 100.0 + 0.5).to_int64()
  "\{hundredths / 100L}.\{(hundredths % 100L).to_string().pad_start(2, '0')}x"
}

///|
pub fn markdown_report(
  analysis : Analysis,
  file_windows : Array[FileContextWindow],
  sampled : Int32,
  omitted : Int32,
  spike_signatures : SpikeSignatureCollector,
  context_mode : ContextMode,
  sources : Array[String],
  sampling~ : SamplingMode = First,
  scans~ : Int32 = 2,
  selected_signature~ : String? = None,
  signature_comparisons~ : Array[SignatureComparison] = [],
) -> String {
  let out = StringBuilder()
  fn line(text : String) -> Unit {
    out.write_string(text)
    out.write_char('\n')
  }
  let c = analysis.config
  let overall = analysis.log_error_ratio()
  let context_targets = if context_mode == Spikes {
    "ERROR + FATAL records inside detected spikes"
  } else {
    "all matching ERROR + FATAL records; untimed records are excluded when a time bound is set"
  }
  line("# MoonLog Incident Report")
  line("")
  line(
    "Deterministic log evidence; spike detection does not establish a root cause.",
  )
  line("")
  line("## Summary")
  line("")
  if sources.length() == 1 {
    line("- Source: \{safe_markdown(sources[0])}")
  } else {
    line("- Sources: \{sources.map(fn(s) { safe_markdown(s) }).join(", ")}")
  }
  line("- Engine: MoonLog 0.1.0 / native MoonBit")
  line("- Lines scanned: \{analysis.total}")
  line("- Lines matching filters: \{analysis.matched}")
  line("- Matched lines without a valid timestamp: \{analysis.untimed}")
  let errors = analysis.counts.get_or_default("ERROR", 0) +
    analysis.counts.get_or_default("FATAL", 0)
  line("- ERROR + FATAL: \{errors}")
  line(
    "- Log error ratio (all observed lines, before level/keyword filters): \{format_ratio(overall)} (\{overall.errors} of \{overall.total} time-valid lines)",
  )
  line("- Detected spikes: \{analysis.spikes.length()}")
  line(
    "- Context targets sampled: \{sampled} (limit \{c.max_samples}); omitted: \{omitted}",
  )
  line("- Sampling mode: \{sampling.label()}; scans: \{scans}")
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
  line("- Context mode: \{context_mode.label()}; targets: \{context_targets}.")
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
    if context_mode == Errors {
      line(
        "Error context is still collected from matching ERROR + FATAL records in errors mode.",
      )
    }
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
  line("## Error signatures by spike")
  line("")
  line(
    "Signatures count only ERROR/FATAL records inside each spike after filters. All spikes share one capacity (max_signatures = \{c.max_signatures}), so the same signature in different spikes occupies separate slots. Tables show at most the top 10 retained signatures; capacity omissions are reported separately.",
  )
  line("")
  if analysis.spikes.is_empty() {
    line("No spikes met the rule, so there are no per-spike signatures.")
    line("")
  } else {
    for i in 0..<analysis.spikes.length() {
      let spike = analysis.spikes[i]
      let signatures = spike_signatures.signatures(i)
      let omitted = spike_signatures.omitted(i)
      line(
        "### Spike \{i+1}: \{format_time(spike.start)} to \{format_time(spike.end)}",
      )
      line("")
      line(
        "Spike ERROR + FATAL records: \{spike.errors}; occurrences omitted by capacity: \{omitted}.",
      )
      line("")
      line("| Signature | Occurrences |")
      line("| --- | ---: |")
      for j in 0..<signatures.length() {
        if j >= 10 {
          break
        }
        let s = signatures[j]
        line("| \{safe_markdown(s.text)} | \{s.count} |")
      }
      if signatures.is_empty() || signatures.length() > 10 || omitted > 0 {
        line("")
      }
      if signatures.is_empty() {
        if omitted > 0 {
          line(
            "No signatures were retained for this spike. This does not mean the spike had no errors: all \{omitted} error occurrence(s) were dropped after the shared signature capacity was reached.",
          )
        } else {
          line("No signatures were retained for this spike.")
        }
      }
      if signatures.length() > 10 {
        line(
          "Showing the top 10 of \{signatures.length()} retained signatures; the other \{signatures.length() - 10} are hidden by this display limit, not by capacity.",
        )
      }
      if omitted > 0 && !signatures.is_empty() {
        line(
          "\{omitted} error occurrence(s) were omitted after the shared signature capacity limit was reached; they are included in the spike error total but cannot be attributed to a retained signature.",
        )
      }
      line("")
    }
  }
  line("## Log error ratio")
  line("")
  line(
    "Scope: time-valid physical log lines inside the time filter, counted before level and keyword filtering. ERROR + FATAL lines form the numerator; every other time-valid line (DEBUG/INFO/WARN/OTHER) stays in the denominator. Lines without a valid timestamp enter neither side, so the denominator can differ from the scanned line count.",
  )
  line("")
  line(
    "This is a share of log lines, not a request failure rate: one request can emit many lines, and a quiet period can raise the share without any new failure. `--level` and `--keyword` do not change these numbers; `--from` and `--to` do. Buckets with no time-valid line report N/A instead of 0%.",
  )
  line("")
  line("### All observed lines")
  line("")
  line("| ERROR + FATAL | Time-valid lines | Ratio |")
  line("| ---: | ---: | ---: |")
  line("| \{overall.errors} | \{overall.total} | \{format_ratio(overall)} |")
  line("")
  line("### By spike")
  line("")
  if analysis.spikes.is_empty() {
    line("No spikes met the rule, so there is no spike interval to measure.")
  } else {
    line(
      "| Spike | Start UTC | End UTC (exclusive) | ERROR + FATAL | Time-valid lines | Ratio |",
    )
    line("| ---: | --- | --- | ---: | ---: | ---: |")
    for i in 0..<analysis.spikes.length() {
      let spike = analysis.spikes[i]
      let ratio = analysis.log_error_ratio(
        start=Some(spike.start),
        end=Some(spike.end),
      )
      line(
        "| \{i+1} | \{format_time(spike.start)} | \{format_time(spike.end)} | \{ratio.errors} | \{ratio.total} | \{format_ratio(ratio)} |",
      )
    }
    line("")
    line(
      "Spike intervals use bucket boundaries with the end excluded, matching the filtered spike table above. When a level or keyword filter is active, the ERROR + FATAL count here can exceed the filtered count there, because the ratio ignores those filters.",
    )
  }
  line("")
  line("### By observation bucket")
  line("")
  let observed = analysis.observation_buckets
  if observed.is_empty() {
    line("No time-valid line was observed, so there is no observation bucket.")
  } else {
    line(
      "| Start UTC | End UTC (exclusive) | ERROR + FATAL | Time-valid lines | Ratio |",
    )
    line("| --- | --- | ---: | ---: | ---: |")
    let limit = 50
    let width = c.bucket_minutes.to_int64()
    for i in 0..<observed.length() {
      if i >= limit {
        break
      }
      let bucket = observed[i]
      let ratio = bucket.log_error_ratio()
      line(
        "| \{format_time(bucket.start)} | \{format_time(bucket.start + width)} | \{ratio.errors} | \{ratio.total} | \{format_ratio(ratio)} |",
      )
    }
    if observed.length() > limit {
      line("")
      line(
        "Showing the first \{limit} of \{observed.length()} observation buckets; the JSON report contains every bucket.",
      )
    }
    line("")
    line(
      "An empty bucket contains no time-valid line, so its ratio is N/A rather than 0%.",
    )
  }
  line("")
  line("## Top error signatures (matching filters)")
  line("")
  line(
    "Decimal runs become #; the message portion is capped at 512 characters (the level prefix is outside the cap). Counts cover retained signatures only. This ranking is global across all matching errors, not restricted to spikes.",
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
  if selected_signature is Some(signature) {
    line("## Selected signature comparison")
    line("")
    line("Selected signature: `\{safe_markdown(signature)}`")
    line("")
    line(
      "Matched exactly against the complete normalized signature: the level prefix plus the message with decimal runs replaced by `#`. Partial messages, bare message text and other levels do not match, and the value is used as given — it is never re-normalized.",
    )
    line("")
    line(
      "Counts apply the same level, keyword and time filters as spike detection. The pre-spike window is the configured \{c.baseline_buckets} × \{c.bucket_minutes} = \{c.baseline_buckets.to_int64() * c.bucket_minutes.to_int64()} minutes before the spike start; both windows are left-closed and right-open. Earlier incidents can fall inside a pre-spike window, so it is a reference period and not a healthy window.",
    )
    line("")
    if signature_comparisons.is_empty() {
      line(
        "No spikes met the rule, so there is no comparison window. This does not mean the selected signature never occurred: it can appear outside detected spikes or below the minimum error count.",
      )
      line("")
    } else {
      let mut counted = 0L
      for i in 0..<signature_comparisons.length() {
        let cmp = signature_comparisons[i]
        counted += cmp.before_count + cmp.spike_count
        line(
          "### Spike \{i+1}: \{format_time(cmp.spike_start)} to \{format_time(cmp.spike_end)}",
        )
        line("")
        line(
          "| Window | Start UTC | End UTC (exclusive) | Minutes | Occurrences | Per minute |",
        )
        line("| --- | --- | --- | ---: | ---: | ---: |")
        line(
          "| Pre-spike baseline | \{format_time(cmp.before_start)} | \{format_time(cmp.spike_start)} | \{cmp.before_minutes} | \{cmp.before_count} | \{format_per_minute(cmp.before_per_minute)} |",
        )
        line(
          "| Spike | \{format_time(cmp.spike_start)} | \{format_time(cmp.spike_end)} | \{cmp.spike_minutes} | \{cmp.spike_count} | \{format_per_minute(cmp.spike_per_minute)} |",
        )
        line("")
        match cmp.rate_multiplier {
          Some(value) =>
            line(
              "Rate multiplier: \{format_multiplier(value)} (\{format_per_minute(cmp.before_per_minute)} per minute before, \{format_per_minute(cmp.spike_per_minute)} per minute during).",
            )
          None =>
            line(
              "Rate multiplier: N/A — the baseline counted \{cmp.before_count} occurrence(s) over \{cmp.before_minutes} minute(s) (\{format_per_minute(cmp.before_per_minute)} per minute) and the spike counted \{cmp.spike_count} over \{cmp.spike_minutes} minute(s) (\{format_per_minute(cmp.spike_per_minute)} per minute). A zero baseline makes the multiplier undefined, not zero.",
            )
        }
        line("")
      }
      if counted == 0L {
        line(
          "The selected signature was not counted inside any of these windows. This does not mean it is absent from the log: only the comparison windows above are counted.",
        )
        line("")
      }
    }
  }
  line("## Context evidence")
  line("")
  line(
    if context_mode == Spikes {
      "Targets are ERROR + FATAL records inside detected spikes. Context lines are physical neighbors and are not filtered."
    } else {
      "Targets are matching ERROR + FATAL records, including when no spike is detected. Context lines are physical neighbors and are not filtered."
    },
  )
  if selected_signature is Some(signature) {
    line(
      "Targets are further restricted to the exact signature `\{safe_markdown(signature)}`; context lines stay unfiltered.",
    )
  }
  line("")
  if file_windows.is_empty() {
    match selected_signature {
      Some(signature) =>
        line(
          "No context matched the selected signature `\{safe_markdown(signature)}` in this mode and filter set. Other signatures may still be failing; this only means no target line was sampled.",
        )
      None =>
        line(
          if context_mode == Spikes {
            "No sampled spike context. Raw stack/unknown lines are preserved only as surrounding evidence."
          } else {
            "No sampled error context. This can happen when no record matches the filters or the sample limit is 0."
          },
        )
    }
  }
  let fence = code_fence(file_windows)
  for i in 0..<file_windows.length() {
    let file_window = file_windows[i]
    let window = file_window.window
    line("### Window \{i+1}")
    line("")
    line("Source: \{safe_markdown(file_window.source)}")
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
