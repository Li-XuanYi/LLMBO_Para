# LGBO 电热 Region 简化实现与验证

日期：2026-10-22。状态：**Task0–4软件实施和验证完成；955项最终完整回归通过。真实API/DFN增益未验证。**

## 范围与版本

用户确认设计18de79e和实施计划0a24247，并批准当前会话执行软件实现及本地测试。复用独立工作树及codex/electrothermal-mo-20261016分支。真实API、DFN、实测及服务器预算均为0；未读取或记录专用密钥。

以LGBO论文§3.2直接confidence映射适配最小化标量GP：均匀区域锚点，lambda=c/sqrt(v)，有符号均值平移，原方差不变，全池Gaussian EI。删除新策略中的目录、公平门槛、eligible、trust/退火/consistency及区域内选点限制。旧策略和旧记录保留；六参数、两目标、模型和WarmStart不变。

实现提交：

- 3afaa28：electrothermal_lgbo.py的数学、严格规范动作校验和采集视图。
- 7306593：直接动作、精简Prompt、配置分派、完整请求绑定及冻结controller。
- e07f5f1：MO逐轮接入、独立公式/原始HTTP审计、零预算模板及工作流测试。
- 47769e7：独立审阅后的失败回复缺失核验，未修改LGBO数学或选点。

主要接口：lgbo_mean_tilt、validate_lgbo_region、apply_lgbo_region、lgbo_request_id、lgbo_wire_payload、decode_lgbo_action、audit_lgbo_round。MOOptimizer.step/summary按一个region_method分派；旧Optimizer不改。

| 职责 | 本轮文件 |
|---|---|
| 数学及采集视图 | src/llmbo_para/electrothermal_lgbo.py |
| 直接动作及配置入口 | electrothermal_lgbo_wire.py、electrothermal_config.py、electrothermal_region_wire.py、electrothermal_requests.py（均在src/llmbo_para） |
| 冻结请求与Prompt | electrothermal_llm.py、prompts/region_preference_lgbo_electrothermal.txt |
| MO及独立审计 | mo_optimizer.py、electrothermal_audit.py、electrothermal_lgbo_audit.py |
| 测试 | tests/lgbo_fixtures.py、test_electrothermal_lgbo.py、test_lgbo_region_wire.py、test_lgbo_region_workflow.py、test_lgbo_region_audit.py |
| 配置与文档 | configs/electrothermal-sub2api-lgbo-software-template.json、docs/Method.md、docs/llm-informed.md及本审计 |

显式变更清单及各文件SHA256另存证据根目录的最终保护核验JSON；历史源代码快照及原始实验不重签。

## 本轮实际软件证据

证据根目录：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-region-20261022/。测试均使用新label、单线程和网络/真实电池求解守卫；历史测试数不充作本轮结果。

| 阶段 | 实际结果 | 退出码 |
|---|---|---|
| 新鲜完整基线 | 852通过，0失败/错误/跳过 | 0 |
| Task1 RED | 28失败，模块缺失 | 1 |
| Task1 GREEN/相关回归 | 28/28；41/41通过 | 0 |
| Task2 RED | 22失败、9通过，尚未实现新配置/接口 | 1 |
| Task2首次GREEN | 56通过、3宿主tuple类型失败 | 1 |
| Task2修正GREEN | 59/59通过 | 0 |
| native controller seam RED | 1缺失deepcopy导入失败 | 1 |
| Task2最终相关回归 | 233/233通过 | 0 |
| Task3 RED | 26失败、1通过，新循环/模板未接入 | 1 |
| Task3首次GREEN | 67通过、20HTTP重建失败 | 1 |
| Task3修正GREEN | 87/87通过 | 0 |
| Task3扩展相关回归 | 76通过、1新增常值仿真夹具参数形状失败 | 1 |
| 夹具修正/受影响回归 | 10/10通过，产品公式不改 | 0 |
| 审阅修复RED | 6删除回复场景失败、8真实无正式回复故障通过 | 1 |
| 审阅修复及新旧审计GREEN | 79/79通过 | 0 |
| 冻结源码最终完整回归 | 955通过，0失败/错误/跳过 | 0 |

最终回归实际耗时1351.94秒，源码提交47769e7650db575bc06ba1bb8a2f212aef2e8fd2。边界network_attempts=0、battery_solve_attempts=0，另有2次既有非电池代数模型Simulation测试；它们不是DFN电热验证。955项是本轮最终结果，852仅为本轮实施前基线。全部TDD失败归属于本轮新接口/实现或新增夹具，最终回归没有既有问题、运行环境失败或未修复引入问题。

最终完整证据路径：

- 日志：D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/lgbo-final-full-1022113214988563/pytest.log。
- JUnit：同目录junit.xml；退出码：exit-code.txt；计数与边界：result.json。
- 调用、线程、起始源码指纹：证据根目录lgbo-final-full.invocation.json；最终闭环：final-closure.json。
- 其它独立RED/GREEN日志、JUnit和result.json位于同级tests/lgbo-*目录，完整索引evidence-index-final.json；新账本的最终副本execution-ledger-final.md。

失败均保留：宿主tuple与模型JSON边界仅规范化可信身份；模型动作仍严格。Chat JSON后缀和Responses冻结payload键顺序按实际传输重建，不放宽比较。新增常值夹具改用仿真器实际要求的参数字典，不修改目标或数据。

已验证：负协方差、c=0、低confidence、均匀锚点、自然不确定性界、实际改变选点的正定样例、区域外赢家、第13轮、失败轮重建、V/mV匹配尺度不变、重复输入缓存、不同输入同Y、两种真实生产worker的离线HTTP边界、共享初始化及9类独立篡改。

独立整体审阅覆盖0a24247..e07f5f1及本轮文档，发现0个Critical、1个Important：失败回复的原始HTTP文件缺失时可能仅凭failed状态通过。先执行14项复现测试（6失败/8通过），再用completion、protocol_issue和parse-error证据要求保留已解码的原始回复；仅有request或failure_stage不自动要求回复，以保留真正的启动、连接、超时和HTTP JSON解码前故障。审阅原文final-review.md及全部负记录保留，优化公式与原方差未改。

## 软件双RMSE闭环

software-comparison/protocol.json先固定种子17/41/59、16候选选8个共享初始点、WarmStart-only/Full各20轮，max_sweeps=0。固定mock区域[.3,.8]^6、c=.65，未调用LLM。观察值来自人工4秒代数模型；倍率标签不是实测电流或5Ah换算，不能与旧60秒真实DFN结果比较。

共120轮BO目标记录、6个完整优化档案，全部通过深审计；另有共享初始化档案。BO-RMSE.csv保留每轮真实软件评价的同参数F_U/F_T，不补齐缺失目标，不拼接两个独立最低误差。

对照档案固定源码指纹85f28cadd6b8ac5b7d919e66d5e2b6df52787849408188877bb6be256aee1dd2，对应Task3/e07f5f1的产品内容；后续47769e7只加强审计，数学/优化器未改。旧档案继续保留旧指纹，不能将其初始化计划自动换签到当前源码。

| 种子 | WarmStart-only固定HV | mock LGBO Full固定HV | Full−对照 |
|---|---|---|---|
| 17 | 92.8647215854 | 92.9004510852 | +0.0357294998 |
| 41 | 92.9681117834 | 92.9397974714 | −0.0283143121 |
| 59 | 92.9479429657 | 92.9098180665 | −0.0381248992 |

各run的summary.json同时保存按固定等权增广Tchebycheff从Pareto选择的代表参数及两个RMSE，原始曲线可以独立复算。正负结果全部保留；这不是LLM有效性或真实电热增益实验。

Full共60轮执行非零倾斜、其中14轮改变选点。按固定规则选择的同参数代表解，电压RMSE（mV）/温度RMSE（K）依次为：种子17对照48.6416/0.254607，Full48.2783/0.262307；种子41对照47.5850/0.253371，Full47.8946/0.243544；种子59对照47.8053/0.245854，Full48.1944/0.247665。BO-RMSE.csv记录逐轮目标，representative-RMSE.csv记录该代表解，不能将两个分别最小的误差拼成一个结果。

独立标准库脚本recompute_software_rmse.py从归档原始曲线线性插值，不导入产品评价/metrics函数：168个档案目标对（含各臂共享初始点）、336条分倍率曲线、672项RMSE、120行BO CSV及6个代表解全部复算一致，最大单项绝对差5.551115123125783e-17；结果rmse-independent.json，退出码0。记录的source_kind=fresh_simulation表示评价来源；是否软件模型由manifest.config.run_kind/model.provider判定，不将该字段误读为真实DFN。

## 兼容、保护与未验证事项

新模板configs/electrothermal-sub2api-lgbo-software-template.json保留软件数据定义和零预算。新策略进入配置/算法/请求签名，旧六维回复不能混用，旧source初始化不得自动换签。旧schema1电压、旧schema2 Region/Prompt/审计、锁定依赖和原多目标参考工程均保留。

CLI预检和CLI深审计均已实际结束，退出码0。最终源码再次核验也通过，见cli-preflight-final.log、cli-audit-final.log、对应exit-code文件及cli-final-checks.json，network/battery均0。修复后的保护核验protection-post-fix.json通过，最终提交后protection-final.json保存同样核验和显式变更清单：主工程124个文件、旧Region函数AST、24个旧数值/Prompt文件及锁版本内容不变；MO是批准的新增分派例外。新源码指纹054f0a7ca110a23640a802055516b9734c536d17d68192c7a53fa27949e8ccb8。保护脚本首次将Windows CRLF工作文件与Git LF blob直接比对，误报一个锁文件；已以Git clean-filter blob和原生SHA分开记录，未改锁文件或换行，诊断保留在protection-helper-line-ending-diagnostic.json。主工程和旧归档不接收产品变更；全部新增证据在本计划自己的目录。

本轮没有新真实API契约验证、真实DFN合成BO或实测辨识。电流、温度测点/单位、初态、冷却条件及热参数研究范围仍按原预检约束；旧3C继续禁用。软件通过不证明物理参数唯一性，也不证明LGBO稳定优于Plain。

验收层级及后续最小路线：

- Level1软件：实现、TDD、全量955项、独立审阅修复、软件双RMSE复算与深审计完成；旧电压接口和旧Region兼容。
- Level2真实DFN：本轮未运行。先按独立有限协议验证新精简API契约，再在明确的新求解预算内采用同一有效初始化计划、冻结尺度和固定种子的WarmStart-only/Full配对；分别记录合法回复、倾斜、选点变化和真实RMSE/HV，保留负结果。
- Level3实测：仍被元数据预检阻塞。确认电流A及时间网格（5Ah仅为容量）、T列单位/电芯测点与环境温度、初态和冷却条件，先做固定参数的电压/温度曲线复算，再启动正式辨识。当前计划使用可靠0.5C/1C/2C；未来可靠3C另建配置、数据签名和归档，不回写旧实验。
