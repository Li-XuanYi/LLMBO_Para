# Method — 基于 LLMBO-MO 的锂离子电池电热耦合多目标参数辨识

> **论文方法草稿（中文，2026-10-22；LGBO Region 简化修订）**
>
> 研究定位：将现有 LLMBO-MO 框架应用于电化学–热耦合参数辨识；本研究不声称提出新的 DFN、集总热方程、ParEGO 或高斯过程算法。软件实现、真实DFN合成验证和实测辨识分别验收；软件闭环不证明参数唯一可辨识或LLM有效。
>
> 与项目设计的关系：以 **docs/superpowers/specs/2026-10-16-electrothermal-identification-design.md（R1.1）** 的物理与优化约定为依据。2026-10-16的scope审计保留为历史；用户2026-10-17确认旧3C数据有问题，当前新版电热拟合排除该数据。其它实测元数据仍待确认。此文是论文正文草稿，不是批准实施计划或实验结果。
> Region的新策略依据已批准的 **docs/superpowers/specs/2026-10-22-lgbo-region-simplification-design.md**，实现及软件证据见 **docs/audits/lgbo-region-simplification-2026-10-22.md**。

## III. Method

### A. Problem Formulation

本文研究锂离子电池在多倍率恒流放电条件下的电化学–热耦合参数辨识。令 \(\mathcal R_{\mathrm{fit}}\) 为实验协议在候选评价前指定的非空有效拟合倍率集合，由新版配置的 `fit_rates` 决定。每一工况 \(r\in\mathcal R_{\mathrm{fit}}\) 具有外部激励和实验边界条件，包括电流 \(I_r(t)\)、环境温度 \(T_{\mathrm{amb},r}(t)\) 及初始电化学与热状态；实验观测包含端电压 \(U_r^{\mathrm{obs}}(t_i^U)\) 和电芯温度 \(T_r^{\mathrm{obs}}(t_j^T)\)，允许两类观测使用不同时间网格。

当前拟采用 \(\mathcal R_{\mathrm{fit}}=\{0.5\mathrm C,1\mathrm C,2\mathrm C\}\)，不使用用户已确认存在问题的旧3C数据。待获得可靠3C观测及其电流、温度和边界元数据后，可另建配置采用 \(\{0.5\mathrm C,1\mathrm C,2\mathrm C,3\mathrm C\}\)，无需修改优化算法。三倍率仍须经过完整实测预检，排除3C不代表其它输入已确认。

倍率成员及执行顺序、选中数据的身份/哈希、观测映射和排除原因进入协议、数据、缓存和最终归档签名。当前三倍率与未来四倍率属于不同实验协议；候选级评价缓存、初始化计划和GP状态不得跨协议直接复用，平均误差和HV也不能直接拼成同一比较曲线。旧原始XLSX、实验、缓存及schema_version=1的四倍率电压流程全部保留。新版不以旧RATE_ORDER推断拟合集合，也不因单个候选失败临时删除某一选中倍率。

第一版选择四个电化学参数和两个热参数构成辨识向量：

\[
\boldsymbol\theta =
\left[
\underbrace{\varepsilon_{s,n},\varepsilon_{s,p},
D_{s,n}^{\mathrm{ref}},D_{s,p}^{\mathrm{ref}}}_{\boldsymbol\theta_{\mathrm{ec}}},
\underbrace{C_{\mathrm{th}},G_{\mathrm{th}}}_{\boldsymbol\theta_{\mathrm{th}}}
\right]^{\!\top}\in\Theta.
\tag{1}
\]

| 待辨识参数 | 物理意义 | 单位 | 优化坐标 |
|---|---|---|---|
| \(\varepsilon_{s,n},\varepsilon_{s,p}\) | 负、正极活性材料体积分数 | — | Linear |
| \(D_{s,n}^{\mathrm{ref}},D_{s,p}^{\mathrm{ref}}\) | 参考温度下的负、正极固相扩散率 | m²/s | Log10 |
| \(C_{\mathrm{th}}\) | 整电芯等效热容 | J/K | 显式配置；合成原型采用 Log10 |
| \(G_{\mathrm{th}}\) | 整电芯有效散热导纳 | W/K | 显式配置；合成原型采用 Log10 |

可行参数域 \(\Theta\) 由参数上下界、正值约束以及活性材料体积分数与固定孔隙率的物理关系决定。各界限须由预先确定的实验协议指定并注明来源；原六参数电压辨识中两极电导率的优化范围不可直接转作热参数范围。其余电化学物性、几何、熵变函数、初始状态、冷却边界和固定活化能另行记录为已知设置，而不作为隐含的可调自由度。

### B. Coupled Electrochemical–Thermal Model

采用 Doyle–Fuller–Newman（DFN/P2D）模型描述电极固相扩散、电解液传输、界面电化学反应和电势分布。在球形颗粒假设下，电极 \(k\in\{n,p\}\) 的固相锂浓度满足：

\[
\frac{\partial c_{s,k}}{\partial t}
=
\frac{1}{r^2}
\frac{\partial}{\partial r}
\left(
D_{s,k}(T)\,r^2
\frac{\partial c_{s,k}}{\partial r}
\right).
\tag{2}
\]

结合电解液和固相电势方程及界面动力学，可以获得端电压 \(\widehat U_r(t;\boldsymbol\theta)\) 和模型发热功率 \(\dot Q_{\mathrm{gen},r}(t;\boldsymbol\theta)\)。在球形颗粒近似下，局部比反应面积 \(a_{s,k}=3\varepsilon_{s,k}/R_k\)；因此电极活性材料体积分数既影响可参与反应的材料量，又影响反应面积及极化过程。

温度采用单节点集总热平衡：

\[
C_{\mathrm{th}}\frac{\mathrm dT_r}{\mathrm dt}
=
\dot Q_{\mathrm{gen},r}(t;\boldsymbol\theta,T_r)
-
G_{\mathrm{th}}\left(T_r-T_{\mathrm{amb},r}\right).
\tag{3}
\]

总发热应由启用的 DFN 热源项一致计算，包括模型支持的欧姆热、不可逆反应热以及依据选定参数化启用的其他热项；不能假设未经来源确认的可逆热贡献已经存在。利用 PyBaMM 25.10.2 的集总热模型及集中热容选项，将两个热参数映射为：

\[
\left(\rho c_p\right)_{\mathrm{cell}}^{\mathrm{eff}}
=\frac{C_{\mathrm{th}}}{V_{\mathrm{cell}}},
\qquad
h_{\mathrm{eff}}=\frac{G_{\mathrm{th}}}{A_{\mathrm{cool}}},
\tag{4}
\]

其中 \(V_{\mathrm{cell}}\) 和 \(A_{\mathrm{cool}}\) 为固定且可追溯的几何量。映射单位分别为 J·K⁻¹·m⁻³ 和 W·m⁻²·K⁻¹，需与求解器实际采用的热体积及冷却面积一致。

模型温度通过物性与反应动力学反馈至电化学方程。对于显式引入温度依赖的固相扩散系数，使用 Arrhenius 形式：

\[
D_{s,k}(T)
=
D_{s,k}^{\mathrm{ref}}
\exp\left[
\frac{E_{D,k}}{R_{\mathrm g}}
\left(\frac{1}{T_{\mathrm{ref}}}-\frac{1}{T}\right)
\right].
\tag{5}
\]

其中参考温度 \(T_{\mathrm{ref}}\) 和扩散活化能 \(E_{D,k}\) 为固定物性设定，必须具有注明来源的值；合成实验中的测试设定不得冒充实测材料常数。采用该律时，\(T=T_{\mathrm{ref}}\) 必须恢复 \(D_{s,k}^{\mathrm{ref}}\)。未经核实的 Chen2020 固相扩散常数和 OCP 熵变项不应被悄然改成温度依赖或非零值。

**双向耦合要求**：DFN 计算热源，热方程更新电芯温度，温度再进入已定义的电化学物性与动力学关系。每一个工况进行同一次耦合模型求解，同时返回 \(\widehat U_r(t;\boldsymbol\theta)\)、\(\widehat T_r(t;\boldsymbol\theta)\)、热源及终止信息。首版温度输出为体平均电芯温度（Volume-averaged cell temperature [K]），而非默认与环境相等的 Surface temperature [K] 变量。若实测为表面探头温度，需独立说明体平均近似的适用条件。

### C. Voltage–Temperature Multiobjective Identification

分别定义电压和电芯温度的固定网格均方根误差：

\[
E_{U,r}(\boldsymbol\theta)=
\sqrt{\frac{1}{N_{U,r}}
\sum_{i=1}^{N_{U,r}}
\left[
\widehat U_r(t_i^U;\boldsymbol\theta)
-U_r^{\mathrm{obs}}(t_i^U)
\right]^2},
\tag{6}
\]

\[
E_{T,r}(\boldsymbol\theta)=
\sqrt{\frac{1}{N_{T,r}}
\sum_{j=1}^{N_{T,r}}
\left[
\widehat T_r(t_j^T;\boldsymbol\theta)
-T_r^{\mathrm{obs}}(t_j^T)
\right]^2}.
\tag{7}
\]

对预先冻结的有效倍率集合分别等权汇总两类误差，形成两个最小化目标：

\[
\boxed{
\min_{\boldsymbol\theta\in\Theta}
\boldsymbol F(\boldsymbol\theta)
=
\begin{bmatrix}
F_U(\boldsymbol\theta)\\
F_T(\boldsymbol\theta)
\end{bmatrix},
\quad
F_U(\boldsymbol\theta)=\frac{1}{|\mathcal R_{\mathrm{fit}}|}
\sum_{r\in\mathcal R_{\mathrm{fit}}}E_{U,r}(\boldsymbol\theta),
\quad
F_T(\boldsymbol\theta)=\frac{1}{|\mathcal R_{\mathrm{fit}}|}
\sum_{r\in\mathcal R_{\mathrm{fit}}}E_{T,r}(\boldsymbol\theta).
}
\tag{8}
\]

\(F_U\) 的单位为 V，\(F_T\) 的单位为 K。温度目标衡量**温度预测误差**，不将电池温度越低视为辨识越准确。实验输入包括已知电流、边界和初始状态；不能把整个实测电芯温度轨迹作为热模型的输入，再以它作为预测目标。

对任何参数候选，只有 \(\mathcal R_{\mathrm{fit}}\) 中全部工况的模型预测完整覆盖各自电压和温度时间网格，且两类残差均有限有效时，才保存真实完整目标对 \([F_U,F_T]\)。任一选中工况失败，完整目标对即缺失，不能缩小分母、补零、外推或采用人为惩罚伪造可训练目标。部分工况的有效曲线和失败诊断应完整保留；未选工况不读取为拟合观测、不参与完整性判定。倍率是工况，不增加优化目标个数。

### D. LLM-Informed Initialization

为提高有限计算预算下初始样本的质量与覆盖度，LLM 首先结合电化学、热物性与模型边界信息提出参数候选集合 \(\mathcal P_{\mathrm{LLM}}\)。确定性筛选检查参数上下界、正值与固相体积分数的物理可行性，然后对通过筛选的候选执行真实电热耦合仿真，以获得可核实的二维误差目标。模型反馈可在有界后续请求中使用，但 LLM 建议不能直接充当真实训练标签。

对完整候选进行 Pareto 非支配分层。取比较协议中事先固定的尺度 \(\boldsymbol s=[s_U,s_T]^\top>0\)，按对称权重 \((0.5,0.5)\) 定义初始化平衡质量：

\[
q(\boldsymbol\theta)
=
\max_{j\in\{U,T\}}
\left\{
\frac{0.5 F_j(\boldsymbol\theta)}{s_j}
\right\}
+
\rho_{\mathrm{aug}}
\sum_{j\in\{U,T\}}
\frac{0.5F_j(\boldsymbol\theta)}{s_j},
\qquad \rho_{\mathrm{aug}}=0.05.
\tag{9}
\]

初始样本选择采用显式版本化规则。已归档实验和缺省配置使用 `pareto_maximin_v1`：只在当前最优未耗尽的非支配层中选择；首点按最小 \(q\) 选取，此后优先最大化到已选参数集合的最小归一化距离，并用 \(q\)、规范化参数字典序及稳定评价 ID 决定同分顺序。可选的 `pareto_core_spacefill_v2` 先按同一规则保留第 0 非支配层；如尚有名额，从全部剩余完整且物理参数唯一的候选中选取距离当前集合最远的点，同分依次比较 \(q\)、Pareto 层号、归一化参数与评价 ID。距离以统一的线性或对数坐标映射后计算：

\[
d(\boldsymbol x,\mathcal S)
=
\min_{\boldsymbol z\in\mathcal S}
\sqrt{\frac{1}{6}\sum_{j=1}^{6}(x_j-z_j)^2}.
\]

同一物理参数的重复评价不能重复占用初始种子名额。最终选择 \(K\ge2\) 个完整初始观测构成 \(\mathcal D_0=\{(\boldsymbol\theta_i,\boldsymbol F_i)\}_{i=1}^{K}\)。如果在事先设置的候选与求解预算内不能获得足够初始观测，则停止并报告初始化不足，不用随机样本自动补齐，也不悄然增加预算。

当第 0 层点数不超过 \(K\) 时，v2 保留候选池的完整非支配集，因此其初始固定空间 HV 与完整池一致；超过 \(K\) 时只保留按既有首层次序选出的 \(K\) 点，须报告实际 HV。两个版本的规则、目标尺度与初始化计划签名分别归档。旧实验继续按 v1 解释；v2 的离线归档回放只检验选点几何与初始指标，不构成后续 BO 增益证明。

### E. ParEGO-Based Multiobjective Bayesian Optimization

在顺序搜索阶段，采用原 LLMBO-MO 的 ParEGO 式分解骨干。每轮 \(t\) 从可复现的二维单纯形权重集合中选择 \(\boldsymbol w_t=[w_{U,t},w_{T,t}]^\top\)，满足 \(w_{U,t},w_{T,t}\ge0\) 及 \(w_{U,t}+w_{T,t}=1\)。

本研究以误差非负下界 \(\boldsymbol z^\star=(0,0)^\top\) 作为固定理想点，使用预先冻结且与算法路线无关的目标尺度 \(\boldsymbol s\)，定义增广 Tchebycheff 标量化：

\[
\boxed{
g_t(\boldsymbol\theta\mid\boldsymbol w_t)
=
\max_{j\in\{U,T\}}
\left(
w_{j,t}\frac{|F_j(\boldsymbol\theta)-z_j^\star|}{s_j}
\right)
+
\rho_{\mathrm{aug}}
\sum_{j\in\{U,T\}}
w_{j,t}\frac{|F_j(\boldsymbol\theta)-z_j^\star|}{s_j}.
}
\tag{10}
\]

当前权重下，把所有**本轮选点前已经获得的完整二维历史记录**重新标量化为 \(g_{i,t}\)，并按其均值与总体标准差线性标准化：

\[
z_{i,t}=\frac{g_{i,t}-\overline g_t}{s_{g,t}},
\quad
s_{g,t}=
\begin{cases}
\operatorname{std}(g_{i,t};\mathrm{ddof}=0),&
\operatorname{std}(g_{i,t})\ge 10^{-12},\\
1,&\operatorname{std}(g_{i,t})<10^{-12}.
\end{cases}
\]

上式最后一项表示：当标准差小于事先定义的近零阈值时，**用 1 代替该标准差**，并记录该回退；正常情况下直接使用观测总体标准差，不将其无条件截断为 1。

以经参数变换得到的归一化坐标 \(\boldsymbol x=\mathcal N(\boldsymbol\theta)\in[0,1]^6\) 为输入，拟合六维 ARD Matérn-5/2 GP：

\[
f_t(\boldsymbol x)
\sim
\mathcal{GP}\!\left(
m_t(\boldsymbol x),
k_{\mathrm{M52},t}(\boldsymbol x,\boldsymbol x')
\right).
\tag{11}
\]

设本轮最佳已观测标量目标在标准化空间中的值为 \(z_t^{\mathrm{best}}\)，GP 后验均值和标准差为 \(\mu_t(\boldsymbol x)\)、\(\sigma_t(\boldsymbol x)\)。对最小化问题，Expected Improvement 为：

\[
\operatorname{EI}_t(\boldsymbol x)
=
(z_t^{\mathrm{best}}-\mu_t(\boldsymbol x))\Phi(\gamma_t)
+\sigma_t(\boldsymbol x)\phi(\gamma_t),
\quad
\gamma_t=\frac{z_t^{\mathrm{best}}-\mu_t(\boldsymbol x)}
{\sigma_t(\boldsymbol x)}.
\tag{12}
\]

其中 \(\Phi\)、\(\phi\) 为标准正态分布函数和概率密度。当 \(\sigma_t\to0\) 时，EI 取 \(\max(z_t^{\mathrm{best}}-\mu_t,0)\)。本目标采用线性标准化，不将旧电压单目标任务特有的对数 RMSE EI 直接复用。

**冻结上下文规则**：本轮先确定权重、标量化标签、标准化统计、incumbent、GP 状态和 EI 阈值，随后进行候选搜索与真实反馈；任何新观测都不追溯改写本轮上下文。下一轮无论上一轮成功或失败，都按新权重重算历史标签、标准化、incumbent、局部搜索中心和 GP；不同权重下的标量数值不可直接比较。

### F. Weight-Conditioned LLM Region-Lift

2026-10-22用户确认新的电热研究策略采用下述F.2的`lgbo_v1`。F.1保留已有相关性启发式及其历史公式，缺少新策略字段的旧配置按原语义执行；两者不混用控制项或LLM回复。

#### F.1 Historical Correlation Policy

除 WarmStart 外，LLM 在迭代搜索时根据当前目标偏好给出候选的优选区域。输入包括 \(\boldsymbol w_t\)、尺度、理想点、当前真实二维观测的摘要与 Pareto 信息；输出为归一化参数空间中的一个有界区域 \(\mathcal B_t\subseteq[0,1]^6\)，或明确弃权。

在区域内生成 \(M\) 个锚点 \(A_t=\{\boldsymbol a_1,\ldots,\boldsymbol a_M\}\)。结合锚点的 EI、GP 不确定性和新颖性，得到非负、和为一的锚点权重 \(\boldsymbol\beta_t\)。以当前真实数据条件下、同一标量化 GP 的后验协方差定义候选与区域响应的相关程度：

\[
\rho_t(\boldsymbol x;A_t)
=
\frac{
\operatorname{Cov}_t\!\left[
f_t(\boldsymbol x),
\sum_{m=1}^{M}\beta_{m,t}f_t(\boldsymbol a_m)
\right]
}{
\sigma_t(\boldsymbol x)
\sqrt{
\boldsymbol\beta_t^\top K_t(A_t,A_t)\boldsymbol\beta_t
}
}.
\tag{13}
\]

LLM 区域只在采集阶段引起有界均值调整：

\[
\widetilde\mu_t(\boldsymbol x)
=
\mu_t(\boldsymbol x)-\Delta_t(\boldsymbol x),
\qquad
\widetilde\sigma_t(\boldsymbol x)=\sigma_t(\boldsymbol x),
\tag{14}
\]

\[
\Delta_t(\boldsymbol x)
=
\operatorname{clip}\!\left[
\lambda_{\max}a(t)c_t\tau_t\eta_t
\max\{\rho_t(\boldsymbol x;A_t),0\},
0,\Delta_{\max}
\right].
\tag{15}
\]

这里 \(a(t)\) 是随迭代衰减的激活系数，\(c_t\) 为 LLM 自报置信度，\(\tau_t\) 为历史反馈驱动的信任值，\(\eta_t\) 是锚点一致性因子；\(\lambda_{\max}\)、\(\Delta_{\max}\) 限定调整强度。将 \(\widetilde\mu_t\) 与不变的 \(\sigma_t\) 代入式（12）计算 Region-Lift EI。区域校验、plain EI 损失与后验不确定性等准入规则失败时，**直接回退本轮普通 EI**。

只有当 Region-Lift 确实改变选点且触发真实新评价时，才根据本轮冻结目标反馈更新信任值：

\[
\tau_{t+1}
=
(1-\beta)\tau_t+\beta\,
\mathbb I
\left[
g_t(\boldsymbol\theta_{t+1})
<
g_t(\boldsymbol\theta_t^{\mathrm{best}})
\right].
\tag{16}
\]

完整目标对缺失时，此次已采用的新增评价算作未改善，但不伪造 \(g_t\)；若 LLM 弃权、调整未实际采用或仅复用旧缓存，则信任保持不变。**LLM 只改变采集阶段候选排序，不修改真实二维目标、GP 训练标签或原始后验方差**。这一过程属于受约束的启发式引导，不是将语言建议转化为新的概率观测。

#### F.2 LGBO Regional Mean Tilt

参考[LGBO论文§3.2](https://arxiv.org/html/2605.17976v1#S3.SS2)，LLM直接给出归一化矩形及置信度 \(c_t\in[0,1]\)，或弃权，不要求解释、区域目录ID或证据ID。输入保留当前权重、尺度、理想点、Pareto及真实历史和动态残差摘要。区域内固定种子生成32个Sobol锚点，按已有物理参数域筛除非法点，对剩余 \(M\) 个点使用均匀权重 \(a_i=1/M\)。

在当轮标准化标量GP空间，令 \(v_t=a^\top K_t(A_t,A_t)a\)。最小化偏好的指数倾斜为

\[
\widetilde p(f_t\mid D_t)\propto
p(f_t\mid D_t)\exp[-\lambda_t a^\top f_t(A_t)],
\quad
\lambda_t=\frac{c_t}{\sqrt{v_t}},
\quad
\widetilde\mu_t(x)=\mu_t(x)-\lambda_t K_t(x,A_t)a,
\quad
\widetilde K_t=K_t.
\tag{17}
\]

这里采用论文直接置信度映射及最大化到最小化的符号适配，不混用作者代码的分位数映射/guidance_scale。保留协方差符号，负相关位置可均值上移；其自然不确定性界为

\[
|\mu_t(x)-\widetilde\mu_t(x)|\le c_t\,\sigma_t(x).
\tag{18}
\]

将倾斜均值及原标准差代入式（12），在整个原可行候选池选择最大EI。没有目录、eligible筛选、公平竞争门槛、trust/退火/consistency乘子或区域内选点限制。置信度小于0.6仍可产生较弱引导，第12轮后也不自动停用。候选仍可自然与Plain相同。

仅保留JSON/请求身份/参数边界/物理域/预算和数值校验；无可行锚点、\(v_t\le10^{-12}\)、非有限后验、错误回复或弃权时回退Plain，\(c_t=0\)精确回到Plain。真实Y、训练标签、原GP及原后验方差不被改写，下一轮倾斜不累计。前述冻结上下文和失败轮换权重规则仍适用。

这一策略是LGBO核心机制的电热多目标适配，沿用本项目Gaussian EI。LGBO论文§3.4的固定方向GP-UCB分析不等于动态ParEGO/EI的性能保证；真实API合法率、非零倾斜、选点变化及真实RMSE/HV增益须分别报告。

Prompt版本由单一的 `optimization.region_method` 选择：`lgbo_v1` 保留原提示词，`lgbo_v2` 共享完全相同的均值倾斜、协方差、Gaussian EI和候选规则，只增强已有历史行的目标解释。对当前冻结上下文，v2明确提供

\[
q_{i,j}=w_{t,j}\left(F_{i,j}/s_j-z_j\right),\qquad
g_t(\theta_i)=\max_j q_{i,j}+\rho_{\mathrm{aug}}\sum_jq_{i,j}.
\]

解释字段记录两个加权分量、最大分量、全部精确同分的主导目标与未舍入的增广值。它帮助LLM结合已有top解、目标极值、近期记录及动态残差识别当前瓶颈；不把相关性视作单参数因果关系。对缺少证据的维度，提示词允许宽边界或弃权，不要求每一维都缩窄。回复仍只有 `request_id` 和 `region`，不要求解释文字。

这不是新的GP目标或数值方法。真实目标、训练标签、incumbent及原方差不被解释字段改写；独立审计从已核验曲线对应的历史目标和冻结的权重、尺度、理想点重算字段。完整请求绑定同时覆盖版本、解释和Prompt，旧回复不能跨版本重放。新增源码/Prompt改变全源码指纹，阶段间初始化须按实际源码重新建立；不重签旧计划。同一实际源码下，v1/v2可以共享满足原严格兼容规则的初始化。固定mock的同动作数值等价测试不能证明新Prompt有实际增益。

### G. Pareto Updating and Overall Procedure

电热模型每次评价后，只有同一拟合倍率集合下、签名和目标有效性均通过检查的完整 \([F_U,F_T]\) 观测，才加入用于下一轮模型拟合的历史数据。同一参数输入的重复评价保留记录和成本，但不重复加入GP训练集；不同参数即使目标相同，仍是不同训练样本。二维非支配筛选维护Pareto参数集，并保留选中各倍率的原始电压曲线、温度曲线、误差、终止状态和求解成本。

为比较不同方法的多目标辨识效率，在事先固定的指标空间

\[
\boldsymbol F^{\mathrm{HV}}
=
\left[
\frac{F_U}{s_U},\frac{F_T}{s_T}
\right]^\top
\]

内使用统一参考点 \(\boldsymbol r_{\mathrm{HV}}\) 计算二维Hypervolume（HV）。同一比较协议下的对照路线与随机种子须保持同一拟合倍率集合、数据、目标尺度、评价窗口和参考点；HV不跟随当前最优值动态改变。三倍率和未来四倍率不因尺度/参考点相同就成为同一指标协议。正式指标参考点未确认时，保留Pareto集，但不虚报HV数值。

**Algorithm 1. Electrochemical–Thermal Parameter Identification with LLMBO-MO**

    Input: Configured fitting-rate set R_fit and dataset/protocol identities;
           current/ambient-temperature trajectories, initial states, voltage and cell-temperature observations;
           coupled DFN–lumped-thermal model; parameter domain Θ;
           fixed objective scales s; reproducible weight schedule {w_t}; budgets.
    1: Obtain LLM-proposed electrochemical–thermal parameter candidates.
    2: Apply physical feasibility checks; evaluate retained candidates using true coupled simulation.
    3: Select K completed samples by Pareto rank and normalized Max–Min diversity.
    4: Initialize complete-objective history D_0 and Pareto set P_0.
    5: For each BO round t within evaluation budget:
    6:     Choose w_t, recompute scalarized labels g_t using only past complete pairs.
    7:     Standardize labels, fit one GP, and freeze current context C_t.
    8:     Generate parameter candidates; compute plain Gaussian EI in context C_t.
    9:     Query a direct region/confidence; form the LGBO mean tilt in context C_t.
    10:    Maximize tilted Gaussian EI over the full feasible pool; use plain EI on invalid/none guidance.
    11:    For each r in R_fit, evaluate selected parameters with one coupled DFN–thermal solve.
    12:    Compute valid F_U and F_T; preserve partial failures and actual costs.
    13:    Update the Pareto set, preserve frozen-context feedback, then advance context.
    14: Return the non-dominated parameter set, per-rate errors and trajectories,
        fixed-space HV (when configured), and simulation/API cost ledger.

## 研究实施边界（不属于论文 Method 正文）

1. **研究定位**：本文件描述现有 LLMBO-MO 用于电热耦合参数辨识的应用路线，并非提出新的多目标优化算法。ParEGO、WarmStart 和 Region-Lift 的方法归属在正式论文中应按原论文引用。
2. **模型范围**：原型是4个电化学参数＋2个热参数、配置驱动倍率集合、共同冷却边界的DFN–集总热模型。当前拟用0.5C/1C/2C，可靠3C以后通过新配置加入；不改变六参数、两个误差目标或优化骨干。参数范围、固定电导率、热几何、温度物性/活化能和观测映射仍须核实。
3. **当前数据限制**：用户已确认旧3C数据有问题，当前新版电热实测拟合禁用该数据；原数据和旧四倍率任务保留。0.5C/1C/2C实际电流、T列单位/测点、初态及共享冷却条件仍须科研组确认，不能把缺失数据自动解释为模型失效。
4. **实验层级**：将软件与解析测试、真实 DFN 合成数据测试和实测辨识分开，不从某一层的成功推论另外一层已验证，更不能将本文 Method 描述当作已得到实测结果。
5. **公平比较**：数值ParEGO、WarmStart-only、完整LLMBO-MO在同一倍率/数据协议中使用统一物理参数域、尺度、权重、评价口径和成本台账；WarmStart-only与Full的Region-Lift消融使用同一经核验有效初始化计划及其指纹，完整归属所有筛选成本。后续加入可靠3C另建配置、签名及实验归档，不覆盖当前三倍率协议。
6. **代码实现状态**：这是论文 Method 文本，不代表开发工作树已完成相应接口；正式提交时应再次与生效源码、固定物性和实验日志逐项核对。
7. **2026-11-01 对照设计**：下一轮固定 `pareto_quality_gated_spacefill_v3`；BO、BO+WarmStart、BO+Region、Full 构成配对2×2消融，优先比较0–10轮HV面积和同一代表性Pareto点的电压/温度RMSE。数值与LLM初始化各实评16点，统一v3筛选为8个GP点，全部实评成本及可用解进入外部评价档案。外部对照包括Sobol、ParEGO、NSGA-II、MOEA/D、qLogNEHVI和多目标JES，具体控制、训练样本区别、资源估算与未实现项见[实验规格](superpowers/specs/2026-11-01-ablation-and-benchmark-design.md)。该设计不是新的效果结果，也不修改旧协议归档。
