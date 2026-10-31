请接入评测CI与机械文档整理，不改算法、标签、评分、参数，不提交不推送。
仓库：/Users/xzx/Documents/ChatGPT/moonlog。先读AGENTS.md和evaluation/POLLUTION.md。

核心已完成：evaluation/pollution.py，adapter评测专用ewma-freeze，4项新测试；生产默认行为未变。results.pollution-v1.json保留24个EWMA场景和80个MAD污染实验全部轨迹。不要覆盖任何历史JSON。

1. 在 .github/workflows/test.yml 中 make integration 后新增以下步骤（保持原有步骤不变）：
- name: Evaluation scoring tests
  run: python3 -m unittest discover -s evaluation -p 'test_*.py'
- name: Build detector evaluation adapter
  run: moon build evaluation/adapter --target native --release
- name: Baseline pollution production-reference check
  run: python3 evaluation/pollution.py --output "${{ runner.temp }}/moonlog-pollution.json"

不在每次提交跑完整参数搜索。Windows工作流本轮不改；Python评分测试不依赖fork，adapter由上面步骤实际构建。

2. evaluation/README.md文末追加一次：
基线污染策略对照与复现见 [POLLUTION.md](POLLUTION.md)，原始轨迹见 [results.pollution-v1.json](results.pollution-v1.json)。EWMA冻结更新只在评测中使用，生产默认未改变；持续异常检出与健康水平变化误报之间存在权衡。

3. 按原始JSON生成一张EWMA表（scenario、alpha、policy、TP/FP/FN、事件检出/总数），另做MAD表（n、污染桶数、shape、order、probe baseline/threshold/hit），写evaluation/pollution-tables.md。不得挑选样本，不解释因果，不宣称准确率提高。可以用Python标准库生成，避免手工改数字。表格必须覆盖全部24/80条。

4. 环境：export DEVELOPER_DIR=/Library/Developer/CommandLineTools；export PATH=/Users/xzx/.moon/bin:/tmp/node24/bin:$PATH。运行make check/test/integration/web-test、Python evaluation测试、上述CI的adapter构建和pollution命令（输出新临时路径）、git diff --check。失败停止并回报，不修核心。

交付改动清单、测试数量、表格行数；不要commit/push。
