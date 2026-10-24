# Region Transport Repair and Gated Gain Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复无法定位 API 故障的诊断缺陷，按证据解决传输问题，确认真实 Region 正常返回并参与采集，然后重新测量 RMSE/HV。

**Architecture:** 保留 urllib 和既有 owned-worker、Responses、LGBO v2 的边界，只增加安全机器诊断。独立研究启动器按同一持久预算先完成真实完整回复/冻结 GP 验收，再释放共享初始化的 Plain/Full 配对验证；失败即停止，不把回退闭环当成有效 Region 增益。

**Tech Stack:** 锁定 Python 3.12、标准库 urllib/ssl/socket/multiprocessing、现有 NumPy、pytest、PyBaMM 25.10.2；不升级或增加依赖。

**Spec:** [本轮调查与修复约定](../../audits/api-transport-investigation-2026-10-24.md)，沿用 [Responses 设计](../specs/2026-10-21-sub2api-responses-transport-design.md)、[LGBO 方法](../specs/2026-10-22-lgbo-region-simplification-design.md)、[工程边界](../specs/2026-10-23-lgbo-engineering-prompt-region-design.md)。不重新设计科研算法。

## Global Constraints

- 当前起点 `17cabc2`，工作树 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`、分支 `codex/electrothermal-mo-20261016`。主工程、原方法参考、旧实验、Codex 全局配置只读；显式文件清单提交。
- **状态：待用户批准。** 本计划不复用已结束的旧额度/时限；当前真实 API/DFN 均为 0。本轮既有网络握手没有 API HTTP 请求或凭据。
- 原生执行流程已经由用户选定，沿用，不另选执行模式；按新基线 → RED → 最小实现 → GREEN → 全量 → 证据推进。
- 端点固定 `https://sidrune.ai/v1/responses`，模型 `deepseek-v4-pro`，凭据仅来自本机专用 `SUB2API_API_KEY`；不打印、入参传递或归档实际值。
- `stream=false/store=false`；不增加未经验证的 thinking/reasoning 扩展，不调用模型发现、不更换协议或模型、不关闭证书验证、不修改系统代理或默认绕过代理。
- 现有 LGBO v2 Prompt、矩形动作、32 锚点、直接 confidence、后验协方差 tilt、原方差、真实标签、GP/EI、ParEGO 和物理参数映射不变；不恢复复杂守卫或信任机制。
- 默认无传输重试。仅 Task3 明确的一次受控冻结请求重放可覆盖此约定；不得在 BO 每轮隐藏重试。
- 单线程；无实测、旧 3C、服务器任务、额外观测生成；保持旧 schema1 和旧缓存/回复的严格签名。

## Review Focus

1. 异常字符串含凭据、代理认证或 provider 任意内容：只保留固定枚举、可信类型和有限编号；Task1 注入 canary 验证全部归档及进程结果。
2. 内层原因为字符串、循环异常链或未知类型：有界解包并标记 unknown，不猜原因；Task1 失败矩阵。
3. 子进程硬超时没有抛回 Python 异常：仍报告截止和已知进度，不伪造 DNS/代理分类；Task1/2 硬截止测试。
4. 小探针成功但正式回复、绑定或 tilt 失败：不释放 DFN 阶段；Task2/3 完整门槛测试。
5. API 先通过后持续失败，全部回退仍有完整 RMSE/HV：区分数值闭环与有效 Region，连续失败终止，不能宣称增益；Task2/4 协议测试。

## Task 0: 新基线、保护与证据目录

**Files:** 新建本计划 `.superpowers/sdd/2026-10-24-region-transport-repair-validation-plan/progress.md`；本轮外部 evidence 下新建守卫入口，不修改旧 runner/ledger。

- [ ] 记录批准、Git/status/diff、主工程124项及参考55项保护清单、产品源指纹、旧 seal 和科学配置哈希。
- [ ] 在原守卫的只读复用方式下运行新全量基线，网络与电池 solve 拦截，保留允许的两个非电池 fixture 成本；单线程。
- [ ] 保存真实计数、退出码、日志、JUnit；失败先分类，未完成不能称通过。此前1205项不当成本轮基线。

## Task 1: 安全的底层网络错误机器诊断

**Files:** 新建 `src/llmbo_para/http_diagnostics.py`、`tests/test_http_diagnostics.py`；修改 `src/llmbo_para/llm.py`、`src/llmbo_para/electrothermal_requests.py`、`src/llmbo_para/electrothermal_llm.py`；扩展 `tests/test_region_transport_repairs.py`、`tests/test_electrothermal_responses_requests.py`。不改请求 body / Prompt。

**Interfaces:**
- `transport_error_fields(exc: BaseException) -> dict`：返回可选嵌套 `network_diagnostic`，字段限 `category/cause_type/os_errno/winerror/tls_verify_code`；无文本值来自 `str(exc)` 或 URL。
- `public_network_diagnostic(value: object) -> dict | None`：严格校验字段、固定 category 和 cause_type 枚举；编号只接受非 bool 的32位整数、证书码非负；非法输入不穿过公开边界。
- category 固定 `dns/connection_refused/connection_reset/connection_aborted/broken_pipe/timeout/tls_certificate/tls_eof/tls_other/remote_disconnected/other_os/unknown`；不推断故障发生在哪个远端服务。
- 解包最多4层 `URLError.reason`/显式 cause，身份去重；字符串 reason 只归 unknown，不保存。cause_type 为对应受支持标准库异常名，其他均 `other`。
- 底层 HTTP 先提取机器字段，`_public_diagnostic()` 保留合法字段；controller 将同份字段传入 outcome 和逐轮 request_outcome。现有错误类型和失败回退含义不改。

- [ ] RED：真实 worker 注入 DNS/拒绝/重置/SSL证书/TLS EOF/字符串 reason/循环 cause，断言正确且不同的安全分类。
- [ ] RED：message/provider body/未知字段含 canary，断言 HTTP错误档、event、child result、supervision、controller outcome 均无泄漏；缺失旧字段仍兼容。
- [ ] 最小实现上述函数及通路；不顺便重构网络客户端。
- [ ] GREEN：新用例、旧 Chat、Responses 和Region transport相关测试，保存实际结果。

## Task 2: 独立审计与受门槛控制的验证入口

**Files:** 修改 `src/llmbo_para/electrothermal_audit.py`，新建 `tests/test_network_diagnostic_audit.py`、`scripts/run_region_transport_validation.py`、`tests/test_region_transport_validation.py`。只在有新机器字段时增加检查；旧归档没有这些字段时继续原核验。

**Interfaces:**
- 新入口 `run_validation(protocol: dict, evidence_root: Path) -> dict`，默认 CLI dry-run；执行要求匹配批准及软件 release。总上限和截止由一个父进程持久 ledger 控制，任何失败请求/solve 在开始前记账，不逐阶段重置。
- `validate_region_effect(payload: dict, formal: dict, round_file: Path) -> dict`：恢复对应 `Matern52GP.from_state()` 和冻结上下文，调用原 `apply_lgbo_region()`；记录 action_valid/tilt_applied/max_abs_shift/selection_changed，并独立复算 EI。
- 既有历史 payload 只作为**明确标记的传输及方法重放上下文**；原 source/signatures/request_id 不重签，不当成当前新 BO 初始化或目标评价。恢复 GP 不搜索超参数，不新增目标值。
- 使用现有 Windows Job Object/父子记账模式及短路径；复用已验证的机制，不改已封存脚本副本。所有 owned 树验证停止、凭据无归档。

- [ ] RED：新机器字段单边篡改/删除、未知字段、错误 reason 类型必须被发现；旧失败记录继续可审计。字段是异常的机器证据，不声称能从归档重新访问历史网络。
- [ ] RED：dry/disabled/无凭据/未批准/0额度为0请求0solve；重复 charge、超时、根崩溃、晚到结果、源码/科学输入污染不释放下一阶段。
- [ ] RED：minimal成功但Region失败、合法none、零confidence、错误绑定、方差/标签改变均不得被算作有效tilt；至少3个完整真实上下文回复且至少1个真实非零tilt才能释放DFN。
- [ ] RED：正式Full连续3次请求失败时整个实验停止，不补轮、不跑剩余种子、不形成有效增益结论。合法none不算请求失败。
- [ ] 最小实现；软件mock完整门槛/后验/EI验证，相关回归；按既定原生流程做一次fresh-context整分支审阅，合并一次修复并以RED/GREEN验证，不启动无限复审。
- [ ] 新全量回归，保存实际 JUnit/退出码；冻结完整软件release、科学输入和入口后才启用真实请求。

## Task 3: 真实 API 定位与 Region 生效门槛

**Independent proposed budget:** 阶段最多6次真实API、0次DFN/BO；最多900s，且受全程10800s截止约束；每次最多8192输出tokens。批准后才启动。

- [ ] 固定历史实际DFN上下文：使用上次seed1709 Full的前三轮请求与对应冻结GP/候选池；封存原始哈希，不向LLM泄露生成真值。小探针不得代替该三上下文。
- [ ] 第1次为最小Responses JSON探针，上限60s；失败立即结束，保留新机器诊断。
- [ ] 第2次发送第一个完整冻结Region，上限60s；响应必须completed/严格JSON/正确绑定。
- [ ] 仅第2次超时，或被安全机器证据分类为暂时性连接故障时，允许同一冻结请求一次显式受控重放，上限120s。它计新API次数，记录恢复原因；不是BO自动重试。
- [ ] 成功后各发送另外两个固定上下文，上限120s；至少3个上下文完整通过且至少1次真实非零tilt，才能通过门槛。none合法但不足以证明生效；不改Prompt诱导强制region或抬confidence。
- [ ] 最多第6次只用于核验由诊断明确支持的**现有配置内**最小修复。可按同一请求60/120s证据冻结120s配置；不能以猜测实现新代理/协议/streaming/供应商扩展。固定三上下文未通过即停。
- [ ] DNS/系统代理/证书/provider外部故障若不能在既有边界内解决，停止并报告明确分类；新增产品传输设计须再提交具体变更审阅，不启动DFN凑指标。当前网络正常不等于已定位历史原因。

## Task 4: 门槛通过后的 RMSE/HV 真实 DFN 合成配对

**New candidate budget:** 同一当前修复版重新评价历史八点一次：8×2=16 solve；3种子×2臂×20新候选×2倍率=240 solve。合计最多**256 DFN**。不重新生成观测，不调用WarmStart API。

- [ ] 配置0.5C/1C各60s，复用已有合成观测和八组坐标；所有目标由当前真实源码重新评价，旧初始化不换签。两臂共享同一新有效八点计划。
- [ ] Plain/WarmStart-only和Full各20轮，种子1709/3253/5501，顺序交替：Plain→Full，Full→Plain，Plain→Full；无结果驱动换种子。
- [ ] 数值设置沿用上次：512全局/8局部候选，4次GP sweeps，半径0.2；目标尺度[0.1V,1K]、rho0.05、权重序列[[.8,.2],[.2,.8],[.5,.5]]、理想点0、HV参考点[10,10]。正式Region固定最多120s/8192tokens，无传输重试。
- [ ] 正式Full最多60次API。连续3次请求失败立即停止全试验；截断/非法绑定/无完整答复均为失败；合法none独立计数。任何不完整配对、source漂移或预算不足均标记inconclusive。
- [ ] 完整真实目标对才进GP/Pareto。失败、缓存、筛选、新求解成本分开，两个RMSE由归档曲线独立复算，固定HV空间独立复算；报告每种子和均值，不将20轮当独立重复。
- [ ] 每轮统计完整回复、合法region/none、非零tilt、改变选点、当轮HV变化；单独注明有效Region参与程度。有效动作/改变选点不等于改善。
- [ ] 仍按固定均衡标量选同一Pareto折中参数报告两个RMSE，并交付完整参数集。真实增益是待测结果，不预设必须为正、不删负结果、不自动无限修复或回退无关工程代码。

## 总批准上限与停止条件

|阶段|DFN最多|API最多|
|---|---:|---:|
|诊断、完整契约与冻结GP生效|0|6|
|重新评价8点|16|0|
|3种子×2臂×20轮|240|60|
|**独立合计**|**256**|**66**|

真实阶段只有一个**10800s（三小时）**绝对窗口，从首个实际API前启动，包含诊断、初始化、六组、审计及停止清理；诊断另受900s上限，不重置总钟。失败请求和仅发出但未收到响应的请求均保守计数。每次最多8192输出tokens，总输出许可上界540672；实际usage缺失为unknown，免费不等于无限调用许可。

本次批准若获得，允许上述一次受控重放；其余无重试。任何阶段失败只报告实际证据，不自动恢复旧窗口、花费未释放额度或替换端点。门槛不通过不消耗DFN额度；未经新批准不扩容。

## Task 5: 封存与交付

- [ ] 保存全部软件基线/RED/GREEN/全量结果、源码及旧记录保护、公共机器诊断、API原始正式回复、固定重放结果、真实配对原始曲线和有效Region参与统计。
- [ ] 将“传输恢复”“Region实际参与”“DFN合成增益”“实测有效”分别报告；本计划不包含实测层。优先给出逐种子的deltaHV和同参数两个RMSE，保留所有负结果。
- [ ] 提交显式源码/测试/报告清单，记录Git、入口、运行ID、退出码和seal；保留工作树，不合并、不推送、不清理旧记录。

## 自审

五类Review Focus均落到Task1/2失败测试；Task3作用门槛与Task4科学增益分开，旧签名不改、真实Y/方差不变。未知历史网络原因没有写成已解决。新产品模块仅一个纯机器诊断工具，其他为既有边界的小改动；不增加GP/LLM策略注册、热参数或新算法。软件审批和上述新真实预算均待用户确认，提交后暂停。
