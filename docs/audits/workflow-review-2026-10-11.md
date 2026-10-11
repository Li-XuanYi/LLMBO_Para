# 提示词、框架与完整流程复核：2026-10-11

两份提示词、LLM 层和主方法软件框架已实现。本轮重新执行真实 API 的完整小规模闭环，并修复参数组语义验收缺口。最终两次调用成功，两个初始建议接受，5 个合成候选完成 20 次倍率评价，深度复算通过；修复后 36 项回归全部通过。

实测数据已核验。用户确认采样间隔为 1 秒，但容量、电流、具体电芯参数和部分工况仍缺，真实电池辨识尚未运行。本报告不把合成评价器结果当作实测辨识结果。

## 五项请求的结论

| 请求 | 当前状态及具体实现 |
|---|---|
| Prompt 是否写好 | 两份均已写好并完成真实调用。Warm Start 输入参数顺序、单位、边界、物理约束和电芯上下文，输出六维参数；另一份输入初始评价的四倍率 RMSE 和标量残差摘要，输出倍率参数子集。科研效果尚需实测及对照实验。 |
| LLM 层是否完成 | 已实现两任务客户端、Chat Completions 适配、严格 JSON 解析、参数合法性与多样性筛选、参数组语义校验、错误归档和安全回退。凭证不落盘，原始曲线不外发，BO 循环不逐轮调用 LLM。 |
| 整体框架是否完成 | 主方法闭环和预检、记录、复算、失败补跑已实现。四个完整六维 GP，初始冻结的 log-RMSE 变换，全维/子集混合核及学习权重，MC Composite EI 最小化四倍率 RMSE 均值。真实 DFN 验收、基线/消融、独立重复、3C 留出和 GPU 尚未完成。 |
| 完整流程是否运行 | 本轮从预检、LLM 初始建议、四倍率评价、LLM 分组、GP 拟合、EI、下一候选、更新到独立审计全部执行；使用真实 API 和合成评价器。实测 DFN 输入预检未就绪。 |
| 实测数据是否接入 | 已读取全部四表，确认 13,043 个电压样本及原始副本哈希一致；补充的采样间隔另存元信息。未改写原表、补造电流或电芯参数。 |

提示词：`src/llmbo_para/prompts/warm_start.txt`、`parameter_groups.txt`。LLM 层：`src/llmbo_para/llm.py`。主流程：`workflow.py`、`optimizer.py`、`surrogate.py`、`acquisition.py`、`evaluation.py`。详见 [架构契约](../architecture.md)。

## 实测数据与最新确认

工作根目录为 `D:\Users\aa133\Desktop\LLMBO_Para`。本轮总归档：`runs/workflow-review/20261011T013203Z_323db0136de1_3e8759fe`，下文简称“审查目录”。

原文件 SHA256：`6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7`，与项目内原始副本相同。

| 倍率 | 电压样本 | 电压范围 / V | I 非空数 | T 范围，单位待确认 |
|---|---:|---|---:|---|
| 0.5C | 6781 | 2.4984–4.1266 | 0 | 24.4–28.3 |
| 1C | 3409 | 2.4981–4.0742 | 0 | 24.7–32.9 |
| 2C | 1714 | 2.4832–3.9713 | 0 | 23.6–44.5186784648123 |
| 3C | 1139 | 2.4975–3.8780 | 0 | 24.4–25.0 |

用户本轮确认每行间隔 1 秒；T“应该是温度”，含义暂定、单位未确认。18650 为尺寸规格，具体厂家/型号和容量未知；科研组参数集和六参数边界暂未提供。最新确认保存在审查目录 `user-data-clarification.json` 以及 `data/metadata/<上述SHA256>/20261011T013203Z_user-clarification.json`。

原研究模板的 49 条校验消息保存在 `measured-run-preflight.json`。这不代表需要用户回答 49 个问题：科研缺项主要是容量/电流、基础参数化、边界/孔隙率和初始/截止条件；解释器、网格、求解器和预算属于后续需要配置核验的工程设置。

1 秒采样已保存为确认元信息；正式模板的兼容模式未开启，因为现有兼容路径还会按容量和倍率构造恒定电流，容量、方向与恒流假设尚未齐全。没有依据尺寸或电压猜值。2C 与 3C 的 T 范围明显不同，后续需核对测温含义；当前不把未确认的 T 强行作为热模型输入。

## PyBaMM 是否存在

| 解释器 | 本机实际发现 |
|---|---|
| 项目 Python 3.12.10 | 未安装 PyBaMM、CasADi 或 SciPy；现有 NumPy 软件流程可运行 |
| 默认 `C:\Python314\python.exe` | 有 PyBaMM 发行包 `0.2.4.post3`，模块自报 `0.2.4`，可导入；加载 Chen2020 抛出 FileNotFoundError，不能作为当前兼容环境 |

本轮仅检查，没有安装或改变全局环境。解释器、包版本、模块位置、命令和错误保存在审查目录的 `environment-command.ps1`、`python-launcher-inventory.txt`、`pybamm-python312.json`、`pybamm-python314.json`。

官方确有内置参数库，例如 Chen2020 对应 LG M50，NCA_Kim2011 对应文献中的 graphite/NCA pouch cell。Ramadass2004 的说明指出它混合了不同来源的参数。这些库能用于独立求解器对照，但不能仅凭“18650”确定本电芯的参数。[PyBaMM 官方参数目录](https://docs.pybamm.org/en/pybamm-v26.9.0.0/source/api/parameters/parameter_sets.html)

## 审计发现与修复

- 一条归档命令因 PowerShell here-string 嵌套解析失败，检查尚未启动；改用独立命令文件后完成，见 `launch-error.json`。
- 首轮两次 API 请求均在本机沙箱内报 WinError 10013，无 HTTP 响应。使用自动审查批准的网络权限后补跑；未关闭 TLS、修改认证或提高并发，见 `network-retry-diagnosis.json`。
- 网络补跑的 LLM 为每个倍率返回全部六个参数，违反真子集要求。客户端将它们清空并使用全维核，但原验收未区分违规回退和明确弃权。新增回归在修复前出现 3 项错误，日志保留。
- 补强提示词，明确禁止全六组且允许证据不足时空组；任务体增加最大组大小与弃权规则。客户端保存各倍率接受/弃权/拒绝及原因；验收要求原始组响应语义合法。修复后 36 项测试通过，并在新会话补跑。

| 会话，均在审查目录的 live-api-sessions 下 | 解释 |
|---|---|
| `20261011T013521Z_fa69c184fd36_f712d622` | 两次本地网络拒绝，LLM 验收失败；合成优化使用回退 |
| `20261011T013639Z_fa69c184fd36_b98de165` | 两次 HTTP 成功，四组均为全六参数；旧入口判为通过，追加 `group-semantic-correction.json` 明确其不满足严格语义验收，原记录不覆盖 |
| `20261011T014046Z_fa69c184fd36_9c26e105` | 修复后两次成功，两个初始建议接受，四组明确为空；属于允许弃权，严格验收和深度审计通过 |

本轮共 6 次 API 尝试：2 次本地拒绝，4 次成功生成；没有相同设置的无条件循环重试。失败任务通过网络权限修正和提示词/验收修正后补跑。

## 最终闭环的实际结果

使用 [newapi-synthetic-smoke.json](../../configs/newapi-synthetic-smoke.json)：CPU 单任务，2 个 LLM 初始点、2 个 Sobol 点和 1 次 BO，共 5 候选；每候选四倍率评价。候选池 64，MC 抽样 64，GP 搜索 2 轮；每次请求最多输出 2048 tokens，超时 60 秒。

请求模型 `deepseek-v4-flash`，两次服务端均自报 `deepseek-v4.1-flash`，分别记录，不推断底层模型身份。最后会话 Warm Start 使用 823 tokens，分组使用 2759 tokens，合计 3582；`credit: 0` 不作为免费账单证明。

最后分组原始响应为四个空数组，验证原因均为 `explicit_empty_group`，不是非法输出被清空。因此四个 GP 使用全维核，权重为零；不宣称本次结构先验生效或带来算法收益。

最后优化子目录为审查目录下 `live-api-sessions/20261011T014046Z_fa69c184fd36_9c26e105/optimization/20261011T014102Z_135c48a6463d_216121e1`。

| 状态 | 结果 |
|---|---|
| 候选完成 / 成功 / 错误 / 运行 / 待运行 | 5 / 5 / 0 / 0 / 0 |
| 倍率评价完成 / 错误 | 20 / 0，每倍率 5 次 |
| 深度复算 | 5 条候选、2 个模型快照、1 次 EI 决策；问题 0 |
| 包括归档与审计耗时 | 约 8.21 秒 |
| 优化器记录速度 / 剩余预计时间 | 约 38.66 个合成候选/分钟 / 0 |
| 实测原始数据外发 / 真实电池求解 | 0 / 0 |

上述速度仅适用于人工评价器。实测辨识未启动，也没有可据以估算 DFN 耗时的实际求解速度。

## 回归与复现

修复后验证：`runs/verification/20261011T014007Z_9d5c94c7`，36 项测试 11.826 秒全部通过；研究模板预期退出码 2；离线五候选 demo、状态和独立 GP/EI 审计通过。命令、日志、解释器与退出码均保留。

机器 SCP，Windows 11 build 26200；解释器 `C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe`。OpenBLAS、MKL、OMP 均为单线程，未使用 GPU。密钥隐藏输入，不保存到源码、配置或命令。

审查目录保存开始时源码快照、提示词及哈希、数据/环境检查、用户补充、预检、回归失败与修复对照和三轮完整会话。最终会话保存修复后实际源码。`live-terminal-outputs.json` 保留三个进程的退出和输出。终期 `review-summary.json` 汇总当前源码、隐私检查和任务状态。原始数据及历史运行不覆盖。

重新执行会产生新的 API 调用和唯一目录，未设置密钥环境变量时使用隐藏输入；沙箱中需相同的已批准网络权限：

```powershell
Set-Location -LiteralPath 'D:\Users\aa133\Desktop\LLMBO_Para'
$runPython = 'C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe'
$env:PYTHONPATH = Join-Path $PWD 'src'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $runPython -X utf8 -B scripts\run_live_synthetic.py configs\newapi-synthetic-smoke.json
```

无网络的结果复核：

```powershell
& $runPython -X utf8 -B -m llmbo_para audit-run 'D:\Users\aa133\Desktop\LLMBO_Para\runs\workflow-review\20261011T013203Z_323db0136de1_3e8759fe\live-api-sessions\20261011T014046Z_fa69c184fd36_9c26e105\optimization\20261011T014102Z_135c48a6463d_216121e1' --deep --output runs/result-audits
```

真实辨识下一步需确定容量/电流、基础参数与工况，配置兼容 PyBaMM，再先运行单候选四倍率 smoke。任何库参数对照都应标明参考电芯，不能当作本电芯的真值。
