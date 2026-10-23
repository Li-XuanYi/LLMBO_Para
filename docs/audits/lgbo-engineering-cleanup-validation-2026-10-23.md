# LGBO 工程整理验收（2026-10-23）

范围：已批准计划40a8c54；当前会话原生实现、TDD和本地软件验证。工作树`C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`，分支`codex/electrothermal-mo-20261016`。主工程、参考工程及旧交付只读。本轮Task0–4软件验收已完成，以下为实际测试与独立审阅结果；真实物理/方法增益未由本轮验证。

## 已实现的接口与兼容性

|文件|变更|
|---|---|
|acquisition.py|FrozenAcquisitionView、build_acquisition_view、validate_acquisition_view；深层不可变且绑定本轮context/pool/GP/标量化/incumbent|
|mo_optimizer.py、electrothermal_lgbo.py|LGBO生产路径共享基础预测；apply可选acquisition_view，旧独立调用仍自行计算|
|electrothermal_json.py|is_json_native、archival_json、decode_archived_http_response|
|electrothermal_region_catalog.py|保留三个旧公共工具包装，catalog几何与解析保留|
|electrothermal_payloads.py|WarmStart、LGBO、旧Region三个构造入口及共享序列化|
|electrothermal_llm.py|原公共payload入口转发；控制器保留传输、预算、归档和回退|
|electrothermal_lgbo_audit.py、electrothermal_region_wire.py|只迁移通用JSON引用；数值审计独立|
|tests/electrothermal_payload_fixtures.py、tests/fixtures/electrothermal_payload_golden_20261023.json|源码变更前固定八类payload/wire与历史顺序；catalog非空；可信身份在producer前冻结|
|tests/test_electrothermal_json.py、tests/test_lgbo_acquisition_view.py、tests/test_electrothermal_payload_refactor.py|独立JSON字面oracle、实际生产重复计数、视图绑定、数值等价和请求golden测试|

公式、GP拟合预算、候选池、目标尺度/HV空间、32锚点和Gaussian EI没有改变。旧四倍率电压任务依原接口；新电热fit_rates仍由配置驱动，旧3C不加入拟合。缺失目标仍不补零。旧初始化/缓存/回复按原签名拒绝，不重签旧计划。旧Prompt字节、归档schema、accepted别名和重复归档数组保留。

## 本轮实际软件证据

证据根：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-engineering-20261023`。每个tests/<label>/包含pytest.log、junit.xml、exit-code.txt、manifest-before.json和result.json；runner禁止网络和真实电池solve，单线程，不读取凭据值。CLI结果在cli/<label>/，没有伪造JUnit。

|本轮运行|通过|失败|错误|跳过|退出码|
|---|---:|---:|---:|---:|---:|
|ge-baseline|1092|0|0|0|0|
|ge-json-red|0|26|0|0|1|
|ge-json-green|336|0|0|0|0|
|ge-view-red|0|27|0|0|1|
|ge-view-green|102|0|0|0|0|
|ge-payload-red|0|13|0|0|1|
|ge-payload-green|332|0|0|0|0|
|ge-final-full|1158|0|0|0|0|

RED均为本轮新增测试对缺少实现的预期失败，不是既有回归失败。视图RED还实际观察到生产predict=2、基础EI=2；GREEN证明各一次。两个非零confidence在同一冻结视图上比较时，总predict=1、EI=3（一次基础加两次调整后），没有删掉调整后EI。独立数值oracle为mean[-1,0,1]、std[0,1,0]、best0时EI[1,0.3989422804014327,0]。新旧apply在有效/none/零confidence/缺回复/负交叉协方差/负或退化区域方差/无可行锚点下逐字段一致。

八类payload/wire两次生成摘要相同，旧v1的77f3a8ca4e03e024578fff5bf9f9a35350bdb4a2b5272a7afdd153b34dbb39c2基准保持。生成golden的34次人工候选评价/68次软件工况调用单列为测试准备；不是正式BO、真实DFN或实测。其余mock/软件单元夹具也不记为物理验证。

初始与Task1保护检查均通过：主工程HEAD811c4c6、status/index、124个文件，55个参考源码文件、固定物性/锁文件/Prompt及受保护函数AST。旧封存10908个文件加52个外部测试证据、另一份529个文件均匹配。最终保护复核同样全部通过；具体哈希与旧seal核验见ge-protection-final.json。

## 科研结论边界与后续顺序

本轮真实API=0、DFN=0、正式BO=0，不重跑旧24组实验。代码实现及软件等价不能证明真实LLM增益、DFN新配对通过、参数唯一可辨识或实测成功。没有发布新Prompt或Region公式，也没有运行c/锚点冻结回放。

已确认设计中的Prompt候选继续只作研究文案。下一步先在相同payload/历史/选择规则/数值预算下比较Prompt；之后才单独研究历史选择或区域信息质量。预留种子101/131/167不是本轮运行结果。若另审c=0/.25/.65、32/128锚点，冻结诊断只报告均值扰动和EI排序，不为未实评替代点填RMSE/HV。实际API/DFN须独立具体协议和预算，保留全部负结果。

实测仍待实际电流与时间、T列单位/测点、初态、冷却条件、热参数范围和固定物性来源确认。可靠3C须新配置与新实验归档；旧XLSX、实验和四倍率电压流程保留。

## 最终交付记录

最终全量回归1158/1158通过，失败/错误/跳过均0、退出码0；result记录墙钟1911.18秒，源码与保护快照在执行前后一致。网络/真实电池solve均0；允许的非电池代数ODE单元调用2次，不属于DFN验证。

日志：[pytest.log](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-engineering-20261023/tests/ge-final-full/pytest.log)；[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-engineering-20261023/tests/ge-final-full/junit.xml)；[结果JSON](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-engineering-20261023/tests/ge-final-full/result.json)。

LGBO v1/v2软件模板CLI预检均exit0，无目标评价；实际旧源码初始化档案预检exit2，错误为`initialization signatures incompatible`，未换签。已有软件测试还验证新同source计划在两版本共享。独立gpt-6-astra整体审阅40a8c54..7be4344：Critical0/Important0/Minor0，无代码修复或第二次审阅；审阅时全量回归尚在运行，交付以本节最终结果补足该条件。

阶段提交：4a4b959（golden）、c11333e（JSON）、f8c3770（预测视图）、61a1939（payload）、7be4344（规范/说明）。最终文档提交以证据closure.json/final_HEAD为准。显式变更清单、完整裁决/审阅报告和封存位于本轮证据根；工作树、分支、独占临时档案均保留，不merge/push/清理。

执行裁决完整记录在ledger-final.md/closure.json：原生Windows运行器替代bash工具（维护/证据遗漏风险）；按用户要求保留工作树和证据（磁盘成本）；只读审阅与全量回归并行但双重门禁（审阅初期缺最终结果）；伪造有限预测值不属于宿主视图算术保证（绕过所有权可能先错选再被审计发现）；直接修改GP内部缓存不属于fit/state生命周期（可能绕过早期检查）；伪造prepared混合策略不属于严格预检后的执行（绕过准备可形成不受支持请求）；不从软件结果声称真实增益、物理有效或固定百分比提速（否则造成无证据结论）。延期小项0。
