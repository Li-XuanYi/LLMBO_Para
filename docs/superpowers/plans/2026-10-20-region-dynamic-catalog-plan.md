# Region Dynamic Evidence and Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复Region缺少非初始动态证据和容易返回错误矩形的问题，并交付不改变当前Lift公式的可审计软件版本。

**Architecture:** 在现有decision_geometry_v2上增加独立版本的动态残差摘要；随后提供由host确定的有限区域目录，LLM返回目录ID，host严格解析成现有规范矩形。GP、Gaussian EI、候选池、锚点、Lift、fair guard和信任反馈保持原数值语义。两项变化独立开关、独立测试和提交。

**Tech Stack:** 现有Python 3.12、NumPy、pytest；不新增依赖、锁文件或模型。沿用Windows原生单线程守护测试入口。

**Spec:** [文献导向设计，第4.1、5、7节](../../research/2026-10-20-literature-guided-region-design.md)；[已批准R1](../specs/2026-10-16-electrothermal-identification-design.md)；[Method](../../Method.md)。本计划是文献建议A的细化，尚未执行，不追溯修改旧规格的历史状态。

## Global Constraints

- 工作树：`C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`；分支`codex/electrothermal-mo-20261016`。
- 计划前HEAD：`8785a19829ebd75f45b3c4bae5831ae25b9fba54`；产品提交`d3e2fa1`；产品指纹`dfd81d9dd988c7b2fa2f284f96c9fa371aadae35f1902ed84b022fe100dac992`。
- 用户本次“继续”用于推进文献建议的工程细化；遵循用户此前“实施计划提交审阅后暂停，批准后修改产品代码”的流程。本轮只提交具体计划与审阅证据。
- 保留4E+2T、DFN+lumped、两个跨配置fit_rates平均RMSE、固定尺度/HV空间、一个ARD Matérn GP、Gaussian EI、原WarmStart选择规则。
- 不增加GP/核/优化目标/热自由变量；不改Chen2020固定物性、电流、初态、采样时间或60秒物理协议。旧3C仍排除，未来可靠3C只由新配置加入。
- 新增付费API、真实DFN、正式实测BO、服务器任务预算均为0。本计划批准也只允许软件实现及本地受控测试，不赋予真实请求或求解预算。
- 旧配置、旧Prompt字节、旧模块接口、旧缓存拒绝条件与旧档案全部保留；新语义必须有新版本/签名，不重新签署旧初始化使其冒充新源码评价。
- 每个实施任务先写失败测试并保存RED证据，再最小实现、针对性GREEN、独立审阅；最终另跑新全量回归。历史530/530不是本计划的新增结果。
- 每轮上下文仍冻结权重/尺度/理想点/标准化/incumbent/GP/池；失败或缓存未新增有效目标后也按现流程下一轮重建。LLM不写改真实Y、训练标签、原后验均值/方差。
- 仅显式列出的文件可提交；主工程与只读参考工程不改，不清理实验、不执行`git add .`。

## Review Focus

1. 第一个观测不一定是初始状态：仅以同次求解trace起点识别初始残差，不能猜测时间0或取obs[0]。任务1测试覆盖缺失起点、非零起点和独立U/T网格。
2. 短网格/长网格均不得制造动态信息：initial-only为无动态；长网格只展示真实索引，但全动态均值包含未展示点。任务1测试n=0/1/2/8/9/100及被省略异常值。
3. 合法几何不等于物理可行或更优：目录不带置信度/偏好，解析后仍走原物理锚点和fair守卫。任务2覆盖边界、重复宽度、物理拒绝和none。
4. 合法ID不能脱离请求重放：权重、尺度、池、历史或目录改变，旧回复必须拒绝。任务2覆盖full/compact、跨轮ID、额外bounds及同维旧回复。
5. 审计不能只比较两个同源摘要：从原始观测/曲线/冻结历史与池重建动态证据和目录，再解析回复。任务1/2测试共同篡改时间、摘要、ID映射和canonical矩形。

## 文件与职责

执行顺序固定为 **Task3 Step1（新基线）→Task1→Task2→Task3 Step2–5**；基线阶段不写产品或新测试。

| 文件 | 职责/动作 |
|---|---|
| `src/llmbo_para/electrothermal_dynamic_evidence.py` | 新建；纯只读动态残差及有界真实观测索引选择 |
| `src/llmbo_para/electrothermal_region_catalog.py` | 新建；确定目录、严格ID回复契约、host映射及结构化解析证据 |
| `src/llmbo_para/electrothermal_config.py` | 显式校验新evidence/proposal枚举及组合，缺省保持旧语义 |
| `src/llmbo_para/electrothermal_llm.py` | payload/新Prompt/回复契约与解析分派；不改apply_electrothermal_region的数值实现 |
| `src/llmbo_para/electrothermal_audit.py` | 新模式独立重建原始历史、动态证据、目录、回复解析及选点；旧分支保持 |
| `src/llmbo_para/prompts/region_preference_dynamic_electrothermal.txt` | 新建200–300词英文Prompt；动态观测证据+现有bounds回复 |
| `src/llmbo_para/prompts/region_preference_catalog_electrothermal.txt` | 新建200–300词英文Prompt；同等证据+有限目录ID回复 |
| `tests/test_region_dynamic_evidence.py` | 新建；信号/数据/版本/payload/篡改测试 |
| `tests/test_region_catalog.py` | 新建；几何/绑定/回复/守卫/审计及零资源集成测试 |
| `docs/llm-informed.md` | 增补新版本与边界，不改旧方法解释 |
| `docs/audits/region-dynamic-catalog-2026-10-20.md` | 新建；实际RED/GREEN/回归/审阅/兼容证据与限制 |

`electrothermal_residuals.py`旧signed接口、`electrothermal_region_evidence.py`旧算术接口、`electrothermal_region_wire.py`传输封套、`mo_optimizer.py`、`surrogate.py`、`acquisition.py`不在预期修改清单。若实际实现需要更改其语义，先说明差异并修订本计划；不能借此替换数学主线。

## 新契约（作为任务接口的共同依据）

### 动态证据：独立于优化标签

配置`optimization.region_evidence='dynamic_decision_v3'`，仅允许与`region_advice='candidate_aware_v1'`、`region_selection='fair_region_v1'`组合。旧三个evidence取值与缺省不变。

保留现有`history_evidence`、每行`signed_residuals`及`decision_evidence`，新增顶层`dynamic_history_evidence`（version=`dynamic_residual_v1`）与每行`dynamic_residuals`。该版本不自动启用目录；因此可单独比较动态证据。

`dynamic_output_summary(output, *, simulation_start_s: float | None) -> dict`输出：`output_valid`、`unit`、`sample_count`、`simulation_start_s`、`status`、`initial_residual`、`dynamic_sample_count`、`displayed_sample_count`、`dynamic_sample_mean`、`dynamic_samples`。残差统一为prediction−observation；仅接收已归一化的V/K，不转换单位。

- 严格读取同次`rate.trace.time_s[0]`作为simulation_start_s；该原始首元素缺失/非有限时为null和`origin_unavailable`，不向后搜索有限时间、不猜测、不以obs[0]替代。
- 观测时间与start精确相等时才产生`initial_residual={time_s,residual}`；其余t>start为动态。有效通道中任何t<start、非单调时间、非有限值或长度错配均抛ValueError，不静默丢点，不降格为invalid_output；有效通道的曲线一致性校验先于origin是否已知的分派。不得用isclose吞掉真实的近初始动态点。
- 无效通道：status=`invalid_output`，残差/动态总数/均值null，展示数0及空数组；起点未知也不把动态总数写0。已知起点且没有动态点：status=`initial_only`、总数0、均值null。存在动态点：status=`dynamic`。
- 动态均值为全部非初始观测残差的等样本算术均值（math.fsum/n），不是时间积分、斜率、温升误差或新增目标。展示残差及均值8有效位；真实时间不做显示舍入。
- n<=8时展示全部动态观测；n>8时按`floor(j*(n-1)/7),j=0..7`选择8个实际索引，含首尾，固定顺序。报告总数/展示数/抽样规则，未展示点仍参与动态均值，不插值生成观测。
- `dynamic_record_summary(record) -> dict`按record.rates分别汇总U/T，各用其原观测网格和同次trace起点。`dynamic_evidence_contract() -> dict`声明上述语义。只对已冻结过去历史构造，不改变评价或RMSE。

### 区域目录：只改提议表达

新增`optimization.region_proposal`，缺省`bounds_v1`，可选`catalog_v1`；后者必须使用dynamic_decision_v3及原candidate-aware/fair组合，未知值或错配拒绝。

`build_region_catalog(context, *, advice: dict, settings) -> dict`仅消费已有shortlist中的eligible alternatives，保留其顺序。对每个候选依次取宽度`min(max_width,k*min_width), k=1,2,4`；同候选重复宽度只保留一次。六维均使用该宽度，lower=`clip(x-width/2,0,1-width)`，upper=lower+width。目录最多33项（现shortlist最多12项，其中1个Plain）；不扩池、不做物理求解、不把几何可行称为物理可行。1/2/4是固定、待验证的表达协议，不是最优区域尺度结论。

目录包含version=`region_catalog_v1`、context_id、pool_digest、ordered entries和catalog_digest。每项含region_id、candidate_id、pool_index、width、lb、ub；region_id对版本/context/候选ID/精确边界做digest，catalog_digest覆盖完整有序内容。Plain不提供项；目录没有偏好/置信度/预测真实目标。

`catalog_proposal_binding(payload: dict) -> str`对完整语义payload做digest，仅排除`artifact_task`、`response_contract`、`proposal_binding`三个键；payload其他字段/Prompt/目录/历史/权重/尺度均纳入。所有字段组装完成后计算，写入顶层`proposal_binding`，最后构造response_contract，避免循环散列。full和compact的region内容均须原样回传该binding；旧bounds模式不新增该字段。

`catalog_region_contract(payload: dict) -> dict`定义新region回复（full/compact外封套仍沿用原严格绑定）：

- region分支仅含`kind='region'`、`coordinate_space='normalized'`、`proposal_binding`、`region_id`、`confidence in [0,1]`、短`reason`（<=400字符）、`evidence_ids`（1–3个不重复的已发送过去history ID）。不接收lb/ub或额外键。
- none分支仅含`kind/coordinate_space/confidence/reason/proposal_binding`，reason同样<=400字符；不得强制选区或抬高confidence。非空evidence IDs只证明引用存在，不证明物理推断正确。

运行时与JSON schema都校验类型；confidence必须是有限int/float且排除bool，ID/reason必须为str，evidence_ids必须为list[str]。不能只发送schema而在resolver接受其他Python类型。

`resolve_catalog_region(response: dict, *, payload: dict) -> tuple[dict,dict]`校验完整封套/重算proposal_binding/目录版本和ID/过去证据ID，然后由host复制精确lb/ub，剥离仅属新提议层的字段，产生旧validator接受的规范envelope，以及结构化resolution证据。没有自动修复、裁剪、匹配最近ID或退回接受旧bounds回复。

在`ElectrothermalLLMController.request`收到且完成原wire解码后、return之前解析目录，以便finally归档一致outcome。调用transport前私有保存完整规范请求序列化，解析时由该副本恢复，不能信任transport可修改的嵌套dict。通过时写`llm/{ordinal:06d}.catalog-resolution.json`：请求身份/proposal_binding/目录digest/模型选择ID/证据ID/confidence/规范矩形；自由reason只作诊断，不参与数值决策。非法回复记录明确`invalid_catalog_response`并返回None，消耗这一次请求且无重试；失败/none/无eligible均沿原plain回退规则。

真实HTTP原回复沿现有档案保存；mock由测试transport提供，不冒充真实请求。新解析证据不含密钥。audit必须同时核对已有HTTP原回复（若有）、wire binding、resolution和canonical envelope；不能只信resolution文件的通过标志。

## Task 1: 非初始动态证据（可独立验收）

**Files:** 新dynamic模块/新dynamic Prompt/新dynamic测试；修改config、llm payload、audit及文档。旧signed/decision接口和旧Prompt不动。

**Interfaces:** consumes `ObservedOutputResult`、`ElectrothermalEvaluationResult`和已冻结历史；produces共同契约的三个dynamic函数。payload仍返回原bounds响应协议。

- [x] **Step 1: 写失败测试。** `test_three_samples_keep_postinitial_temperature_direction`断言T=[0,20,60]、残差=[0,1,-2]时initial=0、动态时间[20,60]、均值=-0.5；U=[0,30,60]独立保持。旧early为0不能令新动态也为0。

  ```python
  summary = dynamic_output_summary(output, simulation_start_s=0.)
  assert summary['initial_residual'] == {'time_s': 0., 'residual': 0.}
  assert summary['dynamic_samples'] == [{'time_s': 20., 'residual': 1.}, {'time_s': 60., 'residual': -2.}]
  assert summary['dynamic_sample_count'] == summary['displayed_sample_count'] == 2
  assert summary['dynamic_sample_mean'] == -0.5
  ```
- [x] **Step 2: 补齐失败矩阵。** 测试无initial、非零start、origin缺失/非有限、t<start、近但大于start、initial-only、无效输出、错单位/形状/时间；n=1/2/8/9/100抽样，其中n=9索引[0,1,2,3,4,5,6,8]，第7项异常仍影响全动态均值。断言输入对象、Y、标签和已冻结GP state的digest未变。
- [x] **Step 3: 执行RED并保存。** 用下方守护入口运行`tests/test_region_dynamic_evidence.py`；预期新模块/新模式未实现导致失败，不能将环境ImportError误作有效算法失败。
- [x] **Step 4: 最小实现上述纯函数及新payload/Prompt/config分支。** 初始点识别来自原trace；历史选择仍用top4+两极值+最近3的有序并集；200–300词Prompt不把权重大解释为贡献大，不以温升越低代替温度误差。
- [x] **Step 5: 独立审计。** 从归档原曲线/观测/完整历史重建起点、索引、全部动态均值及原先有序history；篡改动态残差、时间、起点、遗漏点均值、schema/单位或共同删除history与摘要均失败。旧版本审计不要求新字段。
- [x] **Step 6: GREEN与相关回归。** 新测试及`test_region_signed_residuals.py`、`test_region_decision_evidence.py`、`test_region_payload_repairs.py`、`test_electrothermal_audit.py`；核验旧Prompt SHA未变、默认关闭LLM时0网络/0DFN。实际数量从新JUnit读取。
- [x] **Step 7: 独立审阅后显式提交本任务文件。** 建议commit主题`feat: add past-only dynamic residual evidence for Region`；记录源码指纹和RED/GREEN路径。任务通过只说明证据契约正确，不说明LLM有益。

## Task 2: 有限区域ID契约（独立于任务1的数值算法）

**Files:** 新catalog模块/新catalog Prompt/新catalog测试；修改config、llm request/payload、audit及文档。原wire/优化器/Lift模块不改。

**Interfaces:** consumes Task1的新payload、已有`build_region_candidate_advice`和`InformedSettings`；produces共同契约的catalog/contract/resolver。resolver输出旧canonical envelope供原apply_electrothermal_region使用。

- [ ] **Step 1: 写失败测试。** `test_catalog_is_deterministic_and_contains_no_plain_entry`核对版本/精确宽度/边界平移/稳定ID/最大33项；min=max时每候选只有1项；配置max夹断后重复宽度不重复。目录内没有confidence或声称物理更优的字段。
- [ ] **Step 2: 写回复/隔离失败测试。** 测试合法ID、none、低confidence、NaN/bool/字符串confidence、未知/跨context ID、改目录坐标、错历史ID、重复或超过3个证据ID、附带lb/ub、旧六维回复、错profile/fit_rates/签名、未知配置；full和compact传输都必须通过其原严格封套。另测删/改proposal_binding、只改动态残差或Prompt、transport原地改payload时拒绝受污染绑定，不能以context_id未变就接受。

  ```python
  canonical, resolution = resolve_catalog_region(reply, payload=payload)
  assert canonical['region']['lb'] == entry['lb']
  assert canonical['region']['ub'] == entry['ub']
  assert resolution['proposal_binding'] == payload['proposal_binding']
  assert set(canonical['region']) == {'kind', 'coordinate_space', 'confidence', 'reason', 'lb', 'ub'}
  ```
- [ ] **Step 3: 执行RED。** 新catalog测试应因缺模块/未支持配置失败；保存日志/JUnit/退出码，错误原因应落在新契约。
- [ ] **Step 4: 最小实现目录/回复契约/resolver及payload/controller分派。** 目录选点仅改提议编码；所有新Prompt200–300词，原Prompt字节不变。request中解析失败发生在finally前，outcome/round/成本保持一致；同一个失败请求不自动重发。无eligible不请求。
- [ ] **Step 5: 守卫与数值不变测试。** 在同一冻结上下文和同一规范矩形下，旧bounds与ID映射得到相同锚点、raw shift、fair baseline、选点及反馈；物理锚点拒绝、合法region但fair拒绝、same_as_plain和none仍可出现，不以提高采纳率为验收。新旧配置运行身份不同，不能直接要求context hash相同。
- [ ] **Step 6: 独立审计及篡改测试。** 从冻结pool/advice/history重建目录，核对resolution/真实HTTP回复或mock结构证据/规范矩形；独立重建response_contract并逐项核对，不能因其被循环散列规则排除就允许篡改。共同改ID与矩形、目录顺序、confidence、evidence IDs、历史删行、wire binding或请求ordinal均应拒绝。以原始曲线重算Task1信息，避免多个存档摘要共同篡改绕过。
- [ ] **Step 7: GREEN与相关回归。** 新catalog测试及`test_region_json_wire.py`、`test_region_request_policy.py`、`test_region_failure_audit.py`、`test_region_fairness.py`、`test_region_decision_evidence.py`。mock完整流程分别运行ParEGO、WarmStart-only、Full-none和合法ID，0真实网络/0DFN；旧配置/旧缓存签名仍严格。
- [ ] **Step 8: 独立审阅后显式提交。** 建议commit主题`feat: add request-bound Region catalog proposals`。保存解析成功、失败和守卫拒绝的全部正负证据，不把mock表现称为真实优化增益。

## Task 3: 全量软件验收与可审阅的下一步协议

**Files:** 仅补充本计划进度、docs/llm-informed及新audit文档；如回归暴露产品问题，修复后重跑受影响针对性测试与最终全量，不能掩盖旧失败。

**Interfaces:** consumes Task1/2提交、源码签名和新测试档案；produces实际验收报告、显式变更清单、sealed SHA及默认0资源的后续协议草案。

- [ ] **Step 1: 新基线。** 实施Task1前先在计划提交后的干净树运行一次全量守护测试；记录总数/通过/失败/错误/跳过/退出码。与历史530仅作诊断比较，任何失败区分既有、环境或新引入。
- [ ] **Step 2: 最终新全量。** Task1/2针对性检查通过后，用新label运行整个tests。软件允许有限维/代数mock与非电池进程fixture；禁止真实DFN及外部API。报告实际耗时、线程设置和BoundaryGuard计数。
- [ ] **Step 3: 只读兼容与保护。** 选择已封存旧电热档案按原来源审计，不重签或改写；复核旧电压相关回归、旧Prompt和原数值模块hash。旧审计若GP.from_state调用fit(max_sweeps=0)，分别报告fit方法次数与超参数搜索0，不宣称fit方法0。主工程status/index/Method/123受保护文件保持。
- [ ] **Step 4: 结果报告。** 验收单列代码完成/软件通过/真实API行为未验证/真实DFN增益未验证/实测未开展。归档每个任务RED和GREEN及最终JUnit、退出码、commit、源码指纹、审阅和完整成本。只用显式文件清单提交。
- [ ] **Step 5: 准备不执行的下一步协议。** 先选择固定过去上下文和确切payload做少量API契约预检草案，再决定共享初始化配对；数量/超时/截止时间须届时给出具体可审阅协议，不在本计划默认赋值。既有101/211/307标开发诊断种子，留出验证另预注册。旧256次DFN实验已完成，不复用其剩余API额度。

## 可执行的软件命令与证据位置

以下命令是**计划批准后的命令**，本次编写计划未执行测试。使用任务专用变量，不覆盖HOME/CODEX_HOME。

```powershell
$etPython = 'D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe'
$etManager = 'D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\region-dynamic-catalog-20261020\run_tests.py'
& $etPython -X utf8 -B $etManager test dynamic-catalog-baseline tests
& $etPython -X utf8 -B $etManager test dynamic-evidence-red tests/test_region_dynamic_evidence.py
& $etPython -X utf8 -B $etManager test dynamic-evidence-green tests/test_region_dynamic_evidence.py tests/test_region_signed_residuals.py tests/test_region_decision_evidence.py tests/test_region_payload_repairs.py tests/test_electrothermal_audit.py
& $etPython -X utf8 -B $etManager test region-catalog-red tests/test_region_catalog.py
& $etPython -X utf8 -B $etManager test region-catalog-green tests/test_region_catalog.py tests/test_region_json_wire.py tests/test_region_request_policy.py tests/test_region_failure_audit.py tests/test_region_fairness.py tests/test_region_decision_evidence.py
& $etPython -X utf8 -B $etManager test dynamic-catalog-final tests
```

命令按任务顺序分别执行，不一次性粘贴运行；RED必须在实现前，baseline必须先于Task1所有产品与测试写入。runner将OMP/BLAS线程设1、阻断网络/native solve，并保存到`bo-repair-work/20261017_et_implementation/tests/<label>-<timestamp>/`的pytest.log、junit.xml、result.json、exit-code.txt。GREEN要求实际退出0且failures/errors0；skip逐项解释，不能用跳过掩盖新功能。每次最多等待60秒并持续报告进度，长测试使用后台会话轮询。

## B变体的独立前置决策（不属于本计划产品实现）

文献建议B仍是独立研究候选，不自动随着Task1/2合入。另行规格/计划需首先确定：

1. 归一化使用同一个latent posterior covariance。当前predict把variance floor到1e-14，旧Region的K_AA另加1e-6I；不能混用后声称是latent L的精确标准差。
2. 最小化signed delta=`gamma*K_xA*a/sqrt(a^T*K_AA*a)`保留负协方差的符号；不得套用旧非负raw_shift校验或静默加jitter。负小特征值/零方差/退化v的容差、诚实回退和状态必须显式规定。
3. “同gamma”不等于同作用预算。共同冻结参考池Q、latent sigma、`max_Q(abs(delta)/sigma)`及退化排除规则需预注册；不得以看到真实结果后的幅度调节获得优势。保留legacy原幅度对照与matched-budget形状对照，不能把归一化后的新相关性臂称原legacy。
4. 原GP训练标签/方差不改，只构造采集视图。signed场下的same-field Plain、原Plain及fair gate/shadow全池赢家要分别可复算；取消fair或改候选供给均属另一个实验因素。

因此A的软件交付不包含新公式/移除截断/调强度/去退火/去consistency；更不包含对RMSE或HV一定增益的承诺。

## 本次计划交付状态

- [x] 重新核查工作树干净，读取现实现/旧计划与已封存文献设计。
- [x] 明确A1/A2独立版本、函数接口、失败测试、兼容和验收命令。
- [x] 数学/数据接口独立计划审阅完成并保存证据。
- [x] 用户批准本具体软件计划（直接答复：批准 A1→A2 软件实施）。
- [ ] 新基线、任务实现、RED/GREEN、最终全量及任何真实性能验证。

实施进度：已获直接批准并完成新基线530/530；A1完成52项新测试及最终相关114/114、独立审阅和证据。A2与最终全量待执行，API/DFN仍0；软件fixture包含GP拟合，不宣称本轮GP拟合为0。Windows测试薄适配器沿用manage.py守护逻辑，仅绑定本计划独立LEDGER；首次缺__main__重入中断及修复重跑记录完整保留。

独立审阅位于`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/literature-design-20261020-plan-review/`：`final-plan-math.json/md`、`final-plan-data.json/md`均PASS、未解决阻断0，审阅主体快照SHA为`5dcf7a29cce8397d8da41a7b04d606b8e1fc11e28f00e4e713517f1e662d6511`。其后主审仅补强运行时类型/response_contract独立核对要求及进度状态，没有改变数据或数值设计。主审自检已覆盖规格、步骤粒度、前后接口、五类Review Focus和计划范围；没有将B的未决参数带入A实施。
