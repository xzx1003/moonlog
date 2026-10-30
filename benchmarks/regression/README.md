# MoonLog 完整 CLI 性能回归

本目录用固定、可复现的合成日志测量 MoonLog 原生 CLI 的端到端性能，并在每次运行中校验分析结果和报告字节可复现性。默认只报告数据，不设性能门禁，也不接入 CI。

- `run.py`：唯一的执行脚本，仅依赖 Python 3.9+ 标准库，支持 macOS 与 Linux。
- `results.example.json` / `results.example.md`：一次 **同一二进制自比较** 的示例输出，仅用于展示数据结构。
- 输入日志不入库：默认在系统临时目录生成，运行结束删除；`--keep-work` 才会保留。

## 1. 范围

测量对象是完整 CLI 进程，而不是受限的基准适配器。一次计时运行包含：

1. 进程启动与参数解析；
2. 第一遍扫描：逐行读取、UTF-8 校验、解析文本/JSON Lines、按时间分桶、统计级别与签名；
3. 行数与原始字节 SHA-256 一致性校验；
4. 第二遍扫描：签名计数、spike 签名、上下文目标判定、上下文采样；
5. 第二次行数与 SHA-256 一致性校验；
6. spike 检测（默认 moving-average）；
7. 上下文窗口合并与原文保留；
8. JSON 报告独占创建与写入；
9. 终端摘要输出。

使用的 CLI 参数固定记录在 `parameters.cli_options` 中：

```text
analyze input.log --report report.json --format json --sampling first
--detector moving-average --bucket-minutes 5 --baseline-buckets 6
--multiplier 3 --min-errors 3 --context 10 --context-mode spikes
--max-samples 20
```

单文件加 `first` 采样严格走两遍扫描；多文件或 `distributed` 采样会走三遍，本基准不覆盖后者。改变上述参数会改变工作量，结果不可与默认参数直接比较。

### 与现有基准的关系

- `benchmarks/compare/` 只比较受限的 MoonBit/Go 共同契约，不含上下文提取、签名窗口、Markdown 报告和完整 CLI 选项，不能代表完整 CLI。
- `benchmarks/profile/` 是受限适配器上的消融分析，用于定位阶段开销，不是端到端回归。
- 本目录测量真实 CLI 进程，包含报告落盘和终端输出；三者用途不同，不互相替代。

## 2. 快速使用

```bash
make build

# 默认 10 MiB + 100 MiB；1 次预热 + 5 次计时；基线/候选交替
python3 benchmarks/regression/run.py \
  --baseline /path/to/previous/moonlog \
  --candidate bin/moonlog \
  --output /tmp/moonlog-regression.json
```

- 省略 `--baseline` 时只测候选版本，`statistics.baseline` 为 `null`，不做跨版本比较。
- `--sizes` 默认 `10,100`（单位 MiB）；显式传入覆盖默认值。
- `--runs` 默认 5，`--warmups` 默认 1，`--seed` 默认 `20261029`。
- 输出 JSON 的同时会在同目录写一个同名 `.md` 摘要。
- 默认输出路径是 `benchmarks/regression/results.json`，已被 `.gitignore` 忽略。

仅验证脚本本身时可以用自比较（同一路径）：

```bash
python3 benchmarks/regression/run.py \
  --baseline ./bin/moonlog --candidate ./bin/moonlog \
  --sizes 1 --runs 1 --output /tmp/moonlog-smoke.json
```

自比较不是性能结论：两个版本是同一个二进制，差异只反映噪声。

### Makefile

```bash
make bench-regression BENCH_BASELINE=/path/to/previous/moonlog
make bench-regression BENCH_BASELINE=/path/to/previous/moonlog BENCH_GATE=--gate
make bench-regression-large BENCH_BASELINE=/path/to/previous/moonlog
```

可用变量：`BENCH_CANDIDATE`（默认 `bin/moonlog`）、`BENCH_RUNS`、`BENCH_WARMUPS`、`BENCH_SEED`、`BENCH_REG_SIZES`、`BENCH_REG_OUTPUT`、`BENCH_REG_LARGE_OUTPUT`。`BENCH_GATE` 为空时只报告；设为 `--gate` 才启用门禁。

## 3. 尺寸档位

| 名义尺寸 | 用途 | 启用方式 |
|---:|---|---|
| 10 MiB | PR/日常冒烟 | 默认 |
| 100 MiB | 常规回归 | 默认 |
| 1 GiB | 吞吐量检查 | 显式 `--sizes 1024` |
| 5 GiB | 压力/长资源 | `--sizes 5120 --allow-large` 或 `bench-regression-large` |
| 10 GiB | 长资源/上限 | `--sizes 10240 --allow-large` 或 `bench-regression-large` |

超过 1024 MiB 的尺寸必须显式加 `--allow-large`；5 GiB 和 10 GiB 绝不会默认运行。`bench-regression-large` 固定为 `1024,5120,10240`，耗时以小时计，见第 10 节。

每个尺寸生成 4 个用例：

- 标准文本 + 低错误密度；
- 标准文本 + 高错误密度；
- JSON Lines + 低错误密度；
- JSON Lines + 高错误密度。

## 4. 确定性输入生成

所有用例由固定种子生成，生成过程不参与计时。

- 时间跨度固定为 UTC `2026-10-28 00:00:00` 至 `2026-10-29 00:00:00`，共 288 个 5 分钟桶；每行都有合法时间戳，`untimed = 0`。
- 文本格式：`YYYY-MM-DD HH:MM:SS [LEVEL] message`。
- JSON Lines：`{"ts":"...","level":"...","msg":"..."}`，仅使用默认字段名。
- 基础错误密度：低 1/1000 行，高 200/1000 行。
- 4 个单桶事件：bucket 12、96、180、276，即 01:00、08:00、15:00、23:00 UTC，每个 5 分钟桶内 800/1000 行为错误。
- 第 n 个全局错误中每第 10 个记为 `FATAL`，其余为 `ERROR`；不生成 `DEBUG`、`WARN`、`OTHER`。
- 低密度使用累计整数预算分配错误，避免小尺寸下每桶向下取整后错误数为 0。
- 单桶事件是刻意选择：连续多桶事件会进入 moving-average 的基线，导致后续桶不再触发；单桶设计保证所有尺寸、格式、密度下都恰好出现 4 个 spike，且区间完全相同。
- 错误消息含十进制序号，签名会把连续十进制串归一为 `#`；因此签名数量有界，不会触发 `max_signatures` 溢出。
- `case_seed = seed + size_mib*1009 + format_index*131 + density_index*17`，记录在生成参数中。

每个用例记录：

- 目标 MiB、实际字节、实际 MiB、相对偏差；
- 逻辑行数、错误总数、ERROR/FATAL 数量与占比；
- 输入文件 SHA-256；
- 生成耗时；
- 种子、case 种子、格式、密度、事件桶、FATAL 周期、时间跨度、桶宽、每桶行数等完整参数。

输入使用随机命名临时目录；默认在用例结束后删除整个用例目录。输入文件不会写入仓库。

## 5. 测量协议

- 每个版本、每个用例：1 次预热（不计入统计）+ 5 次计时；`--warmups/--runs` 可改，但结果只在相同设置下比较。
- 基线/候选用例在同一用例目录、同一输入上运行；每次迭代交替运行顺序（第 1 次基线在前，第 2 次候选在前，依此类推），减少系统性缓存/顺序偏差。
- 每个样本独立保存，绝不只保留最快值；统计只使用计时样本。
- 预热后输入已进入操作系统页缓存；生成和校验不计时。这是热缓存基准，不模拟冷缓存或网络文件系统。
- 用 `os.fork` + `os.execv` + `os.wait4` 启动和回收进程：
  - wall：`time.perf_counter` 包住 fork/exec/wait；
  - user/system CPU：`wait4` 的 `ru_utime` / `ru_stime`；
  - 峰值 RSS：`ru_maxrss`，Darwin 单位为字节，Linux 单位为 KiB，统一换算为 MiB；
  - 子进程设置 `LC_ALL=C`、`TZ=UTC`，工作目录为用例目录。
- 以相对路径 `input.log` / `report.json` 运行，报告中的 `source` 固定为 `input.log`，避免临时绝对路径破坏字节可复现性。
- 每次运行前删除旧 `report.json`；CLI 本身也会拒绝覆盖已存在报告。
- 墙钟包含进程启动、两遍扫描、SHA-256、解析、分桶、检测、上下文、报告写入和终端摘要。
- 吞吐 = 实际输入字节 / wall，不把两遍扫描重复计入字节；行吞吐 = 逻辑行数 / wall。
- `allocations` 固定为 `"unsupported"`：当前没有可靠且跨平台的分配量测量，峰值 RSS 不是分配量，不能混用。
- 统计输出 count、median、min、max、mean；仅当样本数 ≥ 20 时输出 P95（nearest-rank），否则为 `null`。5 次计时默认没有 P95。
- 相对变化按候选/基线的中位数计算；另存按迭代配对的 wall/RSS/吞吐变化，仅供观察。

## 6. 每次运行的校验

任何一项失败都会把该次测量判为无效，脚本以退出码 2 结束，并保留已写入的部分结果；这不是性能回归判定。

每次运行（含预热）校验 16 项：

1. `returncode_zero`：返回码为 0；
2. `report_written`：报告文件存在；
3. `report_json_parse`：报告是合法 JSON；
4. `report_structure`：顶层字段、类型、桶/ spike/上下文条目结构完整；
5. `source_sampling_scans`：`source/sources/sampling/scans`、JSON 字段名、config、filter 与固定参数一致；
6. `summary_totals`：total、matched、untimed、errors、spike_count、sampled/omitted 等精确匹配；
7. `level_counts`：DEBUG/INFO/WARN/ERROR/FATAL/OTHER 精确匹配，且总和等于总行数；
8. `log_error_ratio`：total/errors 与 fraction（含零分母 null 语义）正确；
9. `time_buckets`：288 个桶的起点、终点、total、errors 全部逐桶精确匹配；
10. `observation_buckets`：288 个观测桶逐桶匹配，包括每桶比率；
11. `spikes`：数量、起止区间、errors、peak_errors、baseline、比率、桶内签名求和全部匹配；
12. `signature_accounting`：全局签名计数求和等于总错误数，排序为 count 降序、再按 MoonBit 的 shortlex（UTF-16 长度优先）文本升序；
13. `context_sampling`：sampled/omitted 数量、窗口数、采样目标行号序列匹配；
14. `context_windows`：每个窗口的目标集合、行号范围、逐行原文与独立重建结果完全一致；
15. `report_sha_matches_first`：本次报告字节 SHA-256 与同版本第一次计时样本一致；
16. `analysis_core_matches_first`：summary/level_counts/buckets/observation_buckets/spikes/signatures/context_windows 的规范化 SHA-256 与同版本第一次样本一致。

此外：

- 预热报告 SHA 也必须与计时样本一致；
- 所有用例的预期 spike 区间必须相同（`spike_schedule_stable_across_cases`）；
- 运行前后重新计算二进制 SHA-256，二进制在运行期间不得变化；
- 预期分析由生成参数独立推导（包括 288 个桶的错误预算、moving-average 规则、上下文窗口合并和逐行文本重建），不依赖被测程序自身的输出。

### 报告 SHA-256 可复现

报告不含主机时间、随机临时路径或运行统计；输入固定、参数固定、`source` 相对固定，因此同一二进制在同一用例上应产生字节级相同的 JSON。脚本在每次运行后立即计算原始字节 SHA-256，并在所有样本（含预热）之间比较。跨版本比较时，报告 SHA 可以不同，见下一节。

## 7. 跨版本比较与允许差异

跨版本比较使用每个版本第一个通过校验的计时样本。

强制核心字段，永远不可放宽：

```text
summary, level_counts, buckets, observation_buckets, spikes,
signatures, context_windows
```

这些字段必须解析后语义一致。`--allow-report-diff` 只能列出其他顶层字段，列出核心字段会直接报错：

```bash
--allow-report-diff engine_version
--allow-report-diff engine_version,diagnostic_note
```

规则：

- 原始报告字节相同（SHA-256 相同）→ 一致。
- 解析内容完全相同但字节不同（键顺序、空白、等价数字表示）→ 只有显式 `--allow-report-format` 才判为一致。
- 顶层字段有差异且全部在允许列表中，且移除允许字段后其余内容仍相同 → 一致。
- 只要出现未允许字段差异，或核心字段差异 → 不一致。
- 允许差异不会关闭比较：报告会记录 baseline/candidate 原始 SHA-256、差异字段、允许字段、未允许字段、核心差异字段、移除允许字段后的语义是否相等。

结果位置：`cases[].verification.cross_version`。

默认门禁关闭时，跨版本不一致只打印警告并以 0 退出；启用 `--gate` 后视为门禁失败并以 1 退出。每次运行的正确性失败始终以 2 退出，因为那说明测量本身无效。

## 8. 门禁与退出码

默认 **只报告**，不对性能波动做硬失败，也不接入 GitHub CI。

显式启用：

```bash
python3 benchmarks/regression/run.py \
  --baseline /path/to/previous/moonlog --candidate bin/moonlog \
  --gate --gate-wall-pct 15 --gate-rss-pct 20
```

- `--gate` 必须同时提供 `--baseline`，否则参数错误。
- wall：候选中位数相对基线中位数的增长超过 `--gate-wall-pct`（默认 15%）→ 失败。
- peak RSS：候选中位数增长超过 `--gate-rss-pct`（默认 20%）→ 失败。
- 跨版本输出不一致 → 失败。
- 门禁用中位数，不使用最快值；配对变化只作参考。
- 阈值严格大于才失败；门禁关闭时 `gates.passed = null`。

退出码：

| 退出码 | 含义 |
|---:|---|
| 0 | 正常运行；或仅报告模式；或门禁启用且全部通过 |
| 1 | 门禁失败（wall、RSS 或跨版本输出一致性） |
| 2 | 参数错误、运行正确性校验失败、测量无效或未预期异常 |

## 9. 输出与数据整理

顶层结构：

```text
schema_version, tool, started_at_utc, finished_at_utc,
environment, binaries, parameters, cases, checks, gates, result, failure
```

环境记录：git commit/branch/dirty、MoonBit 版本、Node 版本、Python 版本、OS/架构、CPU 型号与逻辑核数、物理核数、内存字节、起始负载、测量时间。二进制记录路径、字节数、SHA-256、运行期间是否保持不变、是否自比较。

每个用例：

```text
name, nominal_mib, format, error_density,
generation, expected, warmup, samples, statistics, verification
```

`generation` 记录输入字节/行/错误/占比/SHA-256/生成参数；`expected` 记录独立推导的逐桶错误数、spike、签名与上下文目标，便于审计。

每个样本：

```text
version, iteration, order, allocations,
wall_seconds, user_cpu_seconds, system_cpu_seconds, total_cpu_seconds,
peak_rss_mib, input_mib_per_second, lines_per_second,
returncode, stdout, stderr,
report_sha256, report_bytes, report_summary, level_counts,
spike_count, context_window_count, bucket_count, analysis_core_sha256,
checks, checks_passed
```

失败样本会额外带 `check_details`。`stdout`/`stderr` 是完整文本；报告原文不直接嵌入 JSON，但每次运行的报告副本、stdout、stderr 会写入临时用例的 `captures/`，配合 `--keep-work` 保留。默认运行结束删除临时目录。

`statistics` 按版本给出每个指标的 count/median/min/max/mean/P95，并给出候选相对基线的百分比变化和配对变化。

`results.example.json` 是 10 MiB、5 次计时、同二进制自比较的示例；生成时主机负载很高（见文件内 `load_average_start`），其中的数字 **不是性能结论**，也不能当作基线。请用自己的基线和候选在安静环境下重新生成。

## 10. 大尺寸资源消耗

每个尺寸会依次生成 4 个用例，每个用例运行 `版本数 × (warmups + runs)` 次，每次计时都扫描输入两遍。

- 生成前检查剩余磁盘，要求约 `1.2 × 输入大小 + 256 MiB`；用例结束默认删除输入，所以 4 个用例是串行的，不需要同时容纳 4 份。
- 10 GiB 用例单次生成约 10 GiB，单次运行读取约 20 GiB；每个尺寸 4 个用例，`bench-regression-large` 共 3 个尺寸、2 个版本、1 预热 + 5 计时，合计约 144 次运行。按机械盘或高负载机器可能需要数小时。
- 5 GiB 和 10 GiB 必须显式启用；建议专用、低负载、接电源的机器，关闭其他大任务，并预留足够临时空间。
- `--keep-work` 会保留所有输入和 capture，5/10 GiB 可能占用数十 GiB；脚本启动时会打印警告。
- 不要在日常 PR 流程中运行 5/10 GiB 档。

## 11. 限制与解释

- 输入是合成日志，错误消息模板、时间分布和签名结构与真实生产日志不同；本基准衡量固定工作量下的相对变化，不代表真实业务吞吐。
- 热页缓存、单文件、`--sampling first`、默认过滤器和默认检测器；冷缓存、多文件、分布式采样、过滤、其他检测器未覆盖。
- 主机负载、CPU 频率、热降频、后台任务都会影响 wall 和 CPU；环境里记录起始负载，但脚本不做隔离。比较时请使用同一机器、同一电源状态、尽量安静的时段。
- RSS 是子进程 OS 高水位，可能受分配器、页大小和内核行为影响；它不是分配量，不用于推断泄漏。`allocations` 始终为 `"unsupported"`。
- P95 需要至少 20 个样本；默认 5 次计时没有 P95，不要用单个最快值下结论。
- 报告字节 SHA 可复现依赖固定输入、固定参数、相对路径和不变二进制；跨版本报告允许显式差异，但核心字段不可放宽。
- 本目录不修改 MoonLog 核心算法和前端，不提交输入，不接入 CI，也不默认启用门禁。

## 12. 维护

- 修改事件桶、密度、种子、时间跨度、桶宽或 CLI 参数，都会改变工作量，旧的 `results.json` 不可直接比较；请同时更新本文档和 `results.example.json`。
- 如果报告 schema 有意变化，先更新 `MANDATORY_CORE_KEYS` 和校验逻辑，再使用 `--allow-report-diff` 列出真正允许的顶层差异；不要为了通过比较而放宽核心字段。
- 修改脚本后至少运行：

```bash
python3 -m py_compile benchmarks/regression/run.py
python3 benchmarks/regression/run.py --help
python3 benchmarks/regression/run.py \
  --baseline ./bin/moonlog --candidate ./bin/moonlog \
  --sizes 1 --runs 1 --output /tmp/moonlog-smoke.json
```

自比较应全部通过、`cross_version.consistent = true`、退出码 0。

### 超时与原始数据保护

`--timeout` 为每次 CLI 子进程的最大秒数，默认 600，须为有限正数。超时或 Ctrl-C 会终止子进程组并回收进程；失败结果仍保存，默认清理工作目录。该限制不包括输入生成与 Python 校验的耗时。大文件慢机器可显式增大该值。

结果 JSON 或同名 Markdown 已存在时直接拒绝运行，防止覆盖旧样本。每次测量须指定新的 `--output`（Makefile 可用 `BENCH_REG_OUTPUT` / `BENCH_REG_LARGE_OUTPUT`）。历史示例测于新增超时保护前，不代表最终脚本的性能基线。

资源保护测试：`python3 benchmarks/regression/test_resources.py`。
