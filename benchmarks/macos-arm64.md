# CLI benchmark

end-to-end CLI: process startup, two input scans, JSON write and terminal summary; warm OS cache, generation and verification excluded; RSS is per-child OS high-water mark

| Case | Actual MiB | Lines | Median s | MiB/s | Max peak RSS MiB |
|---|---:|---:|---:|---:|---:|
| text-10MiB-sparse | 8.5 | 66000 | 0.096 | 88.4 | 3.5 |
| text-10MiB-dense | 8.5 | 66000 | 0.113 | 75.4 | 4.5 |
| jsonl-10MiB-sparse | 10.1 | 66000 | 0.139 | 72.4 | 3.5 |
| jsonl-10MiB-dense | 10.1 | 66000 | 0.161 | 62.4 | 4.5 |
| text-100MiB-sparse | 85.0 | 656000 | 0.795 | 106.9 | 3.5 |
| text-100MiB-dense | 85.0 | 656000 | 0.914 | 93.0 | 3.5 |
| jsonl-100MiB-sparse | 100.6 | 656000 | 1.320 | 76.2 | 3.5 |
| jsonl-100MiB-dense | 100.6 | 656000 | 1.415 | 71.1 | 3.5 |
| text-500MiB-sparse | 427.1 | 3277000 | 4.086 | 104.5 | 3.5 |
| text-500MiB-dense | 427.1 | 3277000 | 4.627 | 92.3 | 3.5 |
| jsonl-500MiB-sparse | 505.2 | 3277000 | 6.419 | 78.7 | 3.5 |
| jsonl-500MiB-dense | 505.2 | 3277000 | 7.137 | 70.8 | 3.6 |

5 measured runs + 1 warmup per case. Seed: 20261029.

Environment:
```
{
  "platform": "macOS-26.6.2-arm64-arm-64bit",
  "machine": "arm64",
  "python": "3.9.6",
  "cpu_count": 10,
  "moon": "moon 0.1.20261023 (3778465 2026-10-23) ~/.moon/bin/moon\nmoonc v0.10.17+d971670cd (2026-10-23) ~/.moon/bin/moonc\nmoonrun 0.1.20261023 (3778465 2026-10-23) ~/.moon/bin/moonrun\n\nFeature flags enabled: rr_moon_mod,rr_moon_pkg\n",
  "binary_sha256": "edc449ea8e22b91a0ba466c78bffa4498c0170393c55332c711a37e0caf0a255",
  "hardware": {
    "cpu": "Apple M5",
    "ram_bytes": 17179869184
  },
  "recorded_at_utc": "2026-10-29T15:25:06.946Z",
  "source_commit": "6aad1df0aa0e16bcd0ae2c81c5d851aba639353d"
}
```

Synthetic workloads only; no JS comparison, no browser performance claim, no constant-memory claim. Nominal sizes are labels; use actual bytes for throughput.
