# 交接：NSGA-II、ParEGO、PSO 电热参数辨识对照

交接时间：2026-11-02 19:21（北京时间）。这是工作状态快照，不是新对照实验的结果报告。

## 用户目标与执行边界

用户要求继续开展 **NSGA-II、ParEGO、PSO 对照试验**，比较既有电热 LLMBO；此前明确要求不要反复拖延或重复询问权限。本轮根据已有对照设计，选择多目标粒子群 **SMPSO**。已经向用户说明：采用相同5个种子、每方法50次新增候选评价、相同0.5C/1C合成数据；复用数值初始化池和既有LLMBO/WarmStart轨迹。

- 不自动调用LLM API；本次新基线设计为 **API 0**。预计无失败时新增 **1500次DFN求解**：5种子 × 3方法 × 50新候选 × 2工况；原有初始化的真实成本需另列。
- 数据为真实DFN生成的 **0.5C/1C、各60秒合成观测**，不是实测辨识。原3C数据存在问题，不得使用；保留原始XLSX、旧四倍率电压任务、缓存和所有旧实验。
- 保留完整二维目标 `(F_U, F_T)`，目标尺度 `(0.1 V, 1 K)`，固定HV参考点 `(10,10)`；温度误差不是温升目标。未知真实电流、温度测点与单位、初态和冷却条件仍待确认。
- 单线程、明确计账、保留失败和负结果；不能把失败目标补零、伪造惩罚目标、覆盖旧产物或把软件mock当成物理验证。多目标PSO按**候选评价次数**对齐预算，不将50次候选误写为50个群体代。
- 用户最新要求是编写交接文件，没有明确取消此前对比任务；接手者可按既有授权继续。需要遵守既定研究和测试流程，但不应再次询问已获授权的范围。

## 工作树与版本

- 开发工作树：`C:\Users\aa133\.codex\worktrees\warmstart-quality-gate\LLMBO_Para`
- 分支：`codex/warmstart-quality-gate-20261029`。
- 交接前HEAD：`5a7c9f8`，提交了本轮对照设计和计划；先前 `060e8ca` 为四臂结果审计，`f22e3ae` 为四臂运行代码。
- 主工程：`D:\Users\aa133\Desktop\LLMBO_Para`。旧多目标参考工程只读：`D:\Users\aa133\Desktop\BO_Multi_12_20\New_LLMBO`。不要修改参考工程、覆盖主工程工作或清理实验。
- DFN锁定解释器：`D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe`，既有锁定物理环境应保持不变。
- 先执行 `git status --short`、`git log -5 --oneline` 和 `git worktree list` 重新核对；不要以本快照假定工作区之后没有变化。此前用户明确暂缓初始化CodeGraph。

阅读本轮书面规格和计划：

- [对照设计](../superpowers/specs/2026-11-02-classical-baselines-design.md)
- [实施计划](../superpowers/plans/2026-11-02-classical-baselines-plan.md)
- [上轮四臂审计报告](../audits/four-arm-ablation-results-2026-11-02.md)
- 本轮执行记录：`D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\classical-baselines-20261102\progress.md`

## 当前真实状态：本轮对照尚未运行

1. 设计/计划已提交 `5a7c9f8`。五个种子固定为 `872104, 195447, 221402, 513225, 162634`；不得根据已见结果重选。
2. 下列三个文件在交接前均为 **untracked、未提交、未完成**。保留它们，先检查差异，不要清理或覆盖：
   - `scripts/et_classical_policy.py`：独立JSON行策略进程的初稿，调用jMetalPy官方NSGAII/SMPSO；包含缓存反馈、50次新评价停止和SMPSO末代截断处理。
   - `scripts/et_classical_worker.py`：签名桥接、评价器及外部策略通信初稿，含ParEGO-16调用；其端到端运行尚未验证。
   - `tests/test_et_classical_baselines.py`：官方策略软件测试及配置测试初稿；大多数测试尚未运行。
3. 为防丢失，以上三份未提交文件已按显式清单复制到 `D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\classical-baselines-20261102\handoff-source-20261102`。这是源码副本而非新实验。SHA-256 分别为：
   - policy：`57d49d92dc1a62279d6fd92ef0ded517d79726ff754d24ff3f4f4b8897af7db7`
   - worker：`9d9ecdac355da338c817b88bc241bff703b25758fe7962abfb61142ed3de94eb`
   - test：`80d1a73afb648ecc8ba81f56c36ce2f188ff25a631b95df29510890bfe161496`
4. **`scripts/run_et_classical_validation.py` 和 `scripts/analyze_et_classical_validation.py` 尚未创建。** 尚无15组软件演练、尚无NSGA-II/ParEGO-16/SMPSO真实DFN对照，不得报告其RMSE、HV或效果。
5. 独立环境路径 `D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\environments\baselines312-20261102` 已建立，但截至交接时 `importlib.util.find_spec('jmetal')` 为False，安装报告不存在，也未发现运行中的python安装进程。`install.log` 最后停在下载SciPy，进程退出原因和退出码**未知**。不要声称安装成功或断定失败原因；检查环境后安全续装 `jmetalpy==1.9.0`，记录新的安装日志、完整依赖版本、wheel/源码哈希，勿升级DFN环境。
6. 交接前 `git status --short` 仅列出上述三份untracked源码；交接文档本身会成为单独的新文件。不要使用 `git add .`。

## 测试证据和未验证风险

本轮测试日志/JUnit位于 `D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\warmstart-v3-trial-20261029`：

| 标签 | 实际结果 | 含义 |
|---|---|---|
| `classical-policy-red-20261102` | 1失败、退出码1 | 策略文件创建前的预期RED，不代表现有策略已通过 |
| `classical-worker-red-20261102` | 1失败、退出码1 | worker创建前的预期RED |
| `classical-worker-green-20261102` | 1通过、退出码0 | 仅验证16点配置和API关闭；不验证DFN或算法闭环 |

完整旧回归曾有未通过记录，不能将其写成全量通过；上轮四臂针对性160项通过和五种子软件演练，是上轮证据，不是本轮新基线测试结果。

接手时先验证以下风险，任何一项均不能因源文件存在而视为已解决：

- 官方jMetalPy 1.9.0 的类签名、初始化生成器、随机数、终止/末代截断和 `algorithm.evaluations` 与策略初稿是否相符。现有SMPSO测试假定某个内部评价数；重复缓存可能改变库的内部计数，需以真实官方执行行为判断，而不能为了让测试通过而掩盖预算偏差。
- 数值初始化旧池是16个真实评价，而旧签名计划仅选8点。`derive_initial_plan()` 预期对原池进行深审计，严格比对data/model/evaluation/comparison/source/rates后派生16点计划；需逐项测试签名不匹配和篡改被拒绝。**不能放宽旧缓存签名**。
- `external_loop()` 将签名计划物理参数归一化后传给外部算法，再反归一化做精确candidate key检查；对对数扩散率可能出现浮点往返差异。需用旧真实池端到端复现并修复，保证同一点不被错误拒绝或重复求解；这是待验证风险，不是已证实故障。
- 外部算法收到真实完整二维目标，重复输入从经验证缓存返回；部分失败必须保留并令对应臂明确失败/右删失，不能提供假的fitness。严格核对50次新增真实候选及SMPSO末代中断状态。
- 当前代码有独立进程设计，但“策略进程不可联网/不可自行求解”的边界和依赖锁定仍需实际核验，不能因注释而声称已实现隔离。核对输出归档、进程退出清理、账本跨阶段累计、源文件/依赖哈希、真实费用与缓存记账。
- 外部NSGA-II/SMPSO使用v2配置仅作为物理评价器载体；实际算法身份必须写入并核验 `baseline-contract.json`，不能把载体中的 `mode=parego` 误报为实际算法。

## 上轮结果与可复用输入

四臂实验根目录：`D:\Users\aa133\Desktop\LLMBO_Para\runs\f1101`。五种子×四臂×50轮全部完成，退出码0，2320次DFN、505次API；独立重放核验通过，新增调用0。`result.json` 中每个seed的 `pools.numeric` 指向同种子已审计的16点评价池；`arms.A11` 为完整LLMBO，`arms.A10` 为WarmStart-only。保留原路径、计划/源哈希与成本证据，勿更改旧归档。

第50轮五种子平均：BO U=2.631 mV/T=0.02463 K/HV=99.806589；WarmStart U=2.081 mV/T=0.02206 K/HV=99.843555；BO+Region U=1.989 mV/T=0.03105 K/HV=99.828747；LLMBO U=1.970 mV/T=0.02309 K/HV=99.797183。Region未表现稳定额外HV增益。完整曲线和逐种子结果请查上方四臂审计报告，不能把这些旧值冒充新基线结果。

注意旧BO是16候选筛选8点后训练，计划中的 **ParEGO-16用全部16点评价训练**；它们是不同初始化变体。新NSGA-II/SMPSO和ParEGO-16同用全部16点，LLMBO保留自身已封存的16选8策略。所有可取得的初始化点应计入评价指标，物理共享计算和逻辑每方法成本分别报告。

## 续做顺序

1. 重查环境与Git，保留三个untracked文件及其快照；确认依赖安装状态，完成独立环境锁定，保留安装和失败记录。
2. 先执行现有官方策略测试观察实际结果，按RED→GREEN修复；增加真实重复、16点签名桥、失败目标、50次精确停止、SMPSO部分代和可重复种子等必要测试。
3. 实现和测试监督器、独立分析器、成本/来源重放与冻结历史比较；新文件显式列入source pin。不要改物理、旧优化器或旧实验，不要重用过期审批门槛阻塞用户已授权的工作。
4. 先做15组×10轮实际冷启动软件闭环（API/DFN=0），再运行针对性回归和深审计；记录真实数量、退出码、日志、JUnit。准备单独的新结果目录、确定性任务次序、全程账本和自动报告。
5. 验收通过后直接启动15组×50次新候选的真实DFN合成实验；实际账本核对运行是否真正开始。完成后报告每方法前10轮和第50轮的电压/温度RMSE、固定HV、逐种子配对增益、失败/缓存和实际资源消耗，完整保留负结果；不得将五种子短窗口结果推广为实测成功。

## 安全与敏感信息

不要把历史聊天中的密钥写入文件、命令参数、日志或快照。本次基线不需LLM密钥或API请求。任何额外端点/凭据均应通过安全环境机制处理。
