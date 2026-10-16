# 当前 WarmStart：纯提示词一次生成

2026-10-15 用户选择“使用纯提示词”。当前推荐入口为 `scripts/run_prompt_warmstart.py`，设置为 `configs/prompt-only-warmstart.json`。本次完成软件接线和离线验证，不启动新的真实实验。

## 机制和预算

1. 从空的候选与评价历史开始，只调用一次 `warm_start.txt`，要求生成24个六维物理参数向量。上下界、单位、固定物理设置和必要库存条件写入上下文；不发送旧候选的仿真结果或 RMSE。
2. 复用原有合法性、归一化去重及最小距离检查。全部返回候选均计入固定24点额度，非法、重复或被过滤的候选不补位。返回数量不符直接保存错误并停止，不发修复请求。
3. 对通过检查的候选逐一做四倍率 DFN。完整实测时段和禁止外推规则保持不变；提前截止不能得到该倍率的有效 RMSE。四倍率均尝试，原始仿真曲线和单倍率观测都保存。
4. 若至少8点完整有效，用程序选8点：先保留平均 RMSE 最佳点，再在 RMSE 前16名有效点中依次最大化归一化参数距离。没有 LLM 二次选点，也没有根据仿真反馈生成新点。
5. 若不足8点，报告实际有效数、失败和成本，停止。不会调用 Sobol 或随机点补足。若后续明确设置 BO 轮数，只有验证过的完整缓存才能进入 BO；其他已支付仿真成本的观测保留在筛选历史中供 GP/完成概率训练使用。

“纯提示词”指 LLM 生成阶段不接收评价反馈、不反复补点、不从候选池调用 LLM 选择；程序的物理校验、真实仿真和最后8点的确定性选择仍然存在。实际 DFN 候选数可能少于24；API、返回候选、解析/物理拒绝、DFN 和各倍率求解成本分别记录。

## 环境与执行

本地工作目录 `D:\Users\aa133\Desktop\LLMBO_Para`，Python `.venv-pybamm312\Scripts\python.exe`（3.12.10），PyBaMM 25.10.2，单进程 CPU，数值库各1线程。设置沿用四倍率、六参数范围、固定初始浓度、固定电解液扩散倍率1.5和2.5/5/10/15 A推算电流。此变更没有重新校准物理模型。

以下预检查不访问 API、不做 DFN、不要求密钥：

```powershell
Set-Location "D:\Users\aa133\Desktop\LLMBO_Para"
& ./.venv-pybamm312/Scripts/python.exe -B scripts/run_prompt_warmstart.py --preflight-only
```

之后需要运行真实初始化时，使用以下命令；本次未执行：

```powershell
& ./.venv-pybamm312/Scripts/python.exe -B scripts/run_prompt_warmstart.py --prompt-for-key
```

密钥通过隐藏输入或 `LLMBO_OPENCODE_API_KEY` 进程环境变量读取，不写入配置。当前 API 为 OpenCode `deepseek-v4.1-flash`，代理 `http://127.0.0.1:7897`；预检查只核对配置与输入文件，不证明代理或 API 可达。默认 `bo_iterations=0`。需要继续 BO 时明确添加例如 `--bo-iterations 25`；不足8个有效点仍不会进入 BO。

每次运行创建 `runs/prompt-warmstart/<UTC时间_配置摘要_随机标识>/`。保存配置与源码、环境、命令、输入哈希、请求/响应、仿真、选点、筛选历史审计、日志和终态，不覆盖历史运行。子目录 `initialization/` 保存初始化证据，显式运行 BO 时另建 `optimization/`。

## 证据边界

此前同为24点的对照中，纯提示词在部分有效倍率上 RMSE 更低且 API 成本更少，但两组完整四倍率有效点均为0。选择纯提示词是简化当前机制、减少交互成本，不代表已证明能获得8个有效初始点或改善最终四倍率 RMSE。旧的质量反馈与分阶段脚本保留用于复现历史结果。

见 [本次接线审计](audits/prompt-only-adoption-2026-10-15.md)、[同预算对照](audits/warmstart-fresh-24-comparison-2026-10-14.md)、[RMSE 对照](audits/warmstart-rmse-comparison-2026-10-15.md)。
