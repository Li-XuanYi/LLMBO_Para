# Region效果不如Plain：机制诊断与同一Lift基线修复

## 结论

已定位并修复一个可解释的选点偏向，尚未证明新策略整体优于Plain。真实证据只有同一冻结上下文的一次有效Region采纳；软件结果也非全面胜出。保留旧方法、旧实验和全部负结果，新策略为显式实验选项。

更根本的效果风险仍是：Region是启发式均值偏置，目前没有证明LLM在已有GP/历史信息之外提供了经过校准的增量信息。合法框、confidence和锚点一致性都不能保证真实收益；收紧数值比较只能消除已定位机制，不能把任意建议变成有效先验。

## 真实同轮证据

原运行`runs/rr/20261020T011721Z_472abdc9cac0_487cc46c`，Full第4轮；同轮WarmStart-only已评价plain。两臂的scalarization/GP/pool逐字段相同。权重[0.2,0.8]、尺度[0.1V,1K]，使用同一best和Gaussian EI。真实观察来自此前已批准的0.5C/1C各60秒DFN合成试验，本轮没有重新求解。

| 量 | plain索引276 | Region索引373 |
|---|---:|---:|
| 原后验mean（标准化标量） | -1.1726868589 | -1.1524805310 |
| 原后验sigma | 0.1981655459 | 0.1890161678 |
| 原EI | 0.1129435122 | 0.0972422832 |
| 原始相关性Lift | 0.0206275094 | 0.0277822841 |
| 旧策略实际施加Lift | 0 | 0.0277822841 |
| 旧策略用于比较的EI | 0.1129435122 | 0.1142632509 |
| 同一原始Lift场下的EI | **0.1261340866** | **0.1142632509** |
| 已归档真实平均电压RMSE | 5.6259550569mV | 15.5283915929mV |
| 已归档真实平均温度RMSE | 0.0283228315K | 0.0293041773K |

候选仅在plain失去自己的相关性Lift后才胜出，优势0.00131974；按同一场比较则落后0.01187084。原mean更高且sigma更低，原GP并不认为它的EI更好；后验成对概率诊断约P(alternative<plain)=0.447，只作描述，未增加概率门槛。旧策略按已批准的eligible规则执行，不是EI或RMSE公式实现错误。

另外有三个限制：LLM confidence0.68与GP锚点consistency0.4565不是经验正确率；对坏建议的信任惩罚只发生在评价后；本例true scalar从incumbent0.03021357升至0.03378179，信任已正确从0.5降到0.4，不能阻止首次错误。温度权重0.8也不允许忽略电压：候选的加权scaled电压项0.0310568已高于温度项0.0234433，Tchebycheff最大项被电压支配。新Prompt明确这些语义。

排除项：EI远大于1e-12下限；shift/sigma约0.147，没有超过局部sigma；两点真值残差分别约-0.358/+0.636个原posterior sigma，没有证据据此认定单位、标准化或方差失效。这也不是整体校准证明。

## 修复与兼容

`fair_region_v1`仍用同一原始Lift、资格门槛及区域内候选，只将改变选点的门槛设为原plain EI与同一原始Lift下plain EI的较大值；必须严格胜出，同分保留plain。plain实际shift仍0，第二项是比较基线。没有增加核、目标、热模型、强度或经验调参阈值；无法保证实际误差始终改善。

新增baseline证据：plain_raw_shift、same_lift_plain_ei、required_ei和advantage。沿用现有冻结审计重算，拒绝基线、raw_shift、policy或请求规则篡改。config严格分派新枚举且要求candidate_aware_v1，独立267词英文Prompt只用于新策略。旧global/eligible默认值与输出保持；初始化/模型/数据签名不放宽，旧源码计划不可直接用于新运行。

真实冻结回放保留276，原始GP/mean/std/锚点/raw_shift完全一致；已实评两点显示本例回退较好，但这是已知坏例的机制回放，不是新实验。三个旧完整真实归档deep审计通过；中断Full仍只有4轮，没有补造20轮轨迹或未求解目标。

## 预注册软件对照：全部结果

种子17/29/43，每种子16个真实代数评价后按Pareto+Max–Min选8共享初始化，三臂各20轮。固定原资格/强度、gp_sweeps1、global64/local32、active_until21；R_fit=[0.5C,1C,2C]为可配置软件fixture，不使用旧3C。脚本建议器固定选所展示合格替代中原EI最高者、坐标同分、0.1宽框、confidence0.9，不读取未观测目标；没有调用LLM，也不评价新Prompt效果。原代码和设置在看结果前做SHA256预注册，未按结果调整。

| Seed | plain EI（WarmStart-only）HV | 旧eligible HV | 新fair HV | 旧/新采纳次数 |
|---|---:|---:|---:|---:|
| 17 | 92.6037874931 | 92.5949194405 | 92.6023473471 | 8/4 |
| 29 | 92.5857616636 | 92.6032470452 | 92.6044150684 | 8/5 |
| 43 | 92.5913533447 | 92.6034513259 | 92.5914180419 | 12/6 |

新策略对plain两胜一负，平均HV差+0.00575932；对旧eligible也是两胜一负，但平均HV差**-0.00114578**。不能只按获胜种子数宣布更好。采纳由28/60降为15/60，也不能把更低/更高采纳率本身当作好坏指标。数据是代数任务，结果不代表真实LLM建议或电池物理RMSE。

软件程序退出0，共684次软件倍率评价、真实API/DFN0。独立检查1944条归档倍率/通道曲线误差（包括验证缓存的重复曲线，不是1944次求解），重算同一参数的两个RMSE、HV及同Lift plain EI门槛；12个deep审计通过。三个模式每种子共享同一计划和首轮数值上下文，所有比较保持固定指标空间。

## 本轮测试与证据

独立工作树`C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`，基点300ce968d719a75c6fd8b398ae35c1994609496d。证据根目录为`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation`。

- 新跑基线：433/433、失败0/错误0/跳过0、退出0、654.33秒。`tests/region-fairness-baseline-1020020434426363/{result.json,pytest.log,junit.xml}`。
- RED：14项预期失败、错误0、退出1。`tests/region-fairness-red-1020021024668695`。
- 针对性：73/73、失败0/错误0/跳过0、退出0、169.54秒。`tests/region-fairness-green-1020021612468449/{result.json,pytest.log,junit.xml}`。
- 修改后完整回归：447/447、失败0/错误0/跳过0、退出0、749.86秒。[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-fairness-full-1020021940768358/result.json)、[日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-fairness-full-1020021940768358/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-fairness-full-1020021940768358/junit.xml)。所有本轮测试network_attempts/battery_solve_attempts均0；全量仅有2次允许的非电池求解fixture调用。
- 软件结果和独立复算：`runs/rf/20261020T021941710801Z/{protocol.json,result.json,report.md,independent-analysis/report.json}`；独立报告包含所有种子的同一参数双目标RMSE、CSV和HV图。
- 诊断/冻结回放/预注册：`region-fairness-repair-20261020/{frozen-real-diagnosis.json,frozen-replay-result.json,software-pre-registration.json,plan.md}`。真实原action SHA256为402e1ab4a8c1f9a0a07d0123b2de26dcd22bb8a21ce36d816a379da24bfd1006，未修改原记录或重签曲线。

下一步是带明确预算的新源码有效初始化、真实API与DFN配对消融；不能从本轮软件结果推断实测辨识、参数唯一可辨识或整体LLM优势。现阶段保留plain作为数值基线，新fair策略作为显式实验选项。

本轮源码指纹`e763c192aa2ca72f6f962fb01e3c94fc62edd6d9167ff778331b075e8c53f739`；修改前为3e972c8f。安全预检配置`region-fairness-repair-20261020/fair.disabled-config.json`显式采用fair_region_v1与compact_v1，LLM关闭、API/DFN预算0，不引用旧初始化计划。预检通过不构成真实启动授权。
