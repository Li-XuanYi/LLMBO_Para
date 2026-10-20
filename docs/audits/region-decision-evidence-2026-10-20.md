# Region 决策证据与几何示例：实现和验收

## 实际性能基线与定位

提交d90b93f的真实DFN合成Region消融已按批准完成：0.5C/1C各60秒，重新评价固定8点，种子101/211/307两臂各20轮。新资源256DFN、43API，外层1755.14秒、退出0；累计当前预算族API45/62。三对ΔHV均0，672项独立归档曲线RMSE检查一致，六臂完整，未证实Region收益。不能将这次真实实验用于宣称下述新模式已经有效。

完整负结果封存于 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-response-repair-20261020/actual-paired-results-20261020.md` 及 `actual-paired-evidence-sha256.json`（2267份文件）。运行session为 `D:/Users/aa133/Desktop/LLMBO_Para/runs/rpc/20261020T065003Z_2f4986ff44f8_2a678770`。Full60轮的去向为17无eligible、26合法none、14服务失败、2区域超宽、1合法区域公平比较失败。最终0次改变选点，而非所有回复都none或Lift完全没有执行。

正式短reason存在标量主导项和几何任务的误读。零API/DFN/fit冻结容量诊断精确重放合法区域的拒绝；保持confidence0.62、同一候选和全部原数值设置，改用明确mock的0.03宽聚焦矩形可通过公平守卫。该诊断没有评价新点，不能抵销真实负结果、给出真实RMSE改善或证明最优宽度。

## 实现范围

显式可选 `decision_geometry_v2` 搭配candidate_aware_v1+fair_region_v1。新增纯计算模块 `electrothermal_region_evidence.py`，从冻结历史计算加权分量、精确同分的主导项、augmentation和原g；从原候选摘要计算标准化mu差，附每个eligible的最小配置宽度坐标示例。边界整体平移、不舍入、不再log变换。示例没有置信度、没有物理或优劣承诺、没有新的排序或目标。

独立285词英文Prompt明确几何示例、符号、尺度、过去曲线和弃权语义，不要求包住Plain/全部候选。旧signed/legacy Prompt及payload保持；compact请求摘要绑定全部新证据。非法回复仍拒绝，不裁剪、不强迫高置信度。GP、训练标签、原方差、真实双目标、权重/上下文、EI/Lift强度、信任及公平门槛不改。

## TDD与独立审阅

修订前完整源码回归498/498封存，作为历史基线而非此次新跑结果。新测试文件首次RED最终为28项中21失败、7通过、错误0、退出1（`region-decision-red-1020074459353022`）；首GREEN28/28、退出0（`region-decision-green-1020074710236871`）。相关旧新路径86/86、退出0（`region-decision-related-1020074914875263`）。上述测试实际网络、电池和其它solve均0。

两名独立审阅者发现并复现审计的两类P2：只改发送历史中的单倍率误差，或同时删/重排历史行与其decision行，可能漏检。追加RED覆盖RMSE、完整标志、联合删行和联合重排，10项中4失败、6通过、错误0、退出1（`region-decision-audit-red-1020075257226301`）。随后仅新模式独立重建top4/两极端/recent3的有序历史并集，核对完整行（含每倍率有效性、误差、失败、参数、目标、g、坐标、signed摘要及键集合），再重建新证据；旧审计路径不改。

最终针对性90/90、失败/错误/跳过0、退出0（`region-decision-final-related-1020075446989422`）。独立副本复核：正常档案通过，原两类篡改均拒绝；API/DFN/fit0，原档案未改。初审与复核报告分别保存，不覆盖失败证据。

证据根目录为主工程 `bo-repair-work/20261017_et_implementation/`，测试各目录含result.json、pytest.log、junit.xml与exit-code.txt。完整新回归和旧真实档案兼容审计的最终结果见后续封存验收记录；尚未结束的测试不算通过。

## 验证界限

本修订解决确定性信息展示和审计完整性问题，不证明LLM会给出更好的区域，不保证RMSE/HV增益。旧真实档案保留原源码、计划与签名；新源码下如开展新DFN实验，仍须建立严格匹配的新初始化，不能重签旧曲线。真实实验已停止，未因剩余API容量而继续请求。本修订的额外实际API和DFN均0；正式实测、电流/测温/初态/边界待确认以及旧3C禁用保持。

## 最终软件验收

本次新增完整回归实际完成530/530，失败0、错误0、跳过0、退出码0，735.68秒。证据目录为 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-decision-full-1020075827849711`，含result.json、pytest.log、junit.xml与exit-code.txt。真实网络尝试0、电池solve尝试0，允许的非电池fixture solve为2；不将后者计为DFN验证。

4个已完成旧真实归档（包含本次d90b93f signed模式Full以及更早默认模式）均通过只读deep=False兼容审计，API/DFN0。恢复后验使用产品既有from_state，它内部有120次fit(max_sweeps=0)方法调用，但没有超参数搜索；不虚称其fit方法调用为0。结果见证据根目录 `decision-evidence-legacy-audit.json`。新的软件验收及显式文件/提交封存在 `decision-evidence-acceptance.json` 与 `decision-evidence-sha256.json`；它们与此前真实消融的封存记录分开。
