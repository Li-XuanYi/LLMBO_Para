# Region Action-Only Reply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让新版 Region 只要求动作 JSON，消除解释文字的长度对动作准入的影响，保持原数值方法和旧归档语义。

**Architecture:** 在现有 region_wire_format 增加 compact_action_v2；传输边界负责无解释回复与内部规范 envelope 的映射。复用现有目录解析、控制器、Lift 与守卫，审计按显式版本重建实际线上请求和回复。

**Tech Stack:** 现有 Python 3.12、NumPy、pytest、Chat/Responses 受监督传输；无新依赖或锁版本变更。

**Spec:** [Region 仅动作回复设计](../specs/2026-10-22-region-action-reply-design.md)。

## Global Constraints

- 工作树 C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para，分支 codex/electrothermal-mo-20261016；计划前 HEAD 09d139d8775af44f4249966117c74cdf14ebd8e5，源码指纹 a98cc1890ea99d4fca5b4b9a9cd53be7b6f97cac16128ac502bd35c7349bcc90。
- 用户已确定不需要解释文字；依用户原“实施计划提交审阅后暂停，批准后修改产品代码”流程，本轮只交付设计与详细计划，不自行开始产品修改。
- 新增真实 API/DFN/BO/服务器预算均为 0；密钥只读环境，不进入测试、配置、命令参数或档案。单线程，保留主工作区与全部旧记录，不使用 git add .。
- compact_action_v2 只允许 catalog_v1；保留 full_v1、compact_v1、旧 Prompt、旧模板和旧解析分支。WarmStart 的接口与双目标/Pareto/Max–Min 选择规则不变。
- 无 reason 是正常回复；若仍附带 reason，仅作为原始记录中的兼容元数据。动作错误、旧身份、非 JSON、未完成回复均不得修复成有效 Region。
- 数值 GP/Lift/EI/方差/信任/尺度/HV/物性/工况均不修改。新模式完整进入签名与绑定，不解禁旧缓存或重标旧失败。
- 审批后先运行并封存当前完整软件基线，再写 RED 测试、最小实现和 GREEN，最后新全量回归；此前 884 项包含仓库和启动器附加测试，是历史结果，不是本计划测试数。

## Review Focus

1. 模型仍附带 417 字符或非字符串 reason：只忽略这一兼容元数据，不能使未知动作字段也被忽略。Task 1 覆盖 reason=缺失/短文/417字符/长文/null/对象及额外 lb 字段。
2. mode 或权重改变而 request_id 看似相同：新绑定和 proposal_binding 必须共同拒绝重放。Task 1 覆盖旧 wire、新 wire、权重和尺度篡改。
3. 审计仍硬编码旧 catalog Prompt：运行看似成功但深审计失败，或错误接受旧 Prompt。Task 2 覆盖归档 Prompt 独立选择及修改检测。
4. 接口同维且缺省旧配置：不能默默启用新模式或改变 WarmStart。Task 1/2 比较旧 wire 请求字节、WarmStart 请求和签名。
5. 传输返回 JSON 并不等于动作或增益有效：Task 2 覆盖 incomplete、非 JSON、错误 ID、低置信度和 plain 回退；保留独立真实验证边界。

---

## Task 0: 封存与完整软件基线

**Files:** 不改产品；在 bo-repair-work/20261017_et_implementation/region-action-reply-20261022/ 新建本计划专用进度、测试与保护证据。

**Interfaces:** 使用现有 protect_workspace.capture()、manage.py 的受控 pytest 和 baseline.BoundaryGuard；只复用其逻辑，不改旧 runner、旧账本或旧封存文件。

- [ ] 记录 HEAD、status、显式文件清单、主工程保护快照和旧 Prompt/数值模块哈希。为本计划创建专用 ledger；Windows 原生受控测试入口将 PLAN/LEDGER 指向新位置，不写旧计划进度。
- [ ] 运行 pytest 的完整仓库 tests，使用新的短 basetemp、清除 PYTEST_ADDOPTS、单线程和网络/电池求解守卫。旧冻结启动器的附加测试如单独运行，必须另列数量，不合并冒充本次仓库回归。
- [ ] 保存 invocation、pytest.log、junit.xml、exit-code.txt、result.json、边界计数及资源/结束状态。按实际数量报告，基线失败先分类，不能掩盖或直接进入实现。

## Task 1: 新版无解释动作传输与宿主映射

**Files:**

- Modify: src/llmbo_para/electrothermal_region_wire.py
- Modify: src/llmbo_para/electrothermal_requests.py
- Modify: src/llmbo_para/electrothermal_config.py
- Modify: src/llmbo_para/electrothermal_llm.py（只改 Prompt 选择和 wire marker，不改数值函数）
- Create: src/llmbo_para/prompts/region_preference_action_electrothermal.txt
- Create: tests/test_region_action_wire.py

**Interfaces:** 保持 region_wire_format(config)、region_wire_payload(payload)、decode_region_wire(response,payload)、build_electrothermal_payload(task,*,prepared,history,context=None) 的签名不变。新增枚举 compact_action_v2，绑定版本 region_compact_action_v2；规范输出继续使用现有 catalog envelope，reason 固定为 structured_catalog_response。

- [ ] 写失败测试：new mode 的 kind=none/region 不带 reason 可解码并通过现有目录解析；旧 compact_v1 的缺 reason 与 417 字符 reason 仍按旧逻辑拒绝。
- [ ] 写失败测试：新 wire 中 reason 不在 required，仅为兼容可选 {} 属性；省略或添加各种 JSON 原生 reason 值产生相同 canonical 动作及 resolution，原输入对象不变。未知动作字段、旧 lb/ub、缺少置信度/绑定/证据或错误目录 ID 仍拒绝；region=null/列表/布尔、confidence=布尔/NaN/字符串和错误证据类型不能被元数据兼容逻辑掩盖。
- [ ] 写失败测试：配置拒绝 new mode+bounds_v1 及非法类型；新 mode 不改变 WarmStart wire；旧 full_v1/compact_v1 请求字节保持；跨模式、权重/尺度/Prompt/历史篡改回复拒绝。
- [ ] 运行受控 RED：tests/test_region_action_wire.py；预期因新枚举/行为尚未实现而失败，记录各测试的实际失败原因。
- [ ] 最小实现：扩展现有 FORMATS/_compact/_binding；new mode 线上合同移除 reason 的 required 和硬类型/长度条件，仅兼容保留 {} 属性。解码验证外层绑定后，复制 region 并只去掉该元数据，添加固定代码标记，其余动作字段原样交给 resolve_catalog_region 严格校验。
- [ ] 任务控制的 wire 格式 allowlist 接纳 new mode；配置显式限制为现有 catalog 组合。payload 对 new mode 选择独立 200–300 词英文 Prompt，明确仅输出动作 JSON、不要求解释，固定身份与物理任务语义不变。新 marker 在 proposal_binding 构造之前写入。
- [ ] 运行 Task 1 GREEN 及旧 Region/WarmStart/Responses 相关测试，封存实际数量、退出码、JUnit 和网络/DFN 为 0 的证据。审阅 diff，显式提交本任务文件。

## Task 2: 深审计、零预算模板和数值不变性验证

**Files:**

- Modify: src/llmbo_para/electrothermal_audit.py
- Create: configs/electrothermal-sub2api-action-software-template.json
- Create: tests/test_region_action_audit.py
- Modify: docs/llm-informed.md（追加新模式，不改旧章节）
- Create: docs/audits/region-action-reply-2026-10-22.md

**Interfaces:** 消费 Task 1 的三个现有 wire 函数和新 marker；audit_electrothermal_run(run_directory,*,deep=False) 签名不变。新模板从旧 Sub2API 禁用模板复制，除下述算法接口与请求设置外保持物理/数据/倍率定义一致。

- [ ] 写失败测试：真实生产 Chat 与 Responses worker 在离线 HTTP 边界分别接收无 reason 的 none/region，经过控制器、规范映射和归档后深审计通过；不以绕过 wire 的 mock 代替此项。
- [ ] 写失败测试：两轮纯软件运行的新模式与同一规范动作控制组具有相同选点、原标签/后验方差/Lift/EI/信任；ParEGO、WarmStart-only、Full 软件路线兼容且 API/DFN 为 0。
- [ ] 写失败测试：修改 mode、归档 Prompt、实际 HTTP 绑定/ID/证据、目录、权重、尺度或 canonical 回复任一项，深审计拒绝；只有附带 reason 改变且动作相同时不改变规范动作。旧模式审计仍维持原拒绝条件。
- [ ] 写失败测试：新模板通过配置校验；llm.enabled=false、优化模式 parego、API/DFN 预算 0；global 与 Region max_tokens=8192、timeout_s=120，WarmStart task max_tokens=4096、timeout_s=120；不引入 thinking provider 扩展。
- [ ] 运行受控 RED：tests/test_region_action_audit.py；记录未实现审计/模板的失败。
- [ ] 最小实现：审计的归档 Prompt 选择和目录 expected.instructions 重建按 wire marker 区分新旧，继续调用真实原始回复 decoder，不能只信已保存 canonical。保留 catalog_response_v1/catalog_resolution_v1 的现有宿主几何语义，由绑定的配置/payload 标识新 wire。
- [ ] 新模板设置 region_advice=candidate_aware_v1、region_selection=fair_region_v1、region_evidence=dynamic_decision_v3、region_proposal=catalog_v1、region_wire_format=compact_action_v2；其余物理/数据/参数定义与旧模板相同。文档明确解释文字已不要求，内部固定 reason 仅为接口标记。
- [ ] 运行 Task 2 GREEN、全部 Region/Responses/WarmStart 相关测试，以及新的完整仓库 tests 回归。保存实际计数/失败/错误/退出码和日志/JUnit，不能用历史 884 代替。旧冻结启动器仍绑定旧源码，应继续拒绝当前新指纹；不得为运行历史附加测试而改写其协议或把其拒绝错误归为需要放宽的兼容问题。
- [ ] 再核查主工程、数值函数 AST、旧 Prompt 字节、旧封存和密钥缺失；对新配置/算法签名、初始化兼容签名在同一源码下的关系进行测试，旧 source 初始化不能自动换签复用。
- [ ] 完成一次整体代码审阅，修复重要问题后再按需重跑相关与全量测试；保留全部负结果。显式提交 Task 2 文件与交付审计，不启动真实 API、DFN、BO 或服务器任务。

## Self-review / 验收状态

计划覆盖去掉解释要求、仅兼容忽略该元数据、版本隔离、传输监督、审计重建、旧流程、数值不变性和零预算模板。Task 2 消费 Task 1 的同名函数与 marker，没有新 GP/公式或大范围输入压缩。真实 API、DFN 和 RMSE/HV 增益不属于本计划授权，后续各自另定协议。

当前仅设计与计划完成，所有执行复选框为空。按用户原先要求，提交本计划审阅后暂停，批准后再执行 Task 0。
