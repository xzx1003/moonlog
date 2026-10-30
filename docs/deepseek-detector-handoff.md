> 此任务单已过时：CLI、配置、终端展示及关键测试已由主代理完成。不要按本文件继续开发。当前只执行 docs/weak-model-detector-task.md。

请在 /Users/xzx/Documents/ChatGPT/moonlog 接入检测算法的CLI、配置、展示、文档与集成验收。先读 AGENTS.md、git diff 和 docs/detectors.md，保留已有改动，不提交、不推送。

核心已实现：types.mbt 的 Detector(MovingAverage/Ewma/Mad) 和 Config.detector/ewma_alpha/mad_threshold；aggregate.detect_spikes 默认原分支不变，detector.mbt 新实现EWMA/MAD；result.mbt与report.mbt已处理非默认算法的JSON和Markdown。91项单测通过，其中7组新算法断言。不要改公式、零MAD规则或阈值口径，发现问题先说明证据。

你负责：
1. CLI与配置新增 --detector moving-average|ewma|mad、--ewma-alpha、--mad-threshold，同名配置键，默认→配置→CLI；缺值/重复/非法浮点/NaN/Infinity/未知值报错，仍在写报告前失败。构造器统一校验。明确alpha仅EWMA有效，mad-threshold仅MAD有效，multiplier对MAD无效，不偷偷改变默认参数。无效算法参数可保留但必须文档说明不生效。
2. TerminalSummary新增所需选择/参数字段，终端与帮助说明有效算法；只在非默认时追加说明，保持原默认输出兼容。不要只打印“3倍基线”来描述MAD。不要动浏览器UI/ABI，本轮浏览器继续默认MA。
3. 集成测试覆盖CLI/配置覆盖、参数错误、默认输出逐字段/逐字节兼容、新算法选定后不同检测结果但计数/占比不变、JSON/Markdown/终端算法规则一致、签名窗口和上下文依旧基于实际尖峰。补核心规则必要测试如MAD精确阈值相等不触发、空输入、长期故障吸收；避免只复制实现。
4. 更新README、示例配置/帮助，链接docs/detectors.md。MAD最坏O(B*n log n)要如实写，不宣传万能异常检测。不要用未完成评测宣称准确率提高。
5. 本轮不要扩成公开数据集工程。docs/detectors.md末尾是后续评测草案：人工事故标注、独立测试集、预热/未知标签排除、桶级与事件级区分、零分母null，尚无成绩。
6. 跑moon info、moon fmt、make check/test/integration/web-test；Node24在/tmp/node24/bin/node，DEVELOPER_DIR=/Library/Developer/CommandLineTools。检查默认MA的Go对照/CLI-WASM仍兼容。

交付修改与测试结果、尚未支持的入口；不commit/push。
