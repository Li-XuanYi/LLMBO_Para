# Region 流式传输修复与分阶段验证：软件通过，真实门槛未放行

本轮依据用户批准的 cc5e3d6 计划执行。测试/执行代码为 `50ac4062e3e3f3452ae9f629739a05d110c4bf04`，核心 fingerprint 为 `80c2ee6852050b159d6dd5a8efee584e677f38b896c6ad527f63524bcd694a9d`。继续使用原独立工作树和分支，不合并、推送、清理旧实验或更改参考工程。

结论：显式 Responses SSE 接收、归档、审计和验证入口已实现并通过完整软件回归。首个真实最小请求在 1.797 秒后返回 HTTP404，按获批规则立即终止。实际只有 1 次模型 API、0 次 DFN、0 轮 BO；真实 SSE、完整 Region、非零 tilt 和 RMSE/HV 增益均未验证。不能将本轮结果解释为方法无增益或已修复历史网关超时。

## 软件验收及失败归因

以下均为本轮实际执行；各行有重叠，不能相加成测试总数。

| 证据标签 | 测试 | 通过 | 失败 | 错误/跳过 | 退出码 | wrapper 秒数 |
|---|---:|---:|---:|---:|---:|---:|
| ge-st-baseline | 1441 | 1440 | 1 | 0/0 | 1 | 7987.638 |
| ge-st-orphan-repro（未改旧测试） | 1 | 1 | 0 | 0/0 | 0 | 11.624 |
| ge-st-controls-sse-green | 232 | 232 | 0 | 0/0 | 0 | 112.39 |
| ge-st-audit-corrected-green | 156 | 156 | 0 | 0/0 | 0 | 335.07 |
| ge-st-entry-joint-green | 157 | 157 | 0 | 0/0 | 0 | 132.14 |
| ge-st-review-final-green | 139 | 139 | 0 | 0/0 | 0 | 125.528 |
| ge-st-review-sse-green | 48 | 48 | 0 | 0/0 | 0 | 9.220 |
| ge-st-final-full | 1581 | 1580 | 1 | 0/0 | 1 | 2888.162 |
| ge-st-orphan-bounded-green | 51 | 51 | 0 | 0/0 | 0 | 50.273 |
| ge-st-orphan-negative-control | 1 | 1 | 0 | 0/0 | 0 | 10.427 |
| **ge-st-final-full-r2** | **1581** | **1581** | **0** | **0/0** | **0** | **2369.748** |

最终 pytest 自身耗时 2363.81 秒；wrapper 包含保护检查等开销。最新 JUnit/result/exit-code.txt 已交叉核对。257 个运行输入 pins 及解释器/依赖一致，source/protection 均未漂移。完整回归守卫记录实际网络尝试0、battery solve尝试0；两个非电池 Simulation 调用另记，不能称为 DFN 验证。

基线和首轮完整回归的唯一失败均为既有 `test_abrupt_parent_exit_cannot_leave_sleeping_grandchild` 的即时 PID 存活断言，早于本轮产品修改存在。仅单项重跑通过不足以消除该问题。因此做了独立离线观测：先核实原孙进程创建时间和 Job 归属，再跟踪不变的旧 close 实现。8 个自建进程场景均有受控清理；4/4 持原句柄场景在 Job active=0 时仍 WAIT_TIMEOUT，3/4 在 supervise 返回时仍 pending，随后同一原进程句柄及相同创建时间的重开句柄均 signaled；4 个释放句柄对照最终 PID 不存在。未观察到 PID 复用或持续残留。

这支持 Job 记账和进程对象终止信号存在观测间隔。Microsoft 文档说明进程终止调用可异步完成，应等待进程对象信号：[TerminateProcess](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-terminateprocess)。本轮仅将旧测试的零超时检查改为最多2000ms的 `WaitForSingleObject`，仍要求真实终止；旧 launcher/product 未改。另用内存中故意不终止子进程的负对照证明：真正存活30秒的子进程仍触发断言失败，并受控清理。没有通过删除断言、跳过测试或重试直到绿色来处理该问题。

TDD 的所有 RED、失败 fixture 及更正记录均保留。早期 audit fixture 的 KeyError 不是产品缺陷，其错误 RED/首个 GREEN 不被当作有效修复证据；更正 fixture 后重新执行了真正的 RED→GREEN。详见本轮 final-review.md、task3-fixture-error.json、orphan-timing-diagnosis.md 和原日志。

## 本轮改动清单

实施提交相对 cc5e3d6 共17个文件，使用显式文件清单提交；交付另新增本审计报告。报告文档提交不改变已测试/执行的50ac406产品与测试内容。

| 文件 | 职责 |
|---|---|
| src/llmbo_para/llm.py | 提取共享响应读取钩子，保留原 HTTP 鉴权、代理、TLS、重定向和非流式行为 |
| src/llmbo_para/electrothermal_config.py | schema2/Responses 独立严格布尔配置 responses_stream |
| src/llmbo_para/electrothermal_requests.py | 传播控制及追加流式归档/安全进度 |
| src/llmbo_para/electrothermal_llm.py | 配置、clone、outcome 的显式控制绑定 |
| src/llmbo_para/electrothermal_responses.py | 显式 SSE 分支；最终完整 JSON 校验保持；普通 RunStore 适配 |
| src/llmbo_para/electrothermal_sse.py | 新增有界 UTF8/SSE 解析及纯协议重放；不以 delta 拼造成功 |
| src/llmbo_para/electrothermal_json.py | 独立流证据/派生 response 一致性核验 |
| src/llmbo_para/electrothermal_audit.py | 配置、请求、supervision/outcome、SSE 证据联审 |
| src/llmbo_para/electrothermal_lgbo_audit.py | 重建带显式流控制的原生请求 |
| configs/electrothermal-sub2api-stream-software-template.json | 默认禁用 LLM/API/DFN 的软件模板 |
| docs/llm-informed.md | 可检查的配置、契约和验证边界 |
| scripts/run_region_stream_validation.py | 默认 dry 的固定诊断、真实 HTTP 子进程等待采样、放行/预算/配对入口 |
| tests/test_responses_stream_controls.py | 控制、兼容、真实离线 spawn 和硬截止 |
| tests/test_responses_sse.py | framing、终止契约、大小限制、脱敏、RunStore 兼容 |
| tests/test_responses_stream_audit.py | 独立重放、篡改负例、旧非流式兼容 |
| tests/test_region_stream_validation.py | 放行、成本、停止、历史上下文、release 和 owned 生命周期 |
| tests/test_lgbo_real_gain.py | 只修正既有 Windows 终止信号的有界观察 |

实现提交：20cd606、d026c7b、a448ba5、26434db、50ac406。独立最终审阅发现的两个 Important 均已 TDD 修正：中间自由文本分片归档漏洞、普通 RunStore 缺少流式 hooks。中间事件现只保留重放协议元数据；原正式终止 response 仍按既有规则脱敏。非法事件不能因投影变成合法证据。

流式解析总上限1MiB/4096语义事件，严格有限 JSON、增量 UTF8、sequence/response ID/终止状态；绝对截止不随保活延长。保留 failed/incomplete 终止证据但不接受为成功；未配置时原非流式 body 不变。没有新 GP 核、Prompt 修改、Region 公式或目标空间改变。

## 真实阶段的事实与限制

北京时间2026-10-25 00:29 左右启动独立账本，UTC日期仍为24日。运行代码50ac406、冻结执行快照、p0归档91个核心输入、软件 release 的 fingerprint 一致。先执行历史 c01 深审计，结果 passed，实际20次GP fit、sweeps未单独计量；该只读步骤0 API/DFN，未使用旧预算。

真实 p0：

- 请求目标 `https://sidrune.ai/v1/responses`；model `deepseek-v4-pro`，reasoning none，8192许可，非流式最小JSON，配置60秒、有效58.703秒；实际 body SHA256 `73e8f95b1332a4939ef3e2674278b318b124f89bf9103d95d93f44ac00a68be2`，wire_verified=true。
- HTTP404，elapsed1.797秒，正式回复未产生，usage未知，不能补0。未到30秒采样时刻，故等待栈样本0是预期现象。
- 旧 failure_stage 字段记为 awaiting_headers，但这里已有真实404 HTTP响应；不能据这个粗标签声称未收到任何响应或发生超时。
- owned_tree_stopped=true、worker exit0、cleanup_error=null、唤醒租约释放。worker正常返回失败诊断，不代表请求成功。
- 新账本4条记录哈希链有效，唯一收费事件p0，API1/DFN0，finish=false，已失败关闭。剩余额度不自动启用。
- s24r只有p0；没有SSE文件、DFN评价、BO轮次或gate proofs。p1–p5、共享8点新评价、三个种子Plain/Full对照均未启动。

公开供应商文档仍给出 `/v1/responses` 作为完整请求路径，并说明模型可用性取决于API Key分组：[Sidrune帮助中心](https://docs.sidrune.ai/user-guide/help-center)。实际请求未拼成重复的 `/v1/v1`。公开文档不证明本密钥对应的DeepSeek分组、模型通道或当次路由可用；本轮证据不足以区分路由、分组/模型支持或代理响应来源。当前错误归档保留了安全机器诊断，未保留足以进一步细分404的供应商错误正文。没有据此猜测更换模型、端点、协议或代理。

下一步只应先定位404，不能把8192继续增大作为已证实修复。已准备一个待批准的独立小诊断提案：最多2次API、0 DFN/BO、180秒，保留脱敏错误码并条件读取可用模型；不恢复本轮配对试验。详见 next-http404-diagnostic-protocol.json。当前批准状态为false，未执行。

## 证据、保护与尚未完成

本轮证据根：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-transport-stages-20261024`。

- 最新软件日志/JUnit/result：`tests/ge-st-final-full-r2/{pytest.log,junit.xml,result.json,exit-code.txt}`。
- 首轮完整失败证据：`tests/ge-st-final-full/`；原基线：`tests/ge-st-baseline/`。
- 离线终止观测：`job-exit-observation/result.json`、独立日志和退出码；负对照JUnit在对应tests目录。
- 放行/协议：`software-release.json`、`validation-protocol.json`、`approval.json`、`s/`冻结执行源码。
- 真实结果：`phase-p0.json`、`validation-result.json`、`budget-journal.jsonl`、`live-validation.log`、`live-exit-code.txt`；原始p0归档在 `D:/Users/aa133/Desktop/LLMBO_Para/runs/s24r`。
- 独立只读审阅：`final-review.md`、`protection-independent-review.md`。

保护核验：27/27数值/Prompt、8/8固定文件/locks、55/55参考工程一致；本轮初始seal30/30一致；旧reasoning1120/1120归档、旧gain2744/2744归档一致。活动工作树路径仅本轮显式允许改动，旧seal本体及归档未重写。主目录有独立并行编辑，未覆盖/恢复或借用；临时未跟踪目录未由本代理清理。

已完成：软件实现、TDD、独立审阅及修正、完整绿色回归、严格软件放行、真实首请求与按规则停止/清理。旧电压任务的软件兼容保留。

未完成：真实SSE、完整Region动作、非零均值调整/选点影响验证，以及RMSE/HV配对。没有新的物理效果验证或实测辨识，也没有“参数唯一可辨识”或“LLM有效”的结论。实际电流/温度测点与单位/初态/冷却条件仍须科研预检，旧3C仍不参与新实测拟合。
