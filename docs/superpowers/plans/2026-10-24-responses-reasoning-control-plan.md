# Responses Reasoning Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐显式内部推理控制，用有限诊断验证完整Region能否返回，不把假说写成已修复的外部根因。

**Architecture:** schema2 Responses新增一个可选全局控制，贯穿serializer/controller/owned worker/审计；独立API-only入口只执行固定5步，无BO或通用调度框架。旧请求缺省字节/语义保持，LGBO数值与全部历史信息不动。

**Tech Stack:** 现有Python3.12、urllib、pytest、NumPy和锁定依赖；不增SDK/依赖。

**Spec:** [待审短设计](../specs/2026-10-24-responses-reasoning-control-design.md)，[本轮调查](../../audits/region-timeout-root-cause-2026-10-24.md)。

## Global Constraints

- 状态待审；源起点83c173b，原独立工作树/分支，主工程、参考、旧封存记录只读，显式git文件清单。
- 命令中的`PY`为`D:/Users/aa133/Desktop/LLMBO_Para/.venv-pybamm312/Scripts/python.exe`；`E`为`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-timeout-root-cause-20261024`。PowerShell调用用`&`和完整引号路径；软件守卫脚本先按Task0创建，label保持ge-前缀。
- 唯一新行为 `llm.reasoning_effort`，全局、Responses/schema2限定，枚举none/low/high/max；缺失不回填，Chat/schema1/task_options拒绝。现有thinking禁令不变。
- 不改Prompt/历史摘要/Region/GP/EI/热模型/目标/倍率/缓存校验；不加SSE、重试、模型或端点切换。签名自然覆盖新配置，旧初始化不得改签。
- 原生实现；先新基线、TDD、针对性、一次fresh-context最终审阅及一次修复，再新的完整回归。软件阶段API/DFN0。
- 候选真实额度独立5API/0DFN/0BO/720秒，8192tokens/次、单线程、无重试；没有新批准前为0。旧窗口不恢复。
- 保留工作树及正负记录，不merge/push/clean，不修改旧runner/worker或旧delivery seal绑定的文件。

## Review Focus

1. 配置缺失/显式null/注入客户端暗带none：仅实际配置可控制请求，旧body不变；Task1负例。
2. Responses新参数误入Chat、schema1或task_options：配置和构造边界拒绝，不静默忽略；Task1矩阵。
3. 原样none被网关忽略、reasoning usage缺失/非零：记录请求值和观测计量，unknown不补0，不冒称thinking已关闭；Task2测试。
4. 改/删effort或只改outcome而原body不变：独立审计发现，旧归档兼容；Task2篡改测试。
5. 对照超时被当作自动重试、旧预算重启或首个完整none失败仍继续：固定请求序列及一次总账，失败关闭且DFN永远0；Task3协议测试。

## Task 0: 基线与保护

**Files:** 新计划自己的`.superpowers/sdd/2026-10-24-responses-reasoning-control-plan/progress.md`和证据根下`run_tests.py`；只读复用现有guard/保护/保持唤醒方法，不调用旧runner的旧ROOT主入口。

- [ ] 记录批准、HEAD/status、主124/参考55保护、旧seal、源码及入口哈希；保存新基线manifest。
- [ ] `PY E/run_tests.py test ge-re-baseline tests`，完整JUnit/日志/退出码；历史1336不算本轮。预期全绿，任何失败先分类和保留，不改产品截止绕过。

## Task 1: 精确的控制配置与传输

**Files:** 修改`electrothermal_config.py`、`electrothermal_requests.py`、`electrothermal_responses.py`、`electrothermal_llm.py`（均在`src/llmbo_para/`）；新建`tests/test_responses_reasoning_control.py`。

**Interfaces:**
- `request_controls(config,task)`可返回同一可选`reasoning_effort`，没有任务级effort覆盖。
- `responses_request_body(payload,*,model,max_tokens,json_mode,reasoning_effort=None)`；新增显式值时只添加`reasoning={'effort':value}`。
- `ResponsesTransport.__init__`、`BoundedResponsesTransport.__init__`新增可选keyword`reasoning_effort=None`并保存；Chat构造接口不变。
- owned spec只在Responses且配置存在时增加新键；base/supervision/outcome仅记录已配置的固定枚举。controller克隆以配置为准，未配置时不得继承注入客户端的effort。

- [ ] RED：四枚举原样映射；缺省body与旧golden逐字段/编码相同；null/bool/别名/Chat/schema1/task_options/与thinking混用拒绝；disabled仍做配置校验而不读key/请求。
- [ ] 运行`PY E/run_tests.py test ge-re-controls-red tests/test_responses_reasoning_control.py`，预期新接口/配置负例失败，保存实际计数。
- [ ] 最小实现上述接口；不改序列化精度、input、instructions、timeout/token、stream/store或default。
- [ ] GREEN：新测试＋`tests/test_electrothermal_responses.py`、`tests/test_electrothermal_responses_requests.py`、`tests/test_http_diagnostics.py`；真实socket/DFN守卫0。原生spawn的memory opener必须看见reasoning字段，不只测构造器。
- [ ] controller typed注入、克隆、两任务、失败/硬截止与无凭据/禁用/0预算通路均断言字段和请求次数；提交显式文件。

## Task 2: 审计、版本与兼容

**Files:** 修改`src/llmbo_para/electrothermal_audit.py`、`electrothermal_lgbo_audit.py`；新增`tests/test_responses_reasoning_audit.py`；实施后追加`docs/llm-informed.md`的可选字段说明。

**Interfaces:** 所有Responses审计重建点都传入同一`controls.get('reasoning_effort')`，包含WarmStart、旧bounds/catalog和LGBO分支；控制存在性和值与配置/body/supervision/outcome一致。

- [ ] RED：合法none/省略新运行独立深审计；raw body删改/添加、outcome或supervision单边/全删、配置签名篡改均失败。旧记录缺失字段继续通过。
- [ ] RED：原始usage无reasoning计量时保持unknown；有0/正数分别如实保留，不以缺失为失败、不伪造关闭证明。真实reply原方差/标签/EI不变。
- [ ] 最小实现；验证新字段改变config/algorithm签名；旧初始化/缓存不改签、不放宽兼容。没有必要改`electrothermal_provenance.py`公式。
- [ ] GREEN：新审计＋原Responses/LGBO/旧电压回归，另做旧封存档只读兼容核验，记录GP审计拟合成本而不是伪报0；提交。

## Task 3: API-only诊断入口与软件验收

**Files:** 新增`scripts/run_responses_reasoning_diagnostic.py`、`tests/test_responses_reasoning_diagnostic.py`；不编辑已封存的两个旧gain脚本或`run_region_transport_validation.py`。

**Interfaces:** `run_diagnostic(protocol,evidence_root,*,execute=False)->dict`默认dry且不读key；`reasoning_diagnostic_worker(spec,connection)`使用实际BoundedResponsesTransport。只读复用现有owned监督/凭据/冻结GP重放函数，不新增优化器、策略注册或通用工作流。

- [ ] RED：未批准/无软件release/无key/0额度/dry均无实际调用；固定cap5API/DFN0、720秒绝对截止、按请求开始前记账、单一hash账本；超时/进程崩溃/晚到/漂移关门并确认owned树停止。
- [ ] RED：固定P0最小none60s→P1上下文0 none120s→P2同上下文0省略120s→P3上下文1 none120s→P4上下文2 none120s；P1失败即停。P2除完整合法答复外，仅已开始的该请求触发120s单次`deadline_exceeded`、总钟仍有效、源码/输入未漂移、owned树已停止时可继续；总截止、普通网络timeout、worker崩溃及其他失败一律停止。任何401/403/404/429/5xx即停，不重试。总钟预留30秒清理，单次执行deadline不得晚于总deadline-30。
- [ ] RED：P1/P2除reasoning外实际body完全相等；三条none使用不同原历史context_id，禁止重签/新增目标。独立`responses_reasoning_probe_v1`元数据绑定新transport controls/实际源码/批准；原payload/signatures只标原上下文。3完整合法＋至少1非零tilt才标transport_ready；effort none与动作kind none区分，usage缺失仍unknown，0计量也不证明网关内部实现。
- [ ] 最小实现，软件fake executor完整序列＋实际spawn/memory opener，全部实际API/DFN0。A/B时序差异只描述，不写统计因果证明。
- [ ] 一次fresh-context整分支审阅；Important一次TDD修复；最终`PY E/run_tests.py test ge-re-final-full tests`及完整受测runtime观察绑定，实际全绿才封存软件release。保存所有RED、GREEN与完整JUnit，提交。

## Task 4: 获批后的真实诊断与交付

**Independent proposed budget:** 最多5API／0DFN／0BO／720秒；每次8192输出许可，最大输出许可40960，实际未知保持unknown。P0/P1失败不自动恢复；P2省略对照的单次预注册超时不算重试；其余顺序严格遵照Task3。

- [ ] 单独的批准和软件release均匹配后，冻结源码、三个历史payload/GP、端点、模型、计划及入口；专用env读取key后、首次真实请求前启动唯一计时，owned子树跟随总截止。
- [ ] 固定sidrune/deepseek-v4-pro和原代理；记录request_id、body SHA、requested effort、完成/绑定/tilt/耗时、原始usage；不主动索取、打印、额外提取/另存或解释推理文本，原始HTTP回复沿用既有归档/脱敏规则，仅分析usage数值。字段不支持就停止，不自动none→low或退回省略。
- [ ] 结果分为字段发送/兼容、实际完整回复、实际tilt、因果假说强弱四层；无DFN、RMSE/HV和实测结论，不自动恢复旧BO。
- [ ] 输出实际测试数/退出码/日志/JUnit、请求次数/退出码、旧保护、Git及seal；全部负结果保留，工作树保留。若仍超时，报告尚不知的组件，另审阅阶段计时/SSE；不能再盲加修复。

## 自审与交付边界

全局单一可选字段避免任务级优先级复杂化；控制沿serializer→clone→spawn→body→supervision→outcome→audit完整贯通。五类Review Focus均有失败测试；所有旧body/签名缺省规则保持。当前仅调查、候选设计与实施计划，软件/API预算均未因本计划自动获得批准。审批后沿用原生执行，不另问执行模式。
