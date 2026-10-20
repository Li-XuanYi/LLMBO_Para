# Region 输出控制与历史方向证据修复

用户要求继续修复并优化Region。基点6a9eeab，沿用独立工作树与既定数值方法，不改变GP、Lift公式/强度、守卫、六参数、两个目标或热模型。旧实验、旧配置和严格缓存签名保留。

## 直接证据

`bo-repair-work/20261017_et_implementation/region-api-preflight-20261020/actual-audit.json`记录唯一获批请求：HTTP200/14.344秒、finish_reason=length、completion/reasoning均1536 tokens、content空，Python退出2；外层18.734秒，API1/DFN0/BO0/重试0。没有进入Region绑定或守卫，不能据此判断数值方法效果。原始记录只读保留。

底层客户端支持thinking，电热配置与request_controls却只接受timeout/tokens。第二个可证明的信息限制是：正负镜像残差具有相同RMSE，旧摘要不带符号，无法区分应解释为预测偏热还是偏冷。信息缺口不等于已证实提供符号必然改善BO。

## 改动

- v2全局及按任务thinking继承/覆盖，严格enabled/disabled，旧缺省不添加字段。任务配置到克隆客户端、worker、HTTP body、outcome与supervision一致；注入客户端不被修改。
- 安全completion摘要记录正式答案长度、结束原因和有效整数用量；空答案且全部completion耗于reasoning的length失败单独可诊断。不存在自动重试、加预算、读取推理正文当答案或放宽JSON校验。
- 显式signed_residual_v1证据选项，必须使用现有candidate-aware fair策略。已有评价曲线提供prediction−observation的均值、首/末四分之一样本均值，V/K，8位有效数字。失败统计null；两个优化RMSE、原GP和方差不变；未来完整或半失败记录在发送前拒绝。
- 独立274词英文Prompt说明误差方向、C/G条件关系、权重与Tchebycheff最大项、短窗混淆与弃权。不增加GP混合核、目标、参数或新的采集算法。
- 审计从实际HTTP文件/事件核对控制字段、从原始响应重算token摘要，从过去曲线重算signed摘要。不能改outcome开关来关闭审计；非法content类型的诚实失败也能正常审计。

## 一手文档与不确定性

DeepSeek官方[思考模式](https://api-docs.deepseek.com/guides/thinking_mode/)和[Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion/)支持thinking.type=disabled，并说明输出用量与结束原因。第三方端点的准确模型路由和透传行为尚未核验；此代码支持不等于服务端已生效。公开文档研究没有消耗推理API请求。

## 验证记录

证据根目录：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-response-repair-20261020`，所有失败记录保留；最终结果汇总在acceptance.json，全文日志/JUnit在父目录tests下。

- 修改前完整基线447/447，失败0/错误0/跳过0，退出0，608.37秒；`tests/region-response-baseline-1020033714762541`。
- thinking RED：28项中13项预期失败，错误0，退出1；`tests/region-thinking-red-1020034817468761`。
- 首轮输出控制针对性69/69、退出0；`tests/region-thinking-green-1020034923357939`。
- 初版审计测试先暴露新fixture未提供必要共享初始化的4项失败；修正fixture后真正观察到3项篡改预期失败/1项通过，错误0、退出1；`tests/region-controls-audit-red-fixed-1020035136508646`。随后控制/worker针对性39/39、退出0；`tests/region-controls-audit-green-1020035227212856`。
- signed残差RED：17项中13项预期失败，错误0、退出1；`tests/region-residual-red-1020035316925572`。随后相关53/53、退出0；`tests/region-residual-green-1020035448752354`。
- 独立审阅指出审计标志绕过、未来半失败输入、非法content类型摘要形状三个边界；新增失败测试3/3预期失败、错误0、退出1；`tests/region-review-red-1020040011103912`。对应修复后再跑针对性与全量，最终实际数字随后写入交付记录。

本轮这些软件测试的实际API/电池solve尝试均为0；完整基线允许2个非电池fixture solve。软件修复后仍需新的明确真实预算；不能把上次失败预检或既有447历史通过当成本轮修复后的全量结果。

## 后续验证与停止规则

先一次有界API核验disabled是否产生正式完整JSON、正确绑定与合法语义；合法none只说明契约通过。失败保留，不自动重试、改模型或加tokens。成功后才在新源码下重新评价固定8个历史坐标，形成严格有效共享初始化，做固定种子、等预算的WarmStart-only/Full消融。旧曲线不重签、不冒充本轮新评价。

真实效果预先固定种子、尺度、HV参考点、最终参数选择规则和停止点，保留API失败/回退及全部负结果。HV变好只支持Pareto集合改善；同一参数下两个误差分别报告，不能拼接不同点的最小值。未见收益则明确报告未证实，不继续盲目调强度直到挑出正结果。实测条件缺失、旧3C禁用及正式实测/服务器限制保持。

最终完成记录：合并针对性113/113、失败0/错误0、退出0；最终完整回归498/498、失败0/错误0/跳过0、退出0。完整证据：`D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\tests\region-response-full-1020040319769291`（result.json/pytest.log/junit.xml）。3个旧完整真实归档只读审计通过（deep=False，恢复冻结GP，不重拟合），新API/DFN0。源码指纹`954ef0099a814b248ae2ddf1ca148bca382dcdf90e0f0497b30ca4a6f550d863`。

旧冻结真实第4轮所发送6条历史、12个倍率项的曲线复算中，温度signed_mean有5正/7负，旧payload没有符号摘要；该只读诊断保留原曲线SHA，不是新性能试验。原始证据见past-sign-diagnostic.json/CSV。
