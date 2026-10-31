# 合成异常评测 v1

仅为同模板独立随机种子的合成场景，不是生产事故准确率。
指标为桶级微平均；事件只需一次命中即可检出，不能代表持续异常全程覆盖。

| 算法 | 参数 | Precision | Recall | F1 | 误报率 | 事件命中/总数 | 已检出延迟中位分钟 |
|---|---|---:|---:|---:|---:|---:|---:|
| moving-average | default | 0.308 | 0.105 | 0.157 | 0.020 | 6/9 | 0.000 |
| moving-average | selected | 0.494 | 0.333 | 0.398 | 0.028 | 9/9 | 0.000 |
| ewma | default | 0.212 | 0.061 | 0.095 | 0.019 | 6/9 | 0.000 |
| ewma | selected | 0.492 | 0.281 | 0.358 | 0.024 | 9/9 | 0.000 |
| mad | default | 0.161 | 0.219 | 0.186 | 0.094 | 6/9 | 0.000 |
| mad | selected | 0.230 | 0.368 | 0.283 | 0.102 | 9/9 | 0.000 |

## 锁定参数

- moving-average: `{"minimum": 1, "multiplier": 2, "parameter_tenths": 30, "window": 12}`
- ewma: `{"minimum": 1, "multiplier": 3, "parameter_tenths": 1, "window": 3}`
- mad: `{"minimum": 1, "multiplier": 3, "parameter_tenths": 60, "window": 12}`

全部搜索、逐序列预测与持续异常参考轨迹见同目录JSON。参数仅由调参集F1选择，未在测试集继续挑选。无置信区间，不能声称统计显著或真实业务泛化。
