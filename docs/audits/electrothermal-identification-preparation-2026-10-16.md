# 电热多目标改造准备与基线审计

日期：2026-10-16（Asia/Shanghai）。本报告只涵盖源码保护、只读核查、当前回归与设计交付；产品实现尚未开始。

## 源码与保护结果

原主目录 HEAD：811c4c699fa3a82fcd64060d71e2bd21c075383c；分支 codex/llm-physics-prompts-20261013。检查时12个跟踪文件修改，并存在未提交的新模块/测试/配置/文档。原两个工作树位于2973855与d95addf，没有复用它们作为本轮基线。

有效源码保护提交：a5d298d2359eb6f3948ce6a33938029114882ae9，分支 codex/electrothermal-baseline-20261016。177个显式文件通过临时索引加入快照，没有整体git add，也没有移动原主目录HEAD或改变原暂存内容。归档及原始清单在 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261016_electrothermal_refactor_preparation`。

开发工作树：C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para；分支 codex/electrothermal-mo-20261016。Git检出使157个文件产生纯换行转换，已经从压缩归档恢复原始字节并刷新该工作树索引；177个文件与主目录保护清单逐一SHA-256一致。最终主目录源码差异0，开发树基线源码差异0。原索引字节指纹保持：True。

源码快照不含虚拟环境、实验记录、原方法工程或.env；不清理任何原记录。受控清单、压缩包、Git快照均独立保存。一次字节恢复命令因命令行引号解析失败，未写入文件；随后以独立脚本完成相同任务并验证，未修改产品代码。

最终状态复核：源码/原HEAD/原索引均未改变。保护清单中的status是在首轮回归运行期间捕获，包含该轮测试新建的tmp7qmqaq7l临时目录；测试的TemporaryDirectory退出后自行清理，status差异仅该临时目录。该目录不在初始用户工作区清单，也不在177文件保护清单，未清理既有实验记录。结构化证据保存了该差异的数量和根目录。

附件已读取：D:/DOC/Codex_LLMBO_MO_Electrothermal_Refactor.md，SHA-256：7e8491db55d064eee3c058ade953a84317ed71e43de20d738ce731a8ecece132。CodeGraph主工程未初始化，用户明确要求继续暂缓，本轮按实际文件核查。参考工程仅查询索引和读取指定源码，无写入、不读取.env。

## 本轮实际全量回归

| 尝试 | 通过 | 失败 | setup错误 | 跳过 | 时间 | 解释 |
|---|---:|---:|---:|---:|---:|---|
| 01 | 157 | 2 | 56 | 0 | 213.12 s | sandbox默认pytest临时目录无法建立 |
| 02 | 190 | 25 | 0 | 0 | 452.44 s | 工程内长路径触发Windows文件创建/复制失败 |
| 03 | 215 | 0 | 0 | 0 | 581.885 s | 使用短独立路径bo-repair-work/3；完整215项，不改测试与断言 |

最终退出码：0。每轮保留原始pytest日志、JUnit与退出码；未删除失败记录，也未引用历史136/113项代替当前结果。未对失败测试进行静默跳过。第一次临时目录问题与第二次路径长度问题通过调整测试运行目录解决；没有更改产品行为或测试预期。

第三轮复现命令：使用主目录 `.venv-pybamm312/Scripts/python.exe -X utf8 -B -m pytest tests -q --basetemp bo-repair-work/3 --junitxml <新的证据路径>`。重复运行必须选择新的临时目录与证据文件，避免pytest清理已有basetemp。启动前设置OMP/OPENBLAS/MKL/NUMEXPR线程为1、关闭遥测，TEMP/TMP指向工程内独立目录；这些仅作用于测试进程。

长临时路径下的归档限制仍存在，本轮通过短测试目录取得有效基线，没有实现通用Windows长路径支持；后续阶段也需沿用独立短路径。

测试范围是现有软件回归，其中包括mock仿真/transport和真实PyBaMM代数eSOH兼容测试；不是新增电热DFN合成验证或实测验证。新电热失败测试尚未编写，须在设计/计划审批后按阶段执行。

## 本机模型与依赖核查

Python3.12.10、PyBaMM25.10.2、NumPy2.5.3、SciPy1.18.1、CasADi3.6.7、pybammsolvers0.3.3、pytest8.4.2、openpyxl3.1.5。三个锁文件全部声明版本与安装版本匹配，无依赖变更。

安装源码确认：thermal=lumped、use lumped thermal capacity=true；Cell heat capacity [J.K-1.m-3]为体积热容。Cell thermal volume使用Cell volume [m3]，总热源W除以该体积得到体积热源；因此C_th/V与G_th/A的设计映射与本机方程一致。默认Ambient表面子模型直接把Surface temperature [K]设置为环境温度；设计明确使用Volume-averaged cell temperature [K]。

一个只读构模检查首次用了错误的选项名lumped heat capacity而报OptionError，原诊断保留为installed-thermal-source.txt。纠正为附件中的实际选项后构模成功，检查了Lumped、Ambient、ThermalParameters和BaseThermal源码；没有调用新增DFN的Simulation.solve。该构模/源码核查不等同于参数映射生效或耦合数值验收。

## 实际变更与未完成项

本轮保护提交保存既有有效代码；本轮开发分支新增设计、阶段修改/验收提案、迁移表、本报告和结构化证据。原src/tests/configs/锁文件未作实现变更。所有暂存/提交采用明确文档路径。

书面设计：docs/superpowers/specs/2026-10-16-electrothermal-identification-design.md。
阶段提案：docs/proposals/electrothermal-identification-stages-2026-10-16.md。
迁移表：docs/audits/electrothermal-identification-migration-2026-10-16.md。

审批节点：superpowers:brainstorming要求“the human partner reviews and approves the written spec”，之后才进入writing-plans；用户和附件也要求遵循已有审批节点。因此详细实施计划docs/superpowers/plans/2026-10-16-electrothermal-identification-plan.md尚未生成，当前阶段提案不冒充已批准计划。待用户审阅设计后生成详细计划并按流程确认，再分阶段实施。

尚未实现或验证：新电热评价器、数值MOBO、双目标LLM、双目标归档审计、synthetic配置/研究模板/运行入口及其新测试。计划完整覆盖这些交付；本报告不宣称工程改造已完成。

研究数据阻塞项：实际电流、T单位/测点、环境温度与初温、初态、统一冷却组、几何/热范围及温度依赖来源、正式尺度/HV参考点。它们只阻塞正式实测辨识，不阻塞后续软件实现。轻量电热DFN验证未给数值预算，将交付显式预算入口并标注未运行。

本轮新增付费API请求0、正式实测BO0、服务器任务0、新电热DFN求解0。软件闭环、物理合成验证、真实实验验证将分别报告，不把回归通过写成可辨识性或LLM有效性证据。

## 后续最小验证

先按阶段A/B/C验收软件闭环与审计。在科研组确认实测输入/探头/冷却/物性后，冻结模型、参数范围、尺度与HV参考点；申请明确预算做一个参数点的四倍率完整窗口U/T/热源验证及积分热收支，再做少量受控热参数/温度律扰动。正式等预算三路线与多种子研究另行开展。
