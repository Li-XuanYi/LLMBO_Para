# Region 区域内竞争版本交付（2026-10-19）

用户在候选信息对齐交付后要求“继续”。本阶段实现先前审阅的独立选点版本，保持真实API/DFN预算0。

## 方法与接口

- optimization.region_selection缺省global_lift_v1，旧输出/重放不变；eligible_region_v1严格要求candidate_aware_v1，作为显式实验开关，不切换现有模板。算法签名包含该字段，比较指标空间与初始化兼容规则保持。
- qualify_region_pool共用原始带1e-12下限的log-EI差、sigma比率、合法性/观测/重复排除；摘要仍最多12条，实际竞争包含全池合格且位于合法区域内的全部替代点。
- 原锚点、协方差、权重、confidence/trust/anneal和raw_shift公式保持。实际shift只作用于区域内合格替代点，plain和其他点为0；与plain原EI严格比较，同分保留plain，替代点同分按同一冻结context的稳定ID。
- apply_electrothermal_region增加selection_mode；eligible_region_competition是纯数值函数。结果记录selection_policy、raw_shift、实际shift、竞争索引、未限制赢家/实际赢家、胜出原因和delta/sigma量级。请求与审计采用同一策略，重建掩码、目标标签和反馈；不改真实Y或原方差。

## 实际软件验收

承接基线为a03981a5543e5f567f19f4a5da47161c3654db0c，源码指纹与上一阶段387/387完整回归精确一致；这是版本核验，没有冒称本阶段重新运行该历史基线。

| 检查 | 测试 | 通过 | 失败 | 错误 | 退出码 |
|---|---:|---:|---:|---:|---:|
| region-competition-green | 54 | 54 | 0 | 0 | 0 |
| region-competition-full | 411 | 411 | 0 | 0 | 0 |

TDD先执行23项失败测试，再执行1项PSD反例失败测试，均退出码1、错误0；最小实现后24项新增测试与上一阶段30项共54项通过。所有网络/电池求解尝试0；完整回归中原有非电池eSOH辅助求解单列，不是电热DFN验证。

PSD反例使用默认守卫与原raw公式：旧全局赢家为框外点2并回退plain0；框内点1的原logEI差约0.01245、sigma比率1，调整后EI约0.209925>原plainEI约0.204511，新版本可选1。联合协方差最小特征值约0.001536>0。这是人工给定均值/协方差控制流样例，不是从真实电池数据拟合的GP。
审计分支fixture另用宽门槛触发路径，不能混写为默认门槛性能证据。旧真实消融两臂和上一阶段candidate-aware软件档案全部deep审计通过。冻结旧7个合法区域仍无合格区域内替代点，新规则不能凭空挽救这些框；没有为未求解点推算RMSE/HV。

## 受控软件对照

固定脚本建议器，最高原EI合格替代点、坐标字典序同分、宽0.1的框、confidence0.9；没有真实LLM或未评价目标前视，没有依据结果调强度或阈值。种子17/29/43，每种子筛选16选8共享初始化，三臂各20轮；起始GP、标签、池及比较空间一致。

| Seed | 策略 | 软件F_U (V) | 同参软件F_T (K) | 软件HV | Region采纳 |
|---|---|---:|---:|---:|---:|
| 17 | warmstart_only | 0.052134371 | 0.23041088 | 92.6037875 | 0 |
| 17 | global_lift_v1 | 0.052133837 | 0.23054416 | 92.6023473 | 4 |
| 17 | eligible_region_v1 | 0.052135305 | 0.23121453 | 92.5949194 | 8 |
| 29 | warmstart_only | 0.052147956 | 0.24019062 | 92.5857617 | 0 |
| 29 | global_lift_v1 | 0.052142058 | 0.23059548 | 92.6044151 | 5 |
| 29 | eligible_region_v1 | 0.05213815 | 0.23451958 | 92.603247 | 8 |
| 43 | warmstart_only | 0.052137489 | 0.23194397 | 92.5913533 | 0 |
| 43 | global_lift_v1 | 0.052138999 | 0.23347457 | 92.5730857 | 6 |
| 43 | eligible_region_v1 | 0.052133676 | 0.23032584 | 92.6034513 | 12 |

结果解释：原全局版本合计采纳15/60轮，新版本28/60轮；配对软件HV仅1个种子提高、2个降低。此结果支持竞争路径能够改变选点，不支持稳定性能提升或真实RMSE改善。更多采纳不等于更好的建议；本阶段维持实验开关，不提升为默认策略。

总计684次代数software调用，初始化筛选每种子只计一次；9臂和3次初始化均独立deep审计。各数值仅为软件fixture，不能与真实DFN的2.9813mV/0.03576K比较，也不能证明LLM或物理参数辨识有效。

## 证据、改动与边界

- region-competition-red: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-red-1019050550891329/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-red-1019050550891329/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-red-1019050550891329/result.json)。
- region-competition-psd-red: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-psd-red-1019050711312899/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-psd-red-1019050711312899/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-psd-red-1019050711312899/result.json)。
- region-competition-green: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-green-1019050847294238/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-green-1019050847294238/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-green-1019050847294238/result.json)。
- region-competition-full: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-full-1019051235996371/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-full-1019051235996371/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-competition-full-1019051235996371/result.json)。

完整对照：D:/Users/aa133/Desktop/LLMBO_Para/runs/rc/20261019T052448546302Z/report.md、result.json及每臂原始曲线/轮次/独立审计。
复现入口：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-competition-20261019/software_compare.py（固定软件协议，零真实API/DFN）；offline_replay.py读取旧档案；fixture-probe.py保存PSD定位样例。verification-index.json绑定本轮精确源码与产物SHA256。

显式变更文件：

- src/llmbo_para/electrothermal_region_advice.py
- src/llmbo_para/electrothermal_region_selection.py
- src/llmbo_para/electrothermal_llm.py
- src/llmbo_para/electrothermal_config.py
- src/llmbo_para/mo_optimizer.py
- src/llmbo_para/electrothermal_audit.py
- tests/test_region_competition.py
- docs/llm-informed.md
- docs/audits/region-competition-2026-10-19.md

主工程HEAD811c4c6、索引、Method和123个受保护产品文件保持，参考工程与旧实验不改。独立分支codex/electrothermal-mo-20261016，起点a03981a；实际提交见verification-index/git log。

尚未验证：新策略在真实API下的建议质量、真实DFN的RMSE/HV改进、实测辨识。当前三倍率数据预检缺失项及旧3C排除保持。后续真实消融需新的明确预算并共享有效初始化；强度诊断已有delta/sigma记录，本阶段没有调参或增加GP核、目标、热变量。
