# Region频繁失败的证据与修复（2026-10-20）

## 结论与原始运行

已确认请求延迟导致前三轮回退；没有证据把这些超时归因于GP、Lift公式或鉴权。第4次请求HTTP200、10.047秒、574输出tokens，严格校验通过，实际选点由plain索引276改为373。HTTP开始约在记账后0.55–0.60秒，启动开销不能解释30秒超时。请求负担可以降低，但外部排队/路由/推理哪个阶段慢尚未得到提供方证据；不声称已定位服务端根因。

本次用户另批“复用15选8计划”的80次DFN/20次Region API/1800秒独立预算；不是补成16选8。启动时审批元数据误用了受保护字段authorization，在任何API/DFN前退出1；修正字段名后继续原截止，没有重置额度。随后执行会话结束，Full第5次HTTP已开始但没有最终outcome；保留为未决中断，不标为超时、成功或20轮完成。原脚本、日志、授权和部分产物全部保留。

| 实际记录 | WarmStart-only | Full |
|---|---:|---:|
| 已完成BO轮数 | 20 | 4 |
| 新增DFN求解 | 40 | 8 |
| API请求已开始 | 0 | 5（4有outcome，1未决） |
| Region有效回复/改变选点 | 0/0 | 1/1 |

合计新增48次DFN、5次HTTP请求开始；复用计划的历史30次DFN/2次API与此前另一次失败恢复API不重新计入本轮新增成本。WarmStart-only最终固定折中点RMSE_U=4.7387428703mV、RMSE_T=0.0343556424K，HV=99.7542851538。Full只有4轮，不能作20轮性能对照。独立复算160个归档倍率/通道误差及部分HV通过；Full无完整summary/terminal，不标记整段deep审计成功。

唯一一次采纳还有单独的质量问题：第4轮两臂的标量化、GP和候选池逐字段相同，Warm臂确实评价了plain点。plain候选为5.6259550569mV/0.0283228315K，Region候选为15.5283915929mV/0.0293041773K，后者两个误差均较高。因此“成功采纳”不等于改善；这一个可配对点不足以推断多种子方法优劣。不能用事后实评结果替代选点时未知的真值，也不据此放大Lift或改核。

## 客户端修复与边界

- 可选紧凑wire：完整冻结请求摘要绑定request_id，严格还原原v2信封；默认full_v1和WarmStart保留。减少签名回抄负担，不删除科学候选信息，不取消任何语义校验。
- HTTP响应头事件、启动耗时、失败阶段与protocol_issue归档；空content、未正常完成、无效JSON、绑定错误分别可辨识。硬时限、无重试和原EI回退保持。
- 审计由原payload重建线上消息、核验回复绑定与规范信封；篡改权重或摘要应失败。
- 一条历史有效回复离线重编码：输入字符16957→14668（减少13.50%），回复1271→420（减少66.96%），规范信封相等；实际API/DFN0。未测新提供方tokens或超时率。
- 源码变更后旧计划按原严格规则报initialization signatures incompatible；没有重签旧数据或绕过缓存。后续真实验证须使用新源码下的有效初始化和另获批准预算。

## 验证证据

工作树`C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`，修改前HEAD为9dd6bbfe7cee24aceb020125210c0e0150dd31e5。新增产品文件electrothermal_region_wire.py；修改electrothermal_config.py、electrothermal_llm.py、electrothermal_requests.py、electrothermal_audit.py、llm.py；新增test_region_transport_repairs.py。没有改变Method定义、六参数物性、标量化/GP/EI/Lift数学、原参考工程或主目录源码。

证据根目录为`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation`，下列tests路径均位于该目录。最终产品源码指纹为`3e972c8fb4211f6b7a2b5153b7fb27e4cd9a34bc6bb761a1864baf34f1b5cb75`，与中断真实试验的旧指纹ce3c3ff不同。

- 基线：411/411，失败0/错误0，退出0，441.38秒。证据`bo-repair-work/20261017_et_implementation/tests/region-reliability-baseline-1020012838250785/{result.json,pytest.log,junit.xml}`。
- 有效RED：18项预期失败、另1项非法wire模式预期失败，错误0；复查另以3项RED复现非法llm对象引起的异常并补类型检查。两个早期pytest导入路径错误的运行保留但不算有效RED。
- 针对性：57/57，失败0/错误0，退出0，52.84秒。证据`.../tests/region-reliability-green-1020013727255993/{result.json,pytest.log,junit.xml}`。
- 首轮修改后完整回归：430/430，失败0/错误0，退出0，507.57秒。证据`.../tests/region-reliability-full-1020013842241354/{result.json,pytest.log,junit.xml}`。随后新增3项非法llm对象兼容检查；最终代码回归另行记录，不能将430当作最后版本的全部测试数量。
- 最终针对性回归：60/60，失败0/错误0，退出0，65.06秒，证据`.../tests/region-reliability-final-targeted-1020014812682270/{result.json,pytest.log,junit.xml}`。
- 最终完整回归：433/433，失败0/错误0/跳过0，退出0，570.33秒。[结果](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-reliability-final-full-1020014938446829/result.json)、[日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-reliability-final-full-1020014938446829/pytest.log)、[JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/region-reliability-final-full-1020014938446829/junit.xml)。全部测试的network_attempts/battery_solve_attempts为0；完整回归仅有2次已允许的非电池求解fixture调用。

修复阶段实际API/DFN预算为0。以上mock、真实worker离线HTTP边界、审计和代数任务不证明真实服务稳定恢复或实测辨识成功。此前已批准的真实DFN合成数据及部分实评记录另列，旧3C未使用。

实验证据：`runs/rr/20261020T011721Z_472abdc9cac0_487cc46c`。请求分析、160通道复算、旧计划拒绝及表示层测量：`bo-repair-work/20261017_et_implementation/region-request-repair-20261020/{observed-failures.json,partial-and-cache-check.json,offline-wire-size.json,interrupted-experiment-sha256.json}`。

新配置`region-request-repair-20261020/compact.disabled-config.json`采用compact_v1与eligible_region_v1，预检通过，LLM关闭、API/DFN预算0、无失效旧initial_plan引用。它是待审阅配置，不是启动授权。真实复验宜先做有明确预算的API契约检查，再以新源码有效初始化做完整共享初始化消融；当前没有新的真实验证结论。
