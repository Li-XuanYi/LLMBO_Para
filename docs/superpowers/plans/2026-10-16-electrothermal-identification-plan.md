# Electrothermal Identification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. 本会话原生顺序实施；不自行派出代理。计划审批前不执行下列产品代码任务。

**Goal:** 在保留v1四倍率电压任务的前提下，按可配置拟合倍率集合实现既定4E+2T电热双目标LLMBO-MO及分层验证。

**Architecture:** v2严格分派到独立数据、映射、评价和MO优化器，共用六维GP、Sobol、RunStore及安全传输。fit_rates贯穿评价/签名/缓存/初始化/审计，优化器不固定3或4。先完成非LLM的ParEGO闭环，再接既定WarmStart和Region-Lift。

**Tech Stack:** 现有Python3.12.10 / PyBaMM25.10.2 / NumPy2.5.3 / SciPy1.18.1 / pytest8.4.2；不新增依赖。

**Spec:** docs/superpowers/specs/2026-10-16-electrothermal-identification-design.md（R1.1）；论文口径见docs/Method.md。路径沿用用户指定的2026-10-16文件名，首次生成日期为2026-10-17。

## 审批与当前状态

Stage 0检查基点0e01af26b3fac8a6754165421d0eca3b0b4dab9e，分支codex/electrothermal-mo-20261016，工作树C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para。最新已有提交只增加Method，当前无电热模块、无此前正式计划。保护提交a5d298d及主目录用户修改保留。本计划已获用户明确批准；Stage A软件验收完成（255/255），B/C顺序继续；真实物理/实测验收另按预算和数据门槛执行。

2026-10-16的215通过/退出码0是已有基线证据，不能当作本次Stage 0或后续阶段的新测试结果。Stage 0只核查和修订文档。批准后A0重跑当前全量回归，再写新增失败测试。

## Global Constraints

- 同一组六参数：[eps_s_n,eps_s_p,D_s_n_ref,D_s_p_ref,C_th,G_th]；DFN/P2D＋单节点lumped thermal；两个误差目标[F_U,F_T]，无额外热变量/目标/GP-LLM核。
- v2显式fit_rates，当前研究模板为[0.5C,1C,2C]；旧3C来源禁用，可靠新3C以后另建数据/配置加入。v1的RATE_ORDER、四倍率语义及严格缓存核验保留。
- v2不得缺省回退旧RATE_ORDER、固定除以3/4、根据候选成败删倍率，或直接复用不同倍率协议缓存。
- 目标尺度/HV空间在比较协议中固定，合法零理想点；每轮选点与反馈冻结上下文；失败/缓存轮次后换权重也重新拟合。
- 只用完整真实目标对训练；同一输入去重，不同参数同目标不去重；部分输出/失败保留，不补零。
- 单worker，BLAS/OpenMP单线程；密钥不进入配置、日志、命令或快照；参考New_LLMBO只读，不用sys.path依赖它。
- 当前付费API、实际新增DFN求解、实测BO、服务器任务预算均为0。mock与解析软件检查可以执行，真实DFN只在另获明确轻量预算后执行。
- 旧实验/缓存/原XLSX保留；禁止git add .、reset/clean、修改旧哈希或静默更换Chen2020固定物性。

## Review Focus

1. 原工作簿含损坏但未选择的3C：不读其观测、不影响三倍率完整性；选中被排除source_id则拒绝。归属A1/A2/A5。
2. 当前三倍率与未来四倍率数值维度均为二维：靠倍率/数据签名隔离，不能按形状通过缓存。归属A5/C3。
3. 某候选2C温度失败但另两倍率成功：目标对null、分母不缩小、成本不漏记。归属A3/A5/B3。
4. 重复输入与不同参数相同Y：前者不重复训练，后者保留两个样本，零标签方差不报错。归属B1/B3。
5. Full与WarmStart-only共享初始化但模式配置哈希不同：校验独立初始化兼容签名，Region开关不触发重求解；改倍率/物性则拒绝。归属A5/C1/C3。

## 文件和公共类型约定

所有产品文件位于src/llmbo_para。新增electrothermal_config/data/parameters/evaluation/provenance/store/synthetic/llm/audit.py和scalarization.py、pareto.py、mo_optimizer.py；小改既有parameters.py、config.py、reference_cell.py、pybamm_adapter.py、metrics.py、workflow.py、cli.py、acquisition.py及必要归档入口。旧Optimizer不承载MO逻辑，旧informed.py只按需要提取纯数学函数，不能调用其绑定log-J的决策路径。

FitRates=tuple[str,...]，在A1的electrothermal_config.py定义并由后续模块导入；保留配置执行顺序，非空且无重复。首版标签域0.5C/1C/2C/3C只在v2边界验证。数据/求解/算法消费传入的FitRates，不导入旧RATE_ORDER作为默认值。所有新整数预算拒绝bool。

v2固定optimization.mode字符串为parego、warmstart_only、full_llmbo_mo；数据使用data.by_rate及data.exclusions，前者只包含fit_rates成员，后者记录source_id/原因。研究source_id由原文件SHA与sheet身份确定，不能靠重命名dataset_id把同一旧3C变为新数据。共享初始计划读取单独的initialization_compatibility，不要求三路线完整config哈希相同。

测试共用tests/electrothermal_fixtures.py：A1提供et_config(fit_rates)，A2提供et_dataset(fit_rates)，A3提供基于该数据的代数SyntheticElectrothermalSimulator及完整/部分结果样例。后续任务只扩充自己需要的fixture，不修改旧测试预期。

## 验证命令和证据约定

以下PowerShell准备在计划批准后、开发工作树执行。现有解释器保持绝对路径；每次red/green/full使用新的短临时目录，避免删除已有pytest目录或触发已知长路径限制：

~~~powershell
$Py = 'D:/Users/aa133/Desktop/LLMBO_Para/.venv-pybamm312/Scripts/python.exe'
Set-Location 'C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para'
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:NUMEXPR_NUM_THREADS='1'
$env:PYBAMM_DISABLE_TELEMETRY='true'
$env:PYTHONDONTWRITEBYTECODE='1'
function Check-ET($label, [string[]]$targets) {
  $id = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
  $ev = "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/et-$id-$label"
  $tmp = "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/t-$id"
  $proc = "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/p-$id"
  New-Item -ItemType Directory -Path $ev,$proc -ErrorAction Stop | Out-Null
  $env:TEMP=$proc; $env:TMP=$proc
  & $Py -X utf8 -B -m pytest @targets -q --basetemp $tmp --junitxml "$ev/junit.xml" *> "$ev/pytest.log"
  $code=$LASTEXITCODE
  Set-Content -LiteralPath "$ev/exit-code.txt" -Value $code
  [pscustomobject]@{Evidence=$ev; ExitCode=$code}
}
~~~

每个任务步骤中Check-ET第二参数为明确测试文件数组；red必须观察到新增契约尚未实现导致的失败，保存退出码/原因，不能将无关既有失败当红灯。green要求对应文件0失败/0错误/退出码0；A/B/C各阶段收尾跑Check-ET 'A-full' @('tests')等全量回归，实际数量以新日志/JUnit为准。审计另存源码/配置/签名/成本及停止原因；所有命令输出不可覆盖旧证据。所有git add均使用任务明确清单，提交前检查暂存差异无其它文件。

---

## Stage A：物理接口和评价闭环

### A0：核验源码并运行当次基线

**Files:** 只读现有src/tests/configs/锁文件；新证据docs/audits/electrothermal-stage-a-2026-10-17.md（或实际完成日期）。
**Interfaces:** 输入当前分支/保护清单；输出本阶段基线日志、JUnit、退出码及源码指纹。

- [x] 重查status/diff/worktree，确认没有并发用户修改；核验当前123个产品文件和锁文件相对Stage 0指纹，新增变化需先解释归属。
- [x] 执行Check-ET 'A-baseline' @('tests')，保存实际统计。失败时区分原有/环境/新增问题；未定位前不把新功能写成回归通过。
- [x] 确认无新增实际DFN solve/真实API；已有eSOH代数兼容检查不计作DFN合成验证。
- [x] 仅显式提交本阶段基线审计文档；不提交临时测试目录。

### A1：参数方案、严格v2配置和倍率协议

**Files:** Modify parameters.py、config.py；Create electrothermal_config.py、electrothermal_parameters.py（先定义参数方案）、configs/electrothermal-synthetic.json、configs/electrothermal-research-template.json；Test tests/test_electrothermal_config.py、tests/test_electrothermal_parameters.py、tests/electrothermal_fixtures.py。

**Interfaces:** 保留ParameterSpace旧构造/方法；末尾增加profile字段默认voltage_6p，from_bounds增加同名keyword-only默认参数。新profile为electrothermal_4e2t，名字/角色/单位/变换有独立常量与定义。config.configuration_errors和parameter_space_from_config先按版本严格分派。

~~~python
validate_fit_rates(value: object) -> FitRates
electrothermal_configuration_errors(config: dict) -> list[str]
electrothermal_space_from_config(config: dict) -> ParameterSpace
~~~

- [x] 写失败测试test_v2_requires_explicit_fit_rates_and_old_v1_stays_four_rate：缺fit_rates、空/重复/错误标签/bool拒绝；R3/R4均可通过合成结构校验，v1原配置仍有效且不接受v2字段。
- [x] 写test_pending_research_and_excluded_source_are_not_assumed_confirmed：旧3C source_id选中则拒绝；三倍率研究模板同时列出实际电流/T语义/初态/冷却/热范围等缺失项。
- [x] 写test_profiles_with_six_values_have_different_semantics：六维旧电导率方案不得被当作C_th/G_th；新扩散log10、单位/正值/孔隙约束验证。
- [x] Check-ET 'A1-red' @('tests/test_electrothermal_config.py','tests/test_electrothermal_parameters.py')；观察新增函数/契约缺失后最小实现。research模板用null/pending，显式fit_rates=R3和旧3C排除来源；synthetic自洽物理数字仅标为fixture。
- [x] Check-ET 'A1-green' @('tests/test_electrothermal_config.py','tests/test_electrothermal_parameters.py')；显式git add上述9个文件后提交。不得以统一放松schema或参数名校验获得兼容。

### A2：输入/观测分离、单位和动态倍率数据

**Files:** Create electrothermal_data.py、electrothermal_synthetic.py（先数据生成）；Modify data.py仅必要分派；Test tests/test_electrothermal_data.py、tests/electrothermal_fixtures.py。

**Interfaces:** electrothermal_data定义TimeSignal(time_s,values,unit,provenance)、Observation(time_s,values,unit,provenance)、ElectrothermalCase(rate,current_a,ambient_temperature_k,voltage,cell_temperature_k,initial_state,cooling_group_id,provenance)、ElectrothermalDataset(fit_rates,cases,data_signature)。全部内部温度K，原单位另存。

~~~python
temperature_to_kelvin(values: Sequence[float], unit: str) -> tuple[float,...]
load_electrothermal_dataset(config: dict, base_dir: Path) -> ElectrothermalDataset
make_synthetic_dataset(fit_rates: FitRates) -> ElectrothermalDataset
~~~

- [x] 写test_unselected_bad_3c_is_not_loaded：spy workbook loader只读取R3，原XLSX可有坏3C；独立R4 synthetic仅换配置可读；数据映射缺项/额外项/重复/非有限或非递增时间拒绝。
- [x] 写test_voltage_temperature_grids_and_initial_vs_ambient_are_separate：U/T分别[0,2,4]与[0,1,4]，25℃只转298.15K一次；恢复已规范K档案不再转换，T_cell0不自动等于T_amb0。
- [x] 写test_unknown_current_temperature_probe_or_cooling_blocks_research：输入覆盖不足、来源不明、不同冷却组汇总拒绝；合成fixture可运行，研究元数据缺失不回填。
- [x] Check-ET 'A2-red' @('tests/test_electrothermal_data.py')后实现上述类型/加载器；只对fit_rates成员读列，不改旧WorkbookSchema/DischargeSeries的四倍率解释。
- [x] Check-ET 'A2-green' @('tests/test_electrothermal_data.py','tests/test_electrothermal_config.py')；按本任务5文件显式提交。

### A3：独立电热结果、RMSE与受控热方程

**Files:** Create electrothermal_evaluation.py；Modify metrics.py、electrothermal_synthetic.py；Test tests/test_electrothermal_evaluation.py、tests/electrothermal_fixtures.py。

**Interfaces:** ElectrothermalTrace(time_s,voltage_v,temperature_k,heat_generation_w,termination,solution_id,applied_parameters)允许缺失输出为None；ObservedOutputResult分别记录valid/rmse/网格/曲线/原因；ElectrothermalRateResult包含voltage与cell_temperature两个独立结果；ElectrothermalEvaluationResult包含fit_rates/rates/objective_components/complete_pair_valid/objectives/成本来源。

~~~python
mean_selected_rmse(errors: Mapping[str,float], fit_rates: FitRates) -> float
ElectrothermalEvaluator(space, simulator, *, fit_rates, max_rate_attempts=1, event_callback=None)
ElectrothermalEvaluator.evaluate(candidate: Sequence[float], dataset: ElectrothermalDataset) -> ElectrothermalEvaluationResult
~~~

- [x] 写test_selected_rate_means_are_not_fixed_three_or_four：
~~~python
assert mean_selected_rmse(dict(zip(R3,[.01,.02,.03])), R3) == pytest.approx(.02)
assert mean_selected_rmse(dict(zip(R4,[.01,.02,.03,.08])), R4) == pytest.approx(.035)
~~~
- [x] 写test_one_temperature_failure_preserves_voltage_but_pair_is_none；温度缺失/覆盖短缺/非有限均不能补0或缩分母；R3一次候选调用模拟器3次，R4为4次，每个rate的U/T共用solution_id。
- [x] 写test_only_targets_change_predictions_do_not：保持模型参数/输入/初温和观测时间，只变后续T目标，仿真轨迹不变、RMSE改变。写test_analytic_cooling_heat_capacity_and_equilibrium：Q=0的T(t)=T_amb+(T0-T_amb)exp(-G*t/C)，恒温平衡及C改变时间常数。
- [x] Check-ET 'A3-red' @('tests/test_electrothermal_evaluation.py')后最小实现模拟器协议、受控代数/解析fixture和独立评价器；旧FourRateEvaluator、mean_rate_rmse、EvaluationResult不改语义。
- [x] Check-ET 'A3-green' @('tests/test_electrothermal_evaluation.py','tests/test_core.py')；按本任务5文件提交。

### A4：PyBaMM映射及一次耦合求解适配器（不执行真实DFN）

**Files:** Modify electrothermal_parameters.py、reference_cell.py、pybamm_adapter.py；Test tests/test_electrothermal_parameters.py、tests/test_electrothermal_adapter.py。

**Interfaces:** AppliedParameters包含parameter_values和可归档原始/原生映射、单位及函数来源；温度扩散函数采用(stoichiometry,temperature)签名。ElectrothermalPyBaMMSimulator独立于旧类的四倍率条件校验，消费A2 case、返回A3 trace。

~~~python
apply_electrothermal_parameters(base, theta: Mapping[str,float], fixed: dict) -> AppliedParameters
build_electrothermal_simulator(config: dict) -> ElectrothermalPyBaMMSimulator
ElectrothermalPyBaMMSimulator.simulate(parameters: Mapping[str,float], case: ElectrothermalCase) -> ElectrothermalTrace
~~~

- [x] 写test_native_heat_mapping_uses_actual_volume_area：fixture C=40J/K,V=2e-5m3,G=.1W/K,A=.005m2时实际体积热容2e6、h=20；只集中热容键可明确新增，未知其它键不得统一绕过校验。
- [x] 写test_reference_diffusivity_function_and_fixed_sources：T_ref恢复D_ref、T改变响应正确、函数不能退化float；缺活化能/固定电导率来源阻塞研究，非零合成值不冒充Chen2020实测。
- [x] 写test_single_solution_contains_cell_temperature_and_heat：fake PyBaMM Simulation.solve调用一次，输出取Volume-averaged cell temperature而非Surface temperature；solver网格覆盖输入及两观测网格，输入不外推，SOC修复保留。
- [x] Check-ET 'A4-red' @('tests/test_electrothermal_parameters.py','tests/test_electrothermal_adapter.py')后实现。可处理真实ParameterValues/构建DFN/检查处理后的符号与热体积，但所有新增真实Simulation.solve通过spy禁止；接口fake solve不计Level2。
- [x] Check-ET 'A4-green' @('tests/test_electrothermal_parameters.py','tests/test_electrothermal_adapter.py','tests/test_pybamm_compat.py')；按本任务5文件提交。

### A5：签名、缓存、归档和成本台账

**Files:** Create electrothermal_provenance.py、electrothermal_store.py；Modify runstore.py、initialization.py、screening_history.py仅必要隔离；Test tests/test_electrothermal_provenance.py、tests/test_electrothermal_store.py。

**Interfaces:** SignatureBundle包含config/data/model_evaluation/evaluation_protocol/comparison_protocol/initialization_compatibility/algorithm/source指纹与fit_rates；完整config身份与初始化兼容性分离。comparison_protocol包含倍率/数据/模型/目标/尺度/HV参考点，不含路线开关。InitialPlan(records,fit_rates,signatures,plan_sha256)只含经复算合格曲线；CostLedger事件唯一ID及分阶段/来源/结果统计。

~~~python
build_electrothermal_signatures(config: dict, dataset: ElectrothermalDataset) -> SignatureBundle
candidate_key(parameters: Sequence[float], profile: str, signatures: SignatureBundle) -> str
load_initial_plan(path: Path, *, space: ParameterSpace, dataset: ElectrothermalDataset, signatures: SignatureBundle) -> InitialPlan
CostLedger.record(event: dict) -> str
CostLedger.summary() -> dict
ElectrothermalRunStore(RunStore).save_evaluation(result: ElectrothermalEvaluationResult) -> str
~~~

- [x] 写test_three_four_rate_signatures_reject_cache_even_with_same_6d_2d_shape；交换fit_rates顺序也改变协议；旧v1六维缓存与新LLM示例拒绝。不能通过改旧SHA或省略签名字段通过。
- [x] 写test_region_switch_changes_run_identity_but_shared_init_is_compatible：Full/WarmStart-only配置哈希不同，初始化兼容签名相同；改fit_rates/观测/函数/截止/物性任一则不相容。初始计划先核验曲线并独立复算，不盲信存档目标。
- [x] 写test_costs_separate_failure_screening_cache_and_fresh_solves：筛选拒绝0solve、失败和重试消耗实际调用、cache命中0新增solve、历史链去重归属、未尝试与solver错误分开；台账相同事件ID不双计。
- [x] Check-ET 'A5-red' @('tests/test_electrothermal_provenance.py','tests/test_electrothermal_store.py')后实现新签名/台账/新型值序列化（含参数函数源码）；旧RunStore不可变写入和旧缓存拒绝条件保留。初始化不足在summary标记phase status，旧terminal状态使用failed。
- [x] Check-ET 'A5-green' @('tests/test_electrothermal_provenance.py','tests/test_electrothermal_store.py','tests/test_screening_history.py')；按本任务7文件提交。

### A6：工作流分派、模板和零预算可检查入口

**Files:** Create electrothermal_workflow.py、scripts/run_electrothermal_smoke.py、configs/electrothermal-dfn-synthetic.json；Modify workflow.py、cli.py、README.md；Test tests/test_electrothermal_workflow.py、tests/test_electrothermal_smoke.py。

**Interfaces:** prepare/run_experiment现有v1分支不变，v2委托新模块。PreparedElectrothermalExperiment(config,space,dataset,signatures,initial_plan)传给后续MO。A阶段只允许fixed-candidate/software模式，未完成B/C时对应优化模式明确拒绝，不调用旧Optimizer伪装。

~~~python
prepare_electrothermal_experiment(config: dict, *, base_dir: Path) -> tuple[dict,PreparedElectrothermalExperiment|None]
run_electrothermal_experiment(config: dict, output: Path, *, base_dir: Path, simulator=None) -> dict
run_electrothermal_fixed_candidates(prepared, candidates, output: Path, *, simulator=None) -> dict
plan_electrothermal_smoke(config: dict, candidates: Sequence[Sequence[float]], budget: dict|None) -> dict
~~~

- [x] 写test_v2_dispatch_and_pending_research_preflight：R3配置由新评价器处理；旧v1仍四倍率，不接受部分新旧混合配置；研究模板列出全部未确认项，退出码2。
- [x] 写test_smoke_dry_run_and_missing_budget_make_zero_solves：CLI electrothermal-smoke CONFIG --dry-run；脚本同模式输出fit_rates、生成/验证任务、len(fit_rates)*候选数*max_rate_attempts调用上界；run缺预算先拒绝。生成合成数据和验证评价分别计预算。
- [x] 写test_software_fixed_candidates_archive_recomputable_pairs：受控fixture端到端出[.02,2]等可复算目标，成本/API明确为软件类型；不得因未启用DFN自动默换真实研究为mock。
- [x] Check-ET 'A6-red' @('tests/test_electrothermal_workflow.py','tests/test_electrothermal_smoke.py')后实现CLI、workflow薄分派和只读plan入口。A阶段run_electrothermal_experiment对未完成的MO模式返回明确错误，B4再完善。README给出软件运行、pending模板预检及未来预算命令；真实run需--budget-file，未给预算实际solve=0。
- [x] Check-ET 'A6-green' @('tests/test_electrothermal_workflow.py','tests/test_electrothermal_smoke.py')后Check-ET 'A-full' @('tests')，保存当前实数统计及A审计，明确Level1通过项与Level2/3未运行；上述8文件和本阶段审计显式提交后汇报再推进B。

## Stage B：先完成无LLM的ParEGO

### B1：增广Tchebycheff、线性标准化和冻结标签

**Files:** Create scalarization.py；Test tests/test_scalarization.py。
**Interfaces:** ScalarizationContext保存不可变原始Y/标签/均值/标准差/ID/权重/尺度/零理想点/incumbent/局部中心/协议指纹。防御性复制输入，归档字段用tuple；不以可变numpy视图冒充冻结。

~~~python
augmented_tchebycheff(y, weights, objective_scales, *, rho_aug=.05, ideal=(0.,0.)) -> np.ndarray
build_scalarization_context(x, y, observation_ids, *, weights, objective_scales, rho_aug, protocol_signature) -> ScalarizationContext
WeightScheduler(weights: Sequence[Sequence[float]], seed: int).next() -> tuple[float,float]
~~~

- [x] 写test_weights_relabel_history_incumbent_and_local_center：
~~~python
assert augmented_tchebycheff([[.1,2],[.2,1]],[.8,.2],[.1,1]) == pytest.approx([.86,1.69])
assert augmented_tchebycheff([[.1,2],[.2,1]],[.2,.8],[.1,1]) == pytest.approx([1.69,.86])
~~~
- [x] 写test_constant_labels_use_one_std_and_equal_y_different_x_remain；总体std<1e-12取1，正常std不截为1，incumbent同分按稳定ID；输入矩阵后续修改不影响context。另写test_scalar_inputs_reject_nonfinite_wrong_shape_or_nonpositive_scales，覆盖权重非二维/和不为1、非有限Y及零尺度。
- [x] Check-ET 'B1-red' @('tests/test_scalarization.py')后实现identity物理目标、固定协议尺度、零下界与有种子无放回二维权重循环；只读过去Y，不能调用旧充电log_transform或旧LogRMSETransform。
- [x] Check-ET 'B1-green' @('tests/test_scalarization.py')；2文件提交。

### B2：Pareto、固定空间HV及高斯EI

**Files:** Create pareto.py；Modify acquisition.py；Test tests/test_pareto.py、tests/test_gaussian_ei.py；surrogate.py只在已有接口无法满足时小改并加相应旧回放测试。
**Interfaces:** 消费真实二维目标、协议固定尺度/参考点、A5 comparison_protocol签名，以及B1标准化阈值/GP预测；输出非支配索引、可选HV和同空间EI数组，旧scalar_log_ei/composite_ei保留。

~~~python
pareto_indices(y: Sequence[Sequence[float]]) -> tuple[int,...]
hypervolume_2d(y, *, objective_scales, reference_point) -> float|None
validate_hv_comparison(protocol_signatures: Sequence[str]) -> str
gaussian_ei(mean, std, best: float) -> np.ndarray
~~~

- [x] 写test_known_front_duplicate_hv_and_fixed_metric_space：[[1,2],[2,1]]到[3,3]的HV=3，重复目标/被支配点不改变HV，不同参数同目标可保留Pareto参数；无参考点返回None且原因可归档。validate_hv_comparison只接受非空且全相同的comparison_protocol签名，不同fit_rates等导致签名不同时拒绝。
- [x] 写test_gaussian_ei_zero_std_and_scale_equivalence：mean=[-1,1],std=[0,0],best=0时EI=[1,0]；负std/非有限拒绝，电压V→mV且尺度×1000后标签/后验/EI决策不变。
- [x] Check-ET 'B2-red' @('tests/test_pareto.py','tests/test_gaussian_ei.py')后实现二维精确矩形并集与同标准化空间Gaussian EI；Matern52GP复用group=()、lengthscale_prior=None，保持predict/posterior_covariance旧契约和原log EI。
- [x] Check-ET 'B2-green' @('tests/test_pareto.py','tests/test_gaussian_ei.py','tests/test_core.py')；按实际改动显式提交4至5文件，未改surrogate不虚列。

### B3：唯一历史与逐轮重拟合MO优化器

**Files:** Create mo_optimizer.py；Test tests/test_mo_optimizer.py。
**Interfaces:** MOOptimizer(space,evaluator,dataset,store,options,initial_plan=None,llm_controller=None)，step()->dict、optimize(total_candidate_budget:int)->dict。MORoundContext包含B1上下文、fit_rates/签名、当前GP不可变序列化状态/指纹和候选池；每轮使用新GP对象。

- [x] 写test_failed_round_still_switches_weight_and_refits：初始两点、某轮温度失败无新Y，下一轮新权重触发全历史重标签/标准化/incumbent/局部中心/后验/EI阈值；spy GP.fit证明不是按n_train未变跳过拟合。
- [x] 写test_duplicate_input_not_duplicate_training_but_equal_y_distinct_parameters_are：同candidate_key重复只计一次训练，另参数相同Y保留；重复评价记录/成本仍在，目标分歧不挑较好值。
- [x] 写test_round_context_frozen_through_selection_and_feedback：冻结旧incumbent/尺度/统计，先按原context评价新结果改善再更新历史；没有完整对不能构造delta标签。
- [x] Check-ET 'B3-red' @('tests/test_mo_optimizer.py')后实现：唯一完整历史→权重→B1标签→新六维GP→Gaussian EI选点→A评价→反馈/归档→唯一Y/Pareto更新。候选用既有六维Sobol及围绕当前incumbent的局部池；global/local数量、半径和种子显式配置并在三模式一致，已有参数过滤保持同口径。
- [x] Check-ET 'B3-green' @('tests/test_mo_optimizer.py','tests/test_scalarization.py')；2文件提交。

### B4：无LLM软件端到端与阶段验收

**Files:** Modify electrothermal_workflow.py、configs/electrothermal-synthetic.json、cli.py；Test tests/test_electrothermal_workflow.py。
**Interfaces:** 完善A6已定义的run_electrothermal_experiment(config,output,*,base_dir,simulator=None)->dict；mode=parego时不构造真实LLM传输。run_experiment的v2分支委托此函数。

- [x] 写test_parego_software_r3_r4_end_to_end：分别用R3和受控R4配置、2个初始点+2次BO尝试，输出双目标、每倍率曲线、轮上下文、Pareto/HV和0API；不得读取旧3C或硬编码rate计数。
- [x] 写test_training_contains_real_complete_pairs_only_and_budget_counts_failures：注入一次部分失败，尝试预算仍耗用且无训练惩罚；改变倍率后不能续用同一运行/初始化缓存。
- [x] Check-ET 'B4-red' @('tests/test_electrothermal_workflow.py')后接入MOOptimizer及软件配置，未开启LLM时任何Transport调用spy必须为0。
- [x] Check-ET 'B4-green' @('tests/test_electrothermal_workflow.py')后Check-ET 'B-full' @('tests')，归档B成本/数值回放和Pareto曲线独立复算；上述4文件及B审计显式提交，汇报Level1结果，Level2/3保持未运行，再推进C。

## Stage C：接入既定LLMBO-MO与独立审计

### C1：新Prompt、确定WarmStart及共享初始化计划

**Files:** Create electrothermal_llm.py、prompts/warm_start_electrothermal.txt、prompts/region_preference_electrothermal.txt；Modify llm.py、electrothermal_workflow.py；Test tests/test_electrothermal_llm.py、tests/test_electrothermal_initialization.py。
**Interfaces:** 消费A3完整评价池、A5 InitialPlan/台账/签名、A6 PreparedElectrothermalExperiment与B2非支配分层；输出稳定选择ID序列、新schema payload和经曲线核验的InitialPlan。类型注解可用TYPE_CHECKING避免工作流与控制器循环导入。

~~~python
select_electrothermal_warmstart(records: Sequence[ElectrothermalEvaluationResult], *, space: ParameterSpace, count: int, objective_scales: Sequence[float], rho_aug: float=.05) -> tuple[str,...]
build_electrothermal_payload(task: str, *, prepared: PreparedElectrothermalExperiment, history: Sequence[ElectrothermalEvaluationResult], context: MORoundContext|None=None) -> dict
ElectrothermalLLMController.generate_warmstart(self, prepared: PreparedElectrothermalExperiment, *, store: ElectrothermalRunStore, budgets: dict) -> InitialPlan
~~~

- [ ] 写test_pareto_maximin_selection_is_deterministic：按R1.1的A/B/D/C例K=2选[A,B]，24种输入排列不变；同分按q/x/稳定ID，重复物理参数仅保留最小稳定ID，ID冲突内容拒绝。
- [ ] 写test_budget_exhaustion_does_not_fill_or_start_mo：|C|<K保留全部记录、initialization.status=insufficient_initialization、terminal failed，不追加请求/Sobol或缩减K。
- [ ] 写test_shared_valid_plan_avoids_new_warmstart_and_solves：WarmStart-only/Full使用同plan_sha256，初始化参数/真实目标一致，导入0新增solve/LLM；改fit_rates或源语义拒绝。
- [ ] Check-ET 'C1-red' @('tests/test_electrothermal_llm.py','tests/test_electrothermal_initialization.py')后实现Pareto层级→首点平衡q→同层maximin及既定tie-break；两个英文Prompt各200–300词，含fit_rates/profile/来源/双目标语义，不沿用objective_v排序。
- [ ] Check-ET 'C1-green' @('tests/test_electrothermal_llm.py','tests/test_electrothermal_initialization.py')，校验真实请求禁用时0付费调用；按本任务7文件显式提交。

### C2：权重条件Region-Lift与冻结信任反馈

**Files:** Modify electrothermal_llm.py、mo_optimizer.py、llm.py；仅必要时从informed.py提取不绑定log-J的纯数学函数；Test tests/test_electrothermal_region.py。
**Interfaces:** 消费B3当轮MORoundContext、GP及候选池和C1回复；输出selected_index、原/调整均值、原std、EI、锚点/原因遥测以及冻结上下文下的trust反馈。不得把调整后均值写回GP。

~~~python
validate_electrothermal_region(response: dict, *, expected_context_id: str, expected_signatures) -> dict
apply_electrothermal_region(gp, context, pool, region, *, settings, trust: float) -> dict
update_electrothermal_trust(context, result, *, previous_trust, beta, adoption) -> dict
~~~

- [ ] 写test_region_uses_current_posterior_covariance_and_changes_only_acquisition：payload含当前w/s/零ideal/Pareto/fit_rates，锚点与EI同C_t；Y、训练标签、GP状态和原方差前后逐项相等。
- [ ] 写test_bad_low_confidence_outside_region_stale_context_and_abstention_fall_back：格式、范围、签名、低置信度、零协方差、无有效锚点、守卫不通过均回退同一plain EI；same_as_plain不算采用。
- [ ] 写test_trust_compares_in_frozen_weight_and_does_not_reward_cache：只有实际改变选点且新评价才更新；完整失败success=0且无伪造g；回退/缓存不更新；下一权重不能复用旧posterior。
- [ ] Check-ET 'C2-red' @('tests/test_electrothermal_region.py')后迁移已核查的heuristic_correlation机制：32锚点、0.60/0.25/0.15的log(Gaussian EI)/sigma/novelty softmax；参数沿用既有InformedSettings的明确配置，均值上限用当前标准化单位。不是调用旧scalar_log_ei或增加核/先验。
- [ ] Check-ET 'C2-green' @('tests/test_electrothermal_region.py','tests/test_informed.py')；只按实际修改4至5文件提交。

### C3：独立审计、三模式回放与最终交付

**Files:** Create electrothermal_audit.py；Modify audit.py（仅v2分派）、electrothermal_workflow.py、README.md；Test tests/test_electrothermal_audit.py、tests/test_electrothermal_workflow.py；按需要补充三模式软件配置，不改旧配置。
**Interfaces:** 消费A5归档输入/曲线/签名/成本、B3上下文和C1/C2的初始化/Region原始记录；输出含passed、逐项差异和成本核对的审计字典，deep=True进一步重建GP及全部采集决策；不调用外部API或solve。

~~~python
audit_electrothermal_run(run_directory: Path, *, deep: bool=False) -> dict
~~~

- [ ] 写test_tampering_temperature_mapping_rates_weight_or_scales_fails：分别改单份温度曲线、C/V或G/A、fit_rates/来源排除、权重/尺度/上下文或共享计划后审计拒绝；只靠重算存档摘要不够，必须从原始曲线/参数/过去记录重建。
- [ ] 写test_three_modes_share_backbone_and_region_ablation_initial_plan：ParEGO、WarmStart-only、Full均用同评价/数值骨干；后两者同有效初始化计划，Region关闭/弃权与plain选点一致；真实传输禁用下实际API=0。
- [ ] 写test_r3_r4_protocol_comparison_is_rejected_and_old_v1_audit_unchanged：HV不能跨倍率协议混比；v1旧审计路径保持原签名要求，兼容不能通过改旧哈希实现。
- [ ] Check-ET 'C3-red' @('tests/test_electrothermal_audit.py','tests/test_electrothermal_workflow.py')后实现从原始U/T网格/映射/真实Y/冻结ctx/GP状态独立复算RMSE、标签、EI/Region、Pareto/HV和成本；audit-run按schema分派，不修改档案、联网或重求解。
- [ ] Check-ET 'C3-green' @('tests/test_electrothermal_audit.py','tests/test_electrothermal_workflow.py')后Check-ET 'C-full' @('tests')，三个模式软件闭环及deep audit独立出档；记录实际数量/退出码、文件/函数/接口、旧流程兼容证据、未验证项与commit。本任务6文件和阶段审计显式提交。

## Level 2 / Level 3的后续门槛

Level1为上述软件/mock/解析/构模/签名审计，不能宣称真实电热行为通过。A6将交付Level2入口及可检查dry-run，当前入口未实现、实际DFN预算0且未运行；之后须明确数据生成和验证分别候选数、fit_rates、最大实际solver调用、重试/时间窗/墙钟预算才执行。核验同参U/T、双向温度反馈、实际热映射、C/G扰动与积分热收支；同求解器同网格零误差仅是接口一致性。

Level3仅在当前三倍率真实电流、T语义/测点、初态/环境/共享冷却、热范围/固定物性来源均确认且另获实测运行授权后进行。旧3C禁用；可靠3C使用新数据/配置/签名和实验归档，不追溯改旧数据或混用三倍率成绩。数据缺失不能判为模型失效。

## 计划自审与阶段汇报清单

已对齐R1.1与Method：A1/A2覆盖倍率协议和未知条件；A3/A4覆盖结果、物理映射和同次求解；A5覆盖签名/缓存/成本；A6覆盖零预算入口；B1–B4覆盖数值闭环与唯一样本；C1–C3覆盖两LLM作用、共享初始化及独立审计。公共类型/函数在拥有任务中定义，不依赖尚不存在的旧电热入口。

每阶段报告：实际文件/函数/接口；已实现/未实现；本阶段新运行测试数及通过/失败/错误/退出码；旧电压兼容与严格缓存证据；未知物性/数据风险；commit和不可变实验/审计路径。分别列“代码完成”“Level1通过”“Level2未运行/通过/失败”“Level3未运行/完成”，不得合并成成功结论。

审批后按A0→A1…A6→A验收→B1…B4→B验收→C1…C3顺序执行，不重新讨论既定算法框架。若发现实际源码/数据或范围冲突，先保留证据、说明影响；未经批准不扩大模型、目标或预算。
