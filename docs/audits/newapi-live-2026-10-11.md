# 替代 API 与 LLM 闭环验收：2026-10-11

用户提供的替代 API 已完成真实调用和小规模闭环验收。请求模型名为 `deepseek-v4-flash`，服务端响应自报 `deepseek-v4.1-flash`。两次真实 LLM 请求均成功，两个初始建议均被接受；5 个合成候选完成 20 次四倍率评估，深度结果审计通过。最终回归 34 项测试全部通过。

这次使用真实 API 和人工构造的电池评价数据。没有执行真实 PyBaMM 电池求解，没有上传 `true_data.xlsx` 或其原始曲线，也没有补造科研组的电芯参数。这些结果证明接口和软件流程可执行，不能证明科研辨识精度或 LLM 带来的收益。

## 最新要求、环境与范围

本次按用户“尝试这个，model 可选用 dsv4flash”继续既有框架，先探测模型和最小生成，再执行小规模验收。沿用既有两项 LLM 任务、参数空间、四 GP、EI 和运行归档；未初始化 CodeGraph。每次变更都创建新运行目录，旧 OpenCode 失败记录和替代 API 首次失败记录均保留。

| 项目 | 实际设置 |
|---|---|
| 机器 / 系统 | SCP / Windows 11 build 26200 |
| 工作目录 | `D:\Users\aa133\Desktop\LLMBO_Para` |
| Python | `C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe`，3.12.10 |
| 依赖 | NumPy 2.5.3，openpyxl 3.1.5；当前解释器未装 PyBaMM / CasADi / torch |
| 算力与并发 | CPU 单任务；OpenBLAS / MKL / OMP 线程均为 1；未提升并发 |
| 接口 | `https://napi.kid1412.qzz.io/v1/chat/completions` |
| 认证 | `LLMBO_NEWAPI_API_KEY` 进程变量或隐藏输入；密钥不写入文件或命令参数 |
| 输出 | 项目内 `runs/api-probes/`、`runs/live-api-sessions/`、`runs/verification/` |
| 验收配置 | [newapi-synthetic-smoke.json](../../configs/newapi-synthetic-smoke.json) |

小规模配置为 2 个 LLM 初始建议 + 2 个 Sobol 点 + 1 次 BO，总预算 5；每个候选评价 0.5C、1C、2C、3C。候选池 64，EI 抽样 64，GP 超参数搜索 2 轮，API 超时 60 秒，每次最多输出 2048 tokens，启用 JSON 对象模式。本配置仅供软件验收，不替代 Method 中正式实验的初始样本和总预算。

## 接口测试和故障修复

以下路径均相对项目根目录，每个目录保留配置、环境、命令、源码快照、请求、脱敏响应和终止状态。

| 次序 | 操作及结果 | 证据目录 |
|---|---|---|
| 1 | `dsv4flash` 返回 HTTP 503 / `model_not_found`，服务说明所处分组无可用通道 | `runs/api-probes/20261011T010646Z_801b06347739_bcb9e312` |
| 2 | 认证后读取模型目录，HTTP 200，返回 31 个模型，包含 `deepseek-v4-flash` | `runs/api-probes/20261011T010838Z_d614e8cc4d81_4b88a955` |
| 3 | 用完整模型名生成最小 JSON，HTTP 200，返回 `{"ok":true}`；32 tokens，约 2.66 秒 | `runs/api-probes/20261011T010925Z_47fff0f49998_9eb10b01` |
| 4 | 首次闭环两次 HTTP 403，正文 `error code: 1010`；虽有 Sobol 回退完成合成优化，LLM 验收明确失败 | `runs/live-api-sessions/20261011T011456Z_fa69c184fd36_ce42472f` |
| 5 | 修复应用标识后重新创建完整闭环，两次 HTTP 200，验收成功 | `runs/live-api-sessions/20261011T011719Z_fa69c184fd36_a07811ce` |

模型简称不是该接口的有效调用名。后续配置保存实际请求名，同时保存响应的模型标签，不能把服务端自报的标签当作已独立验证的底层模型身份。

最小探测使用了本应用的 User-Agent，首次集成客户端仍使用 Python 默认标识。修复为与成功探测相同的真实应用标识 `LLMBO-Para-connectivity-probe/1`，未冒充浏览器或其他客户端。失败与成功归档的 Warm Start 请求体完全一致，源码差异及 SHA256 见成功会话中的 `header-correction.diff` 和 `repair-lineage.json`。错误 1010 的含义可参照 [Cloudflare 官方诊断](https://developers.cloudflare.com/support/troubleshooting/http-status-codes/cloudflare-1xxx-errors/error-1010/)；本次判断同时依据保存的响应和修复前后实际结果。

没有关闭 TLS、跟随认证重定向、自动循环重试或提高并发。首次集成失败的两个任务在新会话中均重新执行成功，原失败会话不被改写成成功。此次替代接口共发出 7 次 HTTP 请求：1 次模型目录、1 次无效模型、1 次最小生成、2 次首次集成、2 次成功集成；4 次成功、3 次失败。历史 OpenCode 测试另见 [旧报告](api-connectivity-2026-10-11.md)。

## 实现方式

复用既有 HTTP 传输并增加 Chat Completions 适配：把任务说明放入 system 消息，其余结构化任务内容放入 user 消息；显式提交模型、输出上限、JSON 模式和非流式设置。只接收正常结束的 JSON 对象，截断、拒绝、非 JSON 和格式错误保留诊断。HTTP 诊断和响应在落盘前脱敏，认证头不进入请求归档。

优化器仍只让 LLM 执行两个任务：提出初始六维参数、按倍率提出参数组。实际电压评价、GP 拟合、EI 选择和目标计算由本地程序完成。新验收入口在优化完成后额外检查真实 HTTP 响应数量、内容解码一致性、两个建议的接受数量、四倍率参数组、错误和独立结果审计，防止把 Sobol 回退误认为 LLM 成功。

涉及源码：`src/llmbo_para/llm.py`、`workflow.py`、`config.py`；复用探测器 `scripts/probe_opencode.py`，增加 `scripts/run_live_synthetic.py` 和 6 项协议/集成回归测试 `tests/test_chat_transport.py`。

## 成功会话的实际结果

成功父目录：`runs/live-api-sessions/20261011T011719Z_fa69c184fd36_a07811ce`。

优化子目录：`optimization/20261011T011738Z_135c48a6463d_c8fab9ad`。

| 验收项 | 结果 |
|---|---|
| 真实 LLM 调用 | 2 / 2 成功，两次 HTTP 200 |
| 初始候选来源 | LLM、LLM、Sobol、Sobol；两个建议均接受 |
| 候选总数 / 成功 / 错误 / 运行 / 待运行 | 5 / 5 / 0 / 0 / 0 |
| 倍率求解 | 20 / 20 完成，每倍率 5 次；错误 0 |
| 优化计时 | 约 5.94 秒，约 50.51 个合成候选 / 分钟 |
| 包括归档和审计 | 约 6.42 秒；当前剩余预计时间 0 |
| 结果深度审计 | 5 条候选记录、2 个模型快照、1 次 EI 决策，问题 0 |
| 原始实验曲线外发 / 真实电池求解 | 0 / 0 |

速度只适用于这次人工评价器，不能用于估算真实 DFN 求解或大规模实验。

| LLM 任务 | 输入 tokens | 输出 tokens | 合计 |
|---|---:|---:|---:|
| Warm Start | 759 | 78 | 837 |
| 四倍率参数组 | 2619 | 215 | 2834 |
| 闭环合计 | 3378 | 293 | 3671 |

加上最小生成 32 tokens，成功生成的服务端报告总量为 3703 tokens。保留完整 usage；响应中的 `credit: 0` 不作为账单费用为零的证明。

### 参数组和零权重核对

0.5C 返回空组，按设计使用全维核。1C、2C、3C 都返回扩散系数和电导率四个参数，对应索引 `[2,3,4,5]`；归档模型均显示 `has_group=true`。最终三个倍率的参数组核权重为 0，未直接解释为随机性或模型差异。

读取保存的五点训练集、超参数和组索引，独立重建 GP；保存的似然值均在 `1e-10` 内复现。固定其他超参数，检查权重 0、0.2、0.4、0.8，三个倍率均以 0 的似然值最高。例如 1C 依次为 -7.63027、-7.69474、-7.76947、-7.99900。证据为成功父目录的 `kernel-weight-diagnostic.json`。这支持此次局部搜索选择零权重的实际行为，不能证明全局最优或正式实验中参数组无用。

## 回归、隐私和复现证据

最终验证目录：`runs/verification/20261011T011906Z_e4308d17`。

- `tests.txt`：34 项测试全部通过，耗时 11.100 秒。
- `expected-incomplete-config.txt`：真实研究模板仍因缺少输入返回预期退出码 2，未擅自填值。
- `demo.txt` / `deep-audit.txt`：离线 5 候选合成流程和独立深度复算通过。
- `command-and-environment.txt`、`transcript.txt`、`verification-summary.json`：命令、解释器、线程、日志、路径和全部退出码。
- 成功会话 `privacy-source-check.json`：扫描 422 个本轮源码/配置/归档文件，未发现密钥样式；实际两项线上请求未发现原始时间、电流、电压数组字段；当前 Python 源码与成功运行快照哈希一致。
- 成功会话 `finalize-evidence.py`、`finalize-command.txt`、`finalize-output.txt`：不访问网络的修复对照、GP 复算和扫描脚本及输出。

复现环境和有界验收命令：

```powershell
Set-Location -LiteralPath 'D:\Users\aa133\Desktop\LLMBO_Para'
$runPython = 'C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe'
$env:PYTHONPATH = Join-Path $PWD 'src'
$env:OPENBLAS_NUM_THREADS = '1'
$env:MKL_NUM_THREADS = '1'
$env:OMP_NUM_THREADS = '1'
& $runPython -X utf8 -B -m unittest discover -s tests -v
& $runPython -X utf8 -B scripts\run_live_synthetic.py configs\newapi-synthetic-smoke.json
```

第二条会重新进行两次真实调用并创建新目录；未预设密钥变量时，脚本要求隐藏输入。服务响应可能变化，因此历史复核优先使用归档的实际响应、候选、GP 状态、随机种子和 EI 候选池：

```powershell
& $runPython -X utf8 -B -m llmbo_para audit-run 'D:\Users\aa133\Desktop\LLMBO_Para\runs\live-api-sessions\20261011T011719Z_fa69c184fd36_a07811ce\optimization\20261011T011738Z_135c48a6463d_c8fab9ad' --deep --output runs/result-audits
```

后续真实电池辨识仍需明确时间轴、电流、各倍率实验条件和科研组参数化，再以单候选四倍率 smoke 验证 PyBaMM。GPU、Method 3.6 基线/消融、独立重复和 3C 留出实验尚未验收。本次未扩大实验规模。
