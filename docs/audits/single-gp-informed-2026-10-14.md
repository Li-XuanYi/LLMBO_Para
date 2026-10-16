# 单 GP 与 LLM-Informed 接入记录（2026-10-14）

## 已确认的范围

用户已确认：只使用一个 GP，拟合四倍率平均 RMSE，使用单一 Matérn-5/2 核。
`Multi_` 的来源和具体 LLM-Informed 分支仍待用户确认；本次暂未改写 LLM Prompt 或增加线上 LLM 调用。

## 已实现

- 配置增加 `optimization.surrogate_mode="single_objective"`；省略时继续执行历史 `per_rate` 路径。
- 联合目标仍为 `J=(RMSE_0.5C+RMSE_1C+RMSE_2C+RMSE_3C)/4`，单位 V；完整实测时间网格、禁止外推的规则不变。
- 先求四倍率 RMSE 的平均值，再对 `J+epsilon` 取对数并标准化；标准化参数在首次足够样本时冻结。**没有改为四个 log-RMSE 的平均值**。
- 只拟合一个 6 维 ARD Matérn-5/2 GP。配置必须关闭 `llm_gp_groups_enabled`，拒绝子集混合核及 `training_data="per_rate"` 的矛盾组合。
- 每个候选都需要完整四倍率结果才能形成联合目标标签。部分失败候选仍记录原始结果，但不编造联合目标或惩罚 RMSE。候选失败后，联合 GP 的训练集不变时复用模型。
- 使用对数正态后验的解析 EI，在 V 尺度计算改善量；无需四 GP 独立采样或蒙特卡洛抽样。数值实现包含接近零方差和非负 RMSE 截断。
- 原有局部候选、全局探索配额、可选完成概率模型继续可用。
- 模型、冻结变换、训练记录编号、原始 EI、约束后分数和选点均保存。深审计支持单 GP 重放，并检查训练标签是否来自真实联合目标。
- 为兼容原有存档读写，采集记录保留 `composite_ei` 数组字段；新模式同时明确标注 `acquisition_kind="analytic_lognormal_ei_v"`、`mc_draws=0`、`mc_seed=null`，不会将其解释为四 GP Composite EI。

这项修改简化了代理建模，尚不能推断拟合效果会改善，也没有修复此前所有提前截止问题。单 GP 模式不再直接吸收只有部分倍率有效的 RMSE 标签，这是用户确认的建模方式带来的取舍。

## 本地环境与小试

- 工作目录：`D:\Users\aa133\Desktop\LLMBO_Para`
- Python：`.venv-pybamm312\Scripts\python.exe`（Python 3.12）
- 命令环境：`PYTHONPATH` 指向工作目录下 `src`，OMP、OPENBLAS、MKL 线程均为 1。
- 独立小试配置：`configs/single-gp-synthetic-smoke.json`，4 初始 + 5 BO，GP 超参数搜索预算 20 轮。
- 本次小试属于**合成软件测试**，不是实测电池拟合，不调用 DFN 或外部 API。
- 已完成 9/9 候选、36/36 个合成倍率评价，失败 0，待运行 0；运行本体约 0.752 s，约 718 候选/分钟（不能外推为 DFN 实验速度）。
- 小试深审计通过，保存了 6 份单 GP 快照和 5 次解析 EI 决策。
- 小试目录：`runs/single-gp-smoke/20261014T000401Z_6d539be8eb31_4b2769ac`。
- 专项测试：`tests/test_single_objective.py`，4 项通过；包括独立数值积分核对 EI、部分失败后模型复用、矛盾配置拒绝、篡改标签或 EI 后审计失败。
- 完整回归测试：91 项通过，129.69 s；日志见 `bo-repair-work/20261014_single-gp-informed/full-tests-01.log`。

PowerShell 复现命令（从项目根目录执行）：

```powershell
$env:PYTHONPATH=(Resolve-Path src).Path
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:MKL_NUM_THREADS='1'
$env:PYBAMM_DISABLE_TELEMETRY='true'
.\.venv-pybamm312\Scripts\python.exe -m llmbo_para run configs/single-gp-synthetic-smoke.json --output runs/single-gp-smoke
```

每次运行自动创建带时间、配置哈希和唯一标识的新目录，不覆盖旧结果。

## LLM-Informed 来源审查：尚未实施的部分

> 后续状态（2026-10-14）：用户随后确认了区域建议与有界均值调整方案，现已完成实现与真实接口小试。见 [完成报告](llm-informed-implementation-2026-10-14.md)。本节保留当时的来源审查记录。

找到候选来源：`D:\Users\aa133\Desktop\BO_Multi_12_20\New_LLMBO`。

关键文件：

- `llmbo/gp_model.py`：单输出 Matérn GP、后验协方差、选点时的预测均值调整。
- `llmbo/region_lifted_gp.py`：区域建议解析、锚点、相关性调整以及 `lgbo_proposition1` 等多个模式。
- `llm/region_prompt.py`：按历史观测和物理背景构建区域建议请求。
- `AI_Assist/Codex总结文档.md`：主线和 Region-Lifted GP 支线说明。

该目录同时含旧复合物理核设计、启发式相关性调整、LGBO 公式分支等，不能仅凭“LLM_Informed”自动选定所有实现细节。已向用户提出来源与方法确认，尚未收到该项回复。

若确认采用区域建议与有界均值调整，迁移时必须处理：

1. 原始对象是 5 维充电协议；本项目是 6 维电芯参数。参数名称、单位、边界、孔隙约束必须来自现有 `ParameterSpace`。
2. 原 `region_prompt.py` 中通用 `round(value, 6)` 会把约 `1e-13` 的扩散系数变成 0。应采用归一化坐标或无损科学计数法，不能原样迁移。
3. 原代码包含对缺失字段填入固定充电默认值的兼容逻辑，不能用其补造本项目的辨识参数。
4. 原设计含 5 维区域体积阈值。直接沿用到 6 维，可能误拒绝合理窄区域；应按维度和归一化宽度明确定义。
5. 充电时间、温升、老化、HV 以及动态多目标标量化不属于本项目当前目标；反馈应以联合 RMSE、各倍率误差及失败摘要构建。
6. LLM 区域建议不是实测标签。调整应明确记录为采集阶段启发式；保存原后验、调整量、使用原因和回退原因，不把调整后的均值当作 DFN 观测。
7. 需要分别验证关闭模块时与普通单 GP 完全一致、均值调整有界、方差不变、输入非法时可追踪回退，以及 API 请求与完整决策重放。

## 失败记录与保存位置

源码修改前备份、Git 状态和源文件 SHA-256、专项与回归日志、小试控制台输出均在：
`bo-repair-work/20261014_single-gp-informed/`。

测试过程遇到的临时目录权限、测试调用参数和 PYTHONPATH 设置问题已逐项记录在该目录 `NOTES.md`，失败日志保留；修改后专项测试和独立小试已补齐。
