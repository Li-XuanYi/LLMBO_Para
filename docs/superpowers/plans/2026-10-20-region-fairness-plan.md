# Region 同一 Lift 基线修复计划（2026-10-20）

用户要求分析并修复Region效果不如Plain。本轮沿用独立分支，基点300ce968d719a75c6fd8b398ae35c1994609496d；顺序实施。真实API/DFN预算0，不恢复过期运行，不改热模型/六参数/双目标/GP或Lift幅度，不重签旧缓存。完整设计与预注册文件保存在主目录证据区`bo-repair-work/20261017_et_implementation/region-fairness-repair-20261020`。

## 已定位机制

旧eligible_region_v1按其设计把plain实际shift固定0、候选保留正Lift。本例原始场下plain也收到相关性信号，候选只有在plain失去这部分信号时才胜出。因此不是RMSE或Gaussian EI实现错误；是需收紧的实验策略偏向。只有一个同上下文真实配对样例，不能概括LLM整体无效。

## 逐项实施与验收

1. 修改前完整回归433/433、失败0/错误0、退出0，654.33秒。真实冻结第4轮逐字段核对GP/标量化/候选池与plain对照一致，排除过期后验、EI数值下限及过大均值调整；保留原曲线与SHA256。
2. 先写`tests/test_region_fairness.py`，观察14项预期失败、错误0。覆盖新枚举、同一信号比较、仍可采纳的正例、同分/稳定ID、空区域、旧默认完全相同、正定协方差、GP不改写及审计篡改。
3. `electrothermal_region_selection.eligible_region_competition(..., selection_mode='eligible_region_v1')`新增可选fair_region_v1。比较门槛`max(EI_plain_original, EI_plain_same_raw_lift)`；区域内合格候选必须严格超过门槛。原EI资格/sigma门槛及raw_shift公式保持，plain实际shift仍0，新增baseline证据，不写GP或标签。
4. `electrothermal_config.py`严格校验新枚举且必须candidate_aware_v1；`electrothermal_llm.py`分派新策略和独立Prompt；`electrothermal_region_advice.py`发送正确比较规则。既有审计从冻结上下文调用同一决策接口重建新增baseline证据，拒绝篡改。旧global/eligible输出保持，旧归档按原配置审计。
5. 新英文Prompt `region_preference_fair_electrothermal.txt`共267词，强调Tchebycheff的尺度和最大项、两个物理误差、候选对plain比较、弃权与confidence不等于经验正确率。只针对新策略，旧Prompt保留。
6. 冻结真实回放应保留索引276而非373；只报告已有两点的真实RMSE，不推演新轨迹。三个旧完整真实归档深审计应通过。
7. 软件对照先预注册种子[17,29,43]、三臂各20轮、每种子16选8共享初始化、global64/local32/gp_sweeps1、全部原强度和资格门槛。脚本建议器固定选当前显示的最高原EI合格替代，0.1宽框、confidence0.9，不看未来目标。代数3倍率fixture，684次软件倍率调用，真实API/DFN0；全部结果保留，不按结果调参。
8. 针对性回归、完整回归与软件对照的原始曲线/HV独立复算、成本与源文件哈希检查完成后，按显式文件清单提交。完整实测/DFN新版本性能仍需新预算与新源码有效初始化。

## 结果解释边界

本次是同一框架内的保守比较守卫，不是新的多目标优化算法或性能保证。新策略是否改善真实LLM/DFN表现尚未验证。软件三种子中任一负结果和均值均需公布；不能只按采纳率或获胜种子数量宣布更优。新策略保持显式实验选项，不覆盖旧记录与默认行为。

完成记录：本轮新跑基线433/433、RED14项预期失败、针对性73/73、最终全量447/447，成功验证退出码均0。冻结真实例回退plain且3个旧完整真实归档deep审计通过。预注册软件684次倍率调用、12个deep审计与1944条归档通道独立检查通过；新策略对plain两胜一负、对旧策略平均HV差为负，全部保留，不调参。真实API/DFN新增0。交付见`docs/audits/region-fairness-repair-2026-10-20.md`及证据区acceptance/哈希索引。
