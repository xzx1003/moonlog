# 连续真实事故验收入口

此入口未附带真实事故数据，没有生产准确率成绩。不要把单元测试的fabricated夹具当真实数据。新增功能是严格输入校验和固定默认参数评分，而不是宣称完成真实验收。

## 输入

JSON对象包含：

- `schema_version`: 1，`bucket_minutes`: 5，`kind`: `real-incident`。
- 非空字符串 `dataset_id`、`provenance`（数据来源/授权）、`annotation_method`（独立事故标注方法）、`annotator`、`annotation_frozen_at`（UTC格式 `2026-01-01T00:00:00Z`）。这些是提供者声明，脚本无法证明来源真实或标注独立。
- `traces`: 非空数组，每项非空唯一 `id`，`buckets` 和 `annotations`。
- `buckets`: 13..2000个连续5分钟桶。每桶 `start` 为UTC整5分钟边界，`total` 与 `errors` 为整数，0<=errors<=total<=2147483647。无日志桶显式写0，缺失采集不能冒充零流量。当前适配器单桶Int32限制不代表生产内核限制；2000桶上限控制argv长度。
- `annotations`: 每项包含 `start`、`end_exclusive`、`label`（normal/incident/unknown）以及非空 `evidence`（工单/监控/事故时间线引用，勿写敏感凭据）。区间左闭右开、不重叠、位于trace内且对齐桶。未标注桶始终unknown，不默认正常。

标签应先于运行冻结，不能查看预测后修改“真相”。相邻incident标签合并成一个连续事件；unknown打断事件。需要区分相邻事故身份的精细事件ID暂未支持。不能确认的时间段写unknown，不能把Loghub行级告警当事故标签。不同trace独立预热，不能随意切片事故前基线以改变得分。

这个入口只验收桶计数检测，不验证日志解析/脱敏。桶统计必须由数据提供方独立从连续日志核对，且注明时区及错误级别映射。前12桶统一排除评分；指标及左截断事件规则继承core.py。只比较三算法默认参数，不在真实测试集调参。

## 执行

```bash
moon build evaluation/adapter --target native --release
python3 evaluation/real.py /path/to/private-annotated-buckets.json --output /path/to/private-results.json
```

输出包含全部输入数据/标签、原始输入哈希、适配器二进制哈希、逐桶预测、独立公式轨迹及所有指标；已存在文件拒绝覆盖。结果可能含来源和证据信息，请存项目外并审核后再共享，脚本不自动脱敏。使用eval adapter真实调用MoonBit检测核心并核对独立Python公式，不伪造真实数据或成绩。
