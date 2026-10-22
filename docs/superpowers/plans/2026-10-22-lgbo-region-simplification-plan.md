# LGBO Electrothermal Region Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将新电热Region简化为LLM直接区域、LGBO协方差均值倾斜及全池Gaussian EI，并保持旧版本可重放。

**Architecture:** 用独立数学模块计算有符号倾斜，独立动作模块处理精简回复和完整请求绑定。现有电热controller、MO循环及审计仅按一个显式region_method分派；旧分支不重写，WarmStart和物理评价器不变。

**Tech Stack:** 现有Python3.12、NumPy、pytest、Sobol6、Matern52GP及Chat/Responses监督传输；无新依赖或锁版本修改。

**Spec:** [已确认的LGBO简化设计](../specs/2026-10-22-lgbo-region-simplification-design.md)，提交18de79ebf981f63f2713b468198ad743cca26a05。用户回复“同意 继续测试”确认该设计；本详细计划新提交，实施批准仍待审阅。

## Global Constraints

- 复用工作树C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para和分支codex/electrothermal-mo-20261016；计划前HEAD为18de79ebf981f63f2713b468198ad743cca26a05。
- 六参数4E+2T、DFN+lumped、配置化fit_rates、真实双RMSE、固定目标尺度/HV、ParEGO、ARD Matérn、Gaussian EI及WarmStart/Pareto-Max–Min规则不改。旧3C仍排除；不新增目标、GP核或热模型。
- 公式固定为delta=c*K(X,A)*a/sqrt(a.T*K(A,A)*a)，mu_tilt=mu-delta；a为可行锚点的均匀权重；保留有符号协方差、原后验和方差。c∈[0,1]；32个Sobol锚点，退化方差容差1e-12。
- 新策略不使用目录、候选eligible筛选、fair gate、信任/退火/consistency乘子、置信度0.6门槛、正相关截断或区域内选点限制。有效候选仍满足已有物理域约束。
- 一个用户入口optimization.region_method="lgbo_v1"；缺省继续旧逻辑。新策略拒绝非空optimization.region、显式region_advice/region_selection/region_evidence/region_proposal及llm.region_wire_format，避免旧控制项被静默忽略。空region={}可兼容，但新模板省略。
- 单线程；本计划真实API/DFN/实测/服务器预算0。当前用户测试请求允许先运行既有代码的软件基线；新产品实现须等待本计划批准。免费API不代表DFN求解预算或不限次数授权。
- 不修改主工程、参考工程、密钥、历史实验、旧封存及旧计划账本；使用显式文件清单，不执行git add .或清理实验产物。
- 执行方式建议沿用本会话原生逐任务执行；不新增探索子代理。先完成新基线，再RED→最小实现→GREEN→相关回归，最后全量和交付审计。

## Review Focus

1. confidence=0、很小的合法confidence、负协方差及区域外赢家：Task1/3证明没有旧阈值、非负截断或inside-box限制。
2. 合法区域内所有锚点物理不可行或区域方差退化：Task1/3要求诚实Plain回退、归档全部采样及原因，不扩大矩形或制造新观测。
3. 第13轮仍有Region请求，以及没有新增完整观测后的下一权重：Task3验证不继承active_until和旧后验。
4. 同六维旧回复、传输修改payload、布尔/NaN/未完成JSON及篡改权重/尺度：Task2/3检查严格绑定、类型边界、回退与独立原始HTTP审计。
5. 倾斜后仍选Plain或错误建议使真实目标变差：Task3明确区分公式执行、选择变化和真实改善，全部保留，不用采纳率代替增益。

---

## Task 0: 当前源码基线和保护

**Files:** 不改产品；新证据目录D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-region-20261022/；新账本.superpowers/sdd/2026-10-22-lgbo-region-simplification-plan/progress.md。

**Interfaces:** 只读导入既有sub2api-responses-20261021/protect_workspace.py的capture()、manage.py的受控pytest以及baseline.BoundaryGuard。新run_tests.py只覆盖本计划PLAN/LEDGER，不调用旧runner的setup或写旧账本。

- [x] 重新检查Git、已有设计及实际模块；新建authorization.json、workspace-before.json和本计划测试适配器。设计所提electrothermal_region_requests.py实际不存在：请求构造位于electrothermal_llm.py，监督控制位于electrothermal_requests.py；后续以这些实际文件为准。
- [x] 按用户“继续测试”启动当前源码的完整tests基线，清空PYTEST_ADDOPTS、单线程、真实网络/电池求解守卫、独立短basetemp；运行中不改产品文件。
- [ ] 等待真正结束，保存实际数量/通过/失败/错误/跳过/退出码、invocation、pytest.log、junit.xml和边界计数；失败分类后处理。历史852项不作为本轮结果。
- [ ] 取得本计划实施批准后再进入Task1。仅有设计确认和基线运行不自动跳过该审批节点。

## Task 1: 独立LGBO数学与区域应用

**Files:** Create src/llmbo_para/electrothermal_lgbo.py；Create tests/test_electrothermal_lgbo.py。

**Interfaces:**

- lgbo_mean_tilt(*, mean, std, cov_xa, cov_aa, confidence) -> dict：校验对齐形状和有限数，内部构造均匀a，返回region_variance、lambda、anchor_weights、signed_delta和adjusted_mean；退化/非法输入抛ValueError。c=0返回精确零调整，不因无关数值除法失败。
- validate_lgbo_region(response, *, expected_context_id, expected_signatures) -> dict：校验规范envelope精确字段schema_version/parameter_profile/fit_rates/signatures/context_id/region_method/region；核验当前身份后返回区域。字段类型、几何及confidence规则与Task2 wire一致，Task2恢复envelope后复用该函数，无循环依赖。
- apply_lgbo_region(gp, context, pool, response, *, space, request_outcome=None) -> dict：消费本轮GP及上述规范envelope，返回原mean/std/plain_ei、signed_delta、adjusted_mean、effective_ei、plain_index/selected_index、action_valid/tilt_applied/selection_changed、fallback_reason、原response及采样/方差证据；accepted仅作为selection_changed的兼容别名。action_valid表示严格合法的region或none，不能当作执行了倾斜。不调用API或评价器；Task1用本地规范动作完成独立测试，Task2另验线上解码。
- 锚点用Sobol6(1+32*(context.ordinal-1)).draw(32)映射到矩形，按space.denormalize逐点过滤；c=0或none精确Plain。固定种子和过滤记录进入归档。

- [ ] 写RED：两候选均值[-.30,-.25]、std=[.4,.4]、一锚点cov_xa=[[.02],[.12]]、cov_aa=[[.16]]、c=.65，断言delta=[.0325,.195]、新均值[-.3325,-.445]；best=-.5时原EI选0、倾斜EI选1。该矩阵可嵌入正定联合协方差，不使用任意不一致的假协方差。
- [ ] 写RED：将首个cross covariance改为-.02，必须保留负delta；c=0逐项等于Plain；均匀多锚点的区域平均均值改变c*sqrt(v)，原协方差不变；delta绝对值不超过c*std（仅测试浮点容差）。
- [ ] 写RED：形状错误、布尔/非有限confidence、负std及非有限协方差拒绝；c>0时v<=1e-12拒绝，c=0不执行退化除法；无可行锚点回退并保存32点过滤结果；GP状态/训练标签/原后验不变。
- [ ] 用本计划run_tests.py记录Task1数学RED，确认失败来自尚未实现的模块/行为；最小实现后跑GREEN。不得套用旧非负raw_shift契约，不添加clip、jitter、trust或自定义强度乘子。
- [ ] 记录针对性测试证据并显式提交这两个文件；未完成的接口联测明确留给Task2/3。

## Task 2: 一个策略入口、直接矩形动作及请求绑定

**Files:** Create src/llmbo_para/electrothermal_lgbo_wire.py、src/llmbo_para/prompts/region_preference_lgbo_electrothermal.txt、tests/test_lgbo_region_wire.py；Modify electrothermal_config.py、electrothermal_llm.py、electrothermal_region_wire.py、electrothermal_requests.py（均位于src/llmbo_para/）。

**Interfaces:**

- lgbo_request_id(payload) -> str：内部规范payload本身不含request_id；对固定版本lgbo_action_v1和完整payload计算摘要，只排除artifact_task。覆盖契约、Prompt、签名、历史、上下文/权重/尺度和方法；wire在计算后添加request_id，因此无自引用。
- lgbo_wire_payload(payload) -> dict：发送精简任务内容及最小response_contract，外层仅要求request_id/region；region要求kind/lb/ub/confidence，none仅kind，不要求reason/coordinate_space/目录或证据ID。
- decode_lgbo_action(response, payload) -> dict：校验完整原生有限JSON、精确字段集合和请求ID，恢复schema_version/parameter_profile/fit_rates/signatures/context_id/region_method/region；区域几何不裁剪，旧envelope不当作新wire接受。
- 复用Task1的validate_lgbo_region(response, *, expected_context_id, expected_signatures)；仅接受长度6且0<=lb<ub<=1的有限实数数组和非布尔confidence，不新增第二套几何准入逻辑。
- 保持现有build_electrothermal_payload、region_wire_payload、decode_region_wire及controller.request/request_region签名；仅新方法分派。WarmStart完全使用原分支。

- [ ] 写RED：新方法配置可用且签名变化；未知/非字符串方法、与Global Constraints列出的旧控制项冲突均拒绝；旧配置/旧wire/WarmStart字节保持。
- [ ] 写RED：矩形/none可解码；缺字段、额外reason/ID、布尔/字符串/NaN/inf坐标或confidence、错误维数/边界及过期签名拒绝。confidence=.1合法、confidence=0合法，不偷偷提高confidence。
- [ ] 写RED：改Prompt、历史、物理参数定义、fit_rates、权重、尺度或当前方法后旧request_id失效；模型不重复抄完整签名仍不可跨任务/上下文重放；输入payload/response均不被修改。
- [ ] 运行Task2 RED，再最小实现：新策略构造200–300词英文Prompt，沿用已有top4/双目标极值/recent3的真实历史选取和dynamic_record_summary，包含当前权重/尺度/理想点、Pareto与工况；不构造catalog/candidate_advice/decision_evidence或旧门槛要求。
- [ ] controller对新策略冻结规范payload并传入独立副本，检测传输修改；保存正式回复证据。受监督Chat/Responses仍经过原worker及统一wire分派；generic注入仅作mock时返回同一最小wire动作并经解码，不绕过绑定。原始HTTP是native路径的审计依据，不能只保存规范动作。
- [ ] 新策略request_region不检查eligible名单；预算和禁用/缺密钥逻辑沿用。request_controls的超时/tokens上限、Responses字段和传输方式不改，仅诊断wire标记按新方法记录为lgbo_action_v1。
- [ ] 跑Task1/2 GREEN及旧Region/Responses/WarmStart相关测试，保留实际RED/GREEN证据，显式提交本任务文件。

## Task 3: MO接入、独立审计和软件闭环

**Files:** Modify src/llmbo_para/mo_optimizer.py、electrothermal_audit.py；Create src/llmbo_para/electrothermal_lgbo_audit.py、tests/test_lgbo_region_workflow.py、tests/test_lgbo_region_audit.py、configs/electrothermal-sub2api-lgbo-software-template.json。

**Interfaces:**

- MOOptimizer.step()按region_method分派新策略：每轮请求，调用apply_lgbo_region，全池EI选点；新策略不解析InformedSettings或更新trust。没有新方法字段的旧路径逐项保持。
- MOOptimizer.summary()为新策略分别统计valid_actions、tilt_applied及selection_changed；既有accepted计数保持“改变选点”的含义，不统计为真实增益。旧策略summary字段语义不变。
- audit_lgbo_round(root, *, event, context, gp, history, prepared, cost_events) -> dict：返回expected_region、selected_index及request_ordinals；由现有audit_electrothermal_run的共同历史重建循环消费，维持历史追加和成本核验顺序。
- audit_lgbo_round按归档Prompt、原始HTTP/注入wire和冻结历史重建请求与动作，按公式独立计算均值/有符号调整/EI。不能仅调用产品函数后比较其自身保存值，也不把选点变化统计成真实改善。

- [ ] 写RED：原始正定样例在生产选点路径改变索引；区域外候选可赢；低confidence不被旧阈值拒绝；第13轮仍请求；无新完整目标的失败轮后，权重/标签/标准化/incumbent/局部中心/GP重建且倾斜不累计。
- [ ] 写RED：ParEGO、WarmStart-only、LGBO Full共用同一份严格核验的有效初始化；相同输入不重复训练、相同Y不同参数可训练；V→mV并同步尺度后决策不变；缓存、失败、筛选和新求解成本保持原区分。
- [ ] 写RED：HTTP边界替换的真实生产Chat/Responses worker分别完成region/none/incomplete/非JSON/错误binding，深审计通过有效运行并诚实重放失败；单次请求次数可核对，真实网络/DFN均为0。
- [ ] 写RED：独立篡改温度曲线、动态摘要、区域边界、权重/尺度、c、lambda/delta、原方差、Prompt或原始回复，审计拒绝；旧电压与旧电热审计回归不变。
- [ ] 运行Task3 RED，最小接入及审计后跑GREEN；新模板从既有软件模板复制物理/数据定义，仅移除旧策略项并启用lgbo_v1，保留parego、llm.enabled=false和API/DFN预算0。
- [ ] 运行明确标记的软件合成闭环，记录双RMSE、Pareto/HV和Region各层诊断；不得写成真实DFN或实测增益。评估错误建议可能有负作用，不据结果挑选种子。
- [ ] 记录相关回归和深审计，显式提交本任务文件。

## Task 4: 完整回归及交付

**Files:** Modify docs/Method.md、docs/llm-informed.md；Create docs/audits/lgbo-region-simplification-2026-10-22.md。仅在批准实施后追加明确的新策略章节，旧文与旧档案来源保持。

**Interfaces:** 用Task0的同一受控runner运行当前tests全量；对新策略档案运行CLI audit-run/deep，输出本轮结果索引与保护差异。

- [ ] 跑完整tests新回归，记录实际tests/pass/fail/error/skip/退出码、日志/JUnit、网络和电池边界计数。只因代码新修改、失败或未解决风险才重复全量。
- [ ] 核查主工程保护快照、旧数值骨干/旧Region函数/旧Prompt、锁文件和旧封存未改；新source/算法签名不能自动给旧初始化重新签名。重要问题修复后重跑对应验证。
- [ ] 保存显式变更清单、各任务commit、RED/GREEN/最终回归、审计及已完成/未验证事项；审阅整段diff并提交文档。
- [ ] 交付可检查的新模板和入口。真实API契约验证、真实DFN共享初始化配对及实测辨识都另列协议；本计划不消耗旧已关闭额度，不自动开始真实优化。

## Self-review / Handoff

数学、精简动作、单一策略、旧版本隔离、全池选点、失败轮上下文和原始回复审计均有具体归属；所有新增函数由上述Interfaces定义。Task0先完成已有代码基线；本计划批准后按Task1→2→3→4在当前会话执行。

本计划不重新讨论已确认的算法，也不添加新的策略组合或性能承诺。当前产品修改尚未开始；Task0只有“已启动”，其最终计数必须以实际JUnit为准。
