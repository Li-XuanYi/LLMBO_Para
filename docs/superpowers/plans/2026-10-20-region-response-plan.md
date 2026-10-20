# Region 输出控制修复与效果验证计划（2026-10-20）

用户已授权继续修复和优化。沿用已确认的六参数、双目标、DFN+lumped、ParEGO/ARD Matérn/Gaussian EI、WarmStart与Region-Lift；本轮先修复有直接证据的请求控制接线缺口，不调整Lift强度、EI/sigma门槛或依据旧软件种子挑选新策略。CodeGraph仍按用户指示暂缓。源码基点6a9eeab，独立现有工作树，原项目和旧实验保留。

## 根因与最小修复

唯一新API的HTTP200、finish_reason=length、1536 completion全为reasoning、content为空，证明传输已完成却没有正式JSON。底层ChatCompletionsTransport已有thinking参数，但v2配置与request_controls只允许timeout/tokens，默认控制没有传至构造器；本轮修复此缺口。官方DeepSeek支持thinking.type=disabled，但第三方vsllm具体路由尚未验证，不伪称已生效。

1. 先完整基线回归；测试运行期间不改产品源码。
2. 失败测试：严格全局/按任务thinking配置，继承/覆盖、不变旧缺省；配置到worker到HTTP的disabled传递；注入客户端不被改写；推理用尽输出的安全分类、不重试；审计拒绝thinking或completion诊断被篡改。
3. 修改electrothermal_config.py、electrothermal_requests.py、electrothermal_llm.py：thinking只接受显式enabled/disabled，缺省省略以保留旧行为；控制按任务解析；Bounded传递并归档实际模式。旧schema1及底层通用传输不修改。
4. requests只提取机器可复核的completion摘要：finish_reason、正式答案长度、有效非负token计数及是否推理耗尽输出。保留protocol_error/unfinished_completion语义，不采信或展示原始reasoning，不提取半截JSON。
5. electrothermal_audit.py从实际HTTP body和响应重算新控制/诊断，保持旧档案重放；有明确thinking控制的新档案必须一致。真实目标、方差、训练标签、权重与信任逻辑不变。
6. 针对性测试→完整回归→旧完整真实档案只读审计；显式文件列表提交。软件测试和元数据修复不计为真实服务成功或RMSE收益。

## 效果分门验证

第二个独立假设：当前Region历史只发非负RMSE和有效性，缺少预测偏高/偏低。镜像残差拥有同一RMSE却应支持不同热参数判断。第一阶段输出控制针对性测试通过后，再按TDD新增可选`optimization.region_evidence=signed_residual_v1`，仅搭配candidate_aware_v1+fair_region_v1；默认legacy_v1保持原payload/Prompt。新增electrothermal_residuals.py，从已评价记录的各自观测网格计算prediction-observation的均值、首/末四分之一均值及单位/样本数；失败项为null，不产生新目标。独立200–300词Prompt解释符号、C/G的条件性影响和不能推断未观测目标。审计从真实归档曲线重新计算摘要，镜像、部分失败、未来信息及篡改测试必须通过。这是输入证据补全，不修改Lift、GP、两个RMSE或选点门槛。

- 门1：一次真实API在原30s/1536tokens限制下，以显式disabled产生完整、正确绑定的JSON，记录服务端reasoning用量；有效none可通过契约但不算Region采纳。服务端忽略/拒绝参数时失败，不能自动换模型、加tokens、修复回复或重试。
- 门2：冻结同一GP/权重/尺度/候选池下，证明一个有证据的有效Region能够按现有守卫改变选点，保持原GP不变。此项软件正例不证明新点真实更优。
- 门3：新源码下真正重新评价历史8个参数坐标（不是改签旧曲线），建立共享计划，WarmStart-only/Full各20轮；0.5C/1C各60s。固定默认Lift、门槛、GP、种子/权重、目标尺度/HV空间，逐轮归档、独立复算完整Pareto/HV与同一参数双RMSE。该固定8点是相对原16选8的明确协议修订。

真实阶段草案需新预算：门1最多1API，成功后门3最多96DFN/20RegionAPI，总墙钟1800s、单线程、无重试。不得在批准前执行。一次配对只代表本次协议的探索性结果；至少三组预先固定种子、相同有效初始化、全部负结果保留后才评价稳定收益。不得反复挑最好种子、只比较单个目标的独立最小值或把采纳率作为有效性标准。

无有效Region/无收益则保留并诊断，不扩大无界试验。“直到有效”在工程上表示持续定位并按预注册证据推进，不表示可以保证一个启发式必然优于Plain，或为了有效而放宽校验/抹除负结果。

## 交付

严格配置与HTTP接线、completion诊断与审计；失败/通过测试、完整JUnit/日志/退出码；源码提交与主目录保护检查；默认API关闭/solver0的示例与门控真实验证协议。付费请求、DFN、正式实测和服务器任务当前预算0。
