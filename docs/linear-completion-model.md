# 四倍率完成概率：标准化线性逻辑模型

本配置只更换 `EI × p_complete` 中的联合完成概率模型。仍使用四个倍率 RMSE GP，六参数、DFN 固定设置、完整实测时段、禁止外推、四倍率平均 RMSE 均不变。不增设概率硬阈值。

配置 `optimization.bo_repair.completion_model = "standardized_linear_cv"`。省略时为 `legacy_diagonal`，可重现历史固定 L2 的逐维二次逻辑模型。

输入仍先按参数空间映射到六维 `[0,1]`（扩散系数使用原 log10 变换）。新模型将每一列按**当前训练数据**均值和标准差再次标准化，计算带截距的线性逻辑概率。标签是实际完成全部四倍率的 0/1；操作性求解失败仍按旧定义计为未完成。成功曲线的末端是右删失时间，本实现不将它伪造为真正的截止时间。

L2 系数从 `[0.001,0.01,0.1,1,10,100]` 中选择。分层折数为 `min(4,成功数,失败数)`，固定划分种子 20261014，用验证折的未加权 log loss 最小化；精确并列选更强正则。每折的均值、标准差都只从该折训练行计算，不做类别重加权。截距正则为 `1e-6`；极小方差列尺度置 1。最终选定系数后在当前全部训练行上重拟合。

模型至少需要 8 个样本、两类各至少 2 个；样本不足、数值拟合失败或预测退化时保存明确原因并回退至原 EI。Newton 求解使用回溯线搜索并核查梯度，不增加 SciPy 运行依赖。模型快照保存所有折划分、折内标准化、系数、损失、逐点折外概率、最终梯度和系数；审计重新拟合并逐项比较，候选概率与加权分数可重放。

交叉验证用于选择正则，不能据此宣称概率已经校准。47 个初始筛选候选是适应性提出的，仅有 8 个成功，负/正极活性物质比例的相关系数约 0.938；训练分布外的预测仍需实际 DFN 验证。当前局部/全局候选策略及每五轮全局配额继续保留。

本地小试模板：`configs/21700-4gp-linear-completion.json`。该模板由控制器填入已验证八点初始化，不能直接拿占位初始化运行。

```powershell
.\.venv-pybamm312\Scripts\python.exe scripts/run_4gp_repair_pilot.py configs/21700-4gp-linear-completion.json --initial-plan runs/method-pilots/20261013T141910Z_298bf451e758_9fa0aac0/initialization/screening/20261013T141939Z_3d9958fa093e_0e73c856/initial-plan.json --bo-iterations 2 --prompt-for-key --proxy http://127.0.0.1:7897
```

工作目录 `D:\Users\aa133\Desktop\LLMBO_Para`，Windows / Python 3.12 虚拟环境 `.venv-pybamm312`，CPU 单 worker、BLAS 单线程。密钥通过隐藏输入读取，仅在进程内存中使用。每次输出到新的 `runs/4gp-repair-pilots/<run-id>`，控制台、资源、配置、源码、输入、历史筛选账本、API、轨迹、模型、指标与审计一并保存。
