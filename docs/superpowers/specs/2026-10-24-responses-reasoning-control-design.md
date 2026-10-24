# Responses 显式推理控制：最小修复设计

状态：待审；这是候选修复，不声称真实超时已经解决。起点83c173b，继续原独立工作树及分支。证据见[根因调查](../../audits/region-timeout-root-cause-2026-10-24.md)。

## 目标与选择

让当前电热Responses请求能够显式控制内部推理，并区分“字段已发送”“网关是否执行”“完整Region返回”“真实优化增益”。不改LGBO公式、GP/EI、Prompt、真实Y、参数、热模型或历史信息。

三个可选方向：

1. **本次推荐：显式reasoning控制。** 官方协议依据明确，修改一个线上字段即可做完整冻结请求比较；网关语义仍须验证。
2. 压缩历史视图：可能减少延迟，但改变LLM可见信息，当前没有长度根因证据，留待独立研究。
3. SSE：能增加进度观测，但需要新事件解析和审计，首事件不能代替完整JSON，本次不引入。

推荐方案属于作者提案，等待用户审批，不标为已选择/实现。沿用用户一次提交可执行计划再批准的流程，将此短设计与详细计划一起审阅，避免重新讨论已确定的BO框架。

## 唯一新增配置及映射

只在schema2、`llm.transport='openai_responses'`允许可选的全局 `llm.reasoning_effort`，严格枚举字符串 `none/low/high/max`。字段缺失保持旧行为且不注入默认值；显式null、布尔、其他拼写拒绝。schema1、Chat和task_options均不接受此新增字段，避免额外任务级优先级。

请求映射 `reasoning_effort='none'` → `{"reasoning":{"effort":"none"}}`。其余三枚举原样传递；None只作为Python接口中“未配置”的默认，不变成JSON null。旧Responses的Chat thinking禁令保持，不静默翻译任何thinking字段。不要改变用户全局Codex配置。

两任务继承同一个显式全局值，timeout/token的既有任务上限和硬截止完全不变。controller构造/克隆客户端、spawn spec、supervision及outcome必须传递并记录该值；配置是唯一真源，不能偷偷继承注入客户端上未配置的推理模式。旧请求不出现新字段。

请求body严格保持原instructions/input/max_output_tokens/text/stream=false/store=false；除可选reasoning外逐字段不变。新配置进入既有config/algorithm签名，不放宽源码/缓存/旧六维回复验证，不给旧初始化改签。

审计从归档配置重建完整body，并比较outcome/supervision的字段和值；删除、添加或改成其他effort均被发现。旧字段缺失的档案原样通过。只请求none不等于已证明服务端关闭thinking：实际推理计量缺失保持unknown，若非零则如实记为与预期关闭不一致，不篡改usage、不丢弃完整合法回复、不新增数值守卫。

## 验证分层

软件：先新完整基线，再RED→最小实现→GREEN→全量；无真实API/DFN。覆盖配置、精确body、注入/克隆/spawn、超时/错误、禁用/零预算、审计篡改和旧档兼容。新配置下的数学行为仍用同一正式动作验证。

真实诊断另需明确批准，拟独立最多 **5 API、0 DFN、0 BO、720秒**，每次8192输出tokens，单线程、无重试。固定sidrune/deepseek-v4-pro、同一代理及严格TLS，只有reasoning字段发生实验性变化；不启用流式或模型发现。

固定序列：最小none60秒 → 上轮完整上下文0、none120秒 → 同一上下文0、省略120秒 → 上下文1、none120秒 → 上下文2、none120秒。第一条完整none失败就停，先避免在无效配置上继续消耗。省略臂是预注册对照，不是失败后的重试；仅本次请求已经开始、触发预注册120秒单次硬截止、总钟仍有效、源码/输入未漂移且owned树已停止时，允许该省略臂截止后继续；其余失败/超时都停止。任何401/403/404/429/5xx都停止，不自动换档/恢复。总窗预留30秒作停止/审计/清理，不另加时间；剩余不足以保留这30秒时不再发新请求。

比较臂除reasoning外body相等，冻结请求身份保持历史重放身份，不作为新BO数据。历史context_id/request_id/signatures仍指原GP上下文；新的transport controls、实际执行源码和批准协议由独立`responses_reasoning_probe_v1`元数据绑定，不能改历史配置再称原签名有效。三个不同none上下文完整合法且至少一次真实非零tilt，才标记transport_ready；`reasoning.effort='none'`是请求控制，`region.kind='none'`是合法弃权，二者不混淆。即使通过也不自动启动DFN。一次时序比较只能提供诊断线索，不能消除服务负载、缓存或随机生成混杂，更不能直接说明RMSE/HV增益。

首次实际请求前开始独立总钟，计入所有失败请求/启动/审计/清理，不复用已关闭旧额度。密钥仅专用环境读取，父进程持久记账、owned tree停止、源码/入口/输入冻结验证沿用现有机制。不主动索取、打印、额外提取/另存或解释推理文本；原始HTTP回复沿用既有归档及脱敏规则，仅分析usage数值，0计量也不升级为网关内部行为证明。不因免费而扩容。

## 交付与审批

详细文件/接口/失败测试见[实施计划](../plans/2026-10-24-responses-reasoning-control-plan.md)。先批准短设计及计划，再产品实施；新的5次真实诊断可随本计划一并批准或维持0。保留原生执行方式及一次最终独立审阅，不另建开发工作树，不合并/推送/清理旧记录。
