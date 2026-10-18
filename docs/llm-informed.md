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
