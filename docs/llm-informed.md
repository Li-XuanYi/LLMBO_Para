# 单 GP + LLM-Informed：实现与复现

本实现对应用户在 2026-10-14 确认的方法：一个 GP 拟合四倍率平均 RMSE；LLM 提出参数区域，在采集阶段对预测均值做有界调整，保持预测方差不变。

## 数学含义

1. 每次 DFN 仍仿真 0.5C、1C、2C、3C；四条曲线必须完整覆盖各自实测时间网格，禁止外推。联合目标 `J` 是四个 RMSE 的算术平均值，单位 V。
2. 一个 6 维 ARD Matérn-5/2 GP 拟合标准化的 `log(J + epsilon)`。长度尺度按维度学习，但没有参数子集核、核混合权重或四个倍率 GP。
3. LLM 每次接收最多 8 个最佳与 8 个最近观测的并集、参数定义、固定条件、RMSE/残差/截止摘要。返回一个六维归一化矩形区域，或者明确弃权。不发送 XLSX 或逐点电压。
4. 区域内取独立 Sobol 锚点，经过参数边界、孔隙条件和已启用的解析容量检查。该检查不等价于保证 DFN 全时段有效。
5. 复用原方法的锚点权重：对数 EI、GP 标准差、距已观测点的距离标准化后，按 0.60/0.25/0.15 组合，再做 softmax。EI 按本项目联合误差的 V 尺度计算。
6. 用真实观测条件下的后验交叉协方差计算候选点与区域加权平均的相关系数 `rho(x)`。均值调整为：

   `delta(x) = clip(lambda_max * (1-t/T) * confidence * trust * anchor_consistency * max(rho(x),0), 0, max_shift_std)`。

   `mu_adjusted(x)=mu(x)-delta(x)`，`sigma_adjusted(x)=sigma(x)`。这些量均在冻结的标准化 log-J 空间中。
7. 用调整后的均值与原方差计算解析 EI；如启用了完成概率加权，仍使用同一个完成概率模型。比较和选择都遵守原候选池的全局探索配额。
8. 新候选必须位于建议区域内，原 EI 的对数损失不得超过设定值，不确定性不能比原候选过低。否则完整回退到原选点。相同选点记录为 `same_as_plain`，不能算作建议被采用。
9. 只有建议实际改变了选点时，才根据其真实联合目标是否改善更新信任值：`trust_next=(1-beta)*trust+beta*improved`。失败/无改善对应 `improved=0`；未采用的建议不更新信任值。

这是**采集阶段的启发式引导**，不是把 LLM 建议当作仿真标签，也不代表经过证据更新的贝叶斯后验。GP 训练集、核、原始后验均值和方差保持独立，可从日志核查。

## 与 Multi_ 原实现的对应

参考目录：`D:\Users\aa133\Desktop\BO_Multi_12_20\New_LLMBO`。

| 原实现 | 本项目对应 |
|---|---|
| `llmbo/gp_model.py` 的后验协方差 | `src/llmbo_para/surrogate.py:posterior_covariance` |
| `llmbo/region_lifted_gp.py` 中 `heuristic_correlation` 的锚点权重、后验相关性、衰减、均值上限与回退规则 | `src/llmbo_para/informed.py:region_decision` |
| `llm/region_prompt.py` 的区域建议接口 | `src/llmbo_para/llm.py:region_preference` 与 `prompts/region_preference.txt` |
| 选点后的可靠性反馈思路 | 显式记录的联合 RMSE 改善 EMA，见 `trust_feedback` |

有意作出的适配：5 维充电变量改为 6 维电芯参数；动态充电多目标改为固定四倍率平均 RMSE；全部区域坐标归一化且扩散系数采用 log10 映射；不迁移充电参数缺失时补默认值的逻辑；不迁移可能误拒绝 6 维窄区域的体积阈值；只接受完整区域或弃权，不自动扩张区域。使用本项目解析 EI，不改变主评价目标。

未启用原目录的 `lgbo_proposition1`、先验核调整及旧物理复合核分支。

## 开关和默认值

新增 `optimization.llm_informed_enabled`，默认 false；设置对象为 `optimization.llm_informed`。启用时必须使用 `surrogate_mode="single_objective"` 且 `llm_gp_groups_enabled=false`。WarmStart 仍有独立开关。

默认 32 个锚点；前 12 次 BO 启用并线性衰减；置信度下限 0.60；调整系数上限 0.25；均值调整上限 0.25 个标准化目标单位；每维归一化宽度 0.03–0.80；信任初值 0.50、更新率 0.20。全部有效设置保存在每次决策记录中。这些是来源方法的工程默认值，尚未证明对实测数据最优。

接口失败在当轮回退，下一轮可以继续请求。JSON 合同错误最多修复一次，两次回复都保存；置信度低、弃权、区域不合规不会被偷偷改造成可接受建议。运行摘要报告请求数、合法回复数、真正采用数、错误数及各类回退原因；接口/计算错误将运行标记为 `completed_with_failures`。

## 可复现入口

环境：Python 3.12，项目现有 `.venv-pybamm312`；本地或服务器均从项目根目录运行。仍使用单 CPU worker，OMP/BLAS 线程数由脚本设为 1。配置文件：`configs/21700-single-gp-informed.json`。

复用已筛选的 8 点计划（推荐用于接入小试；自动校验原始曲线、数据哈希与固定参数）：

```powershell
.\.venv-pybamm312\Scripts\python.exe scripts/run_informed_pilot.py configs/21700-single-gp-informed.json --initial-plan "现有初始计划目录/initial-plan.json" --bo-iterations 2 --prompt-for-key --proxy http://127.0.0.1:7897
```

Linux 将解释器改为对应虚拟环境中的 `python`。代理是执行机器上的代理，不能照抄本地 Windows 地址。也可以预先设置配置指定的凭据环境变量，省略 `--prompt-for-key`；不要把密钥写入配置或命令参数。

不传 `--initial-plan` 时，脚本复用已有 `screen_family` 和 `FeasibleInitializer`：默认调用 LLM 产生/筛选 8 个有效初始点；`--initial-source random` 使用原有随机筛选。该阶段可能有较高仿真成本，默认上限 200 个候选、10 批建议和 30 次选择请求；到达上限时保留全部记录并报出原因。初始化筛选时关闭 Informed，之后再启用。

不要直接用模板配置绕过筛选运行普通 `llmbo_para run`：模板里的 8 个占位 Sobol 初始点不保证有效。上面的入口负责导出经过验证的实际运行配置。

固定候选重试/验证入口会显式关闭三个 LLM 开关，将原始配置另存为 `original-config.json`，不会为重放 DFN 调用 LLM。

## 保存与审计

默认输出 `runs/informed-pilots/<时间_配置哈希_唯一标识>/`。保存环境、资源快照、代码快照、配置、初始化来源及全部历史筛选成本；优化子目录沿用完整仿真轨迹和 RMSE 日志。

- `informed-requests/iteration-*/attempt-*/`：各次 Prompt、回复、合同验证、HTTP 状态、模型标识和用量。
- `informed/candidate-*.json`：原后验、区域、锚点、权重、调整量、调整后 EI、选择与回退原因。
- `informed-feedback/candidate-*.json`：真实结果驱动的信任更新。
- `models/after-*.json`：仅真实联合目标训练得到的单 GP。
- `acquisition/candidate-*.json`：原 EI、实际使用分数、候选配额、采用标记与最终索引。

审计器读取已保存的原始 LLM 回复，重建区域并从 GP 状态重算整个引导过程；无需联网或新仿真。它同时检查发送摘要与先前真实记录一致，保证没有未来观测泄漏。测试还会修改保存的预测均值，确认审计能够拒绝篡改结果。

实现通过软件闭环不等于证明 LLM 优势。真实消融仍需共享初始化、统一仿真与 API 成本、多个随机种子，并分别报告有效候选率及 RMSE 变化。


## Schema v2 电热 LLMBO-MO（2026-10-18）

以上章节保留旧schema1电压任务。新路线是独立的electrothermal_identification与electrothermal_4e2t，不继承旧log-J、RATE_ORDER或六维电导率语义。fit_rates驱动全部评价/签名；当前R3排除旧3C，可靠R4另建协议。

| 参考数值骨干 | 新电热落点与适配 |
|---|---|
| llmbo/optimizer.py的二维权重调度 | scalarization.WeightScheduler：显式二维网格、种子无放回循环，每轮包括失败轮重新建标签和GP |
| llmbo/scalarization.py的增广Tchebycheff | augmented_tchebycheff：max(w*Y/s)+0.05*sum(w*Y/s)；保留物理误差，不迁移第0/2列log及maximum(value,1.0) |
| llmbo/gp_model.py的ARD Matérn与后验 | 复用Matern52GP，group=()，lengthscale_prior=None；线性标准化及Gaussian EI，保留原始方差 |
| Pareto/HV | pareto.py：完整真实二维目标、保留同目标不同参数、固定Y/s指标空间与固定参考点 |
| LLM WarmStart | 新参数/Prompt/schema；顺序真实筛选后按Pareto层级+maximin确定选择；不足K停止，不补随机点 |
| llmbo/region_lifted_gp.py的heuristic_correlation | electrothermal_llm.apply_electrothermal_region：32锚点、0.60/0.25/0.15权重、当前后验协方差、有界均值调整及守卫 |
| 改善信任反馈 | 使用同轮冻结权重/尺度比较；仅采纳且新评价更新，缓存/回退不奖励 |

没有迁移五维充电变量、第三目标、dSOC和电流单调约束，也没有新增混合核。可复现入口仍为CLI run/preflight/audit-run，加独立electrothermal-smoke。三模式由optimization.mode选择parego/warmstart_only/full_llmbo_mo；后两者消融导入同initial_plan文件及SHA256。默认llm.enabled=false、请求预算0；开启真实API需明确环境变量名、完整chat端点、模型及正请求预算，密钥不得进入配置。

### Region 请求与诊断（2026-10-18）

v2 可选 `llm.task_options` 为 `warm_start_electrothermal` 和 `region_preference_electrothermal` 分别指定 timeout_s/max_tokens；缺省继承全局值，不能超过全局上限。真实 Chat 请求由电热专用受控子进程执行，硬截止取任务限制与剩余运行预算的较小值，不自动重试。每次归档实际限制、上下文、HTTP 是否启动及分类结果。请求失败、低置信度、数值守卫拒绝和成功采纳分开记录；summary.region_diagnostics 提供请求尝试、响应、失败、采纳与回退计数。generic 注入传输明确标记不具备硬截止保证。

Region 摘要按当轮 scalar top4、双目标极值和 recent3 稳定去重，最多9条；incumbent 在首位，提供物理参数、计算好的归一化坐标及 linear/log10 公式。完整真实历史、原 GP 标签和方差仍保留。部分结果不产生标量目标；inactive 阶段不再请求。置信门槛与原均值调整/EI 守卫不变，合法宽度边界采用1e-12浮点容差。审计交叉核验 outcome、payload、context 与成本事件，旧记录保留原重放路径与签名校验。

旧20轮实验的 Region 采纳0/20，包含19次传输失败和1次正常低置信度回退；不构成Region增益检验。本轮只修复软件与请求契约，真实服务成功率和物理RMSE改善仍待独立预算验证。详见 `docs/audits/region-lift-diagnosis-2026-10-18.md`。

### 候选信息对齐（2026-10-19）

schema v2 的可选 `optimization.region_advice` 严格取 `legacy_v1` 或 `candidate_aware_v1`。缺省为legacy，旧配置不补写新键，旧归档按其配置重放；schema v1不变。新电热模板显式选择candidate策略，但仍为parego模式、LLM关闭、真实API与DFN预算0。策略进入现有算法/配置签名，所有新模块和Prompt进入源码指纹；没有放宽缓存、LLM回复或初始化计划校验。同一源码下WarmStart-only/Full仍可共享兼容的已冻结初始化计划。

candidate策略从当轮冻结的GP状态恢复后验，不优化超参数，使用同一pool、best、权重和目标尺度。资格逐字采用原守卫：`log(max(EI_plain,1e-12))-log(max(EI_i,1e-12)) <= max_plain_log_ei_gap`，以及 `sigma_i/max(sigma_plain,1e-12) >= min_sigma_ratio`。排除plain、已观测/重复点和参数空间不合法点；不以未经取下限的EI比值代替资格判断。

没有合格替代点时，在任何transport调用前记录当前context的`no_eligible_alternative`跳过；不增加请求、任务计数或LLM成本，不生成请求ordinal。inactive优先于此预检；在活跃且存在替代点时，仍执行原disabled/任务/总预算检查。旧outcome不会沿用到新轮。

提供最多12条候选摘要，plain首先，其余从合格替代点中按归一化六维Max–Min选择（距离除sqrt(6)；精确同分按较高原EI、再context绑定的稳定candidate ID）。摘要保留完整精度坐标、物理值、当前标准化mean/std、原EI、实际EI比率、带下限的log-EI差及sigma比率，并携带context/池/GP状态指纹。实际EI比率仅用于阅读：EI_plain>0时为EI_i/EI_plain，否则明确为null；资格始终以带下限的log-EI差为准。返回合格替代总数与上限，不能把未列出的点伪称已发送给LLM。

独立英文Prompt为`region_preference_candidate_aware_electrothermal.txt`，要求在权重与物理关系下选择覆盖至少一个已提供合格替代点的矩形，或者弃权。仅覆盖plain不够。代码用原始完整精度坐标、包含端点的边界判断覆盖；不自动扩框、裁剪或补点。未覆盖时记录`no_eligible_candidate_in_region`。之后的锚点、协方差相关性、Lift公式和最终守卫全部沿用原版本，真实目标、标签和原方差不变。此版本没有实现“区域内竞争”的另一个采集变体。

每轮保存`candidate_advice`，请求payload保存同一摘要与全部门槛。新模式审计从冻结后验独立重建，逐字段核验摘要、覆盖、跳过原因及请求outcome/成本的一一对应；删除摘要、改预测/索引/数量/门槛或伪造无ordinal跳过均拒绝。legacy输出与旧审计重放路径保持原语义。

本改动的软件测试通过只说明契约和数值实现正确，不证明LLM建议质量或RMSE/HV提升。真实效果需后续同初始化、等预算、多种子配对实验；本轮新增实际API/DFN预算保持0。2026-10-19既有真实消融仍保留原结论：7个合法框均无守卫合格池内候选、0次改变选点，两臂轨迹一致，不能用新预检反推未求解点的RMSE。

### 区域内合格候选竞争实验版本（2026-10-19）

新增可选`optimization.region_selection`，缺省`global_lift_v1`保留全池相关性Lift后检查赢家的原行为。新值`eligible_region_v1`仅允许搭配`region_advice=candidate_aware_v1`；两个字段进入现有算法签名，不改变初始化兼容协议或固定HV指标空间。现有模板不默认切换到这个实验版本。

新版本先按原锚点、权重、协方差、confidence/trust/anneal计算`raw_shift`，再将实际`shift`限制在冻结池内同时满足以下条件的替代点：参数合法、未观测/未重复、位于建议区域（边界包含端点）、原log-EI差和sigma比率符合原门槛。摘要和选点共用同一资格函数，不以12条摘要作为最终搜索范围；区域仍须覆盖至少一个已展示的合格替代点。

plain保留原均值和原EI。合格替代点以`EI(mu-raw_shift,sigma,best)`与plain原EI比较，严格胜出才改变选点；恰同分保留plain，替代点恰同分按同一冻结context绑定的稳定ID选择。区域外、不合格点与plain的实际shift均为0。原始Lift幅度公式、原方差、真实标签、最终EI/sigma守卫和同轮冻结信任反馈均保留；没有调大lambda或放宽门槛。

结果同时归档策略、raw_shift、实际shift、全池合格索引/区域内竞争索引、未限制的Lift赢家、实际赢家和相对局部sigma的最大调整量。请求明确告知竞争范围与原EI基线；审计从冻结后验和区域重建全部内容。缺省global版本不新增这些结果字段，旧归档按其原配置重放。

软件验证分开包括：正定RBF协方差的“框外全局赢家被拒绝、框内合格点恢复”反例；同分/边界/未展示合格点和审计篡改测试；冻结旧区域回放；共享初始化、同种子权重/GP设置的代数合成对照。部分审计fixture使用宽门槛仅为触发分支，不是默认门槛效果证据；PSD反例使用默认门槛。代数对照采用预先固定的脚本建议器，不调用LLM，不代表真实DFN或LLM的RMSE收益。真实API/DFN对照需要另行批准预算。

### 可选紧凑Region传输与阶段诊断（2026-10-20）

`llm.region_wire_format`严格取`full_v1`（缺省）或`compact_v1`。WarmStart及旧默认回复保持原契约。紧凑版仍发送全部专业候选/历史信息，但不要求模型逐项回抄完整签名；线上回复只含`request_id`和`region`。request_id是完整冻结请求（含权重、尺度、物性、历史、候选摘要、签名和Prompt）的摘要，排除仅用于本地文件名的artifact_task。回复键集合与摘要必须严格匹配，再从本地请求恢复原schema2/profile/fit_rates/signatures/context_id，执行既有Region校验。旧缓存、旧六维语义和旧计划签名没有放宽。

每次HTTP记录响应头到达事件。supervision/outcome补充wire版本、HTTP启动耗时、失败阶段及安全枚举protocol_issue；可区分等待响应头、读取正文和content解析，空content与未正常结束的回复分开标记。任务/总预算硬截止、无传输重试及plain EI回退保持。审计独立重建紧凑HTTP请求、核对响应绑定和规范信封，拒绝归档权重或摘要篡改。

一次归档回复的离线重编码将输入消息字符数16957降到14668、回复字符数1271降到420，恢复后的完整信封相等。这是表示层验证，不是新API的token用量、延迟或成功率验证；没有改变Region建议质量和真实目标。详见`docs/audits/region-request-repair-2026-10-20.md`。

### 同一原始Lift下的plain比较基线（2026-10-20）

新增显式`optimization.region_selection=fair_region_v1`，要求candidate_aware_v1。缺省global_lift_v1与已有eligible_region_v1保持原输出和原审计路径。新版本不改变原Lift、GP、真实标签、资格门槛、物性和指标空间，只收紧改变选点的条件。

记原后验为mu/sigma、冻结阈值为best、原相关性Lift场为delta，plain索引p来自原Gaussian EI。区域候选仍按既有完整池资格和区域掩码计算`EI(mu_i-delta_i,sigma_i,best)`，但必须严格超过`max(EI(mu_p,sigma_p,best), EI(mu_p-delta_p,sigma_p,best))`。第二项只提供同一Lift信号的比较基线；plain实际shift仍0，原后验不变。精确同分保留plain，替代同分仍按原context绑定ID；baseline归档原plain shift、同场plain EI、所需门槛及最佳替代的差额，审计完整重算。没有新增可调门槛。

该守卫针对eligible策略可因剥除plain本身的相关性信号而提高采纳率的偏向，不证明所有旧采纳都错误。新独立Prompt要求比较plain、谨慎利用物理关系、尊重Tchebycheff尺度/最大项并允许弃权；不把GP锚点consistency或LLM confidence当作实证正确率。

一个冻结真实样例因此保留已实评plain。预注册三种子软件对照采纳15/60（旧策略28/60）；新策略HV对plain两胜一负、对旧策略也两胜一负，但对旧策略的平均HV差为负。保留全部种子、原参数及默认行为，不作整体优越性结论。详见`docs/audits/region-fairness-repair-2026-10-20.md`；真实新版本API/DFN性能与实测辨识仍未验证。
