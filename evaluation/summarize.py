"""Render saved evaluation metrics, without rerunning or selecting results."""
import argparse
import json
from pathlib import Path

p=argparse.ArgumentParser()
p.add_argument('result',type=Path)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
d=json.loads(a.result.read_text())
lines=['# 合成异常评测 v1','','仅为同模板独立随机种子的合成场景，不是生产事故准确率。',
       '指标为桶级微平均；事件只需一次命中即可检出，不能代表持续异常全程覆盖。','',
       '| 算法 | 参数 | Precision | Recall | F1 | 误报率 | 事件命中/总数 | 已检出延迟中位分钟 |',
       '|---|---|---:|---:|---:|---:|---:|---:|']
def f(x):return 'N/A' if x is None else f'{x:.3f}'
for name,v in d['algorithms'].items():
 for mode in ['default','selected']:
  m=v[mode]['overall']
  lines.append(f"| {name} | {mode} | {f(m['precision'])} | {f(m['recall'])} | {f(m['f1'])} | {f(m['false_positive_rate'])} | {m['detected_events']}/{m['event_count']} | {f(m['median_detected_delay_minutes'])} |")
lines+=['','## 锁定参数','']
for name,v in d['algorithms'].items():lines.append(f"- {name}: `{json.dumps(v['selected']['parameters'],sort_keys=True)}`")
lines+=['','全部搜索、逐序列预测与持续异常参考轨迹见同目录JSON。参数仅由调参集F1选择，未在测试集继续挑选。无置信区间，不能声称统计显著或真实业务泛化。']
with a.output.open('x') as out:out.write('\n'.join(lines)+'\n')
