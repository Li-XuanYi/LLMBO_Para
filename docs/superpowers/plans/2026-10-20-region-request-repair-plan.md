# Region 请求失败修复计划（2026-10-20）

用户已要求“分析Region频频失败的原因 然后修复”。这是既定电热LLMBO-MO的传输修复，不改变六参数、热模型、标量化、GP、EI、Lift幅度或采纳门槛。继续使用独立工作树；顺序实施；不增加实际API或DFN调用，不恢复中断试验，不重签旧初始化计划。

1. **固定证据与修改前回归。** 保留本次WarmStart-only 20轮、Full 4轮和第5次未决请求；不得补造完整对照或将未决请求标为超时。完整基线411/411、失败0/错误0、退出0。记录前三次30秒超时与第4次10.047秒有效回复，及唯一一次采纳点的真实双目标比较。
2. **先失败测试。** `tests/test_region_transport_repairs.py`覆盖新配置校验、旧默认/WarmStart兼容、完整请求绑定、过期权重/尺度/倍率/源码拒绝、混合回复拒绝、真实worker的离线HTTP边界、响应头/正文等待分类、空content分类、归档篡改审计。有效导入路径下18项RED失败，另1项非法wire模式RED失败；复查另以3项RED复现非法llm对象异常并补类型检查。错误0，真实API/DFN0。此前两个因错误pytest导入根目录导致的失败保留，不算有效RED证据。
3. **最小传输实现。** 新增`electrothermal_region_wire.py`，接口`region_wire_format(config)`、`region_wire_payload(payload)`、`decode_region_wire(response,payload)`。`llm.region_wire_format`仅允许`full_v1`（缺省）与`compact_v1`。紧凑版只在线上请求移除完整签名回显，以完整冻结请求的摘要绑定`request_id`；严格核验后从本地请求恢复原v2信封，继续原Region验证。配置、控制器和worker显式接入，不改变训练数据。仅紧凑版压缩user JSON空白；旧默认保持。
4. **诊断与审计。** `llm.py`记录HTTP响应头到达事件、机器可读`protocol_issue`；`electrothermal_requests.py`记录启动到HTTP耗时、失败阶段和wire版本，保留HTTP状态，不复制任意提供方文本。`electrothermal_audit.py`从原始payload重建紧凑请求、核验HTTP消息、响应摘要绑定和本地规范信封；篡改权重/绑定必须失败。
5. **验收与交付。** 先针对性回归，再全量回归，均保存日志/JUnit/退出码和零网络/零电池求解边界。用已归档有效回复测量字符数并证明规范信封相等，不估算新提供方tokens、不宣称已降低真实超时率。配置模板关闭LLM、预算0、删除失效旧initial_plan引用。源码变化按既有签名规则拒绝旧计划，不放宽缓存。显式文件清单提交并保护主目录与旧产物。

外部服务排队/推理延迟尚无法从客户端归档区分；紧凑回复只降低可控负担。一次建议同时劣于已实评plain点不能证明整个方法无效，也不能将安全采纳视作真实改善。后续真实验证需要独立批准预算与新源码下的有效初始化。

完成记录：基线411/411、最终针对性60/60、最终全量433/433，退出码均0；有效RED为18+1+3项预期失败、错误0。修复阶段真实API/DFN均0，证据根目录`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-request-repair-20261020`。原有v1电压回归通过；真实服务成功率与完整实测/合成消融未宣称完成。
