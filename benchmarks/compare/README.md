# MoonBit / Go 对照

这不是完整 MoonLog CLI 与完整 Go 日志产品的对照。两个独立适配器执行相同的**受限计算契约**：

1. 无过滤、无配置覆盖；标准 `YYYY-MM-DD HH:MM:SS [LEVEL] message` 或顶层字符串 `ts/level/msg` JSON Lines。
2. 全量计数、级别计数、UTC 5 分钟桶、连续数字归一化签名排名。
3. 前 6 桶滑动基线、严格超过 3 倍且至少 3 个错误；相邻尖峰合并。
4. 两遍流式扫描，两遍都解析；每遍计算原始字节 SHA-256 并比较。
5. stdout 输出相同的摘要 JSON（桶、尖峰、签名、级别、总数、无时间戳数、SHA-256），每次先验证完整 JSON 相等再计入结果。

**不含**上下文提取、签名窗口对比、脱敏、Markdown、完整 CLI 参数处理。Go 适配器只支持上述生成器的规范输入，不宣称与 MoonLog 在异常 JSON、重复键、时区、资源限制、任意输入上的行为等价。它使用 Go 标准库 JSON/时间/SHA-256；MoonBit 使用当前生产核心及纯 MoonBit SHA-256，因此结果同时反映算法实现、标准库和硬件加速差异，不能归结为语言本身优劣。

## 复现

Go 1.25+、Python 3.9+、MoonBit；Go 仅需标准库，不下载第三方依赖。

```bash
moon build benchmarks/compare --target native --release
go build -o /tmp/moonlog-go-reference benchmarks/compare/main.go
python3 benchmarks/compare/run.py --go /tmp/moonlog-go-reference --sizes 10,100 --runs 5
```

也可执行 `make bench-compare`（通过 `GO=/path/to/go` 指定工具链）。运行前先用标准事故夹具的文本和 JSON Lines 两种编码核对非空尖峰的完整输出一致性。

固定种子 20261029，与 `scripts/bench_cli.py` 共用流式输入生成器、进程计时及 OS `wait4` 峰值 RSS / CPU 测量。每组预热一次，5 次正式运行，两种语言交替先后顺序。输入数据生成与 JSON 比较不计时；进程启动、两遍读取、解析、聚合、SHA-256、输出 JSON 计时。没有人为暂停进度。暖文件缓存，未控制温度与后台负载。每组保存输入 SHA-256、精确字节数、二进制 SHA-256 和逐次 wall/user/system/RSS。

[结果表](results.md) · [原始结果与环境](results.json)

当前 M5 机器上 Go 吞吐量更高；MoonBit 的进程峰值 RSS 更低。结论只适用于上述受限工作负载。本机 Go 来自官方 `go.dev/dl/go1.25.3.darwin-arm64.tar.gz`，归档 SHA-256 为 `7c083e3d2c00debfeb2f77d9a4c00a1aac97113b89b9ccc42a90487af3437382`。

吞吐量同时提供 MiB/s（2^20 字节）、MB/s（10^6 字节）与 lines/s（逻辑输入行数 / 总耗时，两遍扫描不重复计行）。已保存结果中的新增指标由原始测量推导，不是重新计时。

测量所用二进制哈希记录在 results.json；这组数据测于 SHA-256 调度工作区复用和按块摘要改动之前，之后未重测，旧计时和二进制哈希保持不变。`benchmarks/profile/` 的配对消融显示调度复用落在测量噪声内，按块摘要在本机 100/500 MiB 受限契约中把 `full` 模式中位耗时降低约 7.5%–10.2%（`read` 因移除空的逐字节回调降低约 42%–49%，`digest` 约 15%–18%）；这些测量非空闲，未重跑本对照，不能据此更新本表或断言全面超过 Go。`main.mbt` 的 read/digest/parse/aggregate 性能分解模式是消融对照，不是完整 CLI 数据，不能与本表混用。
