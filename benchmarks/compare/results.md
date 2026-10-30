# MoonBit / Go common-contract benchmark

| Case | Language | MiB/s median | Wall s median | CPU s median | Peak RSS MiB max |
|---|---|---:|---:|---:|---:|
| text-10-sparse | moonbit | 63.6 | 0.133 | 0.128 | 2.3 |
| text-10-sparse | go | 338.0 | 0.025 | 0.025 | 10.0 |
| text-10-dense | moonbit | 58.2 | 0.146 | 0.141 | 2.4 |
| text-10-dense | go | 231.3 | 0.037 | 0.036 | 10.2 |
| jsonl-10-sparse | moonbit | 55.4 | 0.181 | 0.176 | 2.4 |
| jsonl-10-sparse | go | 84.0 | 0.120 | 0.118 | 10.5 |
| jsonl-10-dense | moonbit | 52.1 | 0.193 | 0.185 | 2.4 |
| jsonl-10-dense | go | 74.7 | 0.135 | 0.130 | 10.4 |
| text-100-sparse | moonbit | 65.0 | 1.307 | 1.275 | 2.4 |
| text-100-sparse | go | 399.2 | 0.213 | 0.215 | 10.5 |
| text-100-dense | moonbit | 60.1 | 1.415 | 1.382 | 2.4 |
| text-100-dense | go | 259.2 | 0.328 | 0.333 | 10.5 |
| jsonl-100-sparse | moonbit | 55.1 | 1.826 | 1.746 | 2.4 |
| jsonl-100-sparse | go | 86.3 | 1.166 | 1.159 | 11.0 |
| jsonl-100-dense | moonbit | 51.1 | 1.968 | 1.879 | 2.4 |
| jsonl-100-dense | go | 81.2 | 1.238 | 1.250 | 11.1 |

Each result passed full JSON equality and input SHA-256 checks. See README.md for supported input scope and interpretation.
