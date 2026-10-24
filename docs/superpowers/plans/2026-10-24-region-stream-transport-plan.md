# Region Stream Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 定位完整Region的等待层，实现可独立审计的显式SSE候选修复，通过真实回复/作用门槛后才执行RMSE/HV配对。

**Architecture:** 保留urllib与原owned监督，仅为Responses增加显式接收模式；共享HTTP读取钩子，独立有界SSE解析器，独立入口用等待栈观测及固定序列诊断，再接已有冻结GP重放与新预算下的配对运行。

**Tech Stack:** 现有Python3.12、urllib/http.client、faulthandler、pytest、锁定NumPy/PyBaMM；不新增依赖或SDK。

**Spec:** [短设计](../specs/2026-10-24-region-stream-transport-design.md)；[调查/8场景证据](../../audits/region-transport-stages-investigation-2026-10-24.md)。

## Global Constraints

- 待审批；起点89b236e，继续原独立工作树/分支，原生执行方式不另问。先新完整基线、TDD、针对性、一次最终fresh-context审阅/修正、一次新完整回归，再真实请求。
- 仅新可选schema2/Responses全局布尔`llm.responses_stream`；省略维持旧body。配置/签名/归档/审计严格，旧缓存及初始化不改签。
- Prompt、历史、LGBO公式/32锚点、GP/EI、参数/物性、数据/热模型不改。端点sidrune/v1/responses、deepseek-v4-pro、专用SUB2API_API_KEY、代理与TLS保持。8192输出许可，单次最多120秒，数值单线程，无自动重试。
- 候选独立上限66API/256DFN/10800秒；诊断最多6API/0DFN/900秒，首次请求前起总钟，30秒清理预留；未审批前实际额度0。全部失败计入总账，已关闭旧额度不恢复。
- `PY`=D:/Users/aa133/Desktop/LLMBO_Para/.venv-pybamm312/Scripts/python.exe；`E`=D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-transport-stages-20261024。所有命令使用PowerShell完整引号路径。
- E中当前调查文件保留；实施时只新增独立命名工件。不得修改旧reasoning/transport/gain证据根、旧封存runner/worker/seal。主工程/参考只读，显式git文件清单，不merge/push/clean。

## Review Focus

1. 隐藏stream继承、null/Chat/schema1/任务覆盖及disabled：Task1负例和clone/spawn测试，配置唯一真源。
2. 分块UTF8、多行data、保活、EOF、截断或假completed：Task2解析器/真实内存HTTP测试，仅完整终止response进入旧校验。
3. 流式无限保活、超大事件、迟到回复或硬截止部分日志：Task2/3内存与owned硬限测试，字节/事件/绝对截止不重置。
4. 只改派生response或隐藏stream证据：Task3独立篡改审计；旧非流式不要求补流，不把缺usage补0。
5. 观察器只采父等待、密钥泄漏、旧进程/导入身份污染、失败后继续DFN：Task4原生spawn及协议负例，真实门槛和成本总账先于任何solve。

## Task 0: 新基线与保护

**Files:** E下新`run_tests.py`、`workspace-before.json`、源码/入口快照及`.superpowers/sdd/2026-10-24-region-stream-transport-plan/progress.md`；不编辑旧守卫。

- [ ] 记录批准、HEAD/status/worktree、源码/解释器/依赖/入口哈希，保护主124/参考55与index/status、旧seal和数值/Prompt/AST。主目录正在被独立编辑，先记录相较旧快照的全部当前偏差，不恢复它们；本任务运行源只能来自独立工作树，外部并行编辑与本任务写入分开归因。活动工作树文件将获批改动者先复制快照并列允许漂移；封存历史不漂移。
- [ ] 复用原软件网络/DFN守卫，但创建本计划自身的wrapper/manifest；隔离观察器导入，不提前污染canonical spawn模块。
- [ ] `PY E/run_tests.py test ge-st-baseline tests`：记录真实数量/日志/JUnit/退出码。历史1441不能替代；失败分类保留后先解决，不带失败进入真实请求。

## Task 1: 显式配置贯通与共享读取钩子

**Files:** 修改`src/llmbo_para/{llm,electrothermal_config,electrothermal_requests,electrothermal_responses,electrothermal_llm}.py`；新增`tests/test_responses_stream_controls.py`。

**Interfaces:** `request_controls(config,task)`可返回responses_stream；`responses_request_body(...,reasoning_effort=None,responses_stream=None)`和两个Responses构造器增加同名keyword；`HttpJsonTransport._read_response(self,response,*,task,redact)->dict`为默认JSON读取钩子。

- [ ] RED：省略/显式false/true；null、0/1、字符串、schema1、Chat、task_options拒绝；disabled无key/API；reasoning none可同时存在。旧body逐字段及编码golden一致。
- [ ] `PY E/run_tests.py test ge-st-controls-red tests/test_responses_stream_controls.py`，观察新接口/校验失败后再实现。
- [ ] 最小实现字段，完整传递serializer→controller clone→owned spec→实际body→supervision/outcome。未配置不能继承typed注入客户端隐藏stream；Chat不增接口。
- [ ] 仅提取默认读取代码为钩子，保持HTTP鉴权/代理/TLS/NoRedirect/1MiB/错误脱敏和原JSON行为；真值在Task2覆盖，不实现第二套POST。
- [ ] GREEN：新测试及原Responses/requests/reasoning/HTTP测试；真实spawn内存opener核验实际stream及body其余相同。记录计数，显式提交。

## Task 2: 有界 SSE 接收与原正式完成契约

**Files:** 新增`src/llmbo_para/electrothermal_sse.py`、`tests/test_responses_sse.py`；修改`electrothermal_responses.py`的读取钩子与`electrothermal_requests.py`的HTTPArchive公开进度。

**Interfaces:** `read_responses_sse(response,*,archive,task,redact)->dict`返回终止原生response；`decode_sse_events(events)->dict`为无网络纯函数，供独立审计重放同一公开协议，不调用生产Region决策；解析失败抛固定类型/机器原因，不输出原始文本。

- [ ] RED：UTF8跨块、LF/CRLF、多行data、注释保活、递增sequence、完整终止response通过原decode/wire；缺usageunknown，正数reasoning不拒绝。
- [ ] RED：无终止EOF、[DONE]、failed/incomplete/error、仅created/delta、非法有限JSON、错误MIME、身份不符、工具/未知事件、非法sequence、超1MiB/4096事件均拒绝；长单个终止事件允许至总字节上限，不引入隐式64KiB限制。
- [ ] `PY E/run_tests.py test ge-st-sse-red tests/test_responses_sse.py`；最小实现后GREEN。完成判断只用终止response，delta不补全答案。
- [ ] 追加脱敏stream.jsonl和安全进度，完成response.json为派生终止对象；失败保留partial，硬截止尾行截断只作失败证据；已完成后停止读取，不等待EOF。
- [ ] 真正urllib/http.client内存HTTP控制：body只改stream、Content-Length正确；保活不断到达仍在父硬截止停止owned树，晚到completed不接受；所有实际socket/DFN0。
- [ ] 针对性GREEN并显式提交；不得宣称真实网关已支持SSE。

## Task 3: 独立审计、旧兼容及文档

**Files:** 修改`src/llmbo_para/{electrothermal_audit,electrothermal_lgbo_audit,electrothermal_json}.py`；新增`tests/test_responses_stream_audit.py`、默认禁用的软件配置`configs/electrothermal-sub2api-stream-software-template.json`；追加`docs/llm-informed.md`。

**Interfaces:** 从归档配置重建带responses_stream的请求；流式分支从原始stream事件先重放终止response，再核对派生response/formal/绑定/supervision/outcome和当前数值审计。旧非流式走旧路。

- [ ] RED：删/改终止事件、sequence/type/response身份、只改派生response、配置/控制单边及全删、部分流伪报成功均审计失败；坏JSON/截断流不能审成合法失败后绕过真回复。
- [ ] RED：旧缺省非流式、显式false及true分别通过；旧六维缓存/回复不能因新增字段放松；旧c01归档只读兼容。
- [ ] `PY E/run_tests.py test ge-st-audit-red tests/test_responses_stream_audit.py`，最小实现后联合GREEN。审计记录实际GP拟合/sweep成本，不声称只有from_state或0成本。
- [ ] 软件模板LLM disabled、API/DFN0，固定六参和原软件问题；可检查但不触发真实调用。文档区分HTTP完成、正式动作、tilt、选点改变及真实增益。
- [ ] 显式提交；不改Method中的数值方法和旧档案。

## Task 4: 分阶段验证入口、等待观测及放行

**Files:** 新增`scripts/run_region_stream_validation.py`、`tests/test_region_stream_validation.py`；E下新protocol/approval/run wrapper；旧三个gain/transport/worker脚本只读复用函数。

**Interfaces:** `run_validation(protocol,evidence_root,*,execute=False)->dict`默认dry不读key；`observed_responses_worker(spec,payload,run_path,connection)`以局部HTTPArchive观察器调用实际生产worker；`stream_gate_passed(proofs)->bool`在已有冻结GP重放基础上验证本设计门槛。新ledger使用新路径，可只读复用既有ValidationBudget函数但不能调用旧main/ROOT。

- [ ] RED：无批准/软件release/key/额度、dry、源码/依赖/冻结输入漂移、旧关闭账本、重复event_id、边界费用及绝对截止时均不发请求/solve；API开始前父记账并ack，树停止/清理证据齐全。
- [ ] RED：实际HTTP子进程30秒栈采样、finally取消/文件生命周期、只采外层父栈的负例；正常reply无采样也不拒绝。不输出变量/鉴权，禁用debuglevel；Windows真实pickle/spawn，观察器恢复模块引用不污染旧tests。
- [ ] 固定provider和六步骤：p0最小nonstream/60s → p1完整ctx0/nonstream/120s → p2同ctx0/stream/120s → p3 ctx1/stream/120s → p4 ctx2/stream/120s → p5预注册ctx0/stream重复/120s。reasoning均none、8192许可、全历史不改。p1/p2实际body除stream外逐字段相等；p5不是失败后的重试。
- [ ] RED：p0/p2/p3/p4/p5任意失败立即关闭，401/403/404/429/5xx全程立即关闭。**仅p1**已开始且触发预注册120s父硬截止、owned树已停止、输入/源码未漂移、总钟仍有效且无其他HTTP错误时，可继续预注册SSE比较；普通网络timeout、worker崩溃、全局截止不在例外内。若栈显示等待CONNECT/TLS/sendall，停止进入SSE，先据证据处理该层；不以外层awaiting_headers标签代替等待栈。栈缺失/无法分类则停止，不猜测。
- [ ] RED：p2/3/4三个不同ctx均正式完整，p5重复也正式完整；冻结GP原状态/方差/标签不变、独立EI一致且至少一次max_abs_shift>1e-12才放DFN。额外记录EI差/是否改选点；全none或零tilt不放行。p1非流式完成时也必须完成该SSE门槛，不自动改变选定传输。
- [ ] RED：诊断900秒、整体10800秒、30秒清理预留，同时受硬截止；正式连续三次传输/协议失败停止整个配对，弃权另计。任何门槛失败后DFN0、BO0，无隐藏恢复。
- [ ] 全新fake executor全路径＋原生owned内存HTTP GREEN；一次fresh-context最终审阅/一次TDD修正，随后`PY E/run_tests.py test ge-st-final-full tests`，统计真实数量/日志/JUnit/退出码。完整观察绑定本轮源码、实际入口、保护依赖、解释器/版本/批准/协议，导入隔离保持。
- [ ] 封存软件release及新源码提交，缺任一完整绿色/身份绑定不运行API。新attempt若必需则独立命名，保留所有失败，不覆盖manifest。

## Task 5: 获批后固定诊断，再真实DFN合成配对

- [ ] 核验专用凭据仅在环境中加载，不进命令/配置/源码/日志；冻结三个原历史payload/round/manifest，原context/signatures不改签，新transport/runtime/批准用独立stream probe元数据绑定。
- [ ] 启动一次新总钟/账本，按Task4固定请求并归档实际栈/语义事件/完整回复/计量/owned停止；诊断最多6API/0DFN/900秒。比较只提供描述性链路线索，不假定服务端根因或因果增益。
- [ ] 门槛不通过即关闭，保留剩余额度而不续用，报告卡点与未验证事项；不启动DFN。通过后登记完整gate再转init阶段。
- [ ] 只读复用已封存0.5C/1C各60秒人工观测，验证数据哈希与曲线；用旧8坐标作新16次solve，当前配置下创建新共享8点计划，不给旧计划改签。任何不完整目标对阻止开始配对。
- [ ] 种子1709/3253/5501，Plain(WarmStart-only、零Region)／Full各20轮；同一有效8点计划、同512/8候选和4 sweeps，按设计固定权重/尺度/HV空间，交替臂先后。新增至多240DFN/60API；总体66API/256DFN，全部失败计费，无新观测生成solve。
- [ ] 独立复算曲线RMSE/真实Y/Pareto/HV及每轮权重上下文；记录真实请求完成/失败/弃权、tilt、EI差、选点改变、请求/求解/筛选/缓存成本。每个推荐参数同时列FU和FT；不拼造一个共同最优点。
- [ ] 输出每种子配对HV终值/曲线及RMSE；无增益如实记录，不自动换种子、调公式、追加次数或回滚数值。若仅传输不可用则不作Region方法无效结论。
- [ ] 显式改动清单、测试/审计/退出码、Git、旧保护和新seal交付。保留所有正负工件和工作树，不合并/推送/清理；实测仍未开展。

## 自审与审批

五类Review Focus都有失败测试；shared hook避免复制HTTP，纯SSE解析器与独立入口职责分开；
待验证的外部网关能力没有写成已知事实。软件、API作用门槛、DFN增益和实测分别验收。
本计划和短设计一并提交用户，沿用其“计划审批完成后修改产品代码”的要求；
当前仅调查/8场景离线验证及文档，尚未批准本计划产品实施或新真实预算。
