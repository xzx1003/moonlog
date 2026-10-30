# 真实来源日志验证（研究样本）

来源：[Loghub](https://github.com/logpai/loghub)，固定版本 `dd61d0952749ee7963bde24220d1be5ede023033` 的三个 2k structured CSV。数据可用于研究/学术工作，原文许可证见 [LICENSE](https://github.com/logpai/loghub/blob/dd61d0952749ee7963bde24220d1be5ede023033/LICENSE)。引用：Jieming Zhu et al., *Loghub: A Large Collection of System Log Datasets for AI-driven Log Analytics*, ISSRE 2023。数据集许可独立于本项目 Apache-2.0。

## 过程

- Apache：Web 服务器；OpenStack：云平台 API；BGL：超级计算机系统日志。
- 保留 2000 行顺序、日志消息和原时间。来源格式不直接符合 MoonLog，先转换成规范文本；Apache 级别显式转大写，其他未知级别保持未知，不私自改成 ERROR。
- 去除明显 IPv4、UUID / 32 位 ID、路径字段，转换行内换行。只是尽力减少标识符；脱敏不保证完整，转换文件只留在 gitignore 的 `validation/data/`，不公开日志或原始报告。
- 原时区未知，仅用原时钟作 UTC 算术以对齐桶，不表示已确定真实 UTC。BGL 采用记录文本时间，不猜测它与 epoch 字段的时区差异。
- 运行真实 CLI 的默认 5 分钟桶、6 桶基线、3 倍、最少 3 错误。Python 独立核对每桶总数、错误数及全局错误数。全部一致。
- 运行 `python3 validation/prepare_loghub.py` 后执行 `python3 validation/verify_loghub.py`。CLI 需先 `make build`。

## 观察

| 数据集 | 行数 | ERROR + FATAL | 尖峰 | 判读 |
|---|---:|---:|---:|---|
| Apache | 2000 | 595 | 15 | 可定位 mod_jk worker 错误状态的重复聚集；也有访问拒绝消息。可作为人工回查候选，不能据此确定站点中断。 |
| OpenStack | 2000 | 0 | 0 | 当前样本主要是 API 请求记录；零尖峰是本片段的结果，不表示整个云平台健康；约 14 分钟片段还不足以覆盖默认 30 分钟基线。 |
| BGL | 2000 | 388 | 11 | 窗口中可见 storage interrupt、进程加载失败、网络异常等系统错误；业务含义各异，不应合成一个根因。 |

BGL 原始标签有 143 行非 `-` 告警，其中 37 行位于检测出的尖峰时间窗内。其余告警不在尖峰窗中，说明“错误数量突增”与“任意告警”不是同一检测目标。这里不是准确率/召回率评测。

## 能证明与不能证明的内容

这是来自实际系统的公开研究抽样数据，**不是三份完整生产事故记录**。2k 片段不是连续采集，存在时间间隔、抽样偏差和缺少健康基线等问题。缺失桶补零会使稀疏抽样出现貌似突增的窗口。不能凭本测试声称真实事故检测准确、可靠预测故障或发现根因。

本轮已验证跨领域格式适配、计数对账、候选证据的可读性，并发现 WARNING / SEVERE 被归为 OTHER 的适配边界。要完成真正的事故有效性验收，还需连续、脱敏、带已知故障起止和业务判定的日志，按时间线统计误报与漏报。当前没有这些私有业务样本，项目不会编造。

原始哈希、归一化哈希和结构化结果见 [loghub-results.json](loghub-results.json)。
