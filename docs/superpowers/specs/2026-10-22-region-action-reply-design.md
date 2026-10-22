# Region 仅动作回复设计

状态：根据用户 2026-10-22“没有必要解释文字，请优化 Region”的明确方向完成设计；待详细实施计划审批。本轮产品代码、真实 API/DFN/BO 均未启动。

## 目标与边界

参考 WarmStart 的必要任务数据接口，使 Region 不再要求模型生成解释文字，避免非决策文本使有效动作失效。优化限定在回复表达、解析和审计，不改变已批准的 GP、Lift、Gaussian EI、候选池、权重、尺度、HV、信任更新或物理模型。依据 [实际对照审阅](../../audits/region-warmstart-contract-review-2026-10-22.md)。

当前源码指纹 a98cc1890ea99d4fca5b4b9a9cd53be7b6f97cac16128ac502bd35c7349bcc90。旧 8192-token 回复确实 completed 且 JSON 有效，最终因 reason=417 字符超过 400 而拒绝；该失败保持原记录。

## 显式版本与线上动作

新增 llm.region_wire_format=compact_action_v2，仅用于 schema v2 的 catalog_v1 Region；其现有 dynamic_decision_v3/candidate_aware_v1/fair_region_v1 组合约束不变。full_v1、compact_v1 及缺省语义逐字节保持，WarmStart 不使用新 Region 编码。

线上仍只返回 request_id 和 region。region 的必需字段：kind、coordinate_space、confidence、proposal_binding；kind=region 时再要求 region_id 和 evidence_ids，kind=none 时不允许这两个动作字段。没有必需的 reason 字段，Prompt 明确要求只返回动作 JSON、不输出解释或分析。

为避免模型仍附带一个 reason 再次破坏动作，线上 schema 可将 reason 作为唯一允许但不要求的兼容元数据，属性 schema 为 {}、没有长度条件。它不属于动作，接收端不解释、不执行、不传入计算；原始 HTTP 记录保留它。其他额外字段仍拒绝，尤其不能加入 lb、ub、参数坐标或伪造的预测目标。

绑定版本为 region_compact_action_v2，摘要继续绑定完整本地请求，含新 wire 模式、Prompt、原始身份、权重、尺度、物性、历史和目录，仍只排除本地 artifact_task。旧 request_id 或 proposal_binding 不得跨模式、跨轮或跨权重使用。

解码后由宿主从本地请求恢复现有 envelope，并添加固定代码标记 reason=structured_catalog_response，继续交给现有 resolve_catalog_region。这是为保持内部接口的固定标记，不是 LLM 解释。解析器只移除兼容元数据 reason，保留全部动作字段交给原有严格校验，不修复或裁剪动作。

## 校验、兼容与审计

Responses 仍只接受 completed、有限 JSON 和正式回答；不从截断正文、非 JSON 或 reasoning 项中提取动作。身份/类型/目录/证据/置信度及原锚点和公平性守卫保持不变。传输失败继续回退，预算与无自动重试规则保持。

新模式进入已有配置/算法签名及完整请求绑定。旧模式仍按旧规则拒绝超长 reason，旧归档不重新签署或重标成功。当前源码更新后仍严格核对初始化计划和缓存来源，不放宽源指纹。

审计从归档配置选择版本，从归档 Prompt 与冻结历史重建完整请求和实际线上请求，再从原始 HTTP 回复独立解码及解析，核对规范动作和选点证据。修改 wire 版本、Prompt、绑定、ID、证据、权重、尺度或规范区域都必须被发现。兼容 reason 的出现或长度变化不影响动作和数值输出。

本轮不压缩历史或目录输入，不引入结构化生成的未知 provider 扩展，不提高模型硬上限。交付一个新的禁用模板，使用已验证请求上限 8192 tokens/120 秒；enabled=false、API/DFN 预算 0，旧模板保留。

## 验收

软件验收：无 reason 的 region/none 均可解析；417 字符及更长的附带 reason 不改变动作；旧模式行为保持；核心字段篡改和非正式回复拒绝；两种现有传输、WarmStart、三模式软件闭环和深审计通过；相同结构化动作下 GP/Lift/EI 数值一致。

真实 API 验收：后续独立有限预算下确认模型能稳定生成无解释动作，目前未批准新请求。DFN/RMSE/HV 增益验收：另行配对预算，不将软件或 API 契约通过写成增益通过。实测条件和旧 3C 排除协议继续保持。
