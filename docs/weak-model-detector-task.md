你只做文档中的固定替换和运行命令，不设计、不写业务代码、不修复测试、不commit、不push。
项目路径：/Users/xzx/Documents/ChatGPT/moonlog

任务1：只编辑 config/moonlog.example.json，在对象开头加入以下3个键；如果已有则更新，不得产生重复键。其他键和值原样保留：
"detector": "moving-average",
"ewma-alpha": 0.3,
"mad-threshold": 3

任务2：只编辑 docs/deepseek-detector-handoff.md，在第一行之前加以下原文（如已有则不要重复）：
> 此任务单已过时：CLI、配置、终端展示及关键测试已由主代理完成。不要按本文件继续开发。当前只执行 docs/weak-model-detector-task.md。

任务3：在终端逐条执行以下命令，遇到失败立刻停止，把完整报错返回，不要修改代码或测试，不要安装任何软件：
cd /Users/xzx/Documents/ChatGPT/moonlog
export DEVELOPER_DIR=/Library/Developer/CommandLineTools
python3 -m json.tool config/moonlog.example.json
make check
make test
make integration
PATH=/tmp/node24/bin:$PATH make web-test
git diff --check

最后只汇报：修改了哪两个文件、每条命令成功还是失败及测试数量。不要评价算法准确率，不要修改README/其他文件，不要重新生成报告或性能数据。如文件路径缺失、Node24缺失或权限被拒绝，直接返回情况，不自行解决。
