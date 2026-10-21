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

### 任务级思考控制与有方向的历史证据（2026-10-20）

一次明确批准的真实请求返回HTTP200，但1536个completion tokens全部记为reasoning，正式content为空、finish_reason=length。失败在JSON解码之前，不是Region数值守卫拒绝。底层ChatCompletionsTransport早已支持thinking，v2配置和任务解析层却没有接线。新增可选`llm.thinking="enabled"|"disabled"`及同名task_options覆盖；缺省省略，保留旧行为。任务timeout/tokens仍不得超过全局上限，thinking为独立类别控制，显式null/布尔值/对象拒绝。注入Chat客户端按本任务配置克隆，不修改原对象。没有自动加tokens、自动换模型或重试。

DeepSeek官方文档支持请求体`thinking:{"type":"disabled"}`，但不能据此认定vsllm的具体模型别名透传该字段。新版归档记录实际请求模式和安全completion摘要：结束原因、正式答案字符数及有效非负token计数；只有length、空正式答案、completion达到上限且全部被报告为reasoning时，才标记reasoning_budget_exhausted。原protocol_error/unfinished_completion仍保留，不读取reasoning推导答案、不接受半截JSON。审计以HTTP文件/事件判断是否存在请求，不能通过修改outcome标志关闭检查，并从原始响应重算摘要。

另一个输入限制是仅有非负RMSE无法区分预测偏高/偏低。可选`optimization.region_evidence="signed_residual_v1"`仅搭配candidate_aware_v1+fair_region_v1；缺省legacy_v1保持旧payload与Prompt。新模块从已有曲线按各通道自身网格计算prediction−observation的样本均值、首/末四分之一样本均值（ceil(n/4)），附V/K单位、有效性和样本数；显示8位有效数字。失败通道统计为null，温度不再转换，两个优化目标保持原完整曲线RMSE。

新独立274词Prompt解释误差符号、早/晚误差、C/G的条件性热响应和短窗混淆，明确不能虚构未观测候选的分量预测。新模式在发送前拒绝任何不属于冻结GP历史ID的输入记录，包括未来半失败记录；这些失败曲线仍保留在诊断归档。审计从过去原始评价重算摘要并核对独立Prompt。WarmStart payload不加这些字段，原Lift、信任更新、GP、方差、权重、资格门槛和fair基线均不变。

这两项修复分别解决服务可操作性和方向证据缺失，不构成RMSE收益证明。真实验证应先核验完整JSON与服务端用量，再在固定初始化和独立预定种子上比较全部Pareto/HV及同一参数双RMSE；不得以采纳率、软件正例或挑选最优种子宣布有效。证据见`docs/audits/region-response-repair-2026-10-20.md`。

### 冻结标量贡献与坐标示例（2026-10-20）

d90b93f的真实0.5C/1C、60秒、共享八点、三个固定种子两臂各20轮消融已完整结束：新DFN256、API43，三对ΔHV均0。Full60轮中17无eligible、26合法none、14请求失败、2区域超宽；唯一合法区域执行Lift后未胜过同场Plain基线，最终没有改变选点。该结果不证明Region有效，也不是用随机初始化普通ParEGO比较整个LLMBO-MO。原始完整档案、成本、失败与负结果保持封存。

正式短reason存在把权重大小当主导项、试图同时包住Plain和多个alternatives的误读。独立零API/DFN冻结诊断保持原confidence0.62及全部数值设置，只换为更聚焦的mock区域即可通过公平守卫；没有真实评价新点，不能把该选点容量当RMSE改善。

新增可选`optimization.region_evidence="decision_geometry_v2"`，仍须candidate_aware_v1+fair_region_v1，缺省legacy_v1与signed_residual_v1保留原Prompt和payload。新模式继续提供signed曲线证据，只增加`decision_evidence`和独立285词英文Prompt。host从同轮冻结历史计算`w_j*(F_j/scale_j-ideal_j)`、最大项/精确同分、augmentation及原标量g；从已有候选摘要计算`mu_candidate-mu_plain`，负为更低、正为更高的标准化标量预测，不伪装成候选真实U/T。

每个已展示eligible候选平等附一份坐标示例：各轴使用配置已有min_width，中心区间在边界整体平移入[0,1]，不再做物理或log变换，不舍入。示例只保证归一化坐标/宽度，不保证物理anchors、最佳宽度或采纳；Plain不提供示例，没有自动置信度、排序奖励或强制建议。模型可选择合乎证据的区域或弃权；不要求区域包住Plain/全部候选。非法真实回复仍被拒绝，不裁剪修复。

GP、原方差、训练标签、真实目标、权重生命周期、EI/Lift强度、信任和公平门槛完全不变。新模式的算法/源码签名和紧凑请求绑定覆盖新增证据；旧六参数缓存校验不放宽。审计从过去曲线、冻结上下文和候选信息重建新数字/几何，并核对发送的历史原参数、目标、标准化坐标和g；篡改或缺失须失败。详见`docs/superpowers/plans/2026-10-20-region-decision-evidence-plan.md`。新模式的真实API选择行为、RMSE/HV收益仍未验证，需要新的独立预算。

### 非初始动态证据（2026-10-20，A1）

可选`optimization.region_evidence="dynamic_decision_v3"`仍要求candidate_aware_v1+fair_region_v1，保留旧signed与decision字段，另加dynamic_history_evidence和每条过去历史的dynamic_residuals。严格读取同次trace.time_s[0]；缺失/非有限起点为unknown，不猜零、不向后找有限值、不以首个观测替代。有效但畸形通道抛ValueError；无效通道残差/动态数/均值为null。只有观测时间精确等于求解起点才记录initial_residual；之后的真实观测才是动态。

各U/T通道保持自己的观测网格。动态点不超过8个时全部展示；更多时展示8个确定的实际索引及原时间。dynamic_sample_mean始终为全部非初始观测残差的等样本均值，不是时间积分或斜率；被省略的点仍参与。残差为prediction−observation，显示8有效位，温度不再次换算。initial-only的动态均值为null，真实正负抵消得到的零均值仍标dynamic。完整曲线RMSE及GP训练、方差、选点规则不改。

独立英文Prompt解释稀疏证据的限度，但不根据样本数量断言不可辨识或强制弃权。新模式独立签名和审计；从原始归档曲线/观测、冻结历史重建起点、全部动态均值、展示索引及历史顺序。旧模式/Prompt/缓存拒绝条件保留。软件通过不代表新Prompt的真实行为或RMSE/HV增益，后者仍未验证。

### 请求绑定的区域目录（A2）

可选`optimization.region_proposal="catalog_v1"`要求dynamic_decision_v3、candidate_aware_v1及fair_region_v1；缺省bounds_v1保留旧坐标回复。host只从原有最多12条候选摘要中的eligible替代点构造目录，每点使用min_width的1/2/4倍、由max_width封顶且去重。六轴区间在边界整体平移入[0,1]，最多33项；不新增候选点、不排序奖励、不保证锚点物理可行。

新独立英文Prompt让LLM选择一个region_id并引用1–3个已发送的过去evaluation_id，或返回none。模型不能输出或修补坐标。region_id绑定版本/context/candidate/lb/ub；catalog_digest绑定有序目录；proposal_binding绑定整个冻结专业请求，仅排除artifact_task、response_contract及自身以避免循环。完整与紧凑传输都必须返回proposal_binding，none也不例外。旧维数相同的回复、跨倍率/权重/尺度/历史/Prompt的回复不能重用。

resolver严格验证键集合、类型、有限置信度、历史ID和绑定，从host目录逐字复制坐标，输出旧canonical envelope。原Lift、后验方差、真实标签、训练集、EI、信任反馈及fair门槛不变；同一冻结上下文和规范矩形的数值输出与旧bounds控制完全相等。无合格替代点时原控制逻辑仍跳过请求。

controller保留私有序列化请求，只向transport传递独立深拷贝。正式回复另存脱敏JSON文本，非法NaN可作为文本保留用于失败重放，不能进入优化；键和值中的token形文本均遮罩且不合并键。transport修改clone时另存独立证据并单次失败回退，不自动重试。审计从冻结历史、曲线、候选池及配置独立重建完整请求、目录和回复契约，再核对正式回复、resolution、HTTP full/compact封套和canonical结果；不信任自洽重签的派生摘要或失败标志。

本轮只验证接口与软件行为，真实API、DFN和实测预算均0。下一步真实契约预检与独立验证种子的配对实验须另立协议；既有负结果和开发诊断种子101/211/307保留，不将目录采纳率视为RMSE/HV增益。详细证据见`docs/audits/region-dynamic-catalog-2026-10-20.md`。


catalog审计还会重放失败的HTTP completion/JSON/wire，而非依赖outcome声称失败；修复原回复后仍声称invalid_binding会被发现。注入transport须返回原生JSON类型，非原生Python值保留拒绝标记，不能在归档中由tuple变list而变成合法回复。host重建请求则使用与controller相同的canonical JSON边界处理科学数值，不将这一处理用于放宽模型回复。

本轮最终全量软件验收通过，实际数量、源码提交、待机时限失败及恢复、原数值不变和旧归档证据均见region-dynamic-catalog审计。临时测试唤醒请求已释放；真实API/DFN增益与实测没有由此验证，未来契约预检仍是未执行草案。

### Sub2API Responses 传输（2026-10-21）

电热 schema v2 可显式设置 `llm.transport="openai_responses"`。缺省保持原 Chat Completions；schema v1 不接受新取值。新模板为 `configs/electrothermal-sub2api-software-template.json`：目标 `https://sidrune.ai/v1/responses`、模型 `deepseek-v4-pro`、凭据环境变量 `SUB2API_API_KEY`。模板保留原人工软件问题和 ParEGO，LLM disabled、API/DFN 预算均为0；不会默认测试连通性或启动真实辨识。

Responses 请求使用 instructions/input/max_output_tokens/text.format，固定 store=false、stream=false，无工具、会话续接、自动重试或模型发现。Codex CLI 的 review_model、model_catalog_url、features 等不导入科研配置，不修改全局Codex设置。store=false 是客户端请求，不能据此保证第三方日志保留政策；本地脱敏科研归档继续保留。

只接受 completed 且无 error/incomplete_details、单个 completed assistant message 中的单个 output_text JSON 对象。reasoning不作为答案；refusal、截断、多答案、工具、非法JSON和非有限数值拒绝，不从choices或便利output_text猜测补救。现有WarmStart/Region封套、compact绑定、目录校验随后照常执行。新站thinking扩展未确认，首版拒绝显式thinking设置，不静默映射或宣称已关闭推理。

新bounded worker共用原硬截止与自有进程清理，保留真实response_status和usage；缺失计量为unknown，不补0。Y、GP、EI、Lift、fair guard和信任不变。Responses另存 `.responses-formal.json`，审计重建最终请求及冻结边界，核对原始回复、正式收据、完成状态、绑定、监督及成本；真实接收记录不能通过删除HTTP证据并改掉诊断标记逃避审计。旧Chat档案按旧协议重放。

审阅修复另要求：每个请求的payload/outcome/cost完整对应；原始回复存在时完成摘要不可省略。WarmStart正式候选按原顺序对应真实筛选评价、重复/无效候选及预算计数；full和compact的bounds回复均对应实际使用区域。缺密钥在构造传输前跳过，不记API成本且可审计；连接字段类型错误在配置阶段拒绝。以上均不改变WarmStart的Pareto＋Max–Min选择或Region数值公式。

本次软件验证与此前vsllm单次目录预检分别归档。Sub2API真实请求、DFN和正式BO仍为0；需要专用密钥和新明确预算才能测试本站，不能沿用vsllm已关闭额度。实际证据见 `docs/audits/sub2api-responses-2026-10-21.md`。
