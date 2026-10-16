# Method — 基于 LLMBO-MO 的锂离子电池电热耦合多目标参数辨识

> **论文方法草稿（中文，2026-10-16）**
>
> 研究定位：将现有 LLMBO-MO 框架应用于电化学–热耦合参数辨识；本研究不声称提出新的 DFN、集总热方程、ParEGO 或高斯过程算法。本文件描述拟采用的方法，不代表电热辨识代码、实测拟合和多种子实验已经完成。
>
> 与项目设计的关系：以 **docs/superpowers/specs/2026-10-16-electrothermal-identification-design.md（R1）** 的物理与优化约定为依据；研究数据未确认事项以 **docs/audits/electrothermal-identification-scope-2026-10-16.md** 为准。此文是论文正文草稿，不是批准实施计划或实验结果。

## III. Method

### A. Problem Formulation

本文研究锂离子电池在多倍率恒流放电条件下的电化学–热耦合参数辨识。令倍率集合为 \(\mathcal R=\{0.5\mathrm C,1\mathrm C,2\mathrm C,3\mathrm C\}\)。每一工况 \(r\in\mathcal R\) 具有外部激励和实验边界条件，包括电流 \(I_r(t)\)、环境温度 \(T_{\mathrm{amb},r}(t)\) 及初始电化学与热状态；实验观测包含端电压 \(U_r^{\mathrm{obs}}(t_i^U)\) 和电芯温度 \(T_r^{\mathrm{obs}}(t_j^T)\)，允许两类观测使用不同时间网格。

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

四种倍率下两类误差分别等权汇总，形成两个最小化目标：

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
F_U(\boldsymbol\theta)=\frac{1}{|\mathcal R|}
\sum_{r\in\mathcal R}E_{U,r}(\boldsymbol\theta),
\quad
F_T(\boldsymbol\theta)=\frac{1}{|\mathcal R|}
\sum_{r\in\mathcal R}E_{T,r}(\boldsymbol\theta).
}
\tag{8}
\]

\(F_U\) 的单位为 V，\(F_T\) 的单位为 K。温度目标衡量**温度预测误差**，不将电池温度越低视为辨识越准确。实验输入包括已知电流、边界和初始状态；不能把整个实测电芯温度轨迹作为热模型的输入，再以它作为预测目标。

对任何参数候选，只有模型预测完整覆盖其应评价的电压和温度时间网格，且两类残差均有限有效时，才保存真实完整目标对 \([F_U,F_T]\)。无法覆盖的分量设为缺失，不补零、不外推、不采用人为惩罚伪造可训练目标。部分工况的有效曲线和失败诊断应完整保留。

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

初始样本选择使用 **Pareto-first Max–Min Diversity** 规则：只在当前最优未耗尽的非支配层中选择；首点按最小 \(q\) 选取，此后优先最大化到已选参数集合的最小归一化距离，并用 \(q\)、规范化参数字典序及稳定评价 ID 决定同分顺序。距离以统一的线性或对数坐标映射后计算：

\[
d(\boldsymbol x,\mathcal S)
=
\min_{\boldsymbol z\in\mathcal S}
\sqrt{\frac{1}{6}\sum_{j=1}^{6}(x_j-z_j)^2}.
\]

同一物理参数的重复评价不能重复占用初始种子名额。最终选择 \(K\ge2\) 个完整初始观测构成 \(\mathcal D_0=\{(\boldsymbol\theta_i,\boldsymbol F_i)\}_{i=1}^{K}\)。如果在事先设置的候选与求解预算内不能获得足够初始观测，则停止并报告初始化不足，不用随机样本自动补齐，也不悄然增加预算。

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

### G. Pareto Updating and Overall Procedure

电热模型每次评价后，只有签名和目标有效性均通过检查的完整 \([F_U,F_T]\) 观测，才加入用于下一轮模型拟合的历史数据。二维非支配筛选维护 Pareto 参数集，并保留各倍率的原始电压曲线、温度曲线、误差、终止状态和求解成本。

为比较不同方法的多目标辨识效率，在事先固定的指标空间

\[
\boldsymbol F^{\mathrm{HV}}
=
\left[
\frac{F_U}{s_U},\frac{F_T}{s_T}
\right]^\top
\]

内使用统一参考点 \(\boldsymbol r_{\mathrm{HV}}\) 计算二维 Hypervolume（HV）。不同对照路线与随机种子须保持同一目标尺度、评价窗口和参考点；HV 不跟随当前最优值动态改变。正式指标参考点未确认时，保留 Pareto 集，但不虚报 HV 数值。

**Algorithm 1. Electrochemical–Thermal Parameter Identification with LLMBO-MO**

    Input: Current/ambient-temperature trajectories, initial states, voltage and cell-temperature observations;
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
    9:     Query weight-conditioned LLM region and form bounded posterior Region-Lift.
    10:    Use lifted EI only when the acceptance checks pass; otherwise use plain EI.
    11:    Evaluate selected parameters at four rates with coupled DFN–thermal solves.
    12:    Compute valid F_U and F_T; preserve partial failures and actual costs.
    13:    Update the Pareto set and Region-Lift trust under frozen C_t, then advance context.
    14: Return the non-dominated parameter set, per-rate errors and trajectories,
        fixed-space HV (when configured), and simulation/API cost ledger.

## 研究实施边界（不属于论文 Method 正文）

1. **研究定位**：本文件描述现有 LLMBO-MO 用于电热耦合参数辨识的应用路线，并非提出新的多目标优化算法。ParEGO、WarmStart 和 Region-Lift 的方法归属在正式论文中应按原论文引用。
2. **模型范围**：原型是 4 个电化学参数＋2 个热参数、四倍率、共同冷却边界的 DFN–集总热模型。参数范围、固定电导率、热几何、温度物性/活化能和观测映射仍须核实。
3. **当前数据限制**：既有 XLSX 的电流列无可用实测电流；温度 T 列的单位、测点和 3C 冷却工况尚未获实验组确认。实测联合辨识暂不能假定这些输入已经可靠。
4. **实验层级**：将软件与解析测试、真实 DFN 合成数据测试和实测辨识分开，不从某一层的成功推论另外一层已验证，更不能将本文 Method 描述当作已得到实测结果。
5. **公平比较**：数值 ParEGO、WarmStart-only、完整 LLMBO-MO 使用统一物理参数域、尺度、权重、评价口径和成本台账；Region-Lift 消融须保持相同初始化，包含所有筛选评价成本。
6. **代码实现状态**：这是论文 Method 文本，不代表开发工作树已完成相应接口；正式提交时应再次与生效源码、固定物性和实验日志逐项核对。
