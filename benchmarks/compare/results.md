# MoonBit / Go common-contract benchmark

| Case | Language | MiB/s median | MB/s median | lines/s median | Wall s median | CPU s median | Peak RSS MiB max |
|---|---|---:|---:|---:|---:|---:|---:|
| text-10-sparse | moonbit | 63.6 | 66.7 | 494597 | 0.133 | 0.128 | 2.3 |
| text-10-sparse | go | 338.0 | 354.4 | 2628679 | 0.025 | 0.025 | 10.0 |
| text-10-dense | moonbit | 58.2 | 61.0 | 452590 | 0.146 | 0.141 | 2.4 |
| text-10-dense | go | 231.3 | 242.5 | 1798725 | 0.037 | 0.036 | 10.2 |
| jsonl-10-sparse | moonbit | 55.4 | 58.1 | 363651 | 0.181 | 0.176 | 2.4 |
| jsonl-10-sparse | go | 84.0 | 88.1 | 551334 | 0.120 | 0.118 | 10.5 |
| jsonl-10-dense | moonbit | 52.1 | 54.7 | 342017 | 0.193 | 0.185 | 2.4 |
| jsonl-10-dense | go | 74.7 | 78.3 | 490175 | 0.135 | 0.130 | 10.4 |
| text-100-sparse | moonbit | 65.0 | 68.2 | 501733 | 1.307 | 1.275 | 2.4 |
| text-100-sparse | go | 399.2 | 418.6 | 3081954 | 0.213 | 0.215 | 10.5 |
| text-100-dense | moonbit | 60.1 | 63.0 | 463740 | 1.415 | 1.382 | 2.4 |
| text-100-dense | go | 259.2 | 271.8 | 2000678 | 0.328 | 0.333 | 10.5 |
| jsonl-100-sparse | moonbit | 55.1 | 57.8 | 359273 | 1.826 | 1.746 | 2.4 |
| jsonl-100-sparse | go | 86.3 | 90.5 | 562780 | 1.166 | 1.159 | 11.0 |
| jsonl-100-dense | moonbit | 51.1 | 53.6 | 333279 | 1.968 | 1.879 | 2.4 |
| jsonl-100-dense | go | 81.2 | 85.2 | 529684 | 1.238 | 1.250 | 11.1 |

Each result passed full JSON equality and input SHA-256 checks. See README.md for supported input scope and interpretation.

MB/s and lines/s are derived from the saved byte/line counts and measured times; no new timing runs were performed.
