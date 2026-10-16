# 电热辨识分阶段修改清单与验收提案

2026-10-16。状态：设计审阅阶段的修改清单，**不是已获批准的详细实施计划**。设计文件为 `docs/superpowers/specs/2026-10-16-electrothermal-identification-design.md`。书面设计批准后，按 writing-plans 流程生成 `docs/superpowers/plans/2026-10-16-electrothermal-identification-plan.md`，明确任务接口和逐项失败测试；实施前完成该计划的审批节点。

## 已完成的准备

- [x] 核对主目录 HEAD、diff、暂存状态、已有工作树及实际新模块。
- [x] 阅读三个指定项目文档与附件全文。
- [x] 177 文件显式快照，独立临时索引保护用户暂存区。
- [x] 从有效快照创建独立开发工作树和分支。
- [x] 启动本轮实际全量回归，记录首轮临时目录失败并以独立临时目录重跑。
- [x] 只读核对安装版本的热参数/表面温度语义及参考算法。
- [ ] 用户审批书面设计。
- [ ] 生成和审批详细实施计划后实施。

## A：建立电热评价闭环

修改 `parameters.py`, `config.py`, `data.py`, `reference_cell.py`, `pybamm_adapter.py`, `evaluation.py`, `metrics.py`, `workflow.py`。
新增 `electrothermal_parameters.py`, `electrothermal_data.py`, `electrothermal_evaluation.py`。

拟新增测试 `test_electrothermal_parameters.py`, `test_electrothermal_data.py`, `test_electrothermal_evaluation.py`, `test_electrothermal_config.py`。

交付接口：独立 profile/新配置；明确工况与双观测类型；同次耦合仿真 trace；每倍率双 RMSE 及完整目标对。旧配置和返回契约继续成立。

验收：C/V 和 G/A 单位及实际处理值；T_ref 恢复 D_ref；电芯与环境温度分离；单位转换一次；两观测网格完整覆盖；缺失温度不填零；目标温度后续值不泄漏到输入；研究 pending 条件汇总拒绝。受控热方程解析测试通过。记录红→绿与旧全量回归。

## B：数值多目标优化

新增 `scalarization.py`, `pareto.py`, `mo_optimizer.py`；必要改动 `acquisition.py`, `surrogate.py`, `workflow.py`。

拟新增测试 `test_scalarization.py`, `test_pareto.py`, `test_mo_optimizer.py`。

交付接口：二维真实 Y、可重放二维权重、冻结尺度/理想点上下文、线性标准化 GP、高斯 EI、Pareto 参数集合和固定空间 HV。

验收：手工二维标量化、非支配/HV；换权重前后标签/标准化/incumbent/局部中心/后验/EI同步更新，包括失败后没有新有效 Y 的轮次；sigma=0 极限；V↔mV与尺度同步变换后决策不变。失败记录消耗预算且无伪造标签。

## C：LLM 两作用与端到端审计

新增 `electrothermal_llm.py`, `electrothermal_audit.py` 和两个 200–300 词英文 Prompt；复用/小改 `llm.py`, `informed.py`, `runstore.py`, `audit.py`, `initialization.py`, `screening_history.py`。

拟新增测试 `test_electrothermal_llm.py`, `test_electrothermal_audit.py`, `test_electrothermal_workflow.py`。

交付接口：ParEGO、WarmStart-only、完整 LLMBO-MO 三路线；具备新语义签名的 mock/研究 transport；双目标质量＋参数多样性组合选择；权重条件 Region 均值调整；曲线/映射/目标/决策独立审计。

验收：旧六维缓存与 LLM 回复拒绝；Prompt 字数/新 schema；无未来信息；弃权、格式和范围错误的有界重试/回退；LLM只影响采集；训练标签/原后验方差不变；冻结上下文信任比较。分别篡改温度曲线、C/V、G/A、尺度、权重均被审计识别；全部成本可核对。

## 配置、入口和最终交付

拟新增 `configs/electrothermal-synthetic.json`（代数软件 fixture）、`configs/electrothermal-dfn-synthetic.json`（真实 DFN 合成入口配置）、`configs/electrothermal-research-template.json`（pending模板）。

改动 `cli.py`, `workflow.py`, `README.md`；新增 `scripts/run_electrothermal_smoke.py`，必须显式给出轻量 DFN 预算，无预算只交付入口、不求解。详细命令在实现验收后写入 README，不能把当前提案中的文件称为已可运行。

每阶段证据：新增失败测试实际输出、针对性通过日志、全量回归及退出码/JUnit、配置/源码/数据签名、成本、独立审计报告、显式变更清单。所有证据新目录追加，不覆盖既有实验。

## 验收映射

| 用户验收项 | 阶段 |
|---|---|
| 旧配置/模型/评价兼容 | A，并在 B/C 全量回归 |
| C_th/G_th 单位与生效值 | A，C 审计重算 |
| 环境/电芯分离、单位只转换一次 | A |
| 同一次求解同时 U/T | A |
| 双 RMSE 可由归档曲线复算 | A/C |
| 缺失温度不补零 | A/B |
| 换权重全部上下文同步 | B/C |
| 二维标量化/Pareto/HV | B |
| 同维数不同语义缓存隔离 | A/C |
| 曲线/映射/权重/尺度篡改 | C |

## 运行边界

仅单 worker、BLAS/OpenMP 单线程；沿用锁版本。不调用付费 API，不做实测 BO/服务器任务，不修改原 New_LLMBO。不删除旧记录，不整体 git add。物理 DFN 合成与真实实验验证单列，不从 mock 通过推断物理成功。
