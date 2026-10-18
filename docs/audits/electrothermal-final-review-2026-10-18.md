# 电热最终审阅与真实实验准入（2026-10-18）

最新API核验：用户先更换为napi.kid1412.qzz.io，模型列表403、原模型聊天503/model_not_found；随后改为vsllm.cc，模型列表200、deepseek-v4.1-flash最小聊天200并返回OK（35输入/11输出tokens）。新端点两次检查都未启动BO或DFN。包含原401及四次核验，R2总计已用5/23请求、2/74求解，剩余18请求/72求解；原1800s窗口已结束，用户明确选择仅核验API、暂不继续BO。旧记录和既有合成观测保留。精确HTTP证据在主工程bo-repair-work/20261017_et_implementation/vsllm-chat/events.jsonl及vsllm-chat-result.json。

独立只读审阅范围47d464d..ac26065，由fresh-context gpt-6-astra完成；无Critical，五项Important。按一次TDD修复流程完成下列问题；不再派第二次审阅。软件通过不替代真实DFN、实测或LLM有效性证据。

| 审阅问题 | 修复与失败测试 |
|---|---|
| BO缺整候选预算预留及共享截止时间 | SolverBudget.require_candidate、MO进入/评价/LLM前检查；electrothermal_execution.run_with_deadline用单个受控spawn worker和开始握手计实际调用，超时仅终止本次worker。test_reservation_refuses_unaffordable_candidate_before_any_partial_solve、test_global_deadline_stops_software_before_candidate_work、两项native_subprocess_deadline测试 |
| 导入计划丢失初始化历史成本 | InitialPlan.history_evidence保存完整筛选池、选择过程、去重事件和来源；加载独立核验曲线/成本，historical_costs与增量成本分列，不重复相加。test_shared_plan_preserves_full_screening_costs_separately_from_new_calls |
| WarmStart请求数压制后续Region | per-task计数和全局真实请求预算分开；Region最多BO轮数，仍受总API上限。test_region_remains_available_after_warmstart_uses_its_request_cap |
| 缺initialization.json可跳过审计 | MO运行必须有初始化档案，再回放全部数值路径。test_missing_initialization_file_cannot_bypass_algorithm_audit |
| research/DFN可误用代数模拟器 | run_kind/provider双向严格匹配。两项test_nonsoftware_run_kind_cannot_select_algebraic_backend |

补充：原生输出周期显式配置在model.output_period_s，仅synthetic DFN配置采用1s，仍保留独立U/T观测网格；不增加模型自由度、目标或solve次数。真实API请求附机器生成的严格回复schema及电流/环境/初始温度/观测摘要，不发送逐点曲线、XLSX或合成真参数。两项真实payload红/绿测试通过。

首次终审失败测试8fail/2pass；硬截止专项2fail；全部对应红/绿日志均保留。终审修复后首次全量312/312通过；随后为用户批准的真实API补充输入摘要，最终全量 **314/314通过，0失败/错误/跳过，退出码0**。证据：D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\tests\native-bridge-final-full-1018094826952622，包含pytest.log、junit.xml、exit-code.txt、result.json。边界：{'network_attempts': 0, 'battery_solve_attempts': 0, 'allowed_nonbattery_simulation_calls': 2}。最后41项LLM/审计专项通过。Windows单调时钟粒度使1ns截止测试非确定，测试改为明确过去的deadline，未放宽生产截止检查。

两个Minor暂缓：重复格式错误时parse-error诊断仍使用旧任务名；R1规格§11.1/11.2残留待实现/待审批的历史措辞。当前状态以规格头部、本审计及实验报告为准，原记录不清理。

审阅未判断：真实DFN耦合/积分和C/G敏感性必须由独立物理预算验证；当前仅完成部分生成，不能将批准预算写成验证通过。实测数据有效性、可辨识性及LLM增益继续未验证；没有服务器/部署任务；旧完整实现不作额外正确性保证，其兼容结论仅来自本轮实际全量回归。

真实原生桥接补丁：首次R3生成成功后，np.interp产生的np.float64被严格TimeSignal数据契约拒绝；失败测试观察到该错误，最小修复只在生产端显式转为Python float，不放宽数据校验。桥接专项4/4及本次314项全量通过。Windows长临时路径另曾触发CopyFile2路径错误；专项用短路径重跑通过，真实实验使用主目录runs/et-live短根，不修改旧RunStore。软件全量实际耗时362.67s，无真实网络与电池solve。

实际物理记录：独立R3预算仅完成0.5C生成1次，原始便捷runner错误报0，以终端actual_solver_calls=1及partial-physical-validation.json更正为准，历史文件保留；300s窗口已结束。独立R2真实API预算完成0.5C/1C生成2次，原端点首次WarmStart返回401，初始化和20轮BO均未开始，1800s窗口已结束。两倍率真实DFN曲线各61点，热能平衡相对残差约2.77e-6/3.07e-6；独立同参0.5C两次生成的U/T RMSE均为0，仅说明数值自洽，不是BO拟合误差。C/G扰动、完整12次烟测、完整LLMBO-MO的RMSE尚未验证。用户后续明确仅核验替换API，暂不继续BO；端点核验与剩余次数见主工程bo-repair-work/20261017_et_implementation内replacement-api-*和vsllm-*证据，不向源码写入密钥。

已批准实验预算分别为：(1) R3/60s/生成3+同参3+C扰动3+G扰动3，最多12solve/300s/API0；(2) 真实API+真实DFN合成R2/60s，8初始化+20BO，筛选池最多16，生成2+筛选32+BO40=最多74solve，最多23API/每次4096输出tokens与30s，单线程无重试，1800s。两者独立归档，未运行前不写成物理通过。R2实验显式数值配置：seed17、GP4sweeps、全局256/局部128、Region有效期21覆盖20轮；保留既定数值骨干。密钥只允许隐藏stdin进入临时环境变量，不进配置、argv或文件。
