# MoonLog CLI performance regression

End-to-end native CLI: process startup, two scans, SHA-256 consistency, parsing, time buckets, spike detection, context sampling, JSON report write and terminal summary.

## Environment

- Git commit: `e9982ea1b841edb80d5f2bdf5a0a120b19cbf725` (dirty)
- MoonBit: `moon 0.1.20261023 (3778465 2026-10-23) ~/.moon/bin/moon moonc v0.10.17+d971670cd (2026-10-23) ~/.moon/bin/moonc moonrun 0.1.20261023 (3778465 2026-10-23) ~/.moon/bin/moonrun Feature flags enabled: rr_moon_mod,rr_moon_pkg`
- Node: `v24.21.0`
- OS / arch: macOS-26.6.2-arm64-arm-64bit / arm64
- CPU: Apple M5 (10 logical)
- Memory: 16.0 GiB
- Measured at: 2026-10-30T12:38:26.893446+00:00

## Parameters

- Seed: 20261029; sizes MiB: [10]; warmups: 1; runs: 5; interleaved: True
- Allocations: `unsupported`; peak RSS is the child OS high-water mark, not allocations.
- Gates: disabled (report only); wall > 15.0%, RSS > 20.0%, output consistency

## Cases

| Case | Input MiB | Lines | Errors | Baseline s | Candidate s | Δ wall | Baseline RSS MiB | Candidate RSS MiB | Δ RSS | Candidate MiB/s | Outputs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 10MiB-text-low | 10.01 | 148320 | 1795 | 0.213 | 0.213 | -0.4% | 3.6 | 3.6 | -0.4% | 47.1 | consistent |
| 10MiB-text-high | 10.02 | 147456 | 30718 | 0.224 | 0.223 | -0.6% | 3.6 | 3.6 | +0.0% | 44.9 | consistent |
| 10MiB-jsonl-low | 9.99 | 109728 | 1325 | 0.255 | 0.251 | -1.3% | 3.6 | 3.6 | +0.0% | 39.8 | consistent |
| 10MiB-jsonl-high | 9.99 | 109152 | 22739 | 0.259 | 0.261 | +0.8% | 3.6 | 3.6 | -0.4% | 38.2 | consistent |

## Checks

- per_run_validity: PASS
- expected_analysis_matched: PASS
- within_version_sha_reproducible: PASS
- within_version_analysis_stable: PASS
- spike_schedule_stable_across_cases: PASS
- cross_version_consistent: PASS
- correctness_passed: PASS
- output_consistency_passed: PASS

## Gates

Disabled. This run is report-only; no performance gate was applied.

## Notes

- Inputs are synthetic, deterministic, and generated in a temporary directory; they are not committed.
- The 24h UTC span and four incident buckets are fixed across scales, so spike intervals are directly comparable.
- Timing is warm-cache; generation and validation are excluded. P95 is reported only for at least 20 samples.
- `--allow-report-diff` / `--allow-report-format` are the only ways to relax cross-version output comparison; mandatory analysis fields are never relaxable.
- The script does not modify CI, core algorithms, or frontend code.
