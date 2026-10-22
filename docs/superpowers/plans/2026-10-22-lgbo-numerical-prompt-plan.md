# LGBO Numerical Controls and Separate Prompt Enhancement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 先以配对软件对照检验候选密度和GP拟合预算，再独立增强当前权重下的Prompt信息，分别交付证据。

**Architecture:** Stage A只用现有配置入口和独立研究脚本，不改Region公式或候选生成算法。Stage B在Stage A封存后，以单一策略版本lgbo_v2加入加权分量和新Prompt；v1的提示词与行为保留，数值骨干共用。两阶段不混合宣称性能增益。

**Tech Stack:** 当前Python3.12、锁定NumPy/pytest/PyBaMM25.10.2、现有Sobol6/Matern52GP/Gaussian EI及原生owned-worker时限；无新依赖。

**Spec:** 用户已选择[诊断报告a6120ba](../../audits/lgbo-region-optimization-options-2026-10-22.md)的“先比较更密候选与相同GP拟合预算，再单独优化Prompt”。数学与物理遵循[已批准LGBO设计](../specs/2026-10-22-lgbo-region-simplification-design.md)及Method。**本详细计划待审批；当前仅写计划，产品修改和新运行尚未开始。**执行方式沿用本会话原生逐任务实施，最后一次独立整体审阅。

## Global Constraints

- 复用C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para，分支codex/electrothermal-mo-20261016；计划前HEAD=a6120ba1203b9d4067b1a1a9f5e2fceb97925c16，Git干净。主工程/参考工程/旧源码/旧实验/旧账本只读；显式文件清单，不git add .。
- 六参数4E+2T、双RMSE、DFN+lumped、配置化fit_rates、固定目标尺度/HV及真实目标契约不改。旧schema1四倍率行为保留；本计划软件对照仅0.5C/1C，旧3C不用于新优化。
- lambda=c/sqrt(a.T*Kaa*a)、负向均值倾斜、有符号协方差、原方差和真实incumbent不变；32锚点及1e-12容差不变。无新核、长度尺度先验、目录、信任/退火、竞争守卫、区内强制选点或候选锚点扩充。
- 当前权重仅用已有历史重建全部标签/标准化/incumbent/局部中心/后验；选点和反馈保持同一冻结上下文，失败轮也换权重。只收完整真实软件目标对，不补零。
- 单线程；真实API/DFN/实测/服务器预算均0，不读凭据、不重试。Stage A软件实验上限见下；单元测试的人工夹具调用另记账，不混入正式实验数量。
- lgbo_v2只版本化Prompt与解释字段，不是新数值方法。新旧方法仍只通过optimization.region_method选择，不新增可堆叠开关；旧Prompt字节保留，旧签名校验不放宽。
- source_fingerprint覆盖所有src/Prompt。增加v2会改变包括v1配置在内的新源码指纹；旧档案按自身旧源码审计，不重签。阶段A/B初始化分别由其实际源码生成。
- 全部负结果、失败、退出码、曲线和成本保留。更多候选、更高采纳率、软件通过均不等于LLM/DFN/实测增益。

## Review Focus

1. 四档配置意外串改/使用不同拟合政策：Task1验证深拷贝、固定局部池、同组Plain/Full一致，实际优化步数和拟合耗时分别归档。
2. 导入旧85f源码计划或把筛选落选8点泄漏入GP：Task1验证旧源码拒绝，只有新计划选中8点进入训练；四档合法共用同一初始化兼容签名。
3. 增大候选数同时改变随机消耗与比较定义：Task1/2核对同组同种子重现，记录完整候选；不同历史/密度不宣称同池反事实，不擅改现有Sobol算法。
4. 超时、部分目标、缓存导致伪造完整24组：Task1/2验证硬停止、累计成本、缺失标记、无重试，无结果不得填0HV/RMSE。
5. v2解释字段、单位、精确同分及旧回复重放：Task3/4验证两个分量/augmentation、V↔mV、零权重/相等目标、版本绑定及独立篡改审计；不从mock声称Prompt更好。

---

## Selected Protocol

### Stage A — 2×2数值设置，固定mock建议

| cell | global_pool_size | local_pool_size | gp_sweeps |
|---|---|---|---|
| G016_S0 | 16 | 8 | 0 |
| G512_S0 | 512 | 8 | 0 |
| G016_S4 | 16 | 8 | 4 |
| G512_S4 | 512 | 8 | 4 |

- 种子17/41/59，各cell两臂：warmstart_only（共享初始化的Plain-EI）和full_llmbo_mo。lgbo_v1固定矩形[.3,.8]^6、c=.65；不调用真实WarmStart/Region。
- 每臂8初始化+20轮，local_radius=.2；目标尺度[.1,1]、rho_aug=.05、ideal=[0,0]、HV参考[10,10]（Y/scales），权重列表[[.8,.2],[.2,.8],[.5,.5]]不变。
- 人工软件模型和4秒**观测时间窗**沿用当前夹具；4秒不是每次调用的CPU耗时或超时。不能将这些结果外推至60秒DFN或实测。
- 首先在Stage A实际源码下，用Sobol6(17)的16个参数候选重新评价，按既有Pareto＋Max–Min规则选8个。落选8点只用于筛选证据，不进入任何臂的训练/决策历史。
- gp_sweeps=0仍每轮条件化数据；4是最多4个既有MLL坐标搜索sweep，允许按现有规则提前停止，不保证每个长度尺度必然改变。双方同设置/停止规则，不以实现时长恰好相等为标准。
- 总24个优化运行、最多480个BO候选评价+16个筛选评价=496个新软件候选评价，两倍率最多992次software_call；导入8点不重复计费，缓存命中另记，失败不补候选、不重试。
- 单轮目标不完整时按现有失败轮规则保留部分结果、换权重继续，不补点。完成是指24个运行各完成20个BO尝试且审计通过，不要求伪造每轮完整目标；有效目标数量及失败成本另报。
- 实验总硬墙钟3600秒（含筛选、BO、深审计和报告）；每个优化运行的模型工作流最多120秒并受剩余总时限约束。3600秒不含pytest。任一运行未完成/审计失败或总预算耗尽即停止本批次，不开启后续case、不转入Stage B、不重置计数。
- 固定cell顺序如表；seed17/59先Plain后Full，seed41先Full后Plain。独立确定的权重/局部候选流沿用现有实现，mock无随机消耗；不同密度的全局Sobol流不宣称逐轮前缀相同。记录原始池/种子/源码，让密度作为完整现有配置比较。
- 输出每seed的delta(cell)=HV_Full−HV_Plain；分别报告密度差、拟合差及描述性交互差。报告全部运行级结果，不能把480轮当480个独立统计样本；三种子且同一初始化仅支持条件性探索结论。
- 代表参数按固定等权增广Tchebycheff从Pareto选，同一参数报告两个RMSE及每倍率误差。不得改参考点、只挑最低电压或只留赢的seed。

### Stage B — 单独增强Prompt，不混入Stage A

- Stage A先完成24组及其审计、汇总和源码/脚本签名封存，再开始任何src/Prompt修改。后续Prompt配置预定使用G512_S4，不按Stage A胜负选最优配置；如该配置未完成，先报告阻塞，不私自替换。
- region_method=lgbo_v2；增加history行的weighted_objective_evidence，q_j=w_j*(F_j/s_j−z_j)，g=max(q)+rho_aug*sum(q)。z以归一化目标空间表示，首版仍[0,0]。
- 输出version、weighted_components、max_component、active_objectives、augmented_scalar；最大分量以未舍入值比较，相等者全部列出，不新增同分容差改变目标。
- 新200–300词英文Prompt要求根据当前瓶颈和已有动态残差给一个矩形；证据不足的维度允许宽边界。保留已有top4/极值/recent3，不增加解释、reason、目录或证据ID，不声称观察关联是单参数因果。
- wire仍为lgbo_action_v1、回复仍仅request_id/region；request_id本来覆盖完整payload和region_method。v1/v2数值规则完全相同；用相同合法动作应数值等价，但上下文ID/配置签名可以不同。
- 本计划仅软件契约/TDD，不运行真实Prompt效果实验。后续真实API/DFN确认种子预留101/131/167，须另批协议/预算；固定mock相同动作只能证明接入一致，不能证明新Prompt有效。

## Task 0: 新基线、保护及本计划证据入口

**Files:** 新证据根目录D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-numerical-prompt-20261022/；新账本.superpowers/sdd/2026-10-22-lgbo-numerical-prompt-plan/progress.md，不写旧计划账本。

**Interfaces:** 只读复用既有protect_workspace.capture()、baseline.BoundaryGuard、manage.py的受控pytest；新测试适配器只覆盖新PLAN/LEDGER并使用新label。

- [ ] 重查Git/worktree/源码指纹；保存审批、主工程保护快照、锁文件、数值模块及lgbo_mean_tilt AST。955仅是历史最终结果，不代替新基线。
- [ ] 设置OMP/BLAS等线程1、清空PYTEST_ADDOPTS、禁真实网络和电池solve；完整tests真正结束后保存pass/fail/error/skip、退出码、日志/JUnit和边界计数，分类并处理失败。
- [ ] 建立新runner和独立短临时目录；不安装依赖、不初始化CodeGraph、不改变任何旧实验。

## Task 1: Stage A脚本、配置及可核验协议（TDD）

**Files:** Create scripts/run_lgbo_numerical_ablation.py、configs/electrothermal-lgbo-numerical-ablation-software.json、tests/test_lgbo_numerical_ablation.py。src及现有模板不改。

**Interfaces:**

- ablation_protocol(base_config: dict) -> dict：生成上述唯一矩阵/24个case/种子/顺序/预算/固定mock，深拷贝原配置；拒绝非synthetic_software、非software provider、非R2及任何真实LLM/求解预算。
- make_case_config(base_config: dict, *, global_pool_size: int, gp_sweeps: int, seed: int, mode: str, initial_plan: dict) -> dict：按cell生成完整配置；只接受所选矩阵和两臂。
- run_software_ablation(base_config: dict, output: Path) -> dict：新建输出目录，先封存protocol/script/source/配置摘要，再执行筛选和case、深审计及汇总；默认CLI仅--dry-run，显式--execute才启动。
- _ablation_worker(protocol: dict, output: str, connection) -> None：复用run_with_deadline协议的owned child，内部先启用零网络/零电池guard再导入运行器；全局硬时限含此worker，结束/超时关闭自有子进程。
- summarize_numerical_ablation(case_results: list[dict]) -> dict：检查24组覆盖/签名/共同初始化，输出运行级对照；缺失结果标记不完整而非0。拟合时耗可在脚本内用一对一委托fit观察器记录，不改变参数、调用数或state_dict；BO拟合与审计重拟合分别计时。

- [ ] RED：test_factorial_matrix_and_no_config_mutation固定四档/24组/local8/两臂一致，拒绝意外method/provider/seed/mode/非零真实预算；脚本不接受密钥参数，未execute不能评价。
- [ ] RED：test_initialization_semantics_and_no_screening_leak证明旧85f源码计划拒绝；新计划四档config/algorithm不同而initialization_compatibility相同，通过现有load_initial_plan原样导入，训练仅8点，原文件字节未改。
- [ ] RED：test_seeded_pools_and_fit_policy_reproduce验证相同case重现、不同mock不消耗数值随机流，0仍条件化数据，4实际完成1–4个sweep且无新先验/混合核。不要断言不同历史的两个臂池完全一样。
- [ ] RED：test_budget_timeout_partial_and_cache_accounting验证496/992封顶、未完成目标/缓存/失败分开记录、不补零/重试；实际owned-worker超时终止、不泄漏进程、缺少最终boundary快照时标记unknown不能伪造0。
- [ ] 执行并记录RED后最小实现；配置复制现有人工固定物性及数据定义，仅按R2精确裁剪data/conditions键。用现有proposer/controller/evaluator/initial-plan接口，不绕过验证或导入旧plan后改signatures。
- [ ] 跑针对性GREEN及旧MO/初始化/软件边界相关测试，保存独立证据；显式提交这三个文件。

## Task 2: 执行Stage A并封存（不改产品）

**Files:** 只写本计划新证据根目录stage-a/，Create docs/audits/lgbo-numerical-ablation-2026-10-22.md；scripts文件仅在已发现实际缺陷时按RED/GREEN修复。

**Interfaces:** Task1的run_software_ablation、summarize_numerical_ablation；现有run_electrothermal_experiment与audit_electrothermal_run(deep=True)。

- [ ] 先--dry-run核对协议、真实API/DFN0、脚本/source指纹，后--execute一次；启动时冻结3600秒时限，逐case归档，不自动恢复。
- [ ] 用当前源码重新评价16个筛选点，导出不可变8点计划及原始筛选成本。只原样引用其path/hash；同一source/初始化兼容签名通过现有规则跨24组共用，不重签、不把16点都用于GP。
- [ ] 完成24个20轮run及全部深审计；记录尝试/完整对/缓存/新软件calls/GP拟合调用与sweep/拟合耗时/总耗时。观察器必须逐次委托原fit，测试确认开启/关闭科学输出完全相同。
- [ ] 输出protocol.json、run-index.jsonl、case-configs、每轮RMSE.csv、representative-RMSE.csv、factorial-contrasts.csv、summary.json及保护/边界/退出码；按完整共同初始化的run-level配对报告，不隐藏负值。
- [ ] Stage A任何缺失/预算失败使seal状态为incomplete；完整则保存所有case/源文件/计划/成本摘要的stage-a-seal.json。未完整前不进入Task3。
- [ ] 审阅实际结果并记录覆盖改善是否发生、Full−Plain是否改变；不把数值骨干共同改善或mock效果写为LLM收益。提交报告，保留原24档全部记录。

## Task 3: v2当前目标解释和Prompt（Stage A封存后TDD）

**Files:** Create src/llmbo_para/electrothermal_region_context.py、src/llmbo_para/prompts/region_preference_lgbo_v2_electrothermal.txt、tests/test_lgbo_weighted_context.py；Modify electrothermal_lgbo.py、electrothermal_config.py、electrothermal_llm.py、electrothermal_lgbo_wire.py、electrothermal_region_wire.py、electrothermal_requests.py；Extend tests/test_lgbo_region_wire.py。均不改surrogate/scalarization/acquisition/pareto/物理层。

**Interfaces:**

- weighted_objective_evidence(objectives, *, weights, objective_scales, ideal, rho_aug) -> dict：原生有限双目标校验，返回version='weighted_tchebycheff_v1'、weighted_components、max_component、active_objectives（F_U_V/F_T_K）、augmented_scalar。
- is_lgbo_method(value: object) -> bool；lgbo_prompt_filename(method: str) -> str，放在electrothermal_lgbo.py统一识别v1/v2，拒绝未知版本；保留METHOD='lgbo_v1'供旧调用。
- validate_lgbo_region(..., expected_region_method='lgbo_v1')和apply_lgbo_region(..., region_method='lgbo_v1')增加可选关键字，缺省保持v1；lgbo_mean_tilt函数本身不改。
- build_electrothermal_payload签名不变，仅v2行增加weighted_objective_evidence并选择新Prompt；lgbo_request_id/decode_lgbo_action按payload明确method绑定，wire字段和WIRE_VERSION不变。

- [ ] RED已知样例：Y=[.04,.3],w=[.8,.2],s=[.1,1],z=[0,0],rho=.05，q约[.32,.06]、g约.339、active=[F_U_V]；精确同分Y=[.05,.5],w=[.5,.5]得到q=[.25,.25]、g=.275、两者active。
- [ ] RED：零权重/全零误差/不均尺度、V→mV且尺度同步、布尔/NaN/错误维数/非零ideal/非有限派生值拒绝；所有合法行的augmented_scalar与冻结current_scalar_g一致，不舍入训练标签。
- [ ] RED：v1在相同注入冻结身份下payload/Prompt逐字保留，WarmStart不增字段；v2单一配置合法且拒绝旧控件混用；改版本/weighted分量/Prompt后旧request_id拒绝。
- [ ] 先记录RED再实现辅助函数与版本分派，Prompt200–300词，只返回原动作；保留宽维度/温度误差语义，不新增因果方向断言或reason字段。
- [ ] 运行GREEN及旧wire/controller/Responses相关回归后显式提交。本任务仅完成请求接口，v2工作流/审计属于Task4，暂不发布v2运行模板。

## Task 4: v2数值等价接入和独立审计（TDD）

**Files:** Modify src/llmbo_para/mo_optimizer.py、electrothermal_lgbo_audit.py、electrothermal_audit.py；Create tests/test_lgbo_v2_workflow_audit.py、configs/electrothermal-sub2api-lgbo-v2-software-template.json。新模板由Task1的R2软件模板复制，旧v1模板/Prompt保留。

**Interfaces:** MOOptimizer.step/summary及audit_lgbo_round签名不变，识别两版本并传明确method；_independent_tilt增加region_method关键字但仍独立推导原公式。新模板沿用Task1的R2物理/数据定义、G512_S4、mode=parego、LLM禁用及API/DFN0；只将method换为v2。

- [ ] RED：相同有效初始化、权重/尺度/GP/候选和规范动作，v1/v2的mean/std/delta/EI/选中参数/真实Y一致；配置/context ID可不同，不要求跨版本ID相等。第13轮和无完整目标后的换权重规则均保持。
- [ ] RED：用离线HTTP替换边界走两种生产worker，v2合法region/none及未完成/坏JSON/错binding均可独立审计；旧v1/旧策略回归继续。缺失已解码原始回复仍须审计失败，真实无回复故障仍保留。
- [ ] RED：篡改weighted_components、active_objectives、augmentation、method、Prompt或真实温度曲线均被发现。审计从已核验历史Y/当前w/s/z独立重算解释字段，不只调用producer辅助函数比较自身输出。
- [ ] 最小接入后GREEN；增加v2改变全源码指纹，重新评价软件夹具建立Task4测试计划，不将Stage A初始化换签。可共享的是当前新源码下v1/v2的初始化兼容签名。
- [ ] 归档v2软件接入结果并显式提交。固定mock同动作仅验数值/契约等价，不运行或声称真实Prompt增益。

## Task 5: 最终回归、审阅与交付

**Files:** Modify docs/llm-informed.md、docs/Method.md；Create docs/audits/lgbo-numerical-prompt-validation-2026-10-22.md；未来真实确认协议只存本计划证据根目录，不启动。

- [ ] 完整tests新回归并记录实际数量、通过/失败/错误/跳过、退出码、日志/JUnit和边界；不以旧955充作本轮结果。一次独立整体审阅，Important/Critical以新RED/GREEN修复，源代码再变动才补相应验证。
- [ ] CLI软件预检、v1/v2深审计及主工程保护核验；核对lgbo_mean_tilt、旧Prompt、固定物性、锁版本及数值骨干未变；记录Stage A/B指纹不同的原因。
- [ ] 汇总Task0–5显式文件清单、commit、Stage A完整/不完整状态、负结果、v2契约验收和仍未验证内容；保留分支/工作树，不自动merge/push/清理。
- [ ] 形成真实API/DFN确认协议草案：G512_S4、独立种子101/131/167、同source共享初始化、预算和停止条件另行提交审批。当前API/DFN额度仍0，不复用过去已结束的额度。

## Self-review and Handoff

已按实际provenance区分config/algorithm与initialization_compatibility，避免过严误拒合法数值消融，也不放宽跨source核验。4秒为人工观测窗口而非CPU限制。Stage A固定mock、正常拟合与候选密度的四档对照，Stage B版本化Prompt的契约验证，真实LLM/DFN确认三者分别验收。所有Review Focus有Task1或Task3/4失败测试归属。独立协议复核提出的成本/随机流/初始化泄漏/统计单位问题已逐条落实；该复核不代替本计划逐接口、逐测试的自审。

方向已确认；详细计划尚未批准，当前不修改产品代码、不运行新测试或BO。请审阅本计划；批准后按当前会话原生执行方式从Task0开始，每阶段保存证据再推进。
