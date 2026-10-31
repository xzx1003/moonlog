只做机械文档收尾，不改算法/评测代码，不commit/push。
路径：/Users/xzx/Documents/ChatGPT/moonlog

1. 在evaluation/README.md文末追加以下原文一次：

连续真实事故的输入契约和固定默认参数验收命令见 [REAL-DATA.md](REAL-DATA.md)。入口已实现，但尚无独立标注的生产事故样本，因此没有真实故障准确率成绩。

2. 运行以下命令。失败立即停止，返回完整报错，不自行修改：
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
export PATH=/Users/xzx/.moon/bin:/tmp/node24/bin:$PATH
cd /Users/xzx/Documents/ChatGPT/moonlog
python3 -m unittest discover -s evaluation -p 'test_*.py'
make check
make test
make integration
make web-test
git diff --check

不要搜索用户个人日志，不要制造real数据，不要跑真实验收或覆盖现有评测结果。只汇报改动文件、每条命令结果、测试数量。
