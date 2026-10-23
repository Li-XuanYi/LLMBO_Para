# LGBO 工程整理、Prompt 与 Region 优化设计

日期：2026-10-23，Asia/Shanghai。状态：**用户已于本日回复“同意”确认书面设计；详细实施计划待审阅，产品代码和运行策略尚未变更。**

## 1. 目标、当前基线和边界

用户要求优化工程规范，并分析 LLM Prompt 和 Region 方法的改进空间。目标是先降低当前实现的维护和重复计算成本，再分别检验提示信息与区域偏好的价值；不能把工程提速、动作合法或改变选点当成辨识增益。

检查基线：`567002ab010b1e91cae38e673171e2818466f98d`，工作树开始时干净。沿用 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`、分支 `codex/electrothermal-mo-20261016`。主工程与参考工程只读；已有密封交付和实验不修改。CodeGraph 按用户既有决定暂缓初始化。

六参数4E+2T、DFN+lumped、配置化 fit_rates、两个预测RMSE、ParEGO、ARD Matérn GP、Gaussian EI、固定尺度/HV空间保持。旧 schema1 四倍率电压任务、旧配置和签名校验保持。旧3C不参加新版拟合。无新核、热自由变量、目标、信任乘子、候选目录或竞争守卫。

本次只读核查代码/历史证据并查阅一手文献；新增 pytest、GP拟合、目标评价、API、DFN和BO均为0。上一轮1092/1092是历史最终回归，不是本次测试结果。后续软件实施需新基线和TDD；真实API/DFN需独立明确协议与预算。

## 2. 证据与问题定位

|事实|判断|
|---|---|
|MOOptimizer.step和apply_lgbo_region各做一次相同pool的predict/EI|有可消除的生产路径重复；不是每轮训练两个GP|
|electrothermal_llm.py共454行，payload构造混合WarmStart、旧策略与LGBO|职责交叉、兼容分支较多；旧策略不是可直接删除的死代码|
|当前LGBO从region_catalog引用通用JSON归档/HTTP工具|命名与依赖方向不清楚，应隔离通用工具|
|240个已封存Full轮次，外层与region内mean/std/plain-EI完全重复|紧凑JSON约3,925,969字节；是归档冗余，但目前不是主要性能瓶颈|
|LGBO accepted和selection_changed相同|兼容别名，不能解释为真实改善|
|weighted evidence、独立tilt重算位于审计模块|有意的独立验证；不能为了DRY改成调用生产公式自证|
|固定mock的12组配对中4正8负；GP拟合0→4的12个对照均提高HV；候选加密结果混合|没有稳定Region增益证据；不可归因为公式未实现，也不能盲目加大confidence或候选数|

当前WarmStart Prompt为256词，Region v2为266词；长度已符合既定200–300词范围。v2已经提供q分量、活动瓶颈、当前标量g、top4/极值/recent3、动态残差、宽维度和none。历史按evaluation_id去重也已实现，均不列为待补功能。

## 3. 路线选择

**推荐：工程等价整理 → 同payload的Prompt候选 → 证据支持后才研究Region变化。** 三者分开验收，先保留现有数值方法和归档格式。

另两个方向暂不采用：全仓库重写/统一格式化会扩大旧流程风险；同时更改公式、置信度、候选池和Prompt会失去归因。研究备选不作为默认开关叠加到主线上。

## 4. 工程整理的具体设计

### 4.1 一轮一份不可变预测视图

优化器完成当轮历史标量化、GP拟合和pool生成后，只计算一次原始mean/std/EI，形成包含本轮context、候选池身份、GP状态身份和真实incumbent的不可变预测视图。LGBO复用该视图，仅计算区域协方差、tilt和调整后的EI。

视图采用不可变原生数值序列；防止NumPy数组经别名被写入。传入视图必须与当前context、pool、GP状态和incumbent一致，错轮/错池/换权重后旧视图在评价前拒绝。独立调用apply_lgbo_region的旧入口仍可不传视图并自行构造，保持旧调用可用。生产优化器不得再走两次基础预测。

预测视图放在现有采集基础设施，MOOptimizer继续只负责生命周期和调度。32个区域锚点、潜在后验协方差、均匀权重、公式、容差、候选顺序、同分规则、EI阈值及失败回退不改。

### 4.2 分离payload与通用JSON职责

新增一个电热payload模块，内部以明确入口分别构造WarmStart、LGBO和旧策略请求，共用参数/工况/历史的基础序列化。原build_electrothermal_payload作为兼容入口保留；LGBO直接构造自己的动作契约，不先创建旧契约再覆盖。

新增一个通用电热JSON模块，承接原生JSON检查、脱敏归档等与catalog无关的功能。原catalog公开名称保留薄兼容入口，确保旧调用和测试仍可用。HTTP协议的共用部分与传输专属部分保持明确，不将Chat/Responses压成丢失完成状态信息的单一路径。

本轮最多新增这两个生产模块；不为了拆分而新增策略注册框架。控制器保留预算、请求、结果归档与安全回退职责。旧apply_electrothermal_region、update_electrothermal_trust及其行为不动；独立审计继续自己计算数值。

### 4.3 规范与归档策略

仅整理触及模块：一条语句一行、清晰命名、公共边界类型标注、单位/前置条件/错误说明、删除确实未使用的局部导入。保留锁版本，不安装新的格式化/检查依赖，不做全仓库机械格式化。

本次工程整理保留既有归档字段，包括重复数组和accepted兼容别名；它们由同一预测视图生成。用文档区分合法动作、非零tilt、选点变化、当前冻结标量改善与运行级HV收益。存储去重需要独立的归档schema迁移，暂缓；不重写旧档案换取磁盘节省。

### 4.4 工程验收

- 在固定历史、权重、GP、pool和动作下，原始/调整后mean/std/EI、索引、参数、真实Y与旧实现一致。
- 基础predict与plain-EI在生产每轮各一次；不把审计重算计为生产重复，也不靠更少GP拟合获得提速。
- 错context、错pool、错GP状态、旧incumbent和可变输入别名的失败测试；错误在实际目标评价前出现。
- 旧v1/v2 Prompt字节及固定身份下payload golden不变；不修改golden迎合重构。两种离线生产transport、错误回复、失败轮换权重、旧配置、篡改审计继续通过。
- 真实源代码指纹会改变。新软件夹具在实际新源码下建立；旧缓存/初始化计划不换签、不放宽。旧归档按自身旧源码核验。
- 新完整基线、RED→GREEN、针对性回归、全量回归与一次最终独立审阅，保存实际数量、退出码、日志/JUnit、边界和文件清单。重复预测计数是主要工程验收；计时只作同环境描述，不承诺固定百分比提速。

## 5. Prompt 分析与候选

### 5.1 真正缺少的是任务边界与操作语义

这是参数辨识反问题。某参数使预测温度上升，不代表温度RMSE一定下降；需要同时看预测−观测残差、热源和工况。不能照搬配方性能优化中的单调启发式。

当前payload已提供simulation_kind/model_provider和工况摘要，但WarmStart正文要求使用“measured”目标，Region正文始终称DFN。对于synthetic_software，语言与真实来源不完全一致。候选Prompt应明确以来源标签为准，不把软件夹具或DFN合成数据称为实测，也不向模型泄露合成真实theta。

confidence当前是区域平均预测标准差意义下的tilt强度，不是“有c概率赢过Plain”。候选Prompt明确这一点，继续允许none；不加固定低置信度拒绝门槛。

温度初始残差与动态残差已分离，应继续保留。短窗口可能弱约束G_th：由C_th*dT/dt=Q_gen−G_th*(T−T_amb)，当温差很小时，散热项贡献可能较小。这是待真实DFN灵敏度检查的物理判断，不是已证明某参数不可辨识。Prompt应允许弱证据维度维持宽范围。

### 5.2 首个Prompt对照保持payload和host选择不变

第一候选只调整文字，不变字段、历史集合、排序、token上限、动作结构、32锚点和mean tilt。保留200–300词英文、仅JSON、不要求reason或思维解释。WarmStart仍由host进行真实评价和Pareto+Max–Min筛选；Region仍返回一个矩形或none。

当前v1/v2产品Prompt冻结，不覆盖。以下仅为设计中的候选文案，不注册新默认版本。产品发布的版本名与请求签名在后续计划明确；新增版本不等于新增算法或可叠加策略。

**WarmStart候选：**

> Propose initial candidates for identifying one shared six-parameter electrothermal battery model. Read simulation_kind and model_provider first. Software fixtures, DFN synthetic observations, and measured experiments are different evidence sources; describe none as another. Infer no hidden generating parameters.
>
> Use the named active-material fractions, reference solid diffusivities, whole-cell heat capacity C_th, and cooling conductance G_th. Follow supplied bounds, units, transforms, fixed properties, and temperature laws. Reference diffusivities retain their stated reference temperature and activation energies. Do not introduce conductivities, extra thermal variables, or additional objectives.
>
> Minimize the two supplied errors: voltage RMSE in volts and cell-temperature RMSE in kelvin, each averaged over configured fit_rates. All conditions share the same candidate vector. A smaller temperature rise is not the temperature objective. Treat ambient temperature, initial state, and target cell temperature as distinct quantities.
>
> Use evaluated history and residuals to propose a diverse batch. Include balanced alternatives that explore electrochemical and thermal tradeoffs rather than repeating one plausible vector. Physical trends concern model outputs; whether they reduce error depends on the observed residual. Sparse or short-duration evidence does not establish unique parameter values, especially for cooling. Retain uncertainty instead of inventing current, cooling conditions, or measurement details.
>
> Return no more than requested_candidate_count and obey response_contract. Provide distinct candidates using named physical parameters, not normalized bounds or predicted objective labels. The host validates feasibility, evaluates proposals, and selects initialization by its fixed Pareto and diversity rule. Return only the required JSON, with exact task identities and no explanation, reason, or extra fields.

**Region候选：**

> Recommend one parameter rectangle for the current frozen optimization round. Use simulation_kind and model_provider as the authoritative evidence source. Do not treat software fixtures or synthetic observations as measured battery validation. Respect the six named parameters, supplied physical definitions, bounds, transforms, and temperature laws.
>
> The task minimizes voltage and cell-temperature prediction RMSE across fit_rates. It does not minimize temperature rise. Use the current weights, fixed scales, ideal point, rho_aug, and host-computed weighted_objective_evidence. The active maximum component identifies the current scalar bottleneck; a larger weight alone does not. Compare top solutions, objective extremes, recent evaluations, and the supplied dynamic residuals under this same context.
>
> Residuals are prediction minus observation. Mechanistic trends in voltage or temperature do not directly determine trends in fitting error. Multiple parameters can compensate for each other. Do not infer single-parameter causality or uniqueness from sparse correlated trials. Respect initial-versus-dynamic residual separation and the actual observation duration. Keep weakly supported dimensions wide; do not narrow all six dimensions by habit or simply recenter the previous best.
>
> Return one coherent rectangle in the supplied normalized coordinate order, or kind none when evidence cannot support a useful preference. Confidence controls the regional Gaussian mean shift in standard-deviation units; it is not a probability of beating Plain BO. Stronger confidence requires stronger relevant support. The host keeps the original variance and real incumbent, and selects by Gaussian EI over the entire candidate pool, so the tested point may lie outside your rectangle.
>
> Return only JSON matching response_contract. Copy request_id exactly. Supply no explanation, reason, or additional fields.

若后续需要“相近参数但较差g”的对比样例，单独比较历史选择规则；不能同时改Prompt和样例集合后将收益都归于Prompt。当前top4/极值/recent3已经去重，不重复开发。近邻差例也不能证明单参数因果。

## 6. Region 方法能否优化

### 6.1 保留数学核心，先验证偏好的信息质量

当前最小化规则为mu_tilde=mu−c*K_xA*a/sqrt(a^T*K_AA*a)，方差、真实标签和incumbent保持。已有非零tilt及改变选点证据，不能把不增益解释为漏实现公式。自然界abs(delta)<=c*sigma只限制单轮扰动幅度，不保证排名、最终HV或RMSE改善。

可能的限制包括：LLM一般电化学知识未必能定位参数误差低区；轴对齐矩形可能混合相关参数脊线上的好坏点；每轮权重改变意味着偏好目标改变；强GP基线可使Region剩余空间很小。这些是待验证假设，不是本轮已定位的因果原因。

不立即修改直接置信度映射、32锚点、EI或候选生成。尤其不恢复trust/复杂守卫，不强制选区内，不通过增加c追求更高selection_changed。

### 6.2 最小诊断顺序

1. 固定同一旧冻结状态，只重放c=0/.25/.65和32/128锚点的调整幅度与EI排序。候选池固定，分别改变一项；替代点未经真实评价时不给它们填RMSE/HV，不据此挑“最优c”。实际运行须在后续计划审批后进行。
2. 真实LLM效果确认时，共享有效初始化和相同数值预算，分别比较Plain、当前v2、候选Prompt；所有负结果保留。预留种子101/131/167仍未使用作确认；每个运行而非每轮是统计单位。单一初始化、三个种子的证据有限。
3. 如需区分语义信息与任意扰动，再增加大小/confidence匹配的随机区域控制。它是研究对照，不是生产新策略；实验规模和预算另批。
4. 只有明确发现候选覆盖或积分不稳定，才另审区域锚点候选复用或积分点增加。必须匹配候选数量，区分采样位置与tilt贡献，保持context绑定和独立审计；本设计不实施。

### 6.3 验收指标

软件：等价性、冻结上下文、签名/边界、退化/失败回退与审计正确。

真实API：动作合法、绑定正确、请求完成与延迟；不把合法率当优化收益。

真实DFN合成：运行级固定空间HV差、同一代表参数点的双RMSE、逐倍率误差/曲线、有效目标数和实际成本。数据生成theta对LLM隐藏。不能用软件代数夹具代替物理行为验证。

实测：确认实际电流/时间、温度单位和测点、初始状态、冷却条件、热参数范围及固定物性来源后另行开展；坏旧3C继续排除。不以低误差宣称唯一可辨识。

## 7. 一手文献与适配边界

- [LGBO v1，2026-05-18，§3.2/§3.4/§4.3/Appendix B](https://arxiv.org/html/2605.17976v1)：支持区域偏好与协方差均值调整、结构化历史及随机区域对照。其固定方向GP-UCB分析不覆盖本项目动态ParEGO/EI，不能当成本项目增益或不劣保证。本项目保留动作JSON，不迁入论文的解释文字或“机理优先于矛盾观测”的提示规则。
- [LLAMBO v2，2024-03-08](https://arxiv.org/abs/2402.03921v2)：研究上下文、参数语义和历史示例用于BO。对本项目的启示是分别控制任务文案与样例集合；没有证明本设计的对比样例或Prompt最优，也不迁入其LLM surrogate。
- [CALIPER v2，2026-06-12](https://arxiv.org/pdf/2606.01730v2)：讨论多目标先验质量、自报置信度和弃权。仅借鉴“confidence需要实证校验”的问题意识，不迁入多专家、信任市场或门控系统，不将分子离散MOBO的结果视为本电热标量EI的验证。

## 8. 自审、交付和下一步

本设计区分工程等价整理、Prompt假设与方法研究；已存在功能不列为新功能。独立审计不与生产数学实现合并，旧Prompt/归档不改写，源指纹改变后不重签旧计划。候选Prompt仅在本设计内；设计文案和确定性静态检查不能声称软件实现完成或优化增益。

书面设计确认后，生成独立的可执行实施计划，逐项明确实际文件、接口、失败测试、兼容golden、证据和提交。计划审批后才实施工程整理。Prompt和Region的真实API/DFN确认另定具体预算；当前批准数量均0。延续当前会话原生实施方式，不创建新线程或服务器任务。
