# 基线污染对照 v1

本轮只增加评测适配器策略，不改CLI、WASM或生产Detector默认行为。

## EWMA

对照update-all（实际生产EWMA）与freeze-on-alert（仅在评测适配器实现）：判断后，报警桶不更新基线，其余桶正常更新。两个实现都与独立Python公式核对。alpha=.1/.3/.5/.8，各运行持续故障后恢复、预期健康水平上升、间歇故障三个固定场景。记录完整计数、标签、逐桶基线、阈值、预测以及桶级和事件级指标；健康水平上升定义为正常负对照。

冻结可以延缓持续故障被吸收，却可能在健康流量上升后永久报警。计数序列不能自行确定业务真相，因此不据此把冻结设为产品默认。不存在参数搜索或测试集选优。

## MAD

n=6/12，历史污染桶数逐个遍历0..n；污染计数固定20或随桶变化15+3*i，污染放历史前端/末端。历史后接12个20错误的探测桶，再接n个恢复桶。保存首探测桶基线/阈值/命中及完整后续轨迹。

前后位置不改变首探测桶的MAD，但影响之后滚动窗口。污染未过半时也可能抬高MAD导致漏报；达到一半时偶数中位数与尺度可能膨胀，过半时中位数本身可进入异常水平。不能把MAD的常见50% breakdown表述成“低于50%一定检出”。历史污染桶没有服务故障标签，本实验不对其计算事故准确率。

## 复现与边界

```bash
moon build evaluation/adapter --target native --release
python3 -m unittest discover -s evaluation -p 'test_*.py'
python3 evaluation/pollution.py --output /tmp/moonlog-pollution.json
```

输出已存在会拒绝覆盖；保存二进制和源码哈希。原始v1输出见 `results.pollution-v1.json`。轨迹来自独立Python公式并与MoonBit命中及基线核对，不是直接采样生产内核内部状态。全部为固定合成实验，不能代替真实事故验收或证明新策略更优。
