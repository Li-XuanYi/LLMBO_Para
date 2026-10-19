# Region 候选信息对齐交付（2026-10-19）

用户在方法审阅后回复“同意”。本阶段落实候选信息与采纳资格对齐；保留原 Lift 数学、EI/sigma 门槛、GP、双目标与物理模型。区域内竞争变体和强度调参没有在本提交中实施。

## 行为与兼容

- 新的严格可选配置 optimization.region_advice=candidate_aware_v1；缺省legacy_v1。三个电热模板显式采用新策略，但仍默认parego、LLM关闭、API/DFN额度0。
- 从当轮冻结GP状态恢复后验，不优化超参数；按原带1e-12下限的log-EI差和sigma比率判断资格。剔除plain、已观测/重复和参数空间不合法点。
- 先列plain，再以归一化Max–Min、原EI和稳定ID选择合格替代点，摘要最多12条；完整精度坐标、当前标准化mean/std、原EI、真实比率及守卫都明确。EI全零时展示比率为null，资格仍按原数值下限判断。
- 无合格替代点时，在transport前记录no_eligible_alternative，不花请求次数、ordinal或LLM成本。inactive优先，其余原disabled/预算守卫保持。
- 独立264词英文Prompt要求覆盖已提供的合格替代点或弃权。代码精确校验覆盖，不能只包含plain，不扩框、不强制采纳。原Lift数组及后验方差由新旧同fixture逐数组测试验证一致。
- 新模式每轮强制保留预检记录；审计从冻结后验重建摘要，核对门槛、outcome、ordinal、成本与覆盖，拒绝整段删除、伪造跳过和冻结池误绑。
- 旧配置不补写默认键；legacy输出形状和重放保持；schema1、旧Prompt与旧缓存校验未放宽。策略纳入算法签名，新模块/Prompt纳入源码指纹。初始化兼容规则保留，因此同源同协议两臂仍可共享计划。

## 本轮实际验证

| 检查 | 测试数 | 通过 | 失败 | 错误 | 退出码 |
|---|---:|---:|---:|---:|---:|
| region-candidates-baseline | 357 | 357 | 0 | 0 | 0 |
| region-candidates-new-final | 30 | 30 | 0 | 0 | 0 |
| region-candidates-full | 387 | 387 | 0 | 0 | 0 |

TDD红灯：候选功能25项失败、审计加固3项失败、展示比率2项失败，均为失败0错误、退出码1，随后最小实现/修复并通过。红灯不是既有回归故障或环境错误。另有中间70项和73项兼容回归通过，其证据保留。

全部软件验证由现有BoundaryGuard执行，单线程、网络尝试0、电池DFN求解尝试0。完整基线与回归含原有2次非电池代数eSOH辅助求解，不能当作电热DFN验证。

新增源码对上一轮真实DFN消融两臂分别完成离线deep审计并通过；不新增求解。新预检逐轮恢复旧冻结GP，20轮资格数量与独立算式完全一致，7轮没有合格替代点。该回放仅验证资格与兼容，不重用旧LLM回复、不执行新BO、不预测未求解点的RMSE/HV收益。

## 日志和JUnit

- region-candidates-baseline: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-baseline-1019034452433754/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-baseline-1019034452433754/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-baseline-1019034452433754/result.json)。
- region-candidates-red-reviewed: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-red-reviewed-1019035323250185/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-red-reviewed-1019035323250185/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-red-reviewed-1019035323250185/result.json)。
- region-candidates-hardening-red: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-hardening-red-1019040046247917/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-hardening-red-1019040046247917/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-hardening-red-1019040046247917/result.json)。
- region-candidates-ratio-red: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-ratio-red-1019040409087064/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-ratio-red-1019040409087064/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-ratio-red-1019040409087064/result.json)。
- region-candidates-new-final: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-new-final-1019040518462966/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-new-final-1019040518462966/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-new-final-1019040518462966/result.json)。
- region-candidates-full: [日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-full-1019040708987253/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-full-1019040708987253/junit.xml)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-candidates-full-1019040708987253/result.json)。

## 变更清单

- src/llmbo_para/electrothermal_region_advice.py
- src/llmbo_para/electrothermal_llm.py
- src/llmbo_para/electrothermal_config.py
- src/llmbo_para/mo_optimizer.py
- src/llmbo_para/electrothermal_audit.py
- src/llmbo_para/prompts/region_preference_candidate_aware_electrothermal.txt
- tests/test_region_candidate_advice.py
- tests/test_region_candidate_advice_hardening.py
- configs/electrothermal-synthetic.json
- configs/electrothermal-dfn-synthetic.json
- configs/electrothermal-research-template.json
- docs/llm-informed.md
- docs/audits/region-candidate-advice-2026-10-19.md

## 证据、版本和未验证项

受控分支codex/electrothermal-mo-20261016，变更前HEAD92c945f。实际提交见本轮verification-index及git log；测试期间未提交源码的精确source_fingerprint与显式文件SHA256保存在索引中。
证据目录：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-candidate-advice-20261019。legacy-and-frozen-replay.json保存两臂审计和20轮冻结资格；verification-index.json收集测试、输入与产物哈希。
主工程HEAD811c4c6、索引、Method、Git status及123个受保护产品文件保持原样；参考工程和旧实验均未修改，没有清理记录或修改权限。

本阶段只完成代码和软件验收，新增真实API/DFN均0。新Prompt能否改善真实服务输出、Region能否改变选点并改善F_U/F_T/HV，尚未验证；不能把旧两臂相同的2.9813mV/0.03576K写成新策略结果。
后续先单独验证区域内竞争规则与强度诊断，真实对照需新批准预算、相同有效初始化及等求解/请求边界；实际电流、温度测点/单位、初态和冷却等实测前提继续待确认，旧3C仍排除。
