请在 /Users/xzx/Documents/ChatGPT/moonlog 完成此次性能优化的集成验收和文档收尾。先读 AGENTS.md 和 git diff，保留工作区已有改动，不提交、不推送。

核心已经完成：digest.mbt 中 SHA-256 调度工作区按实例复用，轮常量共享。不要修改摘要算法、扫描次数、解析语义、计数或 JSON schema。benchmarks/compare/main.mbt 新增 read/digest/parse/aggregate/full 性能分解模式；benchmarks/profile/ 下有前后测量和说明。

你的任务：
1. 优先在空闲环境对优化前后保留二进制交错运行确认收益（/tmp/moonlog-profile-before 与当前构建；二进制可能随临时目录清理而消失，消失时需从 git 基线独立构建，不准拿当前代码伪造 before）。当前 before 测量期间存在编译与测试后台负载，而且 read/parse 也变化明显，不应宣称稳定加速。阅读 before.json / after.json，独立计算各模式中位耗时变化，核对报告中的百分比。解释消融测量差值不能当精确内部计时，aggregate 两遍均聚合而 full 仅首遍聚合。不得声称已经全面超过 Go。
2. 为 SHA-256 增加必要的回归断言：交错喂入两个实例不串状态，hex() 多次调用且随后继续 feed 正确；用 Python hashlib 独立生成确定的边界长度期望值，不要只拿优化后的实现与自身比较。已有标准向量不要重复堆叠。
3. 运行 moon info、moon fmt、make check、make test、make integration、make web-test。检查 pkg.generated.mbti 的变化：只允许私有结构布局中新增 schedule，不新增无关 API。
4. 如要更新当前 Go 对照结果或完整 CLI benchmark，必须实际重跑并保留旧结果，不能将性能分解数据冒充完整 CLI 数据，也不能把旧二进制测量换上新哈希。README 保留历史版本与当前结果边界。
5. 文档用简短事实描述收益及无明显收益的情况；不写“极致”“性能飞跃”等宣传。不要添加假进度或改前端。

macOS 运行前设置 DEVELOPER_DIR=/Library/Developer/CommandLineTools，避免默认 Xcode 许可问题。交付改动清单、验证结果、残留问题；未获用户指示不要 commit/push。
