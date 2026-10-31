# MoonLog

**本地离线日志分析工具 · CLI / WASM 网页**

**[在线体验 MoonLog](https://xzx1003.github.io/moonlog/)**：点击“使用示例日志”，按默认参数即可查看三段合成错误尖峰、错误签名及前后上下文。也可选择自己的日志，文件仅在浏览器本机处理，不上传。

MoonLog 是一个使用 MoonBit 编写的命令行工具，用于分析应用日志中的错误尖峰，并生成包含统计结果和原始日志上下文的 Markdown 报告。

工具通过确定性的统计规则识别异常错误数量，支持普通文本日志和 JSON Lines。日志解析、过滤、统计、上下文提取和报告生成均由 MoonBit 实现，编译后可作为本机原生 CLI 独立运行，无需 Node.js 或外部服务。

## 快速开始

构建环境需要 MoonBit 工具链和 C 编译器；macOS/Linux 使用 Make，Windows 使用下文的 PowerShell 脚本。本项目当前使用 `moon 0.1.20261023`，已在 macOS arm64 本机及 Linux、Windows CI 上验证。

```bash
make build
./bin/moonlog analyze fixtures/incident.log --report incident.md
./bin/moonlog analyze fixtures/incident.log --report incident.json --format json
./bin/moonlog analyze fixtures/incident.log --report incident-signature.md \
  --signature 'ERROR: database timeout retry=#'
./bin/moonlog analyze app.jsonl --report incident.md \
  --json-time-field timestamp --json-level-field severity --json-message-field message
./bin/moonlog analyze old.log app.log --report incident.md
./bin/moonlog analyze old.log app.log --report incident.md --sampling distributed
./bin/moonlog --help
```

另有实验性的浏览器版：`make web-build && make web-serve`，然后在浏览器打开 <http://localhost:8000/web/>。它通过 Web Worker 调用 MoonBit 核心的 wasm-gc 构建，文件只在本地处理，详见 [`web/README.md`](web/README.md)。

构建完成后，可将 `bin/moonlog` 复制到 PATH 中的目录，之后直接运行：

```bash
moonlog analyze app.log --report incident.md
moonlog analyze app.log --report incident.json --format json
moonlog analyze old.log app.log --report incident.md
```

默认情况下，MoonLog 不会联网。输入日志、分析过程和生成的报告均保留在本机。为避免意外覆盖数据，已有报告文件不会被覆盖；每次分析请指定新的输出文件名。

报告会包含原始日志片段，分享前请检查其中是否存在业务数据、凭据或其他敏感信息。可选的字面替换与 JSON 字段脱敏只能通过配置文件启用，规则不会经过命令行参数；它们是输出层的尽力而为措施，不保证清除所有敏感信息，也不改变统计结果。

## 当前实现

目前已完成日志解析、过滤、时间统计、错误尖峰检测、上下文提取、指定签名的窗口对比和 Markdown 报告生成，并提供核心测试与 CLI 集成测试。

**日志读取与解析**

- 支持普通单行文本和 JSON Lines，两种格式可以混合使用。
- 支持 UTF-8、文件开头的 BOM、CRLF 换行，以及末行没有换行符的情况。
- JSON 日志按可配置的顶层字符串字段读取时间、级别和消息，默认键为 `ts`、`level` 和 `msg`，可用 `--json-time-field`、`--json-level-field`、`--json-message-field` 或配置文件同名键逐项覆盖。字段名精确匹配：不回退到默认键、不推断嵌套路径（`a.b` 是字面键名）、不转换数值字段，也不小写化级别；映射只影响 JSON 行，文本行格式不变。JSON 解析拒绝重复键，最大嵌套深度为 32。
- 无效 JSON、堆栈行及无法识别的格式会保留为 `OTHER` 记录。多行堆栈不会自动合并成一个事件，但可作为上下文原文保留。
- 日志记录保留原始物理行号，便于回查源文件。

**过滤与统计**

- 支持按日志级别、消息关键词和时间范围过滤。
- 级别标签区分大小写。`DEBUG`、`INFO`、`WARN`、`ERROR`、`FATAL` 为可识别级别；其他标签（包括显式写出的 `OTHER`）归为 `OTHER`，也可用 `--level OTHER` 筛选这些记录。
- 统计结果、错误聚合和尖峰检测使用同一组过滤条件；只有日志错误占比例外，它按过滤前的观察口径统计（见下文「日志错误占比」）。
- 时间桶按 UTC 对齐，默认每桶 5 分钟；缺失的时间桶会补零，乱序记录按时间排序后参与统计。
- 错误签名以级别前缀开头，仅将消息中的连续十进制数字替换为 `#`，不尝试推断根因。签名按出现次数排序。

**输出脱敏（可选）**

例如原始行 `{"token":"abc123","message":"authentication failed: abc123"}`，只配置 `redact-fields: ["token"]` 仍会保留消息中的 `abc123`，它也可能进入错误签名。需要同时配置 `redact-text` 字面规则并人工复核。当前不默认猜测凭据模式，避免误删普通业务文本；不提供“完整脱敏”保证。

- 脱敏规则只能写在 `--config` 指定的 JSON 文件中，命令行不接受 `--redact-text` 或 `--redact-fields`，避免凭据进入 shell history。
- `redact-text` 是有序的字面替换数组，元素为 `{"needle": "...", "replacement": "..."}`。它作用于来源路径、关键词、选定签名、排名签名、上下文文本、报告路径提示和会回显这些内容的错误信息。
- `redact-fields` 是 JSON 字段名数组，只在上下文中的原始 JSON 行上递归匹配精确字段名（如 `token`），并把整个值替换为 `[REDACTED]`。合法 JSON 中的嵌套字段也会处理；非法 JSON 只应用字面规则。
- 字段规则不会按字段名递归改写整份报告，因此不会破坏报告结构；它们也不会作用于解析后的消息或错误签名。字段值如果进入了消息或签名，必须用 `redact-text` 覆盖。
- 脱敏只影响渲染输出，源日志、扫描次数、计数、尖峰、签名分组、签名对比和目标选择都保持原样。
- 启用后 Markdown 和终端摘要会显示规则数量与免责声明；JSON 报告增加 `redaction` 元数据。元数据只包含规则数量和“不保证清除所有敏感信息”的说明，不写入规则、字段名、needle 或 replacement。

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

报告中的时间、统计结果和上下文均来自本地输入文件，不依赖外部服务。Markdown 摘要与终端摘要都会列出本次分析使用的有效 JSON 字段映射，便于确认自定义键名是否生效。

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

JSON 记录默认从 `ts`、`level` 和 `msg` 三个顶层字符串字段读取时间、级别和消息，无需在 JSON 对象外添加时间信息。如果日志使用其他键名，可以逐项覆盖：

```bash
./bin/moonlog analyze app.jsonl --report incident.md \
  --json-time-field timestamp --json-level-field severity --json-message-field message
```

映射只做精确的顶层字符串匹配。当前映射未命中的 JSON 行、字段值不是字符串、字段只存在于嵌套对象中，或只提供了默认键名时，该行不会按 JSON 记录解析；工具不会回退到 `ts`/`level`/`msg`，不会把 `a.b` 当作嵌套路径，不会把数值时间戳或数值级别转成字符串，也不会把级别小写化。文本日志（如 `2026-10-28 08:15:30 [ERROR] ...`）始终按原格式解析，与映射无关。三个字段名必须非空、互不相同、不含 C0/DEL 控制字符，且最长 256 个 UTF-16 单元。

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
| `--json-time-field` | JSON 顶层时间字段名，默认 `ts` |
| `--json-level-field` | JSON 顶层级别字段名，默认 `level` |
| `--json-message-field` | JSON 顶层消息字段名，默认 `msg` |
| `--level` | 按日志级别过滤 |
| `--keyword` | 按消息内容过滤，区分大小写 |
| `--signature` | 完整错误签名，用于限定上下文目标并输出各尖峰的对比 |
| `--from` / `--to` | 限定分析的时间范围 |

`redact-text` 和 `redact-fields` 只能写在配置文件中，不是命令行参数；规则内容不会出现在诊断信息里。

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

Markdown 报告包含本次分析的参数与过滤条件（含上下文模式）、日志计数、尖峰区间、每个尖峰内独立的签名排名（最多前 10 项）、全局签名排名、日志错误占比（全范围/各尖峰/各观察时间桶）和原始上下文，结构见 [`docs/example-report.md`](docs/example-report.md)。报告摘要列出有效的 JSON 字段映射（默认 `time=ts; level=level; message=msg`）。启用脱敏时摘要还会增加 `Redaction:` 行，说明字面规则数、JSON 字段规则数和免责声明。观察时间桶的表按前 50 个展示，超出时注明截断，完整数据在 JSON 中。

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
  "json_fields": {
    "time": "ts",
    "level": "level",
    "message": "msg"
  },
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

启用脱敏后，`source`/`sources`、`filter.keyword`、`selected_signature`、签名文本和上下文 `source` 都会先执行字面替换；`context_windows[].lines[].text` 先执行字面替换，若配置了 `redact-fields`，合法 JSON 行还会把指定字段的整个值替换为 `[REDACTED]`。字段规则只作用于这些原始上下文行，不会按字段名递归改写报告自身的键。`redaction` 元数据只在启用时出现。

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
| `json_fields` | 本次分析使用的有效 JSON 顶层字段映射：`time`、`level`、`message`，已合并默认值、配置与 CLI 覆盖 |
| `time_semantics` | 时间语义：UTC、秒向下取整到分钟、过滤含端点、尖峰结束不含 |
| `log_error_ratio_semantics` | 日志错误占比的统计口径说明，随报告一起输出 |
| `summary` | 总行数、匹配数、无有效时间戳数、ERROR+FATAL 数、尖峰数、上下文采样/遗漏数、全局签名遗漏数；另有全范围 `log_error_ratio` |
| `level_counts` | 六个级别的计数，键固定为 `DEBUG`/`INFO`/`WARN`/`ERROR`/`FATAL`/`OTHER` |
| `buckets` | 过滤后统计：每个时间桶的起止（结束不含）、总行数与错误数，空桶补零 |
| `observation_buckets` | 观察口径：每个时间桶的起止（结束不含）与 `log_error_ratio`，不受级别/关键词过滤影响 |
| `spikes` | 尖峰区间、错误数、单桶峰值、起始基线、该区间的 `log_error_ratio`，以及该尖峰内**全部已保留**签名和容量遗漏数 |
| `signatures` | 全局错误签名排名，同样为全部已保留项 |
| `context_windows` | 采样到的上下文窗口：每个窗口含所属 `source`、目标行号与被采集的原始行（`number` 为文件内行号）；启用脱敏时文本已按规则处理 |
| `diagnostic_note` | 结论边界说明，提醒尖峰不代表根因 |
| `redaction` | 仅在启用脱敏时出现：`literal_rule_count`、`json_field_rule_count` 与免责声明；不含规则、字段名或替换值 |

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
- `context_windows[].lines` 保存**未经过滤的上下文行**；未启用脱敏时是原始输入原文，启用后按字面规则和 `redact-fields` 处理。`source`、签名等字段同样可能含业务数据或凭据，分享前请自行检查，并注意脱敏不保证清除全部敏感信息。
- `config` 只覆盖核心 `result.config` 中的字段。`--max-line-bytes` 是宿主读取参数，在进入分析前生效，不在 `result.config` 中，因此 JSON 里没有它；JSON 不代表所有 CLI 参数都已导出。
- `selected_signature` 只有在传入 `--signature` 时才有值，`signature_comparisons` 只有此时才非空。指定签名只影响上下文目标与这一组对比，`summary`、`spikes`、`buckets`、`signatures` 等原有统计保持不变。

### 终端摘要

两种格式都会在报告成功写入后向标准输出打印同一份摘要；写入失败（例如目标文件已存在）时不打印，也不会有残留输出。

```text
Source: fixtures/incident.log
JSON fields: time=ts; level=level; message=msg (exact top-level string keys; text logs unaffected).
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

摘要包含扫描数、匹配数、错误数、尖峰数，全范围日志错误占比与每行的 `errors/total`，每个尖峰的区间（结束不含）、错误数、占比和前 3 类签名及次数，上下文模式与采样/遗漏数，以及签名容量遗漏提示。摘要还会列出本次使用的有效 JSON 字段映射。上面的示例带 `--signature`，因此还包含选定签名与每个尖峰的窗口对比。

- 日志错误占比在分母为零时显示 `N/A`，并同时打印 `errors/total`，因此 `N/A` 与 `0.0%` 不会混淆。
- 摘要里另起一行说明占比口径：只看时间有效行、先于级别/关键词过滤、不是请求失败率。尖峰行的 `errors` 是过滤后的错误数，占比括号里的两个数来自观察口径，两者在 `--level`/`--keyword` 生效时可能不同。
- 每个尖峰最多展示 3 项签名。保留项超过 3 项时会明确说明其余项只是显示截断，不是容量遗漏；完整排名在 JSON 中。
- 没有任何尖峰时，摘要只说明规则未命中，不代表服务正常。
- 带 `--signature` 时追加选定签名与各尖峰的对比行：两侧窗口起止（结束不含）、分钟数、次数与每分钟频率；基线为零时倍数显示 `N/A`，并在同一行给出两侧的次数。没有尖峰时只说明没有比较窗口，不会声称该签名从未出现。
- 签名文本、输入路径和报告路径来自用户输入，打印前会转义换行、回车、制表符、ESC 等控制字符（如 `\x1b`、`\n`、`\t`），避免日志内容伪造终端输出或触发转义序列。JSON 文件保留原文，不做这种展示转义。
- 启用配置脱敏时，来源路径、签名文本和报告路径提示会先执行字面替换，再转义输出；摘要还会增加一行 `Redaction:`，只显示字面规则数、JSON 字段规则数和免责声明。字段规则不适用于终端摘要里的签名或路径，它们需要 `redact-text` 字面规则。

## 可选尖峰检测算法

CLI 默认仍为 `moving-average`，也可用 `--detector ewma` 或 `--detector mad`。三者检测的都是 ERROR/FATAL 日志数量，不是请求失败率；不会自动排除流量或周期变化，也不能保证识别持续故障。

| 参数 | 默认 | 作用 |
|---|---|---|
| `--detector` | `moving-average` | `moving-average` / `ewma` / `mad` |
| `--ewma-alpha` | 0.3 | 仅 EWMA；有限数，0 < alpha <= 1 |
| `--mad-threshold` | 3 | 仅 MAD；有限数，0 < k <= 1000 |

同名配置键可设置默认值，CLI 覆盖配置。配置层的非法值即使被 CLI 覆盖也会被拒绝。合法但对当前算法无效的参数仍接受：alpha 仅用于 EWMA，MAD threshold 仅用于 MAD，`multiplier` 对 MAD 无效。数值采用 JSON 数字语法，拒绝 NaN、Infinity 和字符串类型。

```bash
./bin/moonlog analyze fixtures/incident.log --detector ewma --ewma-alpha 0.3 --report ewma.md
./bin/moonlog analyze fixtures/incident.log --detector mad --mad-threshold 3 --report mad.json --format json
```

预热、零 MAD、严格阈值和基线更新规则见 [检测算法契约](docs/detectors.md)。MAD 每桶 O(n log n)，n 为基线桶数，不能推断与移动平均同速。非默认算法会在 JSON config、Markdown 和终端中注明有效算法及参数；默认输出保持兼容。浏览器本轮仍使用默认 Moving Average，尚无算法切换入口。公开人工事故标注集与 Precision/Recall/F1 评测尚未建立，因此没有准确率提升的结论。

## 流式处理与资源限制

MoonLog 使用多遍扫描完成分析，避免将全部原始日志长期保存在内存中。单个输入文件默认使用两遍；多个文件或 `--sampling distributed` 使用三遍。

1. **首次扫描：** 以 64 KiB 为单位读取每个文件，在 MoonBit 中按物理行切分，解析记录并累计统计数据。所有文件喂入同一个分析器，时间桶与尖峰统一。
2. **尖峰分析：** 整理时间桶、补齐空桶，计算滑动基线并识别连续尖峰区间。
3. **再次扫描：** 统计每个尖峰的签名、选定签名的对比窗口，以及匹配目标的出现总数；同时用固定容量的 Ring Buffer 采集目标行及其前后文，并合并重叠或相邻的上下文窗口。
4. **（可选）第三次扫描：** 多文件或 `distributed` 采样时，按采样计划提取带来源标识的多文件上下文窗口。
5. **生成报告：** 由同一次分析结果生成 Markdown 或 JSON 报告并写入文件，随后在终端打印摘要。

每个文件在每一遍扫描中都会校验自身的行数与原始字节 SHA-256，而不是只比较所有文件的合计值或解码后的字符串哈希；BOM、换行符和末尾换行的变化也会被检测。CLI 与 WASM 共用 MoonBit 增量 SHA-256 实现。该校验用于检查多遍读取是否一致，不是来源认证、文件锁或不可变快照，仍应分析稳定日志副本；当前不支持实时追加日志。

记录总数、级别/签名计数、时间桶/尖峰计数及物理行号使用 `Int64`，数组索引与受限配置保留 `Int32`。单次 Analyzer 最多接受 9,000,000,000,000 行，超出会在累加前报错；该上限使阈值乘法不超出 Int64，并让原有 JSON 数字字段保持精确。已有错误占比和签名对比中的 Int64 字符串字段保持原接口。

为限制资源占用，程序对输入和统计数据设置了以下默认上限：

| 项目 | 默认上限 |
|---|---:|
| 单行长度 | 65,536 字节 |
| 连续时间桶数（含空桶） | 100,000 |
| 全局错误签名数量 | 1,000 |
| 尖峰内签名组合数量（全部尖峰合计） | 1,000 |
| 上下文采样目标数 | 20 |
| 错误签名长度 | 消息部分 512 字符（完整签名含级别前缀，最多 519 字符） |
| `redact-text` 规则数 | 100 |
| 单条 needle / replacement 长度 | 各 1,024 个 UTF-16 单元 |
| `redact-fields` 字段数 | 100 |
| 单个脱敏字段名长度 | 256 个 UTF-16 单元 |

可通过 `--max-line-bytes`、`--max-buckets`、`--max-signatures` 和 `--max-samples` 调整相应限制，具体取值仍受参数自身上限约束。脱敏规则同样有上限：`redact-text` 最多 100 条，needle 与 replacement 各最长 1,024 个 UTF-16 单元；`redact-fields` 最多 100 个字段，字段名最长 256 个 UTF-16 单元。needle 不能为空或含换行，replacement 不能含控制字符且必须与 needle 不同；字段名不能空白、重复或含 C0/DEL 控制字符。配置文本整体仍限制为 64 KiB。

超过限制的输入会报错，不会静默丢弃超长行或超出范围的数据。错误签名达到容量上限后，未保留签名的出现次数会计入遗漏计数。

尖峰内签名容量在全部尖峰之间共享：按文件读取顺序，最多保留 `max_signatures` 个“尖峰与签名”组合；同一签名出现在不同尖峰时分别占用名额。已保留的签名继续精确计数，未保留的错误出现次数累计到对应尖峰的遗漏数。报告会分别标注“仅展示前 10 项”的显示截断和容量不足造成的遗漏；尖峰签名为空且存在遗漏时，报告会明确说明该尖峰并非没有错误。

内存使用量主要取决于时间桶数量、保留的错误签名、上下文样本和当前处理的单行长度，不会随原始日志总行数线性增长。不过，补齐空桶意味着超大的时间跨度仍可能消耗较多内存。记录计数使用 `Int64`；行数上限见上文。当前压力测试规模仍有限，类型范围不代表已验证能够处理同等规模的实际文件。

`nativeio/stdio.c` 只负责操作系统层面的字节 I/O，包括文件打开、读取、写入、关闭及错误处理。解析、行切分、过滤、统计和报告逻辑均由 MoonBit 实现。

文件 I/O 层分别适配 macOS/Linux 的 POSIX 接口和 Windows 原生接口；Windows 使用 UTF-16 宽字符路径 API，接收 UTF-8 编码的路径。

## 测试与性能

项目提供 MoonBit 核心测试、真实 CLI 集成测试和合成日志基准测试。

```bash
make test
make integration
make check
make web-test
make web-bench WEB_BENCH_MB=64
python3 scripts/benchmark.py --lines 500000
```

`make test` 运行 MoonBit 核心断言；`make integration` 编译实际 CLI 并执行 Python 标准库集成测试；`make check` 将警告视为错误，并检查代码格式。`make web-test` 在 Node 中实际实例化 wasm-gc 桥接、执行同一套 JS 分块读取代码，并将报告与 CLI JSON 逐字段对比；`make web-bench` 通过打开的文件描述符按块读取合成文件，测量浏览器路径的两遍扫描吞吐。

测试覆盖以下行为：

- 日志解析、过滤和报告生成的边界条件；
- 10,000 行日志的精确计数；
- 尖峰阈值、零基线、基线预热、空桶、乱序记录、跨日期统计及尖峰合并；
- 每个尖峰的独立错误签名排名、基线噪声隔离及签名容量遗漏提示；
- 上下文窗口的精确行数、文件首尾、窗口重叠和采样上限；
- 上下文模式的无尖峰错误上下文、过滤与时间边界、默认兼容和非法参数；
- 中文 JSON Lines、跨 64 KiB 读取块的 UTF-8、BOM、CRLF 和无换行末行；
- 读取观察顺序：块回调先于该块的行消费，可选的逐字节回调仍完整收到原始字节，超长行报错前已交付的块不被截断，CLI 不生成报告；
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
- 文件变化检测：每一遍扫描逐文件校验行数与原始字节摘要；解码后行相同但 CRLF/末尾换行不同的文件摘要不同，交换文件与快照会被拒绝，变化时不生成报告。

性能测试结果集中在文末 [Benchmark](#benchmark)：包含历史完整 CLI 基线和当前 MoonBit / Go 受限计算契约对照，分别标注版本、测量范围和限制，避免混用。

示例报告见 [`docs/example-report.md`](docs/example-report.md)。

## 浏览器版（实验性）

浏览器版是纯静态 HTML/CSS/JS 页面，通过 Web Worker 调用 `web_bridge` 编译出的 wasm-gc 模块。日志解析、过滤、统计、尖峰检测、上下文采集和 JSON 报告生成仍由 MoonBit 执行，JavaScript 只负责分块读取 `File`、调用导出函数、显示进度、交互和下载。文件不会上传，也没有分析 SDK、遥测或远程资源。

```bash
make web-build    # 生成 web/generated/moonlog_web.wasm
make web-test     # 用真实 WASM 执行桥接测试，并与 CLI JSON 对比
make web-serve    # http://localhost:8000/web/
```

页面必须通过 HTTP 静态服务器打开，`file://` 方式无法创建 module Worker 或读取 WASM。浏览器需要支持 WebAssembly GC 和 JS String Builtins；当前已在本机 Qoder Desktop 内置 Chromium 150（Electron 43.1.1）中验证，其他浏览器尚未验证。

当前只接入单文件、spikes 上下文模式和 first 采样，不展示多文件、distributed、指定签名比较、浏览器配置文件或脱敏。只下载 JSON 报告，不提供 Markdown 导出。报告和上下文可能包含敏感原文，网页版没有脱敏，下载或分享前请自行检查。

桥接导出/导入约定、Base64 分块协议、Worker 消息和与 CLI 的来源名差异见 [`web/README.md`](web/README.md)。

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
browser/              WASM 会话：两遍扫描、分块与上下文收集
web_bridge/           wasm-gc 导出桥接（字符串与 Base64 ABI）
web/                  静态页面、Worker、文件分块与桥接 JS、WASM 测试
cmd/main/             CLI 参数解析、多遍扫描编排、报告分发与终端摘要渲染
nativeio/             MoonBit 流式读取与 C 字节 I/O 封装、输入身份校验
moonlog_test.mbt      MoonBit 核心断言
fixtures/             可复现的故障日志样例
scripts/              CLI/浏览器集成测试、WASM 执行测试与合成数据基准
```

## 后续考虑

当前工作重点是完善原生 CLI 的日志分析能力和运行可靠性。以下方向可根据实际使用需求继续评估：

- **浏览器版完整能力：** 当前已有实验性的单文件页面（JSON 输出，见 [`web/README.md`](web/README.md)）；多文件、distributed 采样、指定签名比较、浏览器配置文件、脱敏和 Markdown 导出尚未接入，也未计划部署。
- **实时日志分析：** 支持持续读取新增日志，并处理时间桶更新和持续性尖峰。
- **更多日志格式：** 根据实际应用场景增加解析规则，避免引入难以预测的通用解析行为。
- **更丰富的故障分析：** 在统计证据的基础上探索其他分析方法。当前版本不包含 AI 根因判断或告警推送。

这些内容属于后续考虑范围，尚未承诺具体的实现时间。

## 许可证

MoonLog 使用 Apache-2.0 许可证，详见 [`LICENSE`](LICENSE)。

## 配置文件

仅在显式传入 `--config` 时读取 JSON，不自动搜索当前目录或用户目录。
覆盖顺序是：内置默认值 → 配置文件 → 命令行。同一命令行选项仍不可重复。

```bash
moonlog analyze app.log --config config/moonlog.example.json --report incident.md
moonlog analyze app.log --config config/moonlog.example.json --context 3 --report incident.json --format json
```

完整示例见 [`config/moonlog.example.json`](config/moonlog.example.json)。键名使用 CLI 长选项去掉 `--` 的形式。
允许的数值键：`bucket-minutes`、`baseline-buckets`、`multiplier`、`min-errors`、`context`、`max-samples`、`max-buckets`、`max-signatures`、`max-line-bytes`；范围与命令行一致。
允许的字符串键：`format`、`sampling`、`context-mode`、`json-time-field`、`json-level-field`、`json-message-field`。
JSON 字段键按字符串校验，并遵守与 CLI 相同的字段名规则：非空、互不相同、不含 C0/DEL 控制字符、最长 256 个 UTF-16 单元。配置文件自身的映射必须合法，即使其中某个键随后被 CLI 覆盖。
未知键、重复键、错误类型及越界值会报错，即使该值被 CLI 覆盖也必须合法。
输入文件、报告路径、过滤条件均须在命令行指定，配置不能改变数据读写目标。
配置文本限制为 64 KiB（按读取后的字符计），单行仍受默认 65,536 字节读取限制。

脱敏键只允许出现在配置文件中，没有对应的 CLI 参数：

```json
{
  "redact-text": [
    {"needle": "alice@example.com", "replacement": "[EMAIL]"},
    {"needle": "token=abc123", "replacement": "token=[REDACTED]"}
  ],
  "redact-fields": ["token", "password", "authorization"]
}
```

`redact-text` 必须是对象数组（空数组合法，相当于不启用字面规则），每个对象只能有 `needle` 和 `replacement` 两个字符串键。替换按数组顺序执行，规则内容不会写入报告、元数据或诊断；配置错误只报告位置（如 `redact-text[0]`），不回显 needle 或 replacement。`redact-fields` 必须是字符串数组（空数组合法），字段名精确匹配、区分大小写，只作用于上下文中的原始 JSON 行。字段规则无法覆盖解析后的消息或错误签名，字段值如果出现在这些位置，需要增加对应的 `redact-text` 字面规则。脱敏是输出层的尽力而为措施，不改变源日志或任何统计结果，也不保证清除所有敏感信息。诊断信息对命中的 needle 使用中性占位符 `[REDACTED]`，而不使用配置的 replacement。

## 安装包与发布流程

在 GitHub Actions 手动运行 **Release packages** 工作流，分别构建 Linux x86_64（Ubuntu 24.04）和 macOS arm64（macos-14）。
每个平台执行检查、单元测试、CLI 集成测试，再生成 `.tar.gz` 与对应 `.sha256`，并对解压后的程序执行冒烟测试。
构建产物可从该次工作流的 Artifacts 下载；工作流不会自动创建正式 GitHub Release。
当前工作流使用安装时最新 MoonBit 工具链，日志保留工具链版本；不承诺跨工具链的逐字节可复现构建。
Linux 包依赖系统 libc，未承诺兼容早于 Ubuntu 24.04 的发行版；macOS 包未签名、未公证。

本机也可打包（需要 Python 3）：

```bash
make build
python3 scripts/package_release.py
```

包内包含可执行文件、许可证、README 与示例配置。包名自动取 `moon.mod` 版本和本机平台；已有包不会覆盖。
下载后先在包所在目录核对校验和，再解压安装（将文件名替换为实际包名）：

```bash
# macOS
shasum -a 256 -c moonlog-v0.1.0-macos-arm64.tar.gz.sha256
# Linux
sha256sum -c moonlog-v0.1.0-linux-x86_64.tar.gz.sha256
# 示例：macOS
tar -xzf moonlog-v0.1.0-macos-arm64.tar.gz
mkdir -p "$HOME/.local/bin"
install -m 755 moonlog-v0.1.0-macos-arm64/moonlog "$HOME/.local/bin/moonlog"
export PATH="$HOME/.local/bin:$PATH"
moonlog --version
```

正式发布时，将已通过测试的两个归档及其校验文件附到相应版本的 GitHub Release。
SHA-256 用于检查下载内容是否一致，不替代发布者签名。当前未创建版本标签或正式 Release。

### Windows 构建

Windows 原生构建需要 Visual Studio 2022（Community/Professional/Enterprise 或 Build Tools）并安装 C++ 工作负载。MoonBit 运行时目前仅支持 MSVC，不支持 MinGW/GCC。

使用 PowerShell 构建：

```powershell
.\build.ps1
# 或带测试
.\build.ps1 --test
```

构建脚本通过 `vswhere` 查找 MSVC，设置 ASCII 临时目录，并编译原生 release 目标。生成的二进制位于 `_build\native\release\build\cmd\main\main.exe`，打包时重命名为 `moonlog.exe`。

Windows 打包：

```powershell
.\package.ps1
```

生成 `dist\moonlog-v<version>-windows-x86_64.zip`，包含 `moonlog.exe`、`LICENSE`、`README.md`、`config/` 和 `fixtures/`。

验证校验和：

```powershell
Get-FileHash dist\moonlog-v0.1.0-windows-x86_64.zip -Algorithm SHA256
```

**已知限制**：
- Windows 特殊文件名相关的 2 项测试会跳过；符号链接创建受权限限制时会明确记录对应检查未执行，重复路径、硬链接和已有报告保护仍会测试。
- 中文路径已正确适配（使用 UTF-16 宽字符 API）
- CI 在 `windows-latest` 上运行，详见 `.github/workflows/windows.yml`

## Benchmark

### MoonBit 与 Go 对照

项目还提供一个与 Go 标准库适配器的同输入、同输出对照，测量吞吐量、CPU 时间和峰值 RSS。它只比较流式解析、5 分钟聚合、签名统计和 SHA-256 等受限计算契约，不代表两种语言在完整 CLI 或任意日志格式上的性能。

在 Apple M5 / 16 GiB、macOS arm64 上，100 MiB 级输入的中位数结果为：文本 MoonBit 60.1–65.0 MiB/s、Go 259.2–399.2 MiB/s；JSON Lines MoonBit 51.1–55.1 MiB/s、Go 81.2–86.3 MiB/s。MoonBit 进程峰值 RSS 约 2.3–2.4 MiB，Go 约 10–11 MiB。完整结果、原始样本和复现命令见 [benchmarks/compare/README.md](benchmarks/compare/README.md)。对照所用二进制哈希记录在 results.json，数据测于 SHA-256 调度工作区复用和按块摘要之前，未重测，旧结果未被替换；调度复用没有可稳定测量的加速，按块摘要在本机 100/500 MiB 消融中把受限 `full` 模式中位耗时降低约 7.5%–10.2%，`read` 因移除空的逐字节回调降低约 42%–49%，`digest` 降低约 15%–18%。这些消融测量在非空闲环境完成，不含生产 CLI 的上下文与报告，不能用于更新上表或宣称全面超过 Go，详见 [benchmarks/profile/](benchmarks/profile/README.md)。

> 以下已保存结果测于 SHA-256 / Int64 重构之前（源提交 `6aad1df`，详见原始数据中的二进制哈希），属于历史基线，不能作为当前版本性能承诺。请用 `make bench` 重测当前实现。

原生 CLI 本机实测（Apple M5、16 GiB 内存、macOS arm64）：每组预热 1 次、正式运行 5 次，以下耗时为中位数。低 / 高错误密度分别为 0.1% / 20%。

| 格式 | 实际文件大小 | 日志行数 | 低错误密度耗时 | 高错误密度耗时 | 吞吐量范围 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 文本 | 85.0 MiB | 656,000 | 0.795 秒 | 0.914 秒 | 93.0–106.9 MiB/s |
| JSON Lines | 100.6 MiB | 656,000 | 1.320 秒 | 1.415 秒 | 71.1–76.2 MiB/s |
| 文本 | 427.1 MiB | 3,277,000 | 4.086 秒 | 4.627 秒 | 92.3–104.5 MiB/s |
| JSON Lines | 505.2 MiB | 3,277,000 | 6.419 秒 | 7.137 秒 | 70.8–78.7 MiB/s |

完整 12 组测试共 60 次正式运行，逐次校验行数、错误数、级别计数及错误占比分子 / 分母，全部通过。各组正式运行的最大进程峰值 RSS 为 3.5–4.5 MiB。

测量包含 CLI 启动、两遍扫描、JSON 报告写入及终端摘要；使用固定种子的合成数据和暖文件缓存。时间跨度、签名类别及采样上限固定，不能据此推断任意输入的常量内存，也不代表浏览器性能或真实事故识别准确率。

- **[完整结果与环境信息](benchmarks/macos-arm64.md)**：全部规模、耗时、吞吐量及峰值内存。
- **[原始测量数据](benchmarks/macos-arm64.json)**：逐次运行记录、输入 SHA-256 和二进制 SHA-256。
- **[测量方法与复现说明](benchmarks/README.md)**：执行 `make bench` 可重新运行；无需第三方 Python 依赖。

### 真实日志样本验收

`validation/` 使用 Loghub 固定版本中的 Apache、OpenStack、BGL 三类公开研究样本，保留行序并做有限标识符替换，独立核对行数、错误计数、时间桶和尖峰结果。摘要与来源见 [validation/loghub-results.md](validation/loghub-results.md)，结构化证据见 [validation/loghub-results.json](validation/loghub-results.json)。原始和归一化日志在本地 `validation/data/`，不会提交。

这组数据验证了不同业务日志的适配边界和报告可读性，但不是连续生产事故记录，也没有已知故障起止。因此不能据此宣称准确率、召回率或根因识别能力；后续仍需要带时间线的脱敏业务样本做误报、漏报验收。

## 合成异常评测

三种检测算法的同数据集比较、调参集/测试集划分、桶级与事件级评分规则见 [evaluation/README.md](evaluation/README.md)，已保存结果见 [evaluation/results.synthetic-v1.md](evaluation/results.synthetic-v1.md)，完整标签、全部参数搜索与逐桶预测见 [evaluation/results.synthetic-v1.json](evaluation/results.synthetic-v1.json)。这是合成异常评测，不是独立人工标注的生产事故准确率；事件命中不代表持续故障全程覆盖，也不能据此宣称某算法普遍更准。
