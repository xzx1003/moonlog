# 基线污染实验表 v1

本表由 `evaluation/results.pollution-v1.json` 机械生成，行序与 JSON 记录顺序一致，覆盖全部 EWMA 记录（24 条）和 MAD 记录（80 条）。全部为固定合成实验；历史污染桶没有服务故障标签，本表不构成真实事故准确率，也不比较算法优劣。

## EWMA 更新策略对照（24 条）

| scenario | alpha | policy | TP | FP | FN | detected events / total |
|---|---:|---|---:|---:|---:|---:|
| sustained-recovery | 0.1 | update-all | 4 | 0 | 26 | 1/1 |
| sustained-recovery | 0.1 | freeze-on-alert | 30 | 0 | 0 | 1/1 |
| sustained-recovery | 0.3 | update-all | 1 | 0 | 29 | 1/1 |
| sustained-recovery | 0.3 | freeze-on-alert | 30 | 0 | 0 | 1/1 |
| sustained-recovery | 0.5 | update-all | 1 | 0 | 29 | 1/1 |
| sustained-recovery | 0.5 | freeze-on-alert | 30 | 0 | 0 | 1/1 |
| sustained-recovery | 0.8 | update-all | 1 | 0 | 29 | 1/1 |
| sustained-recovery | 0.8 | freeze-on-alert | 30 | 0 | 0 | 1/1 |
| healthy-level-shift | 0.1 | update-all | 0 | 4 | 0 | 0/0 |
| healthy-level-shift | 0.1 | freeze-on-alert | 0 | 48 | 0 | 0/0 |
| healthy-level-shift | 0.3 | update-all | 0 | 1 | 0 | 0/0 |
| healthy-level-shift | 0.3 | freeze-on-alert | 0 | 48 | 0 | 0/0 |
| healthy-level-shift | 0.5 | update-all | 0 | 1 | 0 | 0/0 |
| healthy-level-shift | 0.5 | freeze-on-alert | 0 | 48 | 0 | 0/0 |
| healthy-level-shift | 0.8 | update-all | 0 | 1 | 0 | 0/0 |
| healthy-level-shift | 0.8 | freeze-on-alert | 0 | 48 | 0 | 0/0 |
| intermittent | 0.1 | update-all | 5 | 0 | 10 | 2/5 |
| intermittent | 0.1 | freeze-on-alert | 15 | 0 | 0 | 5/5 |
| intermittent | 0.3 | update-all | 5 | 0 | 10 | 5/5 |
| intermittent | 0.3 | freeze-on-alert | 15 | 0 | 0 | 5/5 |
| intermittent | 0.5 | update-all | 5 | 0 | 10 | 5/5 |
| intermittent | 0.5 | freeze-on-alert | 15 | 0 | 0 | 5/5 |
| intermittent | 0.8 | update-all | 5 | 0 | 10 | 5/5 |
| intermittent | 0.8 | freeze-on-alert | 15 | 0 | 0 | 5/5 |

## MAD 历史污染（80 条）

| n | contaminated buckets | shape | order | probe baseline | probe threshold | probe hit |
|---:|---:|---|---|---:|---:|---|
| 6 | 0 | flat | early | 1.0 | 1.0 | true |
| 6 | 0 | flat | late | 1.0 | 1.0 | true |
| 6 | 0 | variable | early | 1.0 | 1.0 | true |
| 6 | 0 | variable | late | 1.0 | 1.0 | true |
| 6 | 1 | flat | early | 1.0 | 1.0 | true |
| 6 | 1 | flat | late | 1.0 | 1.0 | true |
| 6 | 1 | variable | early | 1.0 | 1.0 | true |
| 6 | 1 | variable | late | 1.0 | 1.0 | true |
| 6 | 2 | flat | early | 1.0 | 1.0 | true |
| 6 | 2 | flat | late | 1.0 | 1.0 | true |
| 6 | 2 | variable | early | 1.0 | 1.0 | true |
| 6 | 2 | variable | late | 1.0 | 1.0 | true |
| 6 | 3 | flat | early | 10.5 | 52.7541 | false |
| 6 | 3 | flat | late | 10.5 | 52.7541 | false |
| 6 | 3 | variable | early | 8.0 | 39.1346 | false |
| 6 | 3 | variable | late | 8.0 | 39.1346 | false |
| 6 | 4 | flat | early | 20.0 | 20.0 | false |
| 6 | 4 | flat | late | 20.0 | 20.0 | false |
| 6 | 4 | variable | early | 16.5 | 43.1868 | false |
| 6 | 4 | variable | late | 16.5 | 43.1868 | false |
| 6 | 5 | flat | early | 20.0 | 20.0 | false |
| 6 | 5 | flat | late | 20.0 | 20.0 | false |
| 6 | 5 | variable | early | 19.5 | 39.515100000000004 | false |
| 6 | 5 | variable | late | 19.5 | 39.515100000000004 | false |
| 6 | 6 | flat | early | 20.0 | 20.0 | false |
| 6 | 6 | flat | late | 20.0 | 20.0 | false |
| 6 | 6 | variable | early | 22.5 | 42.515100000000004 | false |
| 6 | 6 | variable | late | 22.5 | 42.515100000000004 | false |
| 12 | 0 | flat | early | 1.0 | 1.0 | true |
| 12 | 0 | flat | late | 1.0 | 1.0 | true |
| 12 | 0 | variable | early | 1.0 | 1.0 | true |
| 12 | 0 | variable | late | 1.0 | 1.0 | true |
| 12 | 1 | flat | early | 1.0 | 1.0 | true |
| 12 | 1 | flat | late | 1.0 | 1.0 | true |
| 12 | 1 | variable | early | 1.0 | 1.0 | true |
| 12 | 1 | variable | late | 1.0 | 1.0 | true |
| 12 | 2 | flat | early | 1.0 | 1.0 | true |
| 12 | 2 | flat | late | 1.0 | 1.0 | true |
| 12 | 2 | variable | early | 1.0 | 1.0 | true |
| 12 | 2 | variable | late | 1.0 | 1.0 | true |
| 12 | 3 | flat | early | 1.0 | 1.0 | true |
| 12 | 3 | flat | late | 1.0 | 1.0 | true |
| 12 | 3 | variable | early | 1.0 | 1.0 | true |
| 12 | 3 | variable | late | 1.0 | 1.0 | true |
| 12 | 4 | flat | early | 1.0 | 1.0 | true |
| 12 | 4 | flat | late | 1.0 | 1.0 | true |
| 12 | 4 | variable | early | 1.0 | 1.0 | true |
| 12 | 4 | variable | late | 1.0 | 1.0 | true |
| 12 | 5 | flat | early | 1.0 | 1.0 | true |
| 12 | 5 | flat | late | 1.0 | 1.0 | true |
| 12 | 5 | variable | early | 1.0 | 1.0 | true |
| 12 | 5 | variable | late | 1.0 | 1.0 | true |
| 12 | 6 | flat | early | 10.5 | 52.7541 | false |
| 12 | 6 | flat | late | 10.5 | 52.7541 | false |
| 12 | 6 | variable | early | 8.0 | 39.1346 | false |
| 12 | 6 | variable | late | 8.0 | 39.1346 | false |
| 12 | 7 | flat | early | 20.0 | 20.0 | false |
| 12 | 7 | flat | late | 20.0 | 20.0 | false |
| 12 | 7 | variable | early | 16.5 | 80.9931 | false |
| 12 | 7 | variable | late | 16.5 | 80.9931 | false |
| 12 | 8 | flat | early | 20.0 | 20.0 | false |
| 12 | 8 | flat | late | 20.0 | 20.0 | false |
| 12 | 8 | variable | early | 19.5 | 72.8736 | false |
| 12 | 8 | variable | late | 19.5 | 72.8736 | false |
| 12 | 9 | flat | early | 20.0 | 20.0 | false |
| 12 | 9 | flat | late | 20.0 | 20.0 | false |
| 12 | 9 | variable | early | 22.5 | 62.5302 | false |
| 12 | 9 | variable | late | 22.5 | 62.5302 | false |
| 12 | 10 | flat | early | 20.0 | 20.0 | false |
| 12 | 10 | flat | late | 20.0 | 20.0 | false |
| 12 | 10 | variable | early | 25.5 | 65.53020000000001 | false |
| 12 | 10 | variable | late | 25.5 | 65.53020000000001 | false |
| 12 | 11 | flat | early | 20.0 | 20.0 | false |
| 12 | 11 | flat | late | 20.0 | 20.0 | false |
| 12 | 11 | variable | early | 28.5 | 68.53020000000001 | false |
| 12 | 11 | variable | late | 28.5 | 68.53020000000001 | false |
| 12 | 12 | flat | early | 20.0 | 20.0 | false |
| 12 | 12 | flat | late | 20.0 | 20.0 | false |
| 12 | 12 | variable | early | 31.5 | 71.53020000000001 | false |
| 12 | 12 | variable | late | 31.5 | 71.53020000000001 | false |
