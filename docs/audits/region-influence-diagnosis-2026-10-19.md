# Region-Lift 作用幅度与单步收益诊断（2026-10-19）

本轮结果支持继续检验区域建议的质量与实际收益，尚不支持盲目调大 `lambda_max`。`eligible_region_v1` 已能改变选点，但“被采纳更多”没有自动转化为稳定的优化收益。本报告区分原有软件对照、归档幅度统计、新增冻结历史单步诊断，以及实际启动后因首次请求失败而停止的真实 API＋DFN 合成消融。

## 范围与版本

- 诊断源码版本：`f116c43caf266822edabb284efdd3114e5c6bdc0`。
- 源码指纹：`ce3c3ff473ff323a770908c7e485f26aec45305399b6ba7c6b202394ec813ba7`。
- 输入为此前三种子（17、29、43）、三策略、每臂20轮的软件任务归档。三个策略为 `warmstart_only`、`global_lift_v1`、`eligible_region_v1`。
- 软件任务包含0.5C、1C、2C三个代数工况；其误差数值不构成真实 DFN 或实测 RMSE 证据。
- 建议器是预先指定的脚本：从已展示的合格替代点中选择原 EI 最高者，坐标字典序处理同分，给出归一化宽度0.1的区域，置信度固定0.9。它不是 LLM，不能以该结果评价真实 LLM 的物理推理能力。
- 离线诊断阶段没有修改产品算法、幅度、守卫、旧实验或旧归档，网络请求和电池求解均为0；后续获批真实请求的实际成本另列。

## 本轮实际执行与证据

新增诊断完成 **6项数值校验**，复核 **180个已归档 BO 动作**。对其中43个 Region 被采纳的动作，补算当轮 plain 候选的软件目标，每候选3个软件工况，共 **129次新增软件评价**。执行退出码 **0**，`result.json` 的 `passed=true`，网络尝试、真实 API、DFN 求解均为 **0**，输入归档哈希核验显示旧记录未变。

这6项数值校验不是一次新的 pytest 完整回归。**411/411、失败0、错误0、退出码0是上一阶段已完成的完整回归**，本轮没有将其重新计作新测试结果。

可复查证据：

- [本轮诊断结果](D:/Users/aa133/Desktop/LLMBO_Para/runs/rd/20261019T053433054460Z/result.json)
- [本轮逐动作 CSV](D:/Users/aa133/Desktop/LLMBO_Para/runs/rd/20261019T053433054460Z/rounds.csv)
- [本轮冻结诊断协议](D:/Users/aa133/Desktop/LLMBO_Para/runs/rd/20261019T053433054460Z/protocol.json)
- [分析入口](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-influence-diagnosis-20261019/analyze.py)
- [原三种子软件对照](D:/Users/aa133/Desktop/LLMBO_Para/runs/rc/20261019T052448546302Z/result.json)
- [上一阶段完整回归日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-full-1019051235996371/pytest.log)
- [上一阶段 JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-full-1019051235996371/junit.xml)

分析入口 SHA-256：`956d3f686059f9d31373225d6bbe682110a68e20b0d46df334aeaa637e359424`。本轮结果保存其协议、源记录路径、输入哈希与逐动作冻结上下文，可追溯复算。

## Region 是否实际改变了采集函数

两个 Full 策略各60轮，原始归档中的回退与采纳分布如下。脚本顾问未发生请求错误，不能据此推断真实 API 可靠性。

| 归档状态 | global_lift_v1 | eligible_region_v1 |
|---|---:|---:|
| 总轮数 | 60 | 60 |
| 有效区域回复 | 52 | 55 |
| 采纳 | 15 | 28 |
| same_as_plain | 35 | 27 |
| no_eligible_alternative | 8 | 5 |
| outside_region | 2 | 0 |

`region.shift` 表示本轮**尝试计算的均值调整**。回退时，归档可能仍保留非零 `shift`、`adjusted_mean`、`lifted_ei`，而实际 `effective_ei` 仍等于 `plain_ei`。因此不能把“有非零 shift”计作 Region 已应用。

幅度复算使用 `delta_i/sigma_i = shift_i / max(std_i, 1e-12)`。下表中“实际应用”在 `accepted=false` 时置0；其余“记录值”保留归档中的尝试幅度。每格依次为 **中位数 / P90 / 最大值**，分位数采用 NumPy 默认线性插值。

| 幅度统计 | global_lift_v1 | eligible_region_v1 |
|---|---|---|
| 全60轮，记录的 plain 点 delta/sigma | 0.003629 / 0.045247 / 0.082481 | 0 / 0 / 0 |
| 全60轮，记录的实际选点 delta/sigma | 0.008319 / 0.062074 / 0.107032 | 0 / 0.083773 / 0.153804 |
| 全60轮，记录的池内最大 delta/sigma | 0.031472 / 0.080558 / 0.124649 | 0.033457 / 0.092353 / 0.153804 |
| 全60轮，实际应用的选点 delta/sigma | 0 / 0.058659 / 0.107032 | 0 / 0.083773 / 0.153804 |
| 仅采纳轮，选点 delta/sigma | 0.057370 / 0.085104 / 0.107032 | 0.050561 / 0.107501 / 0.153804 |
| 仅采纳轮，plain 点 delta/sigma | 0.018765 / 0.045889 / 0.060914 | 0 / 0 / 0 |

新规则保持 plain 原均值、原 EI 不变，确实消除了全局相关抬升对 plain 基线的同步调整。当前采纳点幅度约为后验标准差的0.05倍中位量级；这是保守影响，但不能单靠“幅度小”断定它是收益不足的原因。

原公式仍为 `clip(lambda_max * anneal * confidence * trust * consistency * max(correlation,0), 0, max_shift_std)`，作用于标准化标签空间。公式没有乘后验标准差，所以 `max_shift_std` 当前约束的是标准化标签空间中的绝对调整，并非逐候选的 `delta/sigma` 上界。上表报告实际后验尺度，避免把字段名误读为逐点标准差约束。

## 采纳点原有质量与幅度因子

以下只统计采纳轮，仍为 **中位数 / P90 / 最大值**。

| 指标 | global_lift_v1（15轮） | eligible_region_v1（28轮） |
|---|---|---|
| 原 EI / plain 原 EI | 0.984877 / 0.996798 / 0.997989 | 0.978157 / 0.996522 / 0.998032 |
| 提升后 EI / plain 原 EI − 1 | 0.066586 / 0.090913 / 0.108953 | 0.047139 / 0.082923 / 0.167606 |
| sigma_selected / sigma_plain | 1.038497 / 1.573122 / 1.814168 | 0.988371 / 1.343263 / 1.881277 |
| 原 log-EI 差 | 0.015238 / 0.031058 / 0.102309 | 0.022085 / 0.084309 / 0.121043 |

global 采纳点的原 EI 排名为第2名14次、第3名1次；eligible 为第2名22次、第3名3次、第4名2次、第5名1次。所选点多数本来就是 GP 的近优候选。这说明当前脚本建议主要改变近似平局的顺序，尚未证实其提供超越原 GP 的有效方向信息。

以下幅度因子只统计存在有效回复的52/55轮。

| 因子（中位数 / P90 / 最大值） | global_lift_v1 | eligible_region_v1 |
|---|---|---|
| confidence | 0.9 / 0.9 / 0.9 | 0.9 / 0.9 / 0.9 |
| trust_before | 0.4 / 0.52 / 0.616 | 0.4048 / 0.68 / 0.7952 |
| anneal | 0.547619 / 0.9 / 0.952381 | 0.523810 / 0.885714 / 0.952381 |
| anchor_consistency | 0.464987 / 0.534725 / 0.645787 | 0.459268 / 0.533764 / 0.607719 |
| confidence × trust × anneal | 0.218743 / 0.407143 / 0.437143 | 0.197486 / 0.437253 / 0.524571 |

置信度恒定是脚本设定；trust、退火、锚点一致性与后验相关性共同压缩幅度。它们的量级可以解释调整较小的数值来源，但不能证明应取消约束或调大强度。

## 新增冻结历史单步诊断：采纳是否优于当轮 plain

对43个已采纳动作，本轮仅补算同一个冻结历史下的 plain 候选。使用当时已有的权重、目标尺度、理想点、原训练标签及标准化；补算结果没有反向写入该历史，也没有更新后验或继续生成下一轮候选。HV 使用相同已有历史及固定指标空间，分别只加入 selected 或 plain 的目标对，比较单步增量。

| 同一冻结历史下的比较 | global（15次采纳） | eligible（28次采纳） |
|---|---:|---:|
| selected 标量目标优于 plain | 7 | 15 |
| selected 标量目标差于 plain | 8 | 13 |
| selected 单步 HV 高于 plain | 8 | 11 |
| selected 单步 HV 低于 plain | 4 | 11 |
| selected 单步 HV 与 plain 相同 | 3 | 6 |
| selected 支配 plain | 4 | 9 |
| plain 支配 selected | 4 | 5 |
| 两目标存在权衡 | 7 | 14 |

eligible 的28次采纳在标量目标上15次较好、13次较差，HV 则11次较好、11次较差、6次相同。它增加了可执行影响，但收益有正有负。原 global 的15次采纳也呈7好8差的标量分布。当前证据不能支持通过更频繁地覆盖 plain 来稳定提升目标。

“改善当前 incumbent”与“优于 plain”是不同问题：global 采纳点改善 incumbent 为4/15，而其对应 plain 候选为9/15；eligible 为12/28，对应 plain 为10/28。这些计数只比较各动作自身冻结历史，不能直接解释为两策略的全轨迹性能差异。

## 结论边界与下一步

本次确实发现了两个需要分开的层次：区域竞争机制已生效；建议带来的真实方向质量仍未得到稳定收益支持。采纳率、提升后的预测 EI 和真实单步收益不是同一个指标。仅凭采纳率不足或幅度较小调大 `lambda_max`，可能扩大13个不利建议的影响；本轮没有开展强度调参，也不把这一假设作为已确认根因。

这些轮次来自同一轨迹，后验、trust 与观测历史相关，不能把60轮当作60个独立重复。两策略从首次不同选点后即有不同历史，不进行跨历史逐轮配对，不提供独立轮次显著性或置信区间。43个 plain 补算是有限的单步局部反事实，**不是**完整轨迹反事实、长期 regret 估计或真实 LLM 因果收益证明。原三种子完整软件对照也只有 eligible 相对 global 在1/3种子的终态 HV 改善，不足以宣称普遍性能提升。

拟进行的真实 API＋DFN 合成消融检查包括：真实有效回复是否覆盖可执行替代点、各回退原因、原 EI 排名与实际 delta/sigma、采纳后冻结上下文反馈，以及共享初始化下的完整 Pareto/HV/RMSE 轨迹。本次首次请求失败后未能执行这些检查。保持既定核、目标、物理模型、守卫和强度，不依据离线结果调参。

## 真实 API＋DFN 合成验证状态

新独立预算获批后已实际启动一次：0.5C/1C各60s、16候选评价选8共享初始化、WarmStart-only和新版Full各20轮，限112次DFN、23次API、1800秒，单线程、无传输重试。

**实际停止，未完成辨识对照。** 首次WarmStart请求归档HTTP-start为true，约10.144秒后返回URLError；HTTP状态为空，应用层记录transport_error。监督器16.123秒结束、退出码1，未重试、未恢复。实际API尝试1/23、HTTP-start1、DFN0/112、初始化评价0、BO0；没有新的RMSE、HV或Pareto结果。不能把缺失结果写为零误差或把外部请求失败解释为电热模型/Region方法失效。现有证据不能进一步区分DNS、TLS、网络链路、模型通道或账户原因，也不推断计费。

启动前两次独立软件预演均通过（每次两臂各20轮、112次代数调用、真实API/DFN0，脚本主动弃权，仅验证流程）；最终预演核验共享plan、首轮标签/GP/pool以及deep audit。监督器清理兜底新增3项mock测试：先3失败退出1，再3通过退出0；不是产品完整回归。原taskkill自身超时时跳过根进程清理的路径已修复，内层1780秒、外层1790秒停止等待、最多8秒清理，保持1800秒边界。本次真实失败走正常退出，无需超时清理。

本轮没有更改产品算法、参数映射、Prompt或旧缓存校验，未重跑上一阶段411项完整回归。6项算术校验、180动作检查、43个plain单步软件补算、3项监督器测试与真实请求失败分别记录，不混为软件/真实物理/实测成功。

- 真实归档：D:/Users/aa133/Desktop/LLMBO_Para/runs/ra/20261019T054608Z_2ce36fe2b2cb_758cd318；stopped-attempt-analysis.json、ablation-failure.json及execution-evidence/sha256.json。
- 启动与退出：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-influence-diagnosis-20261019/started.json、supervisor.json、process.log、exit-code.txt。
- 数值检查：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-influence-diagnosis-20261019/supervisor-green.xml、supervisor-green.log；软件预演见software-final.log与software-final/software-v2-result.json。

完整实验deep审计本次**未通过**：失败初始化没有生成electrothermal-summary.json，审计如实返回文件缺失。本轮保留其passed=false及完整issues，不补造summary或降低校验。独立终态、事件成本与HTTP证据核验通过，不能替代完整实验审计，更不能当作真实电热验证通过。

旧记录和原XLSX未修改，旧3C排除保持。真实电流、温度测点与单位、初态和冷却条件仍待实测预检。本次没有自动恢复；任何后续请求须遵守新的明确恢复/预算授权。
