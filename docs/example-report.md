# MoonLog Incident Report

Deterministic log evidence; spike detection does not establish a root cause.

## Summary

- Source: fixtures/incident.log
- Engine: MoonLog 0.1.0 / native MoonBit
- Lines scanned: 30
- Lines matching filters: 30
- Matched lines without a valid timestamp: 0
- ERROR + FATAL: 4
- Detected spikes: 1
- Context targets sampled: 4 (limit 20); omitted: 0
- Untracked signature occurrences after capacity limit: 0
- Bucket coverage (end exclusive): 2026-10-28 08:00:00Z to 2026-10-28 08:40:00Z

## Rules and filters

- Bucket size: 5 minutes, UTC-aligned; empty buckets count as zero.
- Baseline: previous 6 complete buckets, excluding the current bucket.
- Spike: ERROR + FATAL strictly greater than 3 times baseline, with at least 3 errors.
- Zero baseline: trigger at minimum error count. Warm-up: no detection until a full baseline exists.
- Adjacent flagged buckets merge; incident end is the exclusive bucket boundary.
- Timestamps without offsets are interpreted as UTC; seconds/fractions are floored to minutes.
- Context mode: spikes; targets: ERROR + FATAL records inside detected spikes.
- Context: up to 10 physical lines on either side; overlapping/adjacent windows merge. Context includes unfiltered evidence.
- Level: all
- Message keyword (case-sensitive): 
- From (inclusive minute): unbounded
- To (inclusive minute): unbounded

## Level counts (matching filters)

| Level | Count |
| --- | ---: |
| DEBUG | 0 |
| INFO | 26 |
| WARN | 0 |
| ERROR | 4 |
| FATAL | 0 |
| OTHER | 0 |

## Detected spikes

| Start UTC | End UTC (exclusive) | Errors | Peak per bucket | Baseline at start |
| --- | --- | ---: | ---: | ---: |
| 2026-10-28 08:30:00Z | 2026-10-28 08:35:00Z | 4 | 4 | 0 |

## Error signatures by spike

Signatures count only ERROR/FATAL records inside each spike after filters. All spikes share one capacity (max_signatures = 1000), so the same signature in different spikes occupies separate slots. Tables show at most the top 10 retained signatures; capacity omissions are reported separately.

### Spike 1: 2026-10-28 08:30:00Z to 2026-10-28 08:35:00Z

Spike ERROR + FATAL records: 4; occurrences omitted by capacity: 0.

| Signature | Occurrences |
| --- | ---: |
| ERROR: database timeout retry=\# | 4 |

## Top error signatures (matching filters)

Decimal runs become #; the message portion is capped at 512 characters (the level prefix is outside the cap). Counts cover retained signatures only. This ranking is global across all matching errors, not restricted to spikes.

| Signature | Occurrences |
| --- | ---: |
| ERROR: database timeout retry=\# | 4 |

## Context evidence

Targets are ERROR + FATAL records inside detected spikes. Context lines are physical neighbors and are not filtered.

### Window 1

Target source lines: 23, 24, 25, 26. `>` marks sampled targets.

```text
  13: 2026-10-28 08:12:00 [INFO] health check ok
  14: 2026-10-28 08:13:00 [INFO] health check ok
  15: 2026-10-28 08:14:00 [INFO] health check ok
  16: 2026-10-28 08:15:00 [INFO] health check ok
  17: 2026-10-28 08:20:00 [INFO] health check ok
  18: 2026-10-28 08:25:00 [INFO] health check ok
  19: 2026-10-28 08:26:00 [INFO] health check ok
  20: 2026-10-28 08:27:00 [INFO] health check ok
  21: 2026-10-28 08:28:00 [INFO] health check ok
  22: 2026-10-28 08:29:00 [INFO] health check ok
> 23: 2026-10-28 08:30:00 [ERROR] database timeout retry=1
> 24: 2026-10-28 08:31:00 [ERROR] database timeout retry=2
> 25: 2026-10-28 08:32:00 [ERROR] database timeout retry=3
> 26: 2026-10-28 08:33:00 [ERROR] database timeout retry=4
  27: 2026-10-28 08:34:00 [INFO] retry succeeded
  28: 2026-10-28 08:35:00 [INFO] service recovered
  29: 2026-10-28 08:36:00 [INFO] health check ok
  30: 2026-10-28 08:37:00 [INFO] health check ok
```

