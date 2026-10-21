# Sub2API Responses Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为既有电热 LLMBO-MO 增加显式、受预算监督、可独立审计的 Sub2API Responses 传输，保留原 Chat 行为。

**Architecture:** 独立模块负责 Responses 序列化/解析；既有 owned-worker 监督提供仅传输所需的可替换 worker；controller 按 schema v2 的 llm.transport 分派。审计按已冻结配置分别重建两个协议，不改 GP/Region 数学。

**Tech Stack:** 现有 Python 3.12、标准库 urllib/multiprocessing、pytest；无依赖或锁文件变化。

**Spec:** [Sub2API Responses design](../specs/2026-10-21-sub2api-responses-transport-design.md)。先以本规格和现有源码解决冲突，不能根据供应商名称假定协议可用。

## Global Constraints

- 独立工作树 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`；分支 `codex/electrothermal-mo-20261016`；计划前产品 HEAD `4a2baca273d5cc132340000f16da5ec7bba9ddcc`。
- 本具体计划已获用户批准软件实施；实施许可与真实 API/DFN 预算分离，新增付费请求和求解预算仍为0。
- 实现阶段真实 API 0、DFN 0；单线程；允许回归原有有限非电池 fixture，但单列计数。不调用 `/models`、Codex exec 或其他代理代替 HTTP 传输。
- 精确目标 `https://sidrune.ai/v1/responses`、`deepseek-v4-pro`、`SUB2API_API_KEY`；不携带旧站密钥，不自动回退旧站/Chat/其他模型。
- 固定客户端 store=false、stream=false、无工具、无续接和无重试；本地脱敏归档完整保留。thinking 扩展未确认，Responses 首版禁止设置，不能宣称推理已关闭。
- 不改 schema v1、物理/数据输入、GP/EI、Lift、守卫、信任、WarmStart 选择或目录/compact 绑定算法；不放宽缓存签名。
- MAIN、参考工程、旧实验和用户 Codex 全局配置不改；仅显式文件清单提交，不清理产物。
- 执行前新基线；逐任务先 RED、最小实现、GREEN；最终新全量和整分支独立审阅。每项真实数量/退出码/JUnit/源码 SHA 进入本计划 ledger。

## Review Focus

1. 顶层 status completed 但输出含 refusal/多个答案/工具/非正式 reasoning JSON：必须拒绝，不能启用兼容猜测；Task 1 的失败矩阵覆盖。
2. 新 provider endpoint 已配但 LLM disabled、额度 0 或 key 缺失：不能在 import、构造 factory 或模型发现时产生请求；Task 2 单独观测调用数。
3. spawn 子进程在请求前/等待 headers/读取 body 阶段卡住：按原硬截止清理自有子进程，记录真实开始与失败次数；Task 2 使用本地 mock worker，不联网。
4. 同时篡改 raw response、正式回复、监督摘要或 catalog resolution：从原配置/payload 重建协议与 binding，不能只比较两份派生字段；Task 3 提供共同篡改样例。
5. 旧档案没有 transport 字段，新档案伪装成旧 choices 或反向：按配置缺省旧 Chat/显式新 Responses 分派；Task 3/4 验证旧审计和新旧签名隔离。

## 文件与职责

执行顺序固定为 **Task4 Step0（新基线）→Task1→Task2→Task3→Task4 Step1–5**；新基线完成前不写新产品或测试。

| 文件 | 修改目的 |
|---|---|
| `src/llmbo_para/electrothermal_responses.py`（新） | 纯请求/正式 JSON 解码、Responses HTTP 类和独立 owned-worker 入口 |
| `src/llmbo_para/electrothermal_requests.py` | 传输选择；既有监督可替换 worker；HTTPArchive/completion_summary 按显式协议分派，旧缺省不变 |
| `src/llmbo_para/electrothermal_config.py` | v2 的 transport 枚举、对应 endpoint 和 Responses thinking 拒绝校验 |
| `src/llmbo_para/electrothermal_llm.py` | controller 选择新 factory、记录协议诊断；注入测试 transport 的旧接口保持 |
| `src/llmbo_para/electrothermal_region_catalog.py` | HTTP formal reply 重放增加显式 transport 参数，默认 Chat；目录几何/ID/resolver 不改 |
| `src/llmbo_para/electrothermal_audit.py` | 双协议最终请求、正式回复、失败与成本独立重建 |
| `tests/test_electrothermal_responses.py`（新） | 请求/解码/拒绝/计量/脱敏测试 |
| `tests/test_electrothermal_responses_requests.py`（新） | 配置、controller、spawn 和禁用/额度测试 |
| `tests/test_electrothermal_responses_audit.py`（新） | 两任务、catalog/bounds、HTTP 正负例和共同篡改审计 |
| `configs/electrothermal-sub2api-software-template.json`（新） | 复制现有软件模板的物理/目标设置，新增端点配置，保持 LLM disabled、API/DFN 0、原 parego 模式 |
| `docs/llm-informed.md`、`docs/audits/sub2api-responses-2026-10-21.md`（新 audit） | 接入方法、实际证据、未验证事项和后续零激活预算草案 |

既有 `llm.py` 的 Chat/HTTP wire、旧 Prompts、`mo_optimizer.py`、`surrogate.py`、`acquisition.py`、物理映射和数据模块不在本计划修改清单。

## Task 1: Responses 纯协议和 HTTP 适配

**Files:** 新 responses 模块和 `test_electrothermal_responses.py`。

**Interfaces:** consumes 现有 `HttpJsonTransport`、`region_wire_payload(payload)`、`decode_region_wire(reply,payload)`；produces：

- `responses_request_body(payload: dict, *, model: str, max_tokens: int, json_mode: bool) -> dict`。
- `decode_responses_json(value: dict) -> tuple[dict | None, str | None]`：第二项为既有 protocol_issue 枚举；成功是正式 JSON 对象/None，失败是 None/错误分类。
- `responses_completion_summary(value: dict, token_limit: int) -> dict`：真实 response_status、state、answer_characters，存在时才加入真实 token 数；不伪造 finish_reason。
- `ResponsesTransport(endpoint, api_key_env, *, model, max_tokens, json_mode, timeout_s=60., run_store=None, thinking=None).post(payload)`；thinking 非 None 在请求前拒绝。

- [x] **Step 1: 新基线后写 RED 测试。** `test_responses_wire_keeps_binding_and_store_false` 断言完整 endpoint 对应 body 的 instructions/input、text.format、1536 输出上限、store/stream false，无 messages/max_tokens/tools/previous_response_id。分别验证 WarmStart/full/compact payload。
- [x] **Step 2: 写 RED 解码矩阵。** `test_completed_final_json_only` 验证 completed+单 assistant output_text；`test_reasoning_is_never_formal_answer` 允许 reasoning 项但不读其文本；参数化缺/非字符串/空文本、refusal、多消息、多片段、工具、queued/incomplete/failed/error、非法/非对象 JSON、只有 choices/顶层 output_text。对错误 issue 做确切断言。`test_responses_reuses_no_redirect_and_secret_redaction` 用内存 fake opener/HTTP reply 检查不跟随重定向、拒绝超过1MiB、密钥只在真实私有请求头出现且不进入公开归档；不用任何本地/外部 socket。
- [x] **Step 3: 执行 RED。** 守护 runner 运行新文件，保存原失败；预期新模块/新接口缺失或协议断言失败，不能以环境缺包充当有效失败。
- [x] **Step 4: 最小实现上述接口。** 复用现有 HTTPS/no-redirect/脱敏层，不打开真实连接；正式对象之后仍由现有上层封套校验。
- [x] **Step 5: GREEN。** 新文件与 `tests/test_chat_transport.py` 联合运行。新增 `test_unknown_usage_is_not_zero` 和 `test_response_storage_disabled_does_not_disable_local_archive`；不能对未知 usage 补 0。显式提交本任务两个文件。

## Task 2: 监督、配置及 Controller 接入

**Files:** requests/config/controller、新 responses requests 测试，Task1 模块增加 bounded class。

**Interfaces:** consumes Task1 接口；produces：

- `electrothermal_transport_class(config: dict) -> type`，返回现有 `BoundedChatCompletionsTransport` 或新 `BoundedResponsesTransport`，不实例化或联网。
- `BoundedResponsesTransport(...同 Task1 constructor...).post(payload, *, deadline=None)` 沿用现有 owned-process 监督；默认 Chat 的 worker 和输出诊断不变。
- `completion_summary(response, token_limit, *, transport='openai_chat_completions')`；`HTTPArchive(..., transport='openai_chat_completions')` 仅增加可选协议参数。

- [x] **Step 1: 写 RED 配置测试。** `test_v2_default_chat_and_explicit_responses` 断言缺省不回填；`test_transport_endpoint_mismatch_and_unknown_rejected` 检查两个协议与 endpoint 交叉/未知值；`test_responses_thinking_requires_confirmed_mapping` 检查 global/task 两处显式设置均拒绝；v1 仍拒绝新 transport。
- [x] **Step 2: 写 RED 请求测试。** `test_disabled_zero_budget_and_missing_key_never_open_http` 分别观测 factory/HTTP 次数；`test_response_worker_deadline_no_retry` 覆盖 spawn 三个停滞阶段，结束后无存活自有 worker，开始计数与 ledger 一致。使用 mock worker，不启动本地服务或外网。
- [x] **Step 3: 执行 RED。** 新 requests 测试；预期严格新配置/factory/worker 断言失败，保留 JUnit 和退出码。
- [x] **Step 4: 最小接入。** 既有 bounded post 增加可替换 worker 的最小接口；新 worker 选择 ResponsesTransport 并复用 compact decoder；controller 保持注入 factory 优先，真实请求仅显式 enabled+预算满足才构造。diagnostic 仅新模式新增协议及真实 status；Chat 旧字段不改。
- [x] **Step 5: GREEN 与相关回归。** 新 requests 文件、`tests/test_region_request_policy.py`、`tests/test_region_request_worker.py`、`tests/test_region_request_deadlines.py`、`tests/test_region_json_wire.py`、Task1 文件；同一个正式 reply 比较两个协议的 canonical JSON。确认未改 GP/标签/Y，显式提交。

## Task 3: 独立双协议审计

**Files:** audit、catalog HTTP decoder、新 responses audit 测试；不改目录/compact ID 数学。

**Interfaces:** consumes Task1 decoder/summary 和 Task2 配置选择；`decode_catalog_http_response(value, *, payload, transport='openai_chat_completions')` 按显式协议解析后统一走现有 compact 绑定；auditor 保持原入口/结果形状。

- [x] **Step 1: 写 RED 成功/失败审计。** `test_responses_full_and_compact_archives_replay` 覆盖两任务、catalog ID/none、旧 bounds、拒绝/截断/错绑定/低置信度和 fair 拒绝。`test_same_formal_proposal_keeps_region_numbers` 断言相同矩形的 anchors/shift/EI/selected/feedback 不变。
- [x] **Step 2: 写 RED 篡改测试。** `test_responses_audit_rebuilds_wire_and_completion` 分别改 endpoint/model/store/input/instructions/max_output_tokens/status/usage；`test_joint_response_and_resolution_tamper_rejected` 同时改正式 reply、raw response 与 resolution；`test_protocol_is_not_guessed_from_body` 反向伪装新旧协议均拒绝。
- [x] **Step 3: 执行 RED。** 新 audit 文件保存真实失败类别；未经新审计实现不能把仅摘要相等称审计成功。
- [x] **Step 4: 最小实现审计。** 从冻结 config/payload 构造预期最终 HTTP body，再从 raw response 取得正式 JSON，复核完成状态、compact/catalog绑定、规范回复、请求 controls、监督和成本；失败记录也走同样的原始回复核验。
- [x] **Step 5: GREEN。** 新 audit 文件及旧 `test_region_catalog.py`、`test_region_failure_audit.py`、`test_electrothermal_audit.py`；旧档案按旧 source 只读重放，报告 GP state restore 与 hyperparameter search 的真实计数。显式提交。

## Task 4: 模板与最终软件交付

**Files:** 新软件配置、llm-informed、audit 文档、本计划进度；外部本计划 runner/证据目录。

**Interfaces:** consumes Task1–3；produces 零真实预算模板、实际测试档案和待后续审批的预检协议。

- [x] **Step 0（最先执行）: 新基线。** 建立本计划独立 runner 与 ledger，仅重用现有 guard 的软件边界，不向上一计划 ledger 写入。原完整 tests 跑至最终退出；记录数量/通过/失败/错误/跳过/耗时/JUnit/API/DFN/非电池 fixture。此前669仅作历史比较。
- [x] **Step 1: 模板 RED→GREEN。** 先在 `tests/test_electrothermal_responses_requests.py` 添加 `test_sub2api_template_has_zero_live_budget`，再从现有 software 配置生成新文件，只设置 llm.transport/endpoint/keyenv/model/compact，LLM disabled、API/DFN 0、原 parego 设置保持。模板只表明传输设置；A1/A2 消融设置仍由独立实验配置明确选用，不靠此模板切换算法。不得默认加载新站密钥。
- [x] **Step 2: 软件集成。** 用注入的 Responses HTTP fixtures 跑 ParEGO/WarmStart-only/Full-ID/Full-none；继承当前拟合倍率，旧3C不引入。完整日志注明 mock，不产生真实 RMSE 结果声明。
- [x] **Step 3: 全量与兼容。** 最终全量回归，保护 MAIN/旧档案、旧 Prompts 和数值模块 hash；新配置/源码签名隔离。失败要定位、修复并重跑适用验收，不忽略。
- [x] **Step 4: 分支审阅与封存。** 沿用 inline 执行，最后按 executing-plans 做一次 fresh-context 整分支审阅；所需修复 RED→GREEN+全量通过。显式提交全部清单文件，记录 commit/源码 SHA/JUnit、正负结果、调用0、未验证事项，保持现有工作树。
- [x] **Step 5: 只准备后续协议。** 专用 key 未就绪或无新预算则保持0请求。若届时申请1次 API，冻结确切payload/model/endpoint/token/timeout/总截止且无自动模型发现/重试；先审阅协议再请求额度，不沿用旧vsllm预检的已关闭1次预算。

## 可执行测试入口

获准实施后使用新独立外部目录 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/sub2api-responses-20261021/` 的 `run_tests.py`。它绑定本计划 ledger，采用现有 guard 的单线程、网络/DFN拦截和实际退出/JUnit记录。命令逐步执行，不一次运行全部 RED/GREEN。

```powershell
$etPython = 'D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe'
$etRunner = 'D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\sub2api-responses-20261021\run_tests.py'
& $etPython -X utf8 -B $etRunner test responses-baseline tests
& $etPython -X utf8 -B $etRunner test responses-wire-red tests/test_electrothermal_responses.py
& $etPython -X utf8 -B $etRunner test responses-request-red tests/test_electrothermal_responses_requests.py
& $etPython -X utf8 -B $etRunner test responses-audit-red tests/test_electrothermal_responses_audit.py
& $etPython -X utf8 -B $etRunner test responses-related tests/test_electrothermal_responses.py tests/test_electrothermal_responses_requests.py tests/test_electrothermal_responses_audit.py tests/test_region_catalog.py tests/test_region_failure_audit.py tests/test_electrothermal_audit.py
& $etPython -X utf8 -B $etRunner test responses-final tests
```

每个 GREEN 要实际退出0、failures/errors0；逐项解释 skipped。执行前确认所有已有测试文件精确路径，不能把不存在路径的收集错误当成该功能的有效 RED。

## 计划自检与交付状态

- [x] 核查当前工作树干净、HEAD4a2baca及当前 config/controller/bounded worker/HTTP/audit 的实际 Chat 限制。
- [x] 用户用途已明确为 LLMBO；新端点与精确模型保持，专用环境变量未就绪；本站请求0。
- [x] 规格覆盖、接口前后类型、失败状态、Review Focus和旧档案签名逐项自检；没有修改算法主线或推断新站 thinking 扩展。
- [x] 用户确认本具体计划（直接批准软件适配与本地测试）。
- [x] 软件实现与本轮实际测试、独立审阅。
- [ ] 专用 key 和真实 API 预算；不属于计划默认批准范围。

Task1–4软件交付完成：受测产品提交52b9813，最终全量781/781、失败/错误/跳过0、退出0、1206.71s；网络尝试/电池求解尝试0，既有非电池fixture2次。整分支审阅5项Important已通过失败测试和修复验证，未延期Minor。没有发往sidrune的请求。Codex CLI 的 service_tier 或 feature 兼容性不属于本项目适配计划，不修改其全局设置。最终证据在sub2api-responses-20261021/delivery-seal.json封存；保留工作树/分支/ledger，真实API/DFN仍为0。

阶段证据：新基线669/669退出0；Task1 RED45fail→GREEN57；Task2 RED13fail7pass→GREEN96；Task3相关210/210；模板与三模式集成5/5；审阅修复67/67；最终全量781/781；CLI validate-config/preflight及修复后复核退出0。首个全量中断且无最终计数/JUnit，不记通过。完整目录与正负记录见docs/audits/sub2api-responses-2026-10-21.md。
