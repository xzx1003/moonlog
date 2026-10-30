# MoonLog 浏览器版

这是一个静态 HTML/CSS/JS 页面，通过 Web Worker 调用 MoonBit 核心编译出的 wasm-gc 模块。解析、过滤、统计、尖峰检测、上下文采集和 JSON 报告生成都在 MoonBit 中执行；JavaScript 只负责读取文件分块、调用导出函数、显示进度和结果、以及下载报告。

在线入口：https://xzx1003.github.io/moonlog/

页面通过 GitHub Pages 分发静态资源。日志文件只在浏览器本机处理，不上传；没有分析 SDK 或遥测。也可以按下文在本地运行。

## 构建与本地打开

构建需要 MoonBit 工具链；运行测试还需要 Node.js 24 和已构建的原生 CLI。

```bash
make web-build     # 编译 wasm-gc 并复制到 web/generated/moonlog_web.wasm
make web-test      # 构建 CLI 与 WASM，运行可重复的桥接测试
make web-bench WEB_BENCH_MB=64
make web-serve     # 在 8000 端口启动静态服务器
```

然后打开 <http://localhost:8000/web/>。也可以在仓库根目录执行：

```bash
python3 -m http.server 8000
```

必须通过 HTTP 静态服务器访问。直接双击 `index.html`（`file://`）会失败，因为浏览器不允许该页面创建 module Worker 或读取同目录 WASM；这不是 MoonBit 侧的问题。页面也不会访问除自身静态资源之外的任何网络地址。

浏览器需要支持 **WebAssembly GC** 和 **JS String Builtins**。当前页面已在本机 macOS 的 Qoder Desktop 内置 Chromium 150（Electron 43.1.1）中验证；未单独验证 Google Chrome、Safari、Firefox 或其他版本。若浏览器不支持，页面会在 WASM 实例化阶段显示错误。

`web/generated/` 是构建产物，已在 `.gitignore` 中忽略。部署或发布时只需复制 `web/` 下的静态文件（含生成的 WASM），无需 Node 服务。

## 桥接协议

### 构建配置

`web_bridge/moon.pkg` 把 `web_bridge` 声明为 wasm-gc 主包，并打开 JS String Builtins：

```moonbit
pkgtype(kind: "executable")

options(
  link: {
    "wasm-gc": {
      "exports": [
        "moonlog_start", "moonlog_feed_base64", "moonlog_end_pass",
        "moonlog_phase", "moonlog_bytes_processed", "moonlog_cancel",
        "moonlog_result_json", "moonlog_last_error",
      ],
      "use-js-builtin-string": true,
    },
  },
)
```

产物是 `_build/wasm-gc/release/build/web_bridge/web_bridge.wasm`，会复制为 `web/generated/moonlog_web.wasm`。未使用 nativeio 或 C FFI，原生 CLI 的构建与运行不受影响。

### 宿主实例化约定

WASM 从 `wasm:js-string` 导入字符串操作，并从字符串常量模块 `_` 导入常量。宿主必须这样实例化：

```js
const { instance } = await WebAssembly.instantiate(bytes, {}, {
  builtins: ['js-string'],
  importedStringConstants: '_',
});
```

只提供 `wasm:js-string` 而遗漏 `importedStringConstants: '_'` 也会失败。`web/bridge.js` 封装了这些细节。

### 导出接口

字符串参数和返回值都使用 JS String Builtins，跨边界直接是 JS 字符串。

| 导出 | 签名 | 含义 |
| --- | --- | --- |
| `moonlog_start` | `(source, bucketMinutes, baselineBuckets, multiplier, minErrors, context, maxSamples, level, keyword, from, to) -> i32` | `source` 等字符串；数值为 32 位整数。成功返回 0，失败返回 -1。空字符串表示不设置级别、关键词或时间边界。 |
| `moonlog_feed_base64` | `(chunk: string) -> i32` | 传入一个分块的 Base64 文本。成功返回 0，失败返回 -1 并丢弃会话。解码后最多 65,536 字节，编码文本最多 87,384 字符。 |
| `moonlog_end_pass` | `() -> i32` | 结束当前扫描遍。返回 `2` 表示应回到文件开头重新读取；返回 `3` 表示报告就绪；失败返回 -1。 |
| `moonlog_phase` | `() -> i32` | `1` 第一遍统计，`2` 第二遍校验并采集上下文，`3` 完成，`-1` 失败或取消。 |
| `moonlog_bytes_processed` | `() -> f64` | 当前扫描遍已接收的字节数；第二遍会从 0 重新计数。 |
| `moonlog_cancel` | `() -> void` | 丢弃会话。取消后的 Worker 会被页面终止。 |
| `moonlog_result_json` | `() -> string` | 仅在 phase 3 成功；返回完整 JSON 报告，失败返回空字符串。 |
| `moonlog_last_error` | `() -> string` | 最近一次错误信息；下一次 `moonlog_start` 会清空。 |

一次 WASM 实例只保留一个会话。再次调用 `moonlog_start` 会丢弃旧会话。Session 在第二遍结束时校验行数和原始字节 SHA-256；文件在第一遍后发生变化会报错而不是产生不一致报告。

### 分块与 Base64

Worker 通过 `File.slice(offset, end).arrayBuffer()` 读取，每块最多 65,536 字节，等待当前块处理完成后再读下一块。Base64 用来精确传递字节，避免 JS 字符串在任意字节位置切断多字节 UTF-8；MoonBit 只在完整行上做 UTF-8 解码，因此跨块的中文字符不会被破坏。

两遍都从同一个 `File` 重新读取，不保存整个文件，也不使用 `file.text()` 或全文件 `split('\n')`。空文件不会调用 `feed`，两遍结束仍会生成包含 0 行的报告。

### Worker 消息

主页面每次分析创建一个新的 module Worker，并只发送一条：

```js
{ type: 'analyze', file: File, options: { bucketMinutes, baselineBuckets, multiplier,
  minErrors, context, maxSamples, level, keyword, from, to } }
```

Worker 回传：

```js
{ type: 'progress', progress: { pass, phase, bytes, total } }
{ type: 'result', json: '...', chunks: 12 }
{ type: 'error', message: '...', cancelled: false }
```

进度按当前扫描遍计算；`total` 是 `File.size`，可能为 0，显示层必须处理 0 分母。取消、失败或完成后页面都会终止 Worker；取消后再次分析会创建新 Worker，不复用旧实例。失败不会保留或展示上一次结果。

### 与 CLI JSON 的差异

同一输入和参数下，浏览器报告与 `bin/moonlog analyze ... --format json` 的统计字段一致，已由 `scripts/test_web.mjs` 逐字段比较。唯一差异是来源名：

- 浏览器只有 `File.name`，所以 `source` 和 `context_windows[].source` 是 `"incident.log"`；
- CLI 记录命令行传入的路径，例如 `"fixtures/incident.log"`。

其余字段（计数、桶、尖峰、签名、上下文行、过滤条件、配置、采样和扫描次数）相同。

## 当前限制

浏览器版第一版刻意只接入核心已稳定的能力：

- 单文件；
- 上下文模式固定为 spikes；
- 采样方式固定为 first；
- 不支持多文件、distributed 采样、指定签名比较、浏览器配置文件或脱敏；
- 只下载 JSON 报告，不提供 Markdown 导出；
- 页面不展示缓存、实时分析或根因判断。

**报告和上下文可能包含敏感原文。网页版没有脱敏；下载或分享前请自行检查。** 页面只在本地处理文件，不会上传日志。

“日志错误占比”是 ERROR + FATAL 日志行占时间有效日志行的比例，不是请求失败率；没有尖峰不代表服务健康。

## 验证

```bash
make web-test
make web-bench WEB_BENCH_MB=64
```

`make web-test` 使用真实的 wasm-gc 产物和 Node 的 `File`，覆盖：

- 与 CLI 的完整 JSON 对比（来源名归一化后逐字段相等）；
- 空文件、无尖峰；
- 中文字符跨 65,536 字节块边界；
- BOM、CRLF、末行无换行；
- 非法 UTF-8、超长行；
- 核心参数错误与整数边界；
- Base64 块长度和非法编码；
- 取消后重新分析；
- 同一输入重复分析得到逐字节相同的 JSON；
- 页面元素 ID 唯一，`app.js` 的每个 `getElementById` 目标都存在。

`make web-bench` 生成临时合成文件并通过打开的文件描述符按块读取，只测量吞吐与环境，不宣称“常量内存”。

### 实测记录（2026-10-29）

测试环境：macOS arm64；Node v24.21.0；浏览器为 Qoder Desktop 内置 Chromium 150（Electron 43.1.1）。

- `make web-test`：12 项全部通过；WASM 与 CLI 报告在来源名归一化后逐字段一致。
- Node 64 MiB 合成文件：1,218,127 行，两遍扫描 2.65 s（48.4 MiB/s），2,050 个块、2,053 个进度事件，报告 JSON 0.1 MiB；采样到的进程峰值 RSS 为 209.0 MiB（包含 Node、WASM 堆和生成器，不是常量内存结论）。
- 页面 64 MiB 合成文件：1,491,309 行，页面观测约 12,980 ms，2,052 次进度界面更新；该文件不是 Node 基准的同一份内容。
- 页面取消：在 1%（704 KiB）时终止 Worker，用时约 83 ms，未保留结果；随后重新分析 fixture 成功。
- 页面 fixture：30 行、4 个错误、错误行占比 13.3%、1 个尖峰、18 行上下文；空文件显示 N/A，无尖峰文件显示 33.3% 且明确提示“不代表服务健康”。
- 页面筛选：级别 ERROR + 关键词 database + 08:30–08:33 时，匹配 4 行、报告占比 4/4，与 CLI 相同。
- JSON 下载：下载名为 `incident.log.moonlog.json`，Blob 内容与 WASM 返回的报告逐字段一致。
- 页面运行期间未发现控制台错误，也未观察到外部网络请求。

尚未验证：其他浏览器、浏览器下载落盘行为、超长页面停留后的内存回收，以及不同硬件上的性能。

