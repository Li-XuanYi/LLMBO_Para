# 原 LLMBO-MO 迁移核对表

2026-10-16。只读参考：`D:/Users/aa133/Desktop/BO_Multi_12_20/New_LLMBO`。状态：设计阶段核对，尚未迁入产品代码；实际参考文件 SHA-256 见 preparation-evidence.json。未读取 .env、未安装参考工程依赖、未运行原工程。

参考工程有 CodeGraph，先使用 context/explore。发现个别 node 的索引行号与当前文件位置不一致，返回片段不含所请求函数体；因此对已经打开的具体文件补读缺失函数体，以当前源码为准，没有重建索引或写入参考工程。

| 原文件/部件 | 本机核对结果 | 迁移方式/目标 |
|---|---|---|
| `llmbo/scalarization.py::compute_tchebycheff` | max(weighted)+eta*sum(weighted)，默认 eta=0.05 | 保留数学式，新二维输入/显式尺度与理想点，严格验证 |
| `log_transform_objectives` | 第0列 log10(max(value,1.0))；第2列 log10(max(value,1e-12)) | 不迁移；两误差目标 identity，防止 <1V 被压平/第三列越界 |
| `compute_tchebycheff_from_raw_with_ideal` | 先充电目标 log，再理想点距离及预处理尺度 | 新目标identity、协议固定尺度和RMSE合法零下界；不搬充电变换或历史最小值理想点，避免绝对距离误判超越旧最小值的改善 |
| 原动态 minmax/zscore/none | 动态区间含对充电目标全局范围回退 | 首版固定显式物理尺度，无动态范围；可选扩展另行评审 |
| `llmbo/optimizer.py::_next_weight` | 无放回随机排列循环；可配置有放回 | 保留带种子的无放回机制，新二维 simplex 网格 |
| 原权重生成/初始化 | n_obj 默认3，初始化 w=[1/3,1/3,1/3]；原五维充电输入 | 不照搬维度/变量；新固定2目标、6物理参数 |
| `llmbo/gp_model.py::MaternGPModel.fit` | 归一化五维，Constant×ARD Matérn(ν=2.5)+White，sklearn目标标准化 | 数学机制迁移；复用主工程 NumPy六维 Matérn52GP，无新依赖、无分组/长度尺度先验 |
| GP目标变换/后验协方差 | 可选变换、训练目标标准化、latent后验协方差 | 新线性标量标准化上下文；复用主工程posterior_covariance，显式空间标记 |
| `llmbo/acquisition.py::expected_improvement` | 高斯EI公式；std裁到1e-12后该边界直接设0 | 公式迁移；修正sigma→0为max(best-mu,0)，记录有意偏离并测试 |
| 原采集/变量修复 | dSOC、单调充电电流、五维 repair 与额外 prior/risk | 不迁移；仅新参数边界/孔隙约束，三路线同一候选策略 |
| `DataBase/database.py` Pareto/训练记录 | 从可行真实观测取非支配集 | 新二维完整目标对；保留失败诊断与成本，不填标签 |
| `_compute_hypervolume_value` | 第0/2列充电log；pymoo或三维HV回退 | 不搬原三维HV；新固定误差指标空间的精确二维矩形并集 |
| `canonical_hv_from_raw` | 用固定最大HV作比例 | 不默认引入；新HV直接报告固定指标空间及参考点，可选显示比例需独立标注 |
| `llmbo/warmstart_selector.py` | 候选质量、参数多样性及原充电软约束 | 迁移组合思想，使用设计第9.1节确定的pareto_maximin_v1：双目标层级、平衡质量首点、同层maximin、固定同分键和预算不足停止；不带充电偏好 |
| `llm/llm_interface.py` WarmStart | 原变量/工况、结构化候选生成 | 新电热任务/schema/Prompt；只复用主工程安全传输/错误归档 |
| `llmbo/region_lifted_gp.py` | 后验相关性/协方差、confidence/anneal/trust、局部有界均值移位及plain EI保护 | 新当前权重/尺度/理想点上下文的均值调整，不改方差/标签；不搬dSOC守卫 |
| `llm/region_prompt.py` | 原充电目标与区域采样语义 | 独立200–300词电热Prompt，不改旧Prompt |
| 主工程 `informed.py` | 现有六维后验相关性调整，但绑定scalar_log_ei与objective_v摘要 | 复用纯数值、范围校验思想；新上下文/高斯EI/双目标摘要，不能直接调用旧决策路径 |
| 原信任/历史改善 | 原权重与历史上下文依赖需审查 | 本轮选点与反馈同一冻结上下文；下一轮即使无新增目标也重拟合。弃权/回退/缓存不产生新的Region信任证据，不跨权重比较scalar值 |

尚需在实现任务中逐行完成的核对：参考Region-Lift各守卫与新线性目标的单位一致性、已明确的WarmStart选择规则实现、GP预算及后验重放。它们属于阶段B/C审查范围，当前没有声称迁移验收通过。R1书面设计的规则已明确，不表示相应产品代码或物理验证已经完成。

主工程保留全部旧路线。新的参数profile、目标定义、物性函数、模型/数据、算法上下文签名隔离缓存；旧六维数字、旧45mV分数、旧LLM回复均不作为新电热成绩。
