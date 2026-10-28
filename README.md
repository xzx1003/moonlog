# MoonLog

**本地离线日志分析 CLI**

MoonLog 是一个使用 MoonBit 编写的命令行工具，用于分析应用日志中的错误尖峰，并生成包含统计结果和原始日志上下文的 Markdown 报告。

工具通过确定性的统计规则识别异常错误数量，支持普通文本日志和 JSON Lines。日志解析、过滤、统计、上下文提取和报告生成均由 MoonBit 实现，编译后可作为本机原生 CLI 独立运行，无需 Node.js 或外部服务。

## 快速开始

构建环境需要 MoonBit 工具链、C 编译器和 Make。本项目当前使用 `moon 0.1.20261023`，已在 macOS arm64 上完成构建与测试。

```bash
make build
./bin/moonlog analyze fixtures/incident.log --report incident.md
./bin/moonlog analyze fixtures/incident.log --report incident.json --format json
./bin/moonlog analyze fixtures/incident.log --report incident-signature.md \
  --signature 'ERROR: database timeout retry=#'
./bin/moonlog analyze old.log app.log --report incident.md
./bin/moonlog analyze old.log app.log --report incident.md --sampling distributed
./bin/moonlog --help
```

构建完成后，可将 `bin/moonlog` 复制到 PATH 中的目录，之后直接运行：

```bash
moonlog analyze app.log --report incident.md
moonlog analyze app.log --report incident.json --format json
moonlog analyze old.log app.log --report incident.md
```

默认情况下，MoonLog 不会联网。输入日志、分析过程和生成的报告均保留在本机。为避免意外覆盖数据，已有报告文件不会被覆盖；每次分析请指定新的输出文件名。

报告会包含原始日志片段，分享前请检查其中是否存在业务数据、凭据或其他敏感信息。

## 当前实现

目前已完成日志解析、过滤、时间统计、错误尖峰检测、上下文提取、指定签名的窗口对比和 Markdown 报告生成，并提供核心测试与 CLI 集成测试。

**日志读取与解析**

- 支持普通单行文本和 JSON Lines，两种格式可以混合使用。
- 支持 UTF-8、文件开头的 BOM、CRLF 换行，以及末行没有换行符的情况。
- JSON 日志仅读取字符串字段 `ts`、`level` 和 `msg`，拒绝重复键，最大嵌套深度为 32。
- 无效 JSON、堆栈行及无法识别的格式会保留为 `OTHER` 记录。多行堆栈不会自动合并成一个事件，但可作为上下文原文保留。
- 日志记录保留原始物理行号，便于回查源文件。

**过滤与统计**

- 支持按日志级别、消息关键词和时间范围过滤。
- 级别标签区分大小写。`DEBUG`、`INFO`、`WARN`、`ERROR`、`FATAL` 为可识别级别；其他标签（包括显式写出的 `OTHER`）归为 `OTHER`，也可用 `--level OTHER` 筛选这些记录。
- 统计结果、错误聚合和尖峰检测使用同一组过滤条件；只有日志错误占比例外，它按过滤前的观察口径统计（见下文「日志错误占比」）。
- 时间桶按 UTC 对齐，默认每桶 5 分钟；缺失的时间桶会补零，乱序记录按时间排序后参与统计。
- 错误签名以级别前缀开头，仅将消息中的连续十进制数字替换为 `#`，不尝试推断根因。签名按出现次数排序。

**错误尖峰检测**

当前默认使用前 6 个时间桶的错误数量计算滑动平均基线。当前桶的错误数严格超过基线的 3 倍，且至少包含 3 条 `ERROR` 或 `FATAL` 记录时，才会被标记为尖峰。

在基线为零时，只要当前桶达到最少错误数要求，即可触发检测。连续的尖峰桶会合并为一个区间，报告中的起止时间采用桶边界，结束时间不包含在事故区间内。

上下文目标由 `--context-mode` 选择：`spikes`（默认）只采集尖峰区间内的 ERROR/FATAL 记录，`errors` 采集所有满足过滤条件的 ERROR/FATAL 记录，即使没有检测到尖峰。两种模式默认最多采集 20 个目标，其余目标会以数量汇总。每个目标保留前后各 10 行物理上下文；相交或相邻的上下文窗口会合并，以减少重复内容。

这套规则用于发现错误数量的异常变化，不能据此确定故障根因，也不能直接衡量错误率或实际影响范围。持续高错误量可能逐渐进入滑动基线，因此检测区间的结束时间也不代表服务已经恢复。

**日志错误占比**

日志错误占比衡量「时间有效的日志行里，ERROR/FATAL 占多大比例」，用于在尖峰检测之外提供一个覆盖整个观察范围的指标。

- 分母是时间筛选范围内的全部时间有效物理行，包含 DEBUG/INFO/WARN 以及归为 `OTHER` 的记录；没有有效时间戳的行既不进分子也不进分母。
- 分子是其中的 ERROR 与 FATAL 行。
- `--from` / `--to` 会改变分子和分母；`--level` 和 `--keyword` 不会，因为口径在级别、关键词过滤之前统计。
- 分母为零时显示 `N/A`（不是 `0%`）。
- 报告给出三个范围：全范围、每个尖峰区间（桶边界，结束不含）以及每个观察时间桶。

这个数字是日志行比例，不是请求失败率：一个请求可能产生多行日志，错误还会触发重试等额外日志；日志量骤降时占比反而可能升高。它不能替代基于请求数的失败率，也不代表服务健康。

**指定签名对比**

`--signature` 把分析聚焦到一个完整的错误签名上，同时不改动尖峰检测口径。

- 取值必须与 `error_signature` 的输出逐字符相等，例如 `--signature 'ERROR: database timeout retry=#'`。级别前缀属于签名本身，`FATAL: ...` 不会匹配 `ERROR: ...`；消息前缀或裸消息文本（如 `database timeout`）也不会匹配。
- 工具不会再次归一化用户输入：数字不会被替换为 `#`，大小写与空格原样使用。空值、重复传参和缺少取值都会直接报错，且不会生成报告。
- 上下文目标额外按该签名过滤：`spikes` 模式只在尖峰区间内的匹配行中取样，`errors` 模式在所有匹配行中取样，因此没有尖峰时也能取到该签名的上下文；周边上下文仍是未过滤的物理相邻行。
- 第二遍扫描会额外逐行喂入一个比较收集器，为每个尖峰输出「尖峰前窗口」与「尖峰窗口」的对比：窗口起止、分钟数、出现次数、每分钟频率和频率倍数。
- 尖峰前窗口固定为 `baseline_buckets × bucket_minutes` 分钟，尖峰窗口为尖峰区间；两者都是左闭右开，即 `[尖峰起点 - 窗口长度, 尖峰起点)` 与 `[尖峰起点, 尖峰结束)`。计数遵守既有的级别、关键词和时间过滤。
- 尖峰前窗口可能包含更早的事故，它只是参考区间，不能当作「健康窗口」。基线次数为零时频率倍数没有定义，报告显示 `N/A`，并同时给出两侧的次数与频率。
- 该参数不影响尖峰检测、尖峰排名、错误占比和原有的过滤统计；未指定时不创建比较收集器，报告也不出现该小节。

**多文件输入与采样**

`analyze` 接受一个或多个输入文件，位置参数（不以 `--` 开头）依次是输入文件，其后才是选项。多个文件喂入同一个 `Analyzer`，时间桶与尖峰检测在所有文件上统一进行，不按文件分别检测再拼接结果。文件的先后顺序只影响采样顺序和受容量限制时的签名保留顺序，不影响时间统计。

- 输入文件按传入顺序处理，工具不会对文件排序，也不会自动搜索或展开目录。重叠的轮转日志可能被重复计数，工具不去重日志内容。
- 输入身份使用 POSIX `stat` 的设备号与 inode 判定，重复路径、软链接别名、硬链接别名都会被拒绝，而不是靠字符串比较或日志内容去重。
- 采样限额在所有文件之间共享。按输入文件顺序、文件内行序给匹配目标编号后，`first` 取前若干个，`distributed` 均匀选择目标序号并包含两端（只有一个名额时取中间目标）。它不是按时间均匀，也不保证每个文件或每个尖峰都有样本；未选中的目标仍可作为其他样本的相邻行出现。
- 每个上下文窗口都带所属文件 `source` 与文件内行号，行号在每个文件内重新从 1 开始；上下文不会跨文件合并。
- 报告区分「样本目标遗漏」（`--max-samples` 达到上限后未采样的目标）与「签名容量遗漏」（`--max-signatures` 达到上限后未保留的签名出现次数）。

**报告内容**

Markdown 报告包含本次分析使用的参数与过滤条件（含上下文模式）、日志计数、尖峰区间、每个尖峰内独立的错误签名排名（最多前 10 项）、全局错误签名排名、全范围/各尖峰/各观察时间桶的日志错误占比，以及对应的原始日志上下文。

过滤后的统计（级别计数、尖峰错误数、签名排名、上下文采样）与日志错误占比是两套口径：前者受 `--level`、`--keyword` 影响，后者不受影响。报告中分节呈现，并在占比小节内重复说明差异，避免把两者混读。

尖峰内排名只统计该尖峰区间内、满足过滤条件的 ERROR/FATAL 记录，因此不会混入基线时段的噪声；不同尖峰分别排名。全局排名则覆盖所有匹配记录，不受尖峰区间限制。

报告中的时间、统计结果和上下文均来自本地输入文件，不依赖外部服务。

除 Markdown 外，`--format json` 可输出结构化报告，字段说明见下文「报告格式」一节。两种格式都在报告成功写入后打印同一份终端摘要。

## 日志格式与时间处理

普通文本日志示例：

```text
2026-10-28 08:15:30 [ERROR] database timeout retry=1
2026-10-28T08:15:30.123+08:00 [ERROR] database timeout retry=2
```

JSON Lines 示例：

```json
{"ts":"2026-10-28T08:15:30.123Z","level":"ERROR","msg":"database timeout retry=3"}
```

JSON 记录中的时间戳直接从 `ts` 字段读取，无需在 JSON 对象外添加时间信息。

时间解析支持公历日期、秒级时间和小数秒。没有时区标记的时间按 UTC 处理；带 `Z` 或 `±HH:MM` 时区偏移的时间会转换为 UTC。内部时间精度为分钟，秒和小数秒会向下取整，因此 `--from` 和 `--to` 按完整分钟进行筛选。

当前不支持仅包含 `HH:MM:SS` 的时间，也不会自动推断本地时区或处理夏令时。

没有有效时间戳的记录仍会计入日志概览，但不会参与时间桶统计。未指定时间筛选条件时，这些记录仍可被计数；指定 `--from` 或 `--to` 后，它们不会匹配时间条件。

## 命令行参数

以下示例展示了时间范围、日志级别和关键词过滤的组合用法：

```bash
./bin/moonlog analyze app.log --report incident-2.md \
  --bucket-minutes 5 --baseline-buckets 6 --multiplier 3 --min-errors 3 \
  --context 10 --context-mode errors --max-samples 20 \
  --level ERROR --keyword timeout \
  --signature 'ERROR: database timeout retry=#' \
  --from "2026-10-28 08:00:00Z" --to "2026-10-28 09:00:00Z"
```

主要参数如下：

| 参数 | 作用 |
|---|---|
| `--report` | 必填，报告输出路径，已存在的文件不会被覆盖 |
| `--format` | 报告格式：`markdown`（默认）或 `json` |
| `--sampling` | 采样方式：`first`（默认）或 `distributed` |
| `--bucket-minutes` | 时间桶长度，默认 5 分钟 |
| `--baseline-buckets` | 滑动基线使用的历史桶数，默认 6 |
| `--multiplier` | 尖峰检测倍数，默认 3 |
| `--min-errors` | 触发尖峰所需的最少错误数，默认 3 |
| `--context` | 每个目标前后采集的上下文行数，默认 10 |
| `--context-mode` | 上下文目标：`spikes`（默认）或 `errors` |
| `--max-samples` | 最多采集的上下文目标数，默认 20 |
| `--level` | 按日志级别过滤 |
| `--keyword` | 按消息内容过滤，区分大小写 |
| `--signature` | 完整错误签名，用于限定上下文目标并输出各尖峰的对比 |
| `--from` / `--to` | 限定分析的时间范围 |

时间覆盖范围根据时间筛选条件内的全部有效时间戳确定，级别和关键词过滤不会改变时间轴。因此，即使健康期的日志没有匹配关键词，其对应的零错误时间桶仍可参与基线计算。

时间桶中的错误计数则只统计满足全部过滤条件的记录。上下文采集使用另一套规则：目标行必须满足过滤条件；`spikes` 模式还要求位于尖峰区间内，`errors` 模式则接受所有匹配的 ERROR/FATAL 记录。周边上下文保留物理相邻行，不再应用这些过滤条件。

`errors` 模式下，未指定 `--from` 或 `--to` 时，没有有效时间戳的 ERROR/FATAL 记录也可成为上下文目标；设置任一时间边界后，这些记录会被排除。`--context-mode` 不影响尖峰检测、尖峰区间或尖峰内签名排名。

`--signature` 在上下文目标上再叠加一层精确匹配，并额外输出每个尖峰的签名对比。它的取值会原样使用，不做数字归一化，因此必须写成签名最终的样子。

```bash
./bin/moonlog analyze fixtures/incident.log --report incident.md \
  --signature 'ERROR: database timeout retry=#'
```

## 报告格式

`--format` 只决定写入文件的序列化方式；两种格式使用同一次分析的结果，扫描次数和统计规则完全相同。报告文件仍然不可覆盖，已存在的路径会直接报错。

```bash
# 默认 Markdown
./bin/moonlog analyze fixtures/incident.log --report incident.md

# 结构化 JSON
./bin/moonlog analyze fixtures/incident.log --report incident.json --format json
```

`--format` 只接受 `markdown` 和 `json`。未知取值、重复传入以及缺少取值都会报错，且不会创建报告文件。

### Markdown

Markdown 报告包含本次分析的参数与过滤条件（含上下文模式）、日志计数、尖峰区间、每个尖峰内独立的签名排名（最多前 10 项）、全局签名排名、日志错误占比（全范围/各尖峰/各观察时间桶）和原始上下文，结构见 [`docs/example-report.md`](docs/example-report.md)。观察时间桶的表按前 50 个展示，超出时注明截断，完整数据在 JSON 中。

指定 `--signature` 时，报告在全局排名之后多出一节「Selected signature comparison」：每个尖峰一组基线/尖峰窗口表格，加一行频率倍数。示例报告即由 `./bin/moonlog analyze fixtures/incident.log --report incident.md --signature 'ERROR: database timeout retry=#'` 生成。

### JSON

JSON 报告由核心的 `ReportResult::json_report()` 生成，文件内容整体是一份合法的 JSON 文档。终端摘要只写到标准输出，不会混入文件，因此可以直接交给 `jq`、Python 的 `json.loads` 或其他工具处理。

```json
{
  "selected_signature": "ERROR: database timeout retry=#",
  "signature_comparisons": [
    {
      "signature": "ERROR: database timeout retry=#",
      "before_start": "2026-10-28 08:00:00Z",
      "spike_start": "2026-10-28 08:30:00Z",
      "spike_end_exclusive": "2026-10-28 08:35:00Z",
      "before_minutes": "30",
      "spike_minutes": "5",
      "before_count": "0",
      "spike_count": "4",
      "before_per_minute": 0,
      "spike_per_minute": 0.8,
      "rate_multiplier": null
    }
  ],
  "schema_version": 1,
  "engine_version": "0.1.0",
  "source": "fixtures/incident.log",
  "config": {
    "bucket_minutes": 5,
    "baseline_buckets": 6,
    "multiplier": 3,
    "min_errors": 3,
    "context": 10,
    "context_mode": "spikes",
    "max_samples": 20,
    "max_buckets": 100000,
    "max_signatures": 1000
  },
  "filter": {
    "level": null,
    "keyword": "",
    "from_inclusive": null,
    "to_inclusive": null
  },
  "time_semantics": "UTC; seconds floored to minutes; filters inclusive; spike ends exclusive",
  "log_error_ratio_semantics": "Time-valid physical log lines within inclusive time filters; independent of level and keyword; ERROR/FATAL divided by all levels; fraction 0..1, null for zero denominator; not a request failure rate",
  "summary": {
    "log_error_ratio": { "total": "30", "errors": "4", "fraction": 0.13333333333333333 },
    "total": 30,
    "matched": 30,
    "untimed": 0,
    "errors": 4,
    "spike_count": 1,
    "sampled_targets": 4,
    "omitted_targets": 0,
    "omitted_global_signature_occurrences": 0
  },
  "level_counts": { "DEBUG": 0, "INFO": 26, "WARN": 0, "ERROR": 4, "FATAL": 0, "OTHER": 0 },
  "buckets": [
    {
      "start": "2026-10-28 08:30:00Z",
      "end_exclusive": "2026-10-28 08:35:00Z",
      "total": 5,
      "errors": 4
    }
  ],
  "observation_buckets": [
    {
      "start": "2026-10-28 08:30:00Z",
      "end_exclusive": "2026-10-28 08:35:00Z",
      "log_error_ratio": { "total": "5", "errors": "4", "fraction": 0.8 }
    }
  ],
  "spikes": [
    {
      "log_error_ratio": { "total": "5", "errors": "4", "fraction": 0.8 },
      "start": "2026-10-28 08:30:00Z",
      "end_exclusive": "2026-10-28 08:35:00Z",
      "errors": 4,
      "peak_errors": 4,
      "baseline": 0,
      "signatures": [
        { "text": "ERROR: database timeout retry=#", "count": 4 }
      ],
      "omitted_signature_occurrences": 0
    }
  ],
  "signatures": [ { "text": "ERROR: database timeout retry=#", "count": 4 } ],
  "context_windows": [
    {
      "targets": [23, 24, 25, 26],
      "lines": [
        { "number": 22, "text": "2026-10-28 08:29:00 [INFO] health check ok" },
        { "number": 23, "text": "2026-10-28 08:30:00 [ERROR] database timeout retry=1" }
      ]
    }
  ],
  "diagnostic_note": "Rule-based evidence; spikes do not establish a root cause. ..."
}
```

示例为节选：`buckets`、`observation_buckets`、`spikes`、`signatures` 和 `context_windows[].lines` 只保留了部分条目；`selected_signature` 与 `signature_comparisons` 来自同一份带 `--signature` 的运行。

字段说明：

| 字段 | 说明 |
|---|---|
| `schema_version` | 当前为 `1`，结构不兼容变化时递增 |
| `engine_version` | 生成报告的 MoonLog 版本 |
| `source` | 单文件输入路径，按用户传入原样保留；多文件时为 `null` |
| `sources` | 输入文件路径数组，按传入顺序；单文件时为单元素数组 |
| `sampling` | 采样方式：`first` 或 `distributed` |
| `scans` | 实际执行的扫描遍数（单文件默认 2，多文件或 `distributed` 为 3） |
| `config` | 本次分析的核心配置，含上下文模式 |
| `filter` | 级别、关键词与时间边界，时间边界为包含端点 |
| `selected_signature` | 本次指定的完整签名；未指定时为 `null`，且不参与任何统计 |
| `signature_comparisons` | 每个尖峰的基线/尖峰对比：窗口起止、分钟数、次数、每分钟频率与频率倍数；未指定签名时为空数组 |
| `time_semantics` | 时间语义：UTC、秒向下取整到分钟、过滤含端点、尖峰结束不含 |
| `log_error_ratio_semantics` | 日志错误占比的统计口径说明，随报告一起输出 |
| `summary` | 总行数、匹配数、无有效时间戳数、ERROR+FATAL 数、尖峰数、上下文采样/遗漏数、全局签名遗漏数；另有全范围 `log_error_ratio` |
| `level_counts` | 六个级别的计数，键固定为 `DEBUG`/`INFO`/`WARN`/`ERROR`/`FATAL`/`OTHER` |
| `buckets` | 过滤后统计：每个时间桶的起止（结束不含）、总行数与错误数，空桶补零 |
| `observation_buckets` | 观察口径：每个时间桶的起止（结束不含）与 `log_error_ratio`，不受级别/关键词过滤影响 |
| `spikes` | 尖峰区间、错误数、单桶峰值、起始基线、该区间的 `log_error_ratio`，以及该尖峰内**全部已保留**签名和容量遗漏数 |
| `signatures` | 全局错误签名排名，同样为全部已保留项 |
| `context_windows` | 采样到的上下文窗口：每个窗口含所属 `source`、目标行号与被采集的原始行（`number` 为文件内行号） |
| `diagnostic_note` | 结论边界说明，提醒尖峰不代表根因 |

`log_error_ratio` 对象三个字段的含义：

| 键 | 类型 | 说明 |
|---|---|---|
| `total` | 十进制字符串（`Int64`） | 区间内的时间有效日志行数，即分母 |
| `errors` | 十进制字符串（`Int64`） | 区间内的 ERROR + FATAL 行数，即分子 |
| `fraction` | 数值或 `null` | `errors / total`，取值 0..1；分母为 0 时为 `null` |

`total` 和 `errors` 是 64 位整数，JSON 中以十进制**字符串**输出以避免精度丢失，因此 `jq` 里需要 `tonumber` 或字符串比较；`fraction` 是普通数值。

`signature_comparisons[]` 的字段沿用同一约定：`before_start`、`spike_start`、`spike_end_exclusive` 是 UTC 字符串，前窗口 `[before_start, spike_start)` 与尖峰窗口 `[spike_start, spike_end_exclusive)` 都是左闭右开；`before_minutes`、`spike_minutes`、`before_count`、`spike_count` 是 64 位整数，同样以十进制字符串输出；`before_per_minute` 与 `spike_per_minute` 是数值；`rate_multiplier` 在基线次数为 0 时为 `null`，表示倍数没有定义，而不是 0 倍。

使用 JSON 时需要注意：

- 时间统一为 UTC 字符串；`end_exclusive` 按定义不包含在区间内，桶的 `end_exclusive` 是桶边界。
- 数组顺序稳定（文件顺序、时间、排名），但 JSON 对象的键顺序不作为接口保证。
- `spikes[].signatures` 和 `signatures` 输出全部已保留签名，不受终端摘要的 3 项、Markdown 表格的 10 项展示限制；容量遗漏由 `omitted_signature_occurrences` 和 `omitted_global_signature_occurrences` 单独记录。
- `buckets` 是过滤后的统计，`observation_buckets` 和所有 `log_error_ratio` 是过滤前的观察口径：`--level`、`--keyword` 只影响前者。
- `context_windows[].lines` 保存**未经过滤的原始上下文行**，`source`、签名等字段也保留输入原文。这些内容可能含业务数据或凭据，分享前请自行检查。
- `config` 只覆盖核心 `result.config` 中的字段。`--max-line-bytes` 是宿主读取参数，在进入分析前生效，不在 `result.config` 中，因此 JSON 里没有它；JSON 不代表所有 CLI 参数都已导出。
- `selected_signature` 只有在传入 `--signature` 时才有值，`signature_comparisons` 只有此时才非空。指定签名只影响上下文目标与这一组对比，`summary`、`spikes`、`buckets`、`signatures` 等原有统计保持不变。

### 终端摘要

两种格式都会在报告成功写入后向标准输出打印同一份摘要；写入失败（例如目标文件已存在）时不打印，也不会有残留输出。

```text
Source: fixtures/incident.log
Scanned 30 lines; matched 30; untimed 0; errors 4; spikes 1.
Log error ratio (all observed lines): 13.3% (4/30).
Ratio scope: time-valid lines only, OTHER included; level/keyword filters do not apply; untimed lines are excluded; a log-line share, not a request failure rate.
Spike 1: 2026-10-28 08:30:00Z to 2026-10-28 08:35:00Z (end exclusive); errors 4.
  Log error ratio: 80.0% (4/5).
  Top signatures (1): ERROR: database timeout retry=# (4)
Selected signature: ERROR: database timeout retry=#
  Exact match on the complete normalized signature; counts apply the level/keyword/time filters; the pre-spike window can contain earlier incidents and is not a healthy window.
  Spike 1 baseline: 2026-10-28 08:00:00Z to 2026-10-28 08:30:00Z (end exclusive); 30 min; 0 occurrence(s); 0.000 per minute.
  Spike 1 spike: 2026-10-28 08:30:00Z to 2026-10-28 08:35:00Z (end exclusive); 5 min; 4 occurrence(s); 0.800 per minute.
  Spike 1 rate multiplier: N/A (zero baseline: 0 occurrence(s) over 30 min; spike 4 over 5 min).
Context mode: spikes; sampled 4; omitted 0.
Markdown report written to incident.md.
```

摘要包含扫描数、匹配数、错误数、尖峰数，全范围日志错误占比与每行的 `errors/total`，每个尖峰的区间（结束不含）、错误数、占比和前 3 类签名及次数，上下文模式与采样/遗漏数，以及签名容量遗漏提示。上面的示例带 `--signature`，因此还包含选定签名与每个尖峰的窗口对比。

- 日志错误占比在分母为零时显示 `N/A`，并同时打印 `errors/total`，因此 `N/A` 与 `0.0%` 不会混淆。
- 摘要里另起一行说明占比口径：只看时间有效行、先于级别/关键词过滤、不是请求失败率。尖峰行的 `errors` 是过滤后的错误数，占比括号里的两个数来自观察口径，两者在 `--level`/`--keyword` 生效时可能不同。
- 每个尖峰最多展示 3 项签名。保留项超过 3 项时会明确说明其余项只是显示截断，不是容量遗漏；完整排名在 JSON 中。
- 没有任何尖峰时，摘要只说明规则未命中，不代表服务正常。
- 带 `--signature` 时追加选定签名与各尖峰的对比行：两侧窗口起止（结束不含）、分钟数、次数与每分钟频率；基线为零时倍数显示 `N/A`，并在同一行给出两侧的次数。没有尖峰时只说明没有比较窗口，不会声称该签名从未出现。
- 签名文本、输入路径和报告路径来自用户输入，打印前会转义换行、回车、制表符、ESC 等控制字符（如 `\x1b`、`\n`、`\t`），避免日志内容伪造终端输出或触发转义序列。JSON 文件保留原文，不做这种展示转义。

## 流式处理与资源限制

MoonLog 使用多遍扫描完成分析，避免将全部原始日志长期保存在内存中。单个输入文件默认使用两遍；多个文件或 `--sampling distributed` 使用三遍。

1. **首次扫描：** 以 64 KiB 为单位读取每个文件，在 MoonBit 中按物理行切分，解析记录并累计统计数据。所有文件喂入同一个分析器，时间桶与尖峰统一。
2. **尖峰分析：** 整理时间桶、补齐空桶，计算滑动基线并识别连续尖峰区间。
3. **再次扫描：** 统计每个尖峰的签名、选定签名的对比窗口，以及匹配目标的出现总数；同时用固定容量的 Ring Buffer 采集目标行及其前后文，并合并重叠或相邻的上下文窗口。
4. **（可选）第三次扫描：** 多文件或 `distributed` 采样时，按采样计划提取带来源标识的多文件上下文窗口。
5. **生成报告：** 由同一次分析结果生成 Markdown 或 JSON 报告并写入文件，随后在终端打印摘要。

每个文件在每一遍扫描中都会校验自身的行数与滚动摘要，而不是只比较所有文件的合计值。该检查不提供密码学完整性保证，因此建议分析稳定的日志副本。当前不支持实时追加日志。

为限制资源占用，程序对输入和统计数据设置了以下默认上限：

| 项目 | 默认上限 |
|---|---:|
| 单行长度 | 65,536 字节 |
| 连续时间桶数（含空桶） | 100,000 |
| 全局错误签名数量 | 1,000 |
| 尖峰内签名组合数量（全部尖峰合计） | 1,000 |
| 上下文采样目标数 | 20 |
| 错误签名长度 | 消息部分 512 字符（完整签名含级别前缀，最多 519 字符） |

可通过 `--max-line-bytes`、`--max-buckets`、`--max-signatures` 和 `--max-samples` 调整相应限制，具体取值仍受参数自身上限约束。

超过限制的输入会报错，不会静默丢弃超长行或超出范围的数据。错误签名达到容量上限后，未保留签名的出现次数会计入遗漏计数。

尖峰内签名容量在全部尖峰之间共享：按文件读取顺序，最多保留 `max_signatures` 个“尖峰与签名”组合；同一签名出现在不同尖峰时分别占用名额。已保留的签名继续精确计数，未保留的错误出现次数累计到对应尖峰的遗漏数。报告会分别标注“仅展示前 10 项”的显示截断和容量不足造成的遗漏；尖峰签名为空且存在遗漏时，报告会明确说明该尖峰并非没有错误。

内存使用量主要取决于时间桶数量、保留的错误签名、上下文样本和当前处理的单行长度，不会随原始日志总行数线性增长。不过，补齐空桶意味着超大的时间跨度仍可能消耗较多内存。统计计数使用 32 位 `Int`，当前实现面向几十兆至数百兆字节的常规日志，不适用于超过 21 亿行的输入。

`nativeio/stdio.c` 只负责操作系统层面的字节 I/O，包括文件打开、读取、写入、关闭及错误处理。解析、行切分、过滤、统计和报告逻辑均由 MoonBit 实现。

当前文件检查使用 POSIX 接口，支持目标为 macOS 和 Linux，尚未适配 Windows。

## 测试与性能

项目提供 MoonBit 核心测试、真实 CLI 集成测试和合成日志基准测试。

```bash
make test
make integration
make check
python3 scripts/benchmark.py --lines 500000
```

`make test` 运行 MoonBit 核心断言；`make integration` 编译实际 CLI 并执行 Python 标准库集成测试；`make check` 将警告视为错误，并检查代码格式。

测试覆盖以下行为：

- 日志解析、过滤和报告生成的边界条件；
- 10,000 行日志的精确计数；
- 尖峰阈值、零基线、基线预热、空桶、乱序记录、跨日期统计及尖峰合并；
- 每个尖峰的独立错误签名排名、基线噪声隔离及签名容量遗漏提示；
- 上下文窗口的精确行数、文件首尾、窗口重叠和采样上限；
- 上下文模式的无尖峰错误上下文、过滤与时间边界、默认兼容和非法参数；
- 中文 JSON Lines、跨 64 KiB 读取块的 UTF-8、BOM、CRLF 和无换行末行；
- 空输入、非法参数、超长行、无效 UTF-8、目录或缺失输入；
- 已存在的报告文件，以及输入文件的软链接和硬链接保护；
- 默认 Markdown 与显式 `--format markdown` 产出完全一致；
- JSON 报告可被 Python `json.loads` 解析，`schema_version`、时间桶、上下文和遗漏计数完整；
- 两种格式的统计值与终端摘要一致，JSON 文件与终端摘要互不混入；
- 空输入、`errors` 模式、签名容量遗漏在 JSON 与终端摘要中的表现；
- `--format` 的未知取值、重复传参和缺少取值，以及 JSON 报告的文件保护；
- 终端摘要对 ESC、换行、回车、制表符以及含控制字符的输入路径的转义；
- 日志错误占比：`--level ERROR` 与关键词过滤不缩小分母、`--from`/`--to` 生效、空桶显示 N/A 且 JSON 为 `null`、OTHER 行计入分母、无时间戳行不计入，以及 Markdown、终端、JSON 三处数值一致；
- 指定签名：空值/重复/缺值报错、完整签名与级别前缀的精确匹配、`errors` 模式下的邻行保留、窗口左闭右开与时间边界、不同窗口时长、零基线显示 N/A、`--signature` 不改变原有统计，以及 Markdown、终端、JSON 的对比数值一致；
- 多文件：多文件合并统计与单文件合并输入一致、乱序文件与空文件不串上下文、跨文件边界不合并窗口、全局样本限额、`first`/`distributed` 的确定性选择、重复/软硬链接输入拒绝、无目标与零名额、签名筛选，以及 JSON/Markdown/终端三处来源一致；
- 文件变化检测：每一遍扫描逐文件校验行数与摘要，变化时不生成报告。

一次本机基准测试的结果如下：

| 项目 | 结果 |
|---|---|
| 环境 | macOS 26.6.2，arm64 |
| 构建类型 | release |
| 输入行数 | 500,000 |
| 输入大小 | 62,889,957 字节 |
| 运行时间 | 约 0.45 秒 |
| 峰值 RSS | 2,670,592 字节 |

该结果包含两遍文件扫描和报告写入，不包含编译及测试数据生成。测试使用合成数据，且只测量了一次，尚无其他语言的对照结果，因此只能作为当前环境下的参考数据。

示例报告见 [`docs/example-report.md`](docs/example-report.md)。

## 代码结构

```text
moon.mod / moon.pkg   原生目标与核心包配置，无第三方依赖
types.mbt             配置、记录、过滤器、桶与尖峰类型
parser.mbt            日志解析、日期与时区处理、错误签名
aggregate.mbt         流式统计、空桶补齐、滑动基线与尖峰检测
error_ratio.mbt       日志错误占比：观察桶、区间聚合与 JSON 表示
context.mbt           Ring Buffer、上下文窗口合并与采样限制
input_sampling.mbt    多文件采样计划与带来源的上下文收集器
signature_comparison.mbt  选定签名的基线/尖峰窗口计数与 JSON 表示
report.mbt            Markdown 报告生成
result.mbt            报告结果视图：JSON 导出、终端摘要数据
cmd/main/             CLI 参数解析、多遍扫描编排、报告分发与终端摘要渲染
nativeio/             MoonBit 流式读取与 C 字节 I/O 封装、输入身份校验
moonlog_test.mbt      MoonBit 核心断言
fixtures/             可复现的故障日志样例
scripts/              CLI 集成测试与合成数据基准
```

## 后续考虑

当前工作重点是完善原生 CLI 的日志分析能力和运行可靠性。以下方向可根据实际使用需求继续评估：

- **WASM 版本：** 复用现有核心逻辑，替换原生 I/O 宿主；目前尚未验证 WASM 兼容性。
- **实时日志分析：** 支持持续读取新增日志，并处理时间桶更新和持续性尖峰。
- **更多日志格式：** 根据实际应用场景增加解析规则，避免引入难以预测的通用解析行为。
- **可选的 Web 界面：** 为不习惯命令行的使用者提供报告查看与分析入口。
- **更丰富的故障分析：** 在统计证据的基础上探索其他分析方法。当前版本不包含 AI 根因判断或告警推送。

这些内容属于后续考虑范围，尚未承诺具体的实现时间。

## 许可证

MoonLog 使用 Apache-2.0 许可证，详见 [`LICENSE`](LICENSE)。
