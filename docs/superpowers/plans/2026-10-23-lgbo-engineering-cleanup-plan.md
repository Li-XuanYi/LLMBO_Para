# LGBO Engineering Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 用可验证的数值和请求等价性消除当前LGBO工程重复，保留旧流程，并交付独立的Prompt/Region后续验证说明。

**Architecture:** 每轮共享不可变预测视图；payload按职责构造；与catalog无关的JSON/归档解码移入公共模块。兼容入口与独立数值审计保留，不更换策略、Prompt、缓存规则或归档schema。

**Tech Stack:** 现有Python3.12解释器、锁定NumPy/pytest/PyBaMM25.10.2，无新依赖。执行方式沿用当前会话原生实施，最后一次独立整体审阅。

**Spec:** [已确认书面设计e05a7c4](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/docs/superpowers/specs/2026-10-23-lgbo-engineering-prompt-region-design.md)。本计划落实§4；§5的候选Prompt和§6的研究顺序作为文档交付，不发布新Prompt版本、不执行冻结回放或真实效果实验。设计确认不等于本计划已批准。

## Global Constraints

- 工作树 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`，分支 `codex/electrothermal-mo-20261016`，计划前HEAD=e05a7c42754c1eff4c84202a2e5b0a9df9610e26，开始时Git干净。主工程/参考工程只读；旧交付、实验、账本和工作树保留，不merge/push/清理，不git add .。
- 六参数4E+2T、DFN+lumped、配置化fit_rates、两个预测RMSE、ParEGO、ARD Matérn GP、Gaussian EI、固定尺度/HV空间保持。旧schema1四倍率电压任务、旧配置和签名校验保持。旧3C不参加新版拟合。
- 无新核、热自由变量、目标、信任乘子、候选目录或竞争守卫。32锚点、均匀权重、lambda=c/sqrt(a.T*Kaa*a)、最小化符号、原方差、真实incumbent和1e-12容差不变。
- 仅整理触及模块：一条语句一行、清晰命名、公共边界类型标注、单位/前置条件/错误说明、删除确实未使用的局部导入。保留锁版本，不安装新的格式化/检查依赖，不做全仓库机械格式化。
- 最多新增两个生产模块：electrothermal_json.py和electrothermal_payloads.py；预测视图放现有acquisition.py。不格式化或改变旧apply_electrothermal_region、update_electrothermal_trust、Gaussian EI、旧电压EI、标量化或LGBO tilt公式的函数AST。
- 旧v1/v2和WarmStart Prompt字节、相同可信身份下的请求科学内容、动作结构及归档字段不变。accepted兼容别名和重复归档数组保留。本轮不注册lgbo_v3，不添加Prompt/策略配置开关。
- API/DFN/实测/服务器/正式BO新实验预算均0；单线程、无重试、不读凭据值。单元测试人工软件夹具单列，不重跑旧24组实验。CodeGraph继续暂缓初始化。
- 所有新增源文件/重构会改变source_fingerprint。新软件夹具按实际新源码生成；旧初始化/缓存/回复不换签、不放宽；旧档案按自身源码核验。golden的身份归一化仅限测试，不进入生产签名路径。
- 不把历史1092项、软件等价、提速、动作合法或selection_changed当成本轮新回归或真实优化增益。

## Review Focus

1. 无新增完整目标对但换轮/换权重后复用旧视图：Task2验证context与scalarization身份、incumbent全部刷新；无效视图在目标评价前拒绝。
2. pool只是重排、GP同对象被再训练、NumPy输出被别名修改：Task2验证有序pool、GP状态、深层不可变所有权，不只比较对象id。
3. JSON整理错误地把非有限诊断修成合法动作，或破坏脱敏碰撞/两种HTTP完成语义：Task1逐例差分，保留失败类型、原始诊断与旧包装入口。
4. 请求重构遗漏旧策略字段或掩盖Prompt/历史变化：Task0先捕获八场景golden；Task3逐内容/顺序校验，保留v1既有77f3a8ca4e03e024578fff5bf9f9a35350bdb4a2b5272a7afdd153b34dbb39c2基准。
5. 共享生产视图后审计随之自证，或把调整后EI也误删：Task2/4分别验证一次基础预测/EI和一次有效tilt后的EI；生产故障注入必须被独立审计发现。

## File Map and Commands

文件路径以下述工作树为根；各Task的Files是显式修改清单，不允许扩大到原参考工程。

|文件|职责|
|---|---|
|[acquisition.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/acquisition.py)|新增冻结预测视图及绑定校验，已有EI函数不动|
|[mo_optimizer.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/mo_optimizer.py)、[electrothermal_lgbo.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/electrothermal_lgbo.py)|LGBO生产路径共享视图；旧调用仍可不提供视图|
|新增src/llmbo_para/electrothermal_json.py|原生类型、脱敏归档、归档HTTP解码的公共功能|
|新增src/llmbo_para/electrothermal_payloads.py|WarmStart、LGBO和旧Region各自明确的payload构造|
|[electrothermal_llm.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/electrothermal_llm.py)、[electrothermal_region_catalog.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/electrothermal_region_catalog.py)|保持旧公共入口；控制器不承载payload细节或通用序列化|
|[electrothermal_region_wire.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/electrothermal_region_wire.py)、[electrothermal_lgbo_audit.py](C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para/src/llmbo_para/electrothermal_lgbo_audit.py)|只更新通用工具引用；审计数值与协议检查保持|

执行时定义PowerShell变量（不在本次计划编写时执行）：

```powershell
$WT = 'C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para'
$P = 'D:/Users/aa133/Desktop/LLMBO_Para/.venv-pybamm312/Scripts/python.exe'
$E = 'D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-engineering-20261023'
Set-Location -LiteralPath $WT
```

测试用本计划独有 `$E/run_tests.py test LABEL TARGETS`；CLI预检用 `$E/run_tests.py preflight LABEL CONFIG`。该证据工具只在批准后的Task0创建；标签ge-*且不复用，日志/JUnit/结果统一到新根目录tests/或cli/。实际pytest/RunStore使用主工程bo-repair-work内本计划独占的短临时路径，完整路径写入证据，保留不清理。命令省略运行器即视为未完成规定验证。

## Task 0: 新基线、保护和重构前golden

**Files:** Create新证据根目录`$E`及其run_tests.py、approval.json、workspace-before.json、payload-golden-before.json；Create tests/electrothermal_payload_fixtures.py、tests/fixtures/electrothermal_payload_golden_20261023.json。新账本 `.superpowers/sdd/2026-10-23-lgbo-engineering-cleanup-plan/progress.md`，不写旧账本。产品src不改。

**Interfaces:** 测试helper `payload_case(case: str, tmp_path: Path) -> tuple[prepared, history, context_or_none]`，八个case固定为warmstart、legacy_bounds、candidate_aware、fair_dynamic、catalog_full、catalog_compact_action、lgbo_v1、lgbo_v2。从现有电热软件fixtures构造两条真实评价格式记录和匹配GP状态；catalog场景复用已有合法几何fixture并要求至少一个目录条目，不能用空目录避开几何/ID兼容。可信signatures及context在调用producer前固定。沿用既有frozen_identities所需身份替换，不归一化数值、历史顺序、Prompt或区域几何。golden JSON结构为version='payload_golden_v1'、source_fingerprint和cases映射；每case保存payload_sha256、wire_sha256，均由canonical_json摘要产生。

- [x] 重查Git、worktree和规范；建立本计划证据与账本，记录审批、解释器、锁版本、主工程HEAD/status/index/124类保护文件、现有Prompt字节和受保护函数AST。旧密封目录仅核验。
- [x] 新runner只读复用现有BoundaryGuard和保护逻辑，禁止网络/电池solve，清除PYTEST_ADDOPTS，移除继承的已知API凭据变量但不输出值，线程1、遥测关闭、禁止向旧工具目录写pycache。test分支保存命令、源码前后哈希、退出码、JUnit、日志和边界；preflight分支在同一guard中调用cli.main(['preflight', CONFIG, '--output', OWN_SHORT_OUTPUT])，保存同样的日志/结果和边界但不伪造JUnit。输出位置必须属于本计划独占短路径，不能覆盖旧档案。不得调用旧脚本main或写其ROOT/ledger。
- [x] Run `& $P "$E/run_tests.py" test ge-baseline tests`。Expected：完整结束exit0，保存实际pass/fail/error/skip；参考1092但不写死数量。失败先分类既有/环境/本轮，不用历史结果替代。
- [x] 基线通过后、任何src变化前，用新helper和旧公共builder生成八场景golden，独立重复生成并断言canonical摘要相同。v1既有77f3基准保持；保存每个场景实际SHA，不先写未来占位值。人工fixture评价/GP条件化计入测试准备，不记为正式BO实验。
- [x] 显式提交测试helper/golden；记录Task1的BASE。本Task不安装依赖、不改生产Prompt或实验。

## Task 1: 通用JSON职责隔离（TDD）

**Files:** Create src/llmbo_para/electrothermal_json.py、tests/test_electrothermal_json.py；Modify electrothermal_region_catalog.py、electrothermal_lgbo.py、electrothermal_llm.py、electrothermal_lgbo_audit.py、electrothermal_region_wire.py的公共工具引用；现有数学函数不动。electrothermal_requests.py/electrothermal_responses.py没有这些旧工具引用，不修改；旧通用审计保留catalog兼容入口调用。

**Interfaces:** `is_json_native(value: object) -> bool`、`archival_json(value: object) -> str`、`decode_archived_http_response(value, *, payload: dict, transport: str='openai_chat_completions') -> tuple[dict | None, str | None]`。catalog_reply_is_json_native、catalog_archival_json、decode_catalog_http_response保留原签名的薄包装；LGBO私有_native也保留兼容包装。公共模块不能导入控制器/catalog；wire/Responses的协议解码按需局部导入，避免环。

- [x] 写新行为测试：新模块导入在测试体内受存在性断言保护；原生嵌套对象/NumPy类型拒绝；NaN/Inf在诊断归档中保留原有语义，不能被“清洗”为有效动作；token形状字符串/敏感键/脱敏键碰撞/未知Python类型与旧入口输出逐字一致，不读取真实凭据。
- [x] 独立pin值而非只比较两个转发入口。例如`test_archival_json_preserves_diagnostic_and_redaction`至少包含：

```python
assert archival_json({'secret': 'fixture-only'}) == '{"secret": "[REDACTED]"}'
assert archival_json({'x': float('nan')}) == '{"x": NaN}'
assert archival_json({'x': (1, 2)}) == '{"x": {"__rejected_python_type__": "tuple"}}'
assert not is_json_native(np.array([1.0]))
```

脱敏键碰撞用测试合成的token形状字符串，检查掩码长度/唯一键保留；不使用任何真实密钥。归档可保留NaN诊断，不意味着LGBO动作允许NaN。
- [x] 写两协议归档解码测试：Chat完整/截断/空内容/坏JSON/绑定错误，Responses completed/incomplete/空文本/绑定错误，未知transport保持旧异常类型与信息。Expected RED：公共模块缺失而测试失败，不产生collection error或网络调用。
- [x] Run `& $P "$E/run_tests.py" test ge-json-red tests/test_electrothermal_json.py`；观察RED后才迁移公共逻辑和旧包装，保留所有校验边界与原因分类。结构原生类型检查不代替有限数校验。
- [x] Run `& $P "$E/run_tests.py" test ge-json-green tests/test_electrothermal_json.py tests/test_region_catalog.py tests/test_region_action_wire.py tests/test_region_action_audit.py tests/test_electrothermal_responses.py tests/test_electrothermal_responses_audit.py tests/test_lgbo_region_wire.py tests/test_lgbo_region_audit.py`。Expected：全部通过exit0；无导入环，旧动作、拒绝和审计语义保持。
- [x] 检查显式diff/受保护AST和Prompt；只提交本Task文件并记录实测结果。Task2消费新模块时不能进一步改变JSON策略。

## Task 2: 一轮一次基础预测与EI（TDD）

**Files:** Modify acquisition.py、mo_optimizer.py、electrothermal_lgbo.py；Create tests/test_lgbo_acquisition_view.py。不改surrogate.py、scalarization.py或独立tilt审计。

**Interfaces:** 在acquisition.py新增`@dataclass(frozen=True) FrozenAcquisitionView`，字段为context_id、pool_digest、gp_state_digest、scalarization_digest、pool、best、mean、std、plain_ei、plain_index；数值集合为深层不可变原生tuple。`build_acquisition_view(gp, context, pool) -> FrozenAcquisitionView`一次predict+Gaussian EI；`validate_acquisition_view(view, gp, context, pool) -> None`只核验身份、shape/有限性/非负std和EI/原始argmax等前置条件，不重新预测或重算EI。GP状态必须匹配context.gp_state_json，有序pool必须匹配context.pool。

`apply_lgbo_region(..., *, ..., acquisition_view: FrozenAcquisitionView | None=None)`增加可选关键字，旧参数和输出保持。提供视图则严格校验并复用；不提供时保留原独立调用路径，不强制旧测试/外部调用具备完整MORoundContext。MOOptimizer仅在LGBO路径建立/传递视图；旧策略apply/trust不改。

- [x] 先写真实生产路径回归 `test_full_step_predict_and_plain_ei_once`：现有mock none动作、spy Matern52GP.predict与各调用模块Gaussian EI，单步基础predict/EI应各一次。Expected RED：现有代码各两次；不是只测新增类是否存在。
- [x] 上述测试复用`test_lgbo_region_workflow.optimizer(tmp_path)`；对acquisition、mo_optimizer和electrothermal_lgbo的Gaussian EI引用安装同一计数包装，避免只patch一个已被from-import复制的别名。关键断言：

```python
event = opt.step()  # 控制器返回none，既无tilt后的EI，也无真实API
assert calls == {'predict': 1, 'ei': 1}
assert event['region']['fallback_reason'] == 'abstained'
```
- [x] 写独立数值oracle：pool为[0]*6/[.5]*6/[1]*6，mean=[-1,0,1]、std=[0,1,0]、best=0，EI应为[1,0.3989422804014327,0]，plain_index=0。输入pool/预测数组事后修改不改变视图；tuple元素不可赋值。并列最大EI仍取原pool最早索引。
- [x] 写错context、换权重、同GP实例再训练、pool重排、best改变、非法数值及未新增有效Y但换轮的拒绝测试；都在目标评价前失败，不悄悄重新预测修复。新分配但数值/顺序相同pool可用。同一context下改变的是confidence c时可复用，改变标量权重w则必须新视图，二者不能混淆。
- [x] Run `& $P "$E/run_tests.py" test ge-view-red tests/test_lgbo_acquisition_view.py`；确认RED后最小实现。视图不作为LLM可提交的可信凭据；数学正确性仍由独立审计验证。
- [x] 新旧apply同动作做逐项对照：region/none/c=0/负协方差/退化方差/无可行锚点。真实GP状态、训练标签、std、incumbent不变；提供视图不增加基础predict或基础EI；合法非零tilt允许且应再计算一次调整后EI，不能误删。保存调整结果和外层数组由同一视图产生，但归档字段不减。
- [x] Run `& $P "$E/run_tests.py" test ge-view-green tests/test_lgbo_acquisition_view.py tests/test_electrothermal_lgbo.py tests/test_lgbo_region_workflow.py tests/test_lgbo_v2_workflow_audit.py tests/test_mo_optimizer.py`。Expected：exit0，含失败轮刷新与第13轮；受保护数值函数AST不变，旧入口不传视图仍通过。
- [x] 显式提交，记录基础predict/EI计数及针对性回归证据。不通过减少GP拟合或更换候选池“提速”。

## Task 3: payload职责和代码规范（TDD）

**Files:** Create src/llmbo_para/electrothermal_payloads.py、tests/test_electrothermal_payload_refactor.py；Modify electrothermal_llm.py；使用Task0的fixtures/golden。不扩大到其他审计/调用模块，不改任何Prompt、配置或响应契约。

**Interfaces:** 新模块 `build_electrothermal_payload(task: str, *, prepared, history, context=None) -> dict`分派到`build_warmstart_payload(*, prepared, history) -> dict`、`build_lgbo_payload(*, prepared, history, context) -> dict`、`build_legacy_region_payload(*, prepared, history, context) -> dict`。原electrothermal_llm.build_electrothermal_payload保持同名同签名兼容包装；新模块不反向导入控制器。内部共用基础元数据/历史/工况序列化，LGBO直接创建动作schema；所有顺序与内容保持。

- [x] 写测试要求三个明确builder入口存在且LGBO构造不会调用legacy builder。八场景的canonical payload和实际wire都必须匹配Task0已固定摘要，列表顺序单独比较；原兼容入口与新入口结果相等，修改返回值不污染prepared/history或下次请求。Expected RED：新模块缺失或当前混合builder未拆分。
- [x] `test_payload_and_wire_match_pre_refactor_goldens`对八个case参数化，task仅在warmstart时使用warm_start_electrothermal，其余使用region_preference_electrothermal。核心断言如下；goldens必须读Task0已提交的JSON，禁止在此任务重新生成：

```python
assert digest_value(payload) == goldens['cases'][case]['payload_sha256']
assert digest_value(region_wire_payload(payload)) == goldens['cases'][case]['wire_sha256']
```
- [x] 写失败边界：未知task、缺Region context、history越出冻结上下文继续拒绝；WarmStart不获得Region字段；v2科学内容/weighted evidence和旧Prompt逐字保持。golden仅归一化可信身份，不去掉错误字段或重排历史来通过。
- [x] Run `& $P "$E/run_tests.py" test ge-payload-red tests/test_electrothermal_payload_refactor.py`；观察RED后移动/拆分构造逻辑，旧apply/trust函数保持AST。仅整理触及的语句与公共边界，不大范围重排旧控制器或旧优化器。
- [x] 保留producer故障注入的可观测性：weighted_objective_evidence按模块属性/运行时查找，不能因顶层绑定旧函数使现有独立审计故障测试失效。审计继续独立验证q/active/g与tilt，不调用新预测视图来自证。
- [x] Run `& $P "$E/run_tests.py" test ge-payload-green tests/test_electrothermal_payload_refactor.py tests/test_electrothermal_llm.py tests/test_lgbo_weighted_context.py tests/test_lgbo_region_wire.py tests/test_lgbo_v2_workflow_audit.py tests/test_region_catalog.py tests/test_region_action_wire.py tests/test_region_action_audit.py tests/test_region_dynamic_evidence.py`。Expected：exit0，77f3既有v1golden和新八场景golden不改；两协议离线生产worker及producer错误检测仍通过。
- [x] 显式提交，保存新source指纹及原golden引用；所有后续运行fixture按新source重建，不重签旧初始化。

## Task 4: 最终验收、审阅和研究交接

**Files:** Modify docs/llm-informed.md；Create docs/audits/lgbo-engineering-cleanup-validation-2026-10-23.md。仅在确有接口说明变化时补docs/Method.md，不改数学定义。新证据根目录保存研究交接protocol.json，不启动研究。

- [x] 检查新模块/改动块一条语句一行、命名/类型/错误说明、无无用导入和导入环；用标准库ast与`git diff --check`核验，不新增工具依赖。完整tests新回归：`& $P "$E/run_tests.py" test ge-final-full tests`，Expected实际全量pass、fail/error/skip0、exit0；记录日志/JUnit/源码前后哈希和真实边界，不引用历史数量。
- [x] 一次最终独立整体审阅；Critical/Important由原生执行者逐项RED→GREEN修复，源代码实际变更后补针对性与全量回归。不得以审阅意见或已启动替代测试结果。保存裁决、延期小项和证据。
- [x] Run `& $P "$E/run_tests.py" preflight ge-cli-v1 "$WT/configs/electrothermal-sub2api-lgbo-software-template.json"`和`& $P "$E/run_tests.py" preflight ge-cli-v2 "$WT/configs/electrothermal-sub2api-lgbo-v2-software-template.json"`。Expected两者exit0、guard计数0且无实际目标评价；新source下旧源码实际初始化档案仍被严格拒绝，新同source共享计划可用。单位与缓存兼容已有回归继续覆盖。
- [x] 重核主工程HEAD/status/index/文件、参考工程只读边界、旧Prompt、固定物性/锁文件/数值函数AST、旧交付seal。归档schema及accepted别名不变；工作树保留、显式文件清单和commit可查。
- [x] 报告工程等价性、基础预测计数、可选同环境时间描述，区分软件测试与正式实验成本；本轮真实API/DFN/正式BO均0。候选Prompt继续仅存在于已确认设计中，不复制到产品或注册v3。
- [x] 交接文档固定下一步研究顺序：先同payload的Prompt-only比较，再考虑独立历史选择/区域质量对照；c和32/128锚点冻结回放只用于诊断EI排序，不给未实评点填RMSE/HV。真实API/DFN需另行具体协议和预算。当前不运行冻结回放，不修改公式，不为追求正结果追加实验。
- [x] 最终显式文档提交、Git状态与保护校验、归档并封存新证据。更新本计划Task0–4完成状态；实现未完成时如实标记，不用预算/时限替代完成。

## Self-review and Approval Handoff

已对照Spec§4逐项落到Task0–4；§5候选Prompt和§6研究仅文档交接，没有悄悄发布新策略。共享JSON和payload各新增一个模块，视图留在现有采集模块；所有接口消费者和旧包装路径已明确。Review Focus五项均有对应失败测试，基础EI与调整后EI分别计数，c与w分开，独立审计不复用生产视图数学。已静态核对所有现有测试/配置路径，纠正旧测试名称，不运行pytest；实际执行仍先检查仓库变化，不按旧状态假定。

用户已经确认书面设计和当前会话原生方式；计划提交时尚待批准；用户随后明确批准当前会话软件实施与测试。现Task0–4已按新基线、TDD、针对性回归、最终全量回归及一次独立审阅完成；实际数量/退出码/日志见docs/audits/lgbo-engineering-cleanup-validation-2026-10-23.md。本轮真实API/DFN/正式BO均0，工作树和全部证据保留。
