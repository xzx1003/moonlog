项目 /Users/xzx/Documents/ChatGPT/moonlog。本轮评测核心已经完成，不要重新设计评分/标签/参数网格，不改MoonBit代码，不改evaluation/core.py和evaluation/run.py，不提交、不推送。

只做以下机械收尾：
1. 在README.md文末追加下面原文一次（已有则不要重复）：

## 合成异常评测

三种检测算法的同数据集比较、调参集/测试集划分、桶级与事件级评分规则见 [evaluation/README.md](evaluation/README.md)，已保存结果见 [evaluation/results.synthetic-v1.md](evaluation/results.synthetic-v1.md)，完整标签、全部参数搜索与逐桶预测见 [evaluation/results.synthetic-v1.json](evaluation/results.synthetic-v1.json)。这是合成异常评测，不是独立人工标注的生产事故准确率；事件命中不代表持续故障全程覆盖，也不能据此宣称某算法普遍更准。

2. 逐条运行（失败立刻停止，回传报错，不修代码）：
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
export PATH=/Users/xzx/.moon/bin:/tmp/node24/bin:$PATH
cd /Users/xzx/Documents/ChatGPT/moonlog
python3 -m unittest discover -s evaluation -p 'test_*.py'
make check
make test
make integration
make web-test
git diff --check

3. 只汇报：改了哪个文件、每条命令是否通过及测试数量。不要重跑参数搜索或覆盖结果JSON，不要把事件级成绩当桶级，不宣传准确率提高。
