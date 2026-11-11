# 本地四组消融实验与审计（2026-10-11）

四组均完成 8 个有效初始点后的 25 次 BO，四份深度审计通过。运行位置为本机 SCP / Windows 11，使用项目 .venv-pybamm312 的 Python 3.12.10、PyBaMM 25.10.2；一个 CPU 工作进程和一个数值线程。LLM 实际模型为 gpt-5.6-sol。

| 组别 | 初始最优均 RMSE（mV） | 结束最优均 RMSE（mV） | BO 有效 / 无效 |
|---|---:|---:|---:|
| 关闭两个 LLM 组件 | 48.164801 | 48.164801 | 0 / 25 |
| 仅 WarmStart | 47.351050 | 47.351050 | 1 / 24 |
| 仅 GP LLM | 48.164801 | 48.164801 | 0 / 25 |
| 完整方法 | 47.351050 | 47.351050 | 1 / 24 |

100 次 BO 中 2 次完整有效、98 次失败；失败消耗迭代，保留具体原因，不生成 GP 罚分标签。 四组均未改进各自的初始最优值。
这验证了完整软件闭环，不能据此认定 GP 增强或完整方法有效。每组只有一个固定种子，且可行性失败率高；需要把 BO 的选点和约束处理作为后续方法问题讨论，不能以随机性解释。

随机家族累计 12526 个原始生成点，387 次 DFN 候选评价取得 8 个有效点；保留原 200 次历史，本次新增 187 次。LLM 家族生成 40 个建议，2 次生成、5 次独立选择，28 次 DFN 候选评价取得 8 点；没有随机替代。两家族分别通过两点检查和全筛选审计。

本次新增 315 次候选评价、1260 次倍率求解；计入链接的历史筛选则为 515 次候选、2060 次倍率求解。32 次初始标签复用不计为新求解。主方法 API 请求 9 次，额外验证 3 次（qwen 额度拒绝、GPT 连通性、GPT 分组小试）；令牌用量和响应模型见 API 档案。更早的严格八点、截止诊断、校准和两步 BO 小试不混入此成本。

六参数范围、固定孔隙率、四倍率全部实测采样点、2.5 V 截止、禁止外推及四 RMSE 等权平均保持不变。数据为科研组的 21700 实测 XLSX，1 秒间隔已确认；I 列为空，电流仍依据 Reference 的 5 Ah 推算；T 单位未确认，未接入。保持 Reference/Chen2020 初始浓度、298.15 K 等温及在同一数据上校准的固定电解液扩散乘数 1.5。识别值是在这些固定设定下的拟合结果，尚未获得独立实验验证。

全部配置、提示词、HTTP 请求/响应、求解记录、失败、GP 模型状态、采集函数、命令、日志、输入及源代码快照保存在独立运行目录。原 qwen 配置和 403 记录保留，用户随后明确选择 GPT；没有上传远端。

[完整结果与成本](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/study-results.json)

[结果 CSV](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/results/ablation-summary.csv)

[实测与拟合电压曲线](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/results/fitted-voltage.png)

[逐点残差](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/results/voltage-residuals.png)

[按 BO 次数及含筛选成本的收敛曲线](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-ablations/20261011T110139Z_881f3df2256c_a47713cc/ablation-curves.png)

[四组及深度审计索引](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-ablations/20261011T110139Z_881f3df2256c_a47713cc/study-summary.json)

[API 与令牌档案](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/api-provenance.json)

复现时使用同一源代码快照、项目解释器和 canonical XLSX。随机续筛命令见 random-resume/command.json；WarmStart 命令见 llm-screen/command.json；正式四组命令见 formal-ablations/command.json。RunStore 自动创建新目录，勿改写历史目录。正式命令提供两份完成的初始计划，不再预筛；各自实际预算以链接的 screening-policy.json 和本研究 study-protocol.json 为准。API 密钥通过隐藏输入放入进程环境，不写入文件。

本报告生成命令：runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/finalize-study.py

[带完整参数名称、单位和范围的识别参数表](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/results/best-parameters.csv)

相同最终曲线并非忽略了 GP LLM。配对记录复查表明：两对的 25 次 Composite EI 值均发生变化；基线与 GP LLM 仅 8 次选点相同，WarmStart 与完整组的 25 次 argmax 选点仍相同。完整组末次训练的混合核权重为 0/0/0.8/0，GP LLM 组为 0.6/0.8/0.6/0.6；非零权重和模型状态已进入深度审计。完整组改变了 EI 数值，但在本轮候选池中未改变排序第一的候选。见 [配对采集函数复查](D:/Users/aa133/Desktop/LLMBO_Para/runs/local-studies/20261011T103842Z_bd73d43d42ab_cca8ccd6/paired-acquisition-differences.json)。

BO 失败的倍率记录中，基线为 71 次完整时间覆盖不足；GP LLM 为 96 次覆盖不足；WarmStart 和完整组分别为 73 次覆盖不足、1 次求解器收敛失败。GP LLM 选择的正极固相扩散系数范围约 1.15e-16 至 1.93e-14，低于其初始有效点的约 5.28e-14 至 3.01e-13，失败的 3C 曲线中位覆盖约 33%。库存门槛只保证理想容量的必要条件，当前有效点 GP 尚不对失败区域建模，采集函数因此仍会选入无法完成放电的区域。原始参数、每倍率覆盖、空失败标签和采集函数均已检查；没有以随机性解释这些结果。
