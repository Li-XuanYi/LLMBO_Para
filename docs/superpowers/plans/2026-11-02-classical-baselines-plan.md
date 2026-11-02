# Classical baseline execution plan

授权：用户要求实际继续NSGA-II/ParEGO/PSO对比，沿用5种子50次新增评价、直接实施和运行的边界。本次API=0；不改已有实验。使用executing-plans原生执行，不额外委派。规格见同日classical-baselines-design.md。

1. 环境：独立venv，下载核验jMetalPy固定版本；保存完整pip freeze、包文件/源码哈希和安装报告，不改变DFN解释器。
2. TDD新增`scripts/et_classical_policy.py`：官方NSGAII/SMPSO、指定初始生成器、JSON评价接口、精确新增评价停止与状态归档。失败测试：身份/配置、16点顺序、不同种子/同种子、重复不扣真实评价、50次边界/partial不补零。软件二维目标验证真实stock算法。
3. 新增`scripts/et_classical_worker.py`：严格full16来源桥接、现有ParEGO16、外部policy交互、统一评价/成本/曲线归档。测试：旧签名不得强行兼容、完整来源验证、单次耦合求解、独立温度网格、重复和失败。
4. 新增`scripts/run_et_classical_validation.py`：复用冷spawn、OwnedWindowsJob和持久FactorialBudget；15阶段平衡顺序，0API，旧初始池只读；source/policy环境/依赖/输入文件pin；每种子完成即分析。
5. 新增`scripts/analyze_et_classical_validation.py`：通用深审计+外部算法协议重放，逐轮RMSE/HV、与冻结LLMBO/WarmStart-only配对、所有16初值成本及来源。已知样例与篡改检查先失败后实现。
6. 针对性回归、15组10轮实际冷spawn软件演练（API/DFN=0），观察结果后提交代码冻结；启动15组50轮真实合成，不再触发API。保留全部负结果，完成自动报告。

可执行入口应明确--software/--execute、--factorial-root、--policy-python、--output、--rounds、--seed-count与软件证明；无导入副作用。不使用原始实验目录写入新文件。完整历史回归尚未通过的状态仍保留，本轮不将针对性通过写成全量通过。
