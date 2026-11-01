# 消融/外部方法对照的准备证据

日期2026-11-01；独立工作树 `warmstart-quality-gate/LLMBO_Para`。用户要求保留v3并直接开展实验设计。

## 已交付

- [设计规格](../superpowers/specs/2026-11-01-ablation-and-benchmark-design.md)：四臂配对2×2、匹配初始化成本、全池指标、前十轮终点、独立确认、经典/现代基线、候选不足补点及失败策略。
- [实施计划](../superpowers/plans/2026-11-01-ablation-and-benchmark-plan.md)：准备器已完成；四臂监督、初始化完成策略、独立分析和外部算法适配仍需实施。
- `scripts/prepare_et_ablation_benchmarks.py`：仅准备配置，无真实运行分支。未改评价器、GP、EI、Region公式或旧配置的默认规则。
- 任务包：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/ablation-benchmark-20261101`。
- 第一阶段新种子：872104、195447、221402、513225、162634；另五个确认种子在协议中已固定。

## 实际验证

TDD RED：准备器不存在的检查失败，1失败/退出1，记录在旧独立证据根下 `factorial-design-red-20261101/`。GREEN和最终验证：`tests/test_et_ablation_benchmark_design.py` **7通过、0失败、0错误、0跳过，退出码0**。

最终日志/JUnit/结果：

`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/warmstart-v3-trial-20261029/factorial-design-release-20261101/{pytest.log,junit.xml,result.json}`。

实际配置准备CLI退出0。任务包包含20份严格schema校验通过的四臂禁用配置、10个初始化任务、50个正式任务条目；`preparation-audit.json` 独立核对24个文件SHA、660候选评价上限×2倍率=1320次solve估算，以及115次API估算。实际API/DFN均为0。配置所有调用额度为0；基线条目明确记录尚未完成的适配。

物理/观测模板来自既有DFN合成档案，数据与参数映射逐项保留。初始评价池为16点，消融GP选8点；外部GP基线允许使用全部16点，方法名称区分A00和B1。所有实评点进入指标档案，筛选成本不隐藏。

## 限制与状态

此验证只证明准备器、协议与禁用边界；没有运行新的软件BO、真实DFN、LLM请求或外部算法性能试验。当前解释器未安装torch、gpytorch、botorch、pymoo，不能报告现代/进化基线已可执行。历史产品全量回归尚未通过，不能以本轮7项测试替代。

旧的两份中间准备目录 `factorial-benchmark-design-20261101`、`ablation-benchmark-protocol-20261101` 保留，不作为最终任务包使用；最终入口为上面的 `ablation-benchmark-20261101`。
