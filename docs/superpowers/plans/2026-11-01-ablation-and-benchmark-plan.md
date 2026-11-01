# Four-arm ablation and baseline implementation plan

> **For agentic workers:** Use superpowers:executing-plans for inline execution; do not spawn agents without user authorization. Complete tasks against this spec, preserving old trials.

**Goal:** 固定 v3，完成四组消融和经典/现代多目标方法的可复现对照，优先得到前10轮证据。

**Architecture:** 复用电热数据、评价器、标量化及当前 Region；由父进程统一管理初始化、ask/tell、真实成本和归档。外部算法只返回归一化参数候选，不得自行调用DFN或LLM。

**Tech Stack:** 当前锁定 Python3.12/PyBaMM25.10.2；现代基线和 pymoo 用独立环境及核验后的lock。

**Spec:** `docs/superpowers/specs/2026-11-01-ablation-and-benchmark-design.md`

## Task 1 — 设计与禁用调用的任务包（本轮交付）

- [x] 新建 `scripts/prepare_et_ablation_benchmarks.py`，纯配置准备，无真实执行分支。
- [x] `build_design(template, *, template_path, replicates=5, rounds=10)` 生成四臂定义、10个新种子、配对运行次序、资源估算和外部方法清单。
- [x] `write_bundle(bundle, output)` 仅写新目录，输出协议、20份禁用配置、50个正式任务条目、初始池任务、模板副本及文件哈希。
- [x] 新建 `tests/test_et_ablation_benchmark_design.py`：先证明入口缺失，再实现，验证成本、因子/初始化绑定、禁用调用、参数/观测保持、重复写入拒绝、秘密字段拒绝。
- [x] 运行准备命令和独立复核；7项通过、退出码0，24文件哈希及成本复核通过；见 `docs/audits/ablation-benchmark-design-2026-11-01.md`。设计不是实际算法效果结果。

## Task 2 — 四臂监督与初始化完成策略

文件：新增 `scripts/run_et_factorial_validation.py`、`scripts/et_factorial_worker.py`，复用 `et_selection_trial_budget.py`；按必要范围扩展 `et_three_arm_validation_worker.py` 的可复用函数，不增加第二套优化数学。

接口：`prepare_numeric_pool(spec,budget)`、`prepare_warmstart_pool(spec,budget)`、`run_factorial_arm(spec,budget)`；不可在模块导入时导入科学模块。Region-only 必须在签名数值初始化上以 full Region mode 执行，不能触发 WarmStart。

- [ ] 先失败测试：四臂模式和初始化来源；BO两臂无WarmStart请求；W两臂同序八点；数值池16点与LLM池16点分别v3筛选。
- [ ] 实现明确来源的Sobol补点，覆盖15/16、重复、坏回复、最多3请求、16评价/128补点提议限制；所有成本进入同一账本。
- [ ] 测试全新实际Windows spawn进入候选池；科学源在子进程选择前必须为空，路径检查使用短 runs 根。
- [ ] 不通过 monkey-patch `_live_preflight` 启动正式主线；实际发布路径、协议和恢复路径均为显式参数，经哈希绑定。
- [ ] 预算跨进程、跨恢复累计；固定绝对deadline。恢复只读取已签名已归档真实结果；失败不能重新分配无限额度。
- [ ] 验收：五种子四臂软件10轮，API/DFN0；逐轮深审计；然后才使用绑定的新真实预算。

## Task 3 — 逐轮独立评价与因子效应

文件：新增 `scripts/analyze_et_factorial_validation.py`，复用现有独立曲线RMSE和HV实现。

接口：`trajectory(initial_pool, initial_plan, rounds)` 必须把完整初始池计入评价档案，GP只导入计划中的八点；`factorial_effects(seed_metrics)` 计算W、R及交互。

- [ ] 已知二维样例核对0..10轮HV、代表点和归一化AUC。
- [ ] 校验同输入不重复训练、同目标不同输入有效、partial缺失不补零、失败轨迹右删失。
- [ ] 测试所有初始实评点纳入指标，筛掉的点不能凭空丢失。
- [ ] 五个种子分别报告，未完成种子和回退Region轮保留；不同协议旧曲线不得合并。
- [ ] 输出逐轮表、配对差、完整Pareto参数集、初始计划哈希、成本/失败/缓存和图。

## Task 4 — 外部方法适配

新增小型 `CandidatePolicy` 适配边界（候选接口+状态归档），禁止改电热评价器和本方法Region公式：

`initialize(X,Y,seed,settings)` / `ask(history,remaining_budget)` / `tell(x,complete_result)` / `state_dict()`。

- [ ] Sobol与ParEGO-16先接入，同一N池16点全部作为历史。
- [ ] 独立基线环境锁定 pymoo/PyTorch/GPyTorch/BoTorch，记录实际解析版本及源码类名。不得在DFN环境顺手升级依赖。
- [ ] pymoo NSGA-II(16 population/1 offspring)和MOEA/D(16方向)适配，参数见spec。失败不改名成普通BO。
- [ ] BoTorch qLogNEHVI(q=1)与多目标JES(q=1)适配，先验证最大化符号、noise floor、目标标准化与reference同步。
- [ ] 对所有适配器运行已知二维软件问题，精确评价计数、初始化共享、重复处理、可行性筛选和独立HV复算。不要为凑方法数接入尚未验证的算法。
- [ ] 冻结调参设置后才用电池确认种子。以同一N池及A11轨迹复用进行外部比较，避免重新烧初始化/LLM成本。

## Task 5 — 两层真实验证与交付

- [ ] Stage A：五种子四臂10轮，估算720DFN/115API；检查来源、失败率和Region实际非零调整。
- [ ] Stage B：追加六基线各10轮，估算增加600DFN/0API；总1320DFN/115API，实际全局预算需新绑定。
- [ ] 无论正负都完成预定所有臂；只在全局预算、模型错误或不能保证数据完整性时停止。
- [ ] 预定延伸到50轮不换种子/初始化/Prompt；联合上限5320DFN/515API，不自动采用这个额度。
- [ ] 后五个新种子作独立确认；实测阶段保持输入预检，不用旧3C。
- [ ] 交付版本、源快照、协议/数据/配置/初始计划哈希、全部逐轮RMSE/HV、负结果及实际API/DFN/墙钟。

历史完整回归目前尚未通过，已有路径/换行兼容失败和修复记录都保留。本轮任务包生成器的测试只覆盖准备功能，不能用来宣称整个产品已通过全量回归。
