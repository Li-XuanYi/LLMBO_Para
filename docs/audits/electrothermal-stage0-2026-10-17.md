# 电热辨识Stage 0：倍率协议与实施计划

2026-10-17，Asia/Shanghai。状态：Stage 0文档交付完成，正式实施计划待用户审批，产品代码未开始。

## 实际检查状态

开发工作树C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para，分支codex/electrothermal-mo-20261016，检查基点0e01af26b3fac8a6754165421d0eca3b0b4dab9e。工作树开始时干净；最新0e01af2仅新增351行Method。原受控快照a5d298d继续使用，没有创建替代工作树或丢弃主目录未提交修改。

正式计划此前不存在。electrothermal_data/parameters/evaluation、scalarization、pareto、mo_optimizer和新LLM/audit等模块此前均未实现。旧ParameterSpace仍严格旧六参数名；FourRateEvaluator、mean_rate_rmse、Composite EI及工作流仍固定原四倍率。已有GP/后验协方差、单目标informed、缓存/RunStore可复用，但不能称为已有电热MO实现。

首次沙箱内Git访问托管工作树元数据被拒绝，使用已获准的只读元数据访问完成指纹捕获；没有改变权限配置或产品代码，也不将该诊断记成pytest结果。CodeGraph按用户既有选择保持暂缓。

## Stage 0实际修改

- docs/Method.md：一般化R_fit及1/|R_fit|双目标，当前三倍率/未来可靠3C四倍率区分；更改算法第11步和研究边界，保留原用户Method修改前副本/哈希。
- R1.1规格：显式fit_rates、旧3C来源排除、动态完整性/分母/预算；三/四倍率贯穿所有签名/缓存/归档。新增共享初始化签名与完整配置身份分离，并明确相同输入/相同目标的不同处理。
- 正式计划：docs/superpowers/plans/2026-10-16-electrothermal-identification-plan.md，路径按用户指定保留16日，首次生成于17日。14任务A0–A6/B1–B4/C1–C3，文件、函数接口、命名失败场景、red/green命令、阶段全量回归和提交/汇报要求均列明。
- 同步阶段概览与迁移表，原scope审计和llm-informed历史文档保持原样。本轮不修改新旧产品代码、配置模板、原始数据、实验或旧缓存。

## 数据协议决定

用户2026-10-17已明确旧3C数据存在问题，当前新版电热拟采用fit_rates=[0.5C,1C,2C]，正式运行仍需实际电流、T单位/测点、初态/环境、共享冷却、几何与物性范围预检。旧3C按来源身份排除，未来可靠3C须新数据身份/哈希及新配置；不能仅改标签解禁旧来源。

未选择3C不读其拟合观测；选中工况失败不删倍率或缩分母。三/四倍率协议即使维数同为六参数/双目标，也不得混用候选缓存、初始计划、GP状态或直接比较HV。v1原四倍率流程/缓存/旧记录保留，不放松旧校验，也不根据新数据决定追溯改旧哈希。

## 本轮验证与证据

本轮软件pytest数量0，未运行，因此没有本轮新增pytest退出码或JUnit；不把旧215项当成本轮测试。实际运行的是29项文档/指纹检查，29通过、0失败，退出码0。123个产品文件及锁文件指纹全部不变，参考源码指纹不变，主目录HEAD/暂存区和用户Method不变。

此前文档检查尝试1次，失败记录不删除：首轮28/29通过，缺少4个任务的显式Interfaces标题，修订计划补全后重新检查。该失败属于本轮文档结构问题，不是软件pytest或物理仿真失败。

原始Stage 0证据：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_electrothermal_stage0/validation-20261017T125146764798Z，包含validation.log、checks.json及exit-code.txt。修改前文档副本/源码指纹在D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_electrothermal_stage0。这不是Level1新功能测试，更不是Level2物理验证。

2026-10-16已完成的基线为215通过/0失败/0错误/0跳过/退出码0；日志和JUnit仍在bo-repair-work/20261016_electrothermal_refactor_preparation/baseline-03-pytest.log与baseline-03-junit.xml。计划批准后A0重新跑当次全量回归，再写新失败测试。

## 已完成、未完成与下一步

已完成：当前源码/文档核查、一般化倍率协议、Method/R1.1和正式实施计划、Stage 0审阅证据。未完成：任何Stage A/B/C产品代码、新电热单元测试、真实DFN入口实现、三模式软件闭环、Level2和实测辨识。拟交付入口不能当成已可运行。

Level1：新功能未实现/未执行，A0将先重跑当前基线。Level2：未运行，实际DFN预算0，A6将交付dry-run和缺预算拒绝入口。Level3：未运行，电流/温度/边界元数据及正式运行授权未满足。付费API、实测BO、服务器任务和新增DFN调用本轮全部0。

阶段门槛按用户要求：计划提交审阅后暂停，计划批准才执行A0/A1。各阶段分别报告代码/软件测试/DFN合成/实测四种状态，保存真实成本与审计，再推进。算法框架不重新设计。
