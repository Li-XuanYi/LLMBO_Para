# 21700 实测数据与 Reference 对齐审计

用户最新要求将实测 XLSX 的电芯规格从 18650 更正为 21700，并指定沿用 Reference 的 DFN 仿真设计。原始 XLSX、Reference、旧元数据和历史运行均保留。当前完成环境与接口准备；扩散系数含义和孔隙率约束仍待用户确认，真实辨识尚未启动。

唯一工作目录为 `D:\Users\aa133\Desktop\LLMBO_Para`，机器为 SCP。此次 [归档目录](../../runs/measured-identification/20261011T021237Z_5c536026feeb_6f940f7b/) 保存图片、要求、参考设计、环境、依赖、命令与检查记录。XLSX 的 SHA-256 为 `6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7`，规格更正另存于 `data/metadata/` 下的新记录。

图片范围按内部 Method 顺序整理如下；图片的正极体积分数在前，不能按图片行号直接传数组。

| 内部顺序 | 决策变量 | 图片范围 | 映射状态 |
|---|---|---|---|
| 1 | 负极活性材料体积分数 | [0.2, 0.8] | 明确 |
| 2 | 正极活性材料体积分数 | [0.2, 0.8] | 明确 |
| 3 | 负极扩散系数 | [1e-16, 1e-12] | 图片 D_e,n 与 Reference 的颗粒固相扩散系数映射待确认 |
| 4 | 正极扩散系数 | [1e-16, 1e-12] | 图片 D_e,p 与 Reference 的颗粒固相扩散系数映射待确认 |
| 5 | 负极固相电导率 | [100, 300] S/m | 明确 |
| 6 | 正极固相电导率 | [0.2, 0.8] S/m | 明确；覆盖 Reference 较旧的上界 |

建议扩散项采用 Reference 实际修改的 `Negative particle diffusivity [m2.s-1]` 和 `Positive particle diffusivity [m2.s-1]`，并用 log10 坐标搜索；其余四项用线性坐标。尚未激活待确认的映射。

Chen2020 的固定负极/正极孔隙率为 0.25/0.335。沿用这些值时，活性体积分数与孔隙率之和不能超过 1，可行上限分别为 0.75/0.665。建议保留图片名义范围，通过已有物理约束过滤越界候选；用户尚未确认。Reference 示例正极体积分数 0.7269410915620462 在该约束下不可行，不能直接作为有效候选。

Reference 源码单元已提取为脱敏证据，未执行 Notebook、未读取其执行输出。它使用标准 DFN、Chen2020、1C 放电到 2.5 V，详细示例设置 1 s 输出。当前主流程继续分别评价四个倍率。参数集容量为 5 Ah，对应 0.5C/1C/2C/3C 的模型电流为 2.5/5/10/15 A。这些电流依据用户选定的 Reference 推导，XLSX 的 I 列仍为空，不能标为实测电流。

沿用等温 298.15 K、2.5 V 截止及参数集初始浓度。Reference 直接 solve()，没有 initial_soc。因此新增 `initial_state_mode=parameterization`，要求各倍率 `initial_soc=null`，求解时省略 initial_soc，保留初始负极/正极浓度 29866/17038 mol/m³。新工厂每次返回 Chen2020 对象，候选仅覆盖六个决策变量；既有 explicit_soc 模式继续适用于明确给定 SOC 的配置。这些标量经本地安装检查，并可对照 [PyBaMM 25.10.2 Chen2020 源码](https://raw.githubusercontent.com/pybamm-team/PyBaMM/v25.10.2/src/pybamm/input/parameters/lithium_ion/Chen2020.py)。

Notebook 没有固定求解器或网格。已安装版本的默认求解器为 IDAKLUSolver，rtol=1e-4、atol=1e-6；现有框架提供 CasadiSolver safe 模式，工程提案为 rtol=atol=1e-6、dt_max=60 s，五个 DFN 网格维度各 20 点。物理设计与数值设置分别记录，尚未声称与旧 Notebook 数值结果完全一致。T 单位尚未确认，按 Reference 等温设计不将该列用作热模型输入。

评价保留 Method 的固定实测时间网格、无外推、四倍率 RMSE 均值。Reference 旧代码的外推、负 MSE 和失败罚值不进入当前流程。候选若提前到达截止电压，无法覆盖完整实测时间，应保存短曲线并诊断，不能伪造剩余电压或 RMSE。Reference 另有一个标题写 2C、实际读取与实验都为 1C 的单元，不能照抄标题。

专用环境为 `.venv-pybamm312\Scripts\python.exe`（Python 3.12.10），固定 PyBaMM 25.10.2、CasADi 3.6.7、NumPy 2.5.3、SciPy 1.18.1。40 个依赖的版本、SHA-256、安装报告、离线命令和 wheel 均已保存。实际下载索引是 Aliyun PyPI 镜像，记录实际 URL；未修改全局 Python。设置 `PYBAMM_DISABLE_TELEMETRY=true`，三种数值线程变量均为 1，保持单任务 CPU。资源观察时内存负载 84%、可用约 4.7 GiB，未提高并发。

第一次新增测试因测试辅助函数引用错误失败，原日志保留在 `runs/verification/20261011T022203Z_4ade7656/`。修复后，原 Python 的 38 项测试和五候选合成闭环深审计通过，记录在 `runs/verification/20261011T022513Z_3beda580/`。同一套验证在新 PyBaMM 环境再次通过，记录在 `runs/verification/20261011T022648Z_60ef756e/`：候选完成 5、失败 0、待运行 0，倍率评价完成 20，深审计通过。合成评价耗时 0.3511 s，约 854.49 候选/分钟，仅为软件检查速度。

本轮真实 DFN 求解 0 次、API 调用 0 次。确认两项科学设置后，先做一个候选的四倍率真实 smoke，检查截止事件、时间覆盖和电压轨迹，再运行小预算 LLMBO 闭环及结果复算。实测小规模验证前不扩大预算，不报告辨识结果或真实运行速度/ETA。

已有环境的软件验证命令如下；每次验证创建新归档：

```powershell
Set-Location 'D:\Users\aa133\Desktop\LLMBO_Para'
$env:PYBAMM_DISABLE_TELEMETRY = 'true'
.\scripts\verify.ps1 -PythonExe 'D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe'
```

离线重建使用此次归档的 `resolved-requirements.lock` 与 `wheels/`；完整绝对路径命令见 `environment-install-command.ps1`。需创建新环境，使用 pip install --no-index --find-links wheels --no-deps --require-hashes -r resolved-requirements.lock。新设置与新实验另建归档，不覆盖本轮记录。
