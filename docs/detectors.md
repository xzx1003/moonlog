# 错误计数检测核心契约

核心入口 `Config::new(detector=MovingAverage|Ewma|Mad, ...)` → `Analyzer::finish()` 或 `detect_spikes(buckets, config)`。CLI 已提供 --detector / --ewma-alpha / --mad-threshold 及同名配置键；浏览器仍默认 MovingAverage。输入必须是按时间排序、固定桶宽、已补齐空桶的非负计数（Analyzer 自动保证）；直接调用者负责这些条件。

所有算法只检测 ERROR/FATAL 计数；不是请求失败率检测，不自动校正流量、季节性或持续故障。`baseline_buckets=n`（1..1000）为预热长度；少于或等于 n 桶不检测。当前桶不得进入自己的参考值；所有算法要求 `errors >= min_errors` 且严格超过阈值。空桶为零。使用相同区间合并、计数、上下文及签名后处理：只有相邻且命中的桶合并，未命中立即断开，结束时间不包含在区间内。

## MovingAverage（默认）

保留旧实现的整数比较：当前错误数 × n > multiplier × 前 n 桶错误数之和；参考和为零时达到 min_errors 即命中。默认 n=6、multiplier=3、min_errors=3。默认 JSON/Markdown 不新增检测字段，兼容既有输出。

## EWMA

alpha=`ewma_alpha`，默认0.3，有限且 0 < alpha <= 1。用头 n 个桶的均值作为首次预测 E。当前 x > multiplier × E 时命中；判断后更新 E = alpha × x + (1-alpha) × E。所有桶（包括异常）都更新，持续故障仍可能被吸收。它是乘法阈值 EWMA，不是带方差/控制限的 EWMA 控制图，不能用“3倍”解释成“三西格玛”。multiplier 与 min_errors 沿用已有参数。

## MAD

只取前 n 桶，计算中位数 m；偶数长度取中间两值均值。d = median(abs(x-m))，阈值为 m + mad_threshold × 1.4826 × d；mad_threshold 默认3，有限且 0 < k <= 1000。1.4826 是正态分布下常用尺度因子，不代表当前数据服从正态分布。d=0 时退化为严格 x>m，仍要求 min_errors；小幅变化可能因此触发。multiplier 对 MAD 无效。单桶开销 O(n log n)、临时空间 O(n)，n最大1000；不要宣称百万桶输入下与移动平均同速。

## 结果与参数导出

Spike.baseline 为区间首个命中桶的参考水平：MA均值、EWMA预测或MAD中位数。不是阈值，不是健康期保证；合并后不改此值。新算法的 JSON config 额外导出 detector 及有效的 ewma_alpha 或 mad_threshold，默认算法维持原格式。Markdown 核心已分算法说明规则。CLI、配置及非默认算法终端说明已接入。

## 后续公开评测口径（尚未执行）

先固定桶级标签：只在各算法共同预热完成且有标注的桶评分，未知标签桶排除；相同输入和参数预算。TP/FP/FN由桶命中与人工异常标签交叉计算；分母为零的指标用null，不能强行写0或1。Precision=TP/(TP+FP)，Recall=TP/(TP+FN)，F1=2TP/(2TP+FP+FN)。另报每个真实事件是否被命中及首次发现延迟，不把桶级分数冒充事件级分数。

合成场景需覆盖突发、持续故障、单纯流量上涨、周期任务、低流量、正常波动。生成器记录规则和随机种子，标签是“合成异常”，不是实际服务故障。训练/调参与最终测试按场景/来源划分，不能随机打散同一事故相邻桶形成泄漏。真实数据只有独立事故时间线支持时才能标服务故障，Loghub记录级异常标签不等价。当前未建立公开人工标注事故集，没有准确率成绩。
