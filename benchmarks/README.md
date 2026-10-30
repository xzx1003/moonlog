# MoonLog benchmark

## 复现

macOS / Linux，Python 3.9+，MoonBit 工具链，无第三方 Python 依赖：

```bash
make build
python3 scripts/bench_cli.py --sizes 10,100,500 --runs 5 --output benchmarks/local.json
```

快速检查：`python3 scripts/bench_cli.py --sizes 1 --runs 1 --output /tmp/moonlog-smoke.json`。
脚本遇到退出失败或统计不一致会中止，不会把失败运行算成性能结果。

## 测量口径

- 12 组：3 个规模 × 文本/JSON Lines × 0.1%/20% 错误密度。
- 固定随机种子 20261029；每 1000 行精确放置 1 或 200 条 ERROR；其余 INFO。
- 每组先预热一次，再运行 5 次独立进程。保留每次耗时、CPU 时间和 RSS，报告耗时/吞吐中位数及最大峰值 RSS。
- 端到端耗时包含进程启动、两遍文件扫描、JSON 写盘和终端摘要；数据生成与结果验证不计时。吞吐量使用输入字节数除以总耗时，不把两遍读取重复计为输入量。
- `os.wait4` 获取每个子进程的 OS 峰值 RSS，macOS 按字节、Linux 按 KiB 换算。不是轮询采样，也不是整个系统内存。
- 数据生成和预热会使文件缓存变热。结果属于暖缓存测试，不代表冷磁盘读取；未控制 CPU 温度、频率或后台负载。
- 日志时间单调，固定在一天内，固定默认桶宽和签名类别；规模增大主要增加行数，不增加时间跨度或签名基数。不能据此推断任意数据的常量内存。
- 规模名是标称值。按完整 1000 行块生成，文本和 JSON 行长度不同，结果表记录实际 MiB、字节数和 SHA-256，吞吐计算只使用实际字节。
- 每次运行独立核对总行数、匹配行数、错误数、无时间戳数、ERROR 级别计数、错误占比的分子和分母。不是尖峰检测准确率 benchmark。
- JSON 报告写入临时目录，完成自动清理。原始测量和环境信息保存为 JSON，同时生成 Markdown 表格。

## 结果

保存的 macOS 结果是 SHA-256 / Int64 重构前的历史基线；新实现应重新运行，不能直接沿用这些数值描述当前性能。

[本机 macOS arm64 测量](macos-arm64.md)，[原始数据](macos-arm64.json)。
结果仅代表所记录机器和输入。没有实现等价的 JS 对照，不宣称比 JS 快；Node WASM 的补充测量可通过 `make web-bench` 运行，它的 RSS 是 Node 进程采样值，不能和这里的原生 OS 峰值直接比较。
