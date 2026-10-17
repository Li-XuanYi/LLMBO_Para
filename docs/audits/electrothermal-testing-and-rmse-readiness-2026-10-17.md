# 本轮回归与 RMSE 测试准备审计（2026-10-17）

测试基点 `cf84d59986345debdb7bb95cda1c05bec3e1973c`，分支 `codex/electrothermal-mo-20261016`，工作树 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`。用户本轮授权“开始测试，并准备方法 RMSE”，因此执行现有回归和独立计算检查；未推定为此前待审实施计划或真实 DFN 求解预算已批准。

## 本轮实际测试结果

| 运行 | 测试 | 通过 | 失败 | 错误 | 跳过 | 退出码 |
|---|---:|---:|---:|---:|---:|---:|
| 当前仓库完整回归 | 215 | 215 | 0 | 0 | 0 | 0 |
| 独立 RMSE 专项 | 22 | 22 | 0 | 0 | 0 | 0 |

上述是本轮新运行结果，不引用 2026-10-16 的通过数量作为本轮证据。完整回归 pytest 用时 313.31 s，含插件初始化等的 runner 用时 346.63 s；专项 pytest 用时 0.29 s，runner 用时 7.94 s。19 个现有测试文件保持原样。两次运行均为单线程设置、独立短临时路径，使用既有 Python 3.12.10 / PyBaMM 25.10.2 及锁定依赖；完整版本和实际模块来源见 manifest。

完整回归：[日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/baseline-1017131324322466/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/baseline-1017131324322466/junit.xml)、[退出码](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/baseline-1017131324322466/exit-code.txt)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/baseline-1017131324322466/result.json)。

RMSE 专项：[日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/rmse-1017131939237801/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/rmse-1017131939237801/junit.xml)、[退出码](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/rmse-1017131939237801/exit-code.txt)、[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/rmse-1017131939237801/result.json)。原始证据和测试脚本均保存在 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness`，机器可读审计同时记录其 SHA256。

本轮没有失败或错误，无需将其归因为既有/环境/本轮产品问题。历史临时目录权限及 Windows 长路径失败保留原记录；本轮选用新短路径，没有修改产品代码以绕过失败。

## RMSE 结果的含义

专项中 14 项验证现有 `metrics.rmse` 和旧聚合接口：独立公式、零/极大/极小残差、非法值、V→mV、温度单位误差一致性，以及旧四倍率聚合器继续拒绝三倍率输入。8 项为新规格的独立测试参考样例，覆盖双网格/两目标均值、人工未来四倍率、不读取未选择 3C、部分温度失败、温度篡改和环境温度分离。这 8 项并未调用新电热产品评价器；该模块尚不存在。

| 人工三倍率样例 | 电压 RMSE (V) | 温度 RMSE (K) |
|---|---:|---:|
| 0.5C | 0.01 | 1.0 |
| 1C | 0.02 | 2.0 |
| 2C | 0.03 | 3.0 |
| 等权目标 | 0.0200000000000002 | 2.0 |

预期为 `[0.02 V,2 K]`，浮点差小于 1e-12。未来四倍率参考额外使用完全人工的 3C（0.08 V/4 K），得到约 `[0.035 V,2.5 K]`；没有读取或拟合原始有问题的实测 3C。参考曲线和逐倍率复算保存在 `rmse-reference-fixture.json`、`rmse-reference-r3.json`、`rmse-reference-r4.json`。

这些数值是人为构造的验收值，不是 LLMBO-MO 优化得到的成绩。当前没有新方法的真实 DFN RMSE、Pareto 结果或实测拟合结果。

## 运行边界和兼容证据

两次运行守卫均记录网络连接尝试 0、真实电池 `Simulation.solve` 尝试 0。完整回归中有 2 次非电池模型 `Simulation.solve`（现有 eSOH 代数兼容检查），不计作 DFN 合成验证。没有付费 API、新 DFN 瞬态求解、正式实测 BO 或服务器任务。

两次运行前后核验 Stage 0 的 123 个产品文件 SHA256 全部相同；主目录 Git 索引及用户 Method 文件未改变，工作树测试后仍干净。旧电压接口及严格缓存回归通过；专项再次验证旧四倍率汇总未放宽。没有修改、删除或覆盖旧实验、缓存、XLSX 或参考工程；测试守卫和新专项只位于忽略证据目录。

本次提交仅新增本 Markdown 与同名 JSON 两份审计文档，不勾选尚未批准的 Stage A 产品实现任务。`run_checks.py baseline` / `run_checks.py rmse` 是本轮可复现测试入口；每次生成全新证据和临时目录。

## 后续方法 RMSE 验证准备与尚未验证项

详见 [20261017_rmse_readiness/rmse-test-protocol.md](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_rmse_readiness/rmse-test-protocol.md)。已准备当前三倍率两种独立观测网格的参考输入、期望值和错误样例。后续真实 DFN 同参 U/T 往返的提议为 3 次生成 + 3 次评价、最多 6 次求解、每倍率一次尝试、60 s 窗口、300 s 墙钟、单 worker/API 0；`dfn-rmse-budget-proposal.json` 明确 approved=false，当前实际预算仍为 0。

代码状态：Stage 0 设计/计划已交付，Stage A 新电热实现尚未开始。Level 1：现有回归及 RMSE 检查通过；尚不能宣称新电热软件闭环通过。Level 2：未运行；双向热反馈、实际 C/V 与 G/A 映射及温度变量行为尚未由真实耦合求解验证。Level 3：未运行；三倍率实际电流、T 单位与测点、初态、环境/冷却、热参数范围和固定活化能来源仍待确认，旧实测 3C 禁用。

下一步仍按已提交计划审批后从 Stage A 实现，完成 A6 入口并另获明确预算后再进行真实 DFN RMSE；不重新设计既定算法，也不把软件通过当成唯一可辨识性或 LLM 有效性证据。
