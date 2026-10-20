# Region 决策证据与合法几何示例修复计划

既有用户授权为持续分析并修复Region；数值方法和资源边界保持。此修订不需要新的实际API或DFN，先按TDD完成本地软件验证；新的真实性能试验仍须独立预算。保留已完成实验的冻结源码、批准、失败及负结果，不回写新Prompt到旧档案。

## 已复现的问题与假设

冻结提交d90b93f的三种子真实DFN合成消融全部完成，ΔHV=[0,0,0]；43次请求中26合法none、2region超宽、1合法region经公平守卫拒绝、14服务失败，另17轮无eligible。正式短reason中可复核到温度权重大被误当温度项主导，以及误以为区域应包住Plain和一批alternatives。

零API/DFN/fit的冻结容量审计精确复现合法region拒绝；在同一后验、候选、置信度0.62和全部原门槛下，使用最小合法宽度的聚焦矩形可改变选点，公平EI优势+0.000135689。该mock正例只证明几何通道有作用，没有新增真实目标，也未证明RMSE更好。不调Lift强度或降低守卫。

待检验假设：host直接提供已知的加权贡献、预测均值差方向和合法坐标示例，能消除一部分算术/几何错误；不保证模型给出有价值的偏好，不强迫提高confidence或采纳。

## 显式文件、接口与步骤

1. 新增 `tests/test_region_decision_evidence.py`，首先运行观察缺少新证据的失败；禁止真实API和电池求解。以冻结数学例子验证T高权重仍U主导、精确同分、目标单位和尺度同步变换不变、预测mean差负号表示更小的标量目标。
2. `electrothermal_config.py` 增加可选 `optimization.region_evidence=decision_geometry_v2`，必须同时使用candidate_aware_v1与fair_region_v1。legacy_v1和signed_residual_v1缺省/既有行为不变，仍严格拒绝未知字段和旧缓存混用。
3. 新增 `electrothermal_region_evidence.py::build_region_decision_evidence(context, *, advice, settings, observation_ids)`。只读冻结已观测y/weights/scales/ideal/raw labels与已有候选后验摘要，不fit、不求解、不调用模型。按传入的过去唯一ID输出加权分量、主导项、最大项、augmentation和g；按候选顺序输出mu_candidate−mu_plain。为eligible平等提供每维既有min_width的中心矩形，越边界时整体平移到单位立方体，不舍入或重复log变换；Plain不提供示例。它只保证坐标/宽度，不代表最佳宽度、所有锚点物理可行或更优的真实目标；示例没有confidence，不修改后续区域验证。
4. `electrothermal_llm.py` 只在新模式增加顶层decision_evidence，继续带原signed曲线摘要；独立英文Prompt为200–300词。明确只比较可支持的局部候选，不要求包住Plain/所有alternative；可参考几何示例或诚实弃权，不伪造未观测双目标。旧Prompt字节保持。
5. `electrothermal_audit.py` 对新模式从归档冻结上下文/候选建议独立重建全部新证据，核对发送历史的原参数、目标与标量值、Prompt及signed曲线；篡改主导分量、均值差、矩形或删除字段均须失败。旧真实档案可继续只读审计，不重签。
6. 针对性绿色测试、独立代码审阅、完整回归、旧真实档案兼容审计；保留日志/JUnit/退出码和显式文件清单后提交。主工程及参考项目不改。

## 验收与未验证事项

软件验收为数值/单位/几何/签名/审计及旧接口保持，默认API关闭且无新增DFN；不以这些测试替代LLM实际选择行为。原GP训练、后验方差、真实标签、权重生命周期、EI、Lift、信任和公平比较规则不改。

原d90b93f运行源码的完整回归498/498、失败/错误/跳过0、退出0已封存为本次修订前基线；实施后必须另跑新完整回归，不能把这个历史数量当新增结果。真实消融结果封存在主工程bo-repair-work/20261017_et_implementation/region-response-repair-20261020与runs/rpc/20261020T065003Z_2f4986ff44f8_2a678770。

真实LLM是否选择更合法/聚焦区域、真实RMSE/HV是否改善、短窗热参数可辨识性和实测表现均尚未验证。下一次真实验证应先冻结少量上下文核验新契约与建议质量，再决定是否值得进行新配对，不能因本次未见收益自动消耗剩余API额度、重跑预算或挑选新种子。
