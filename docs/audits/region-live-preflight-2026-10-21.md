# Region 真实 API 预检：超时关闭记录

用户已批准修复版a485e16的一次受控恢复，沿用原512DFN/121API及北京时间2026-10-22 00:45:52总截止，不增加次数或重置计时。恢复授权与公开凭据确认记录分别写入runtime-bootstrap-fix-20261021/bootstrap-recovery-approved.json及credential-confirmed.json，均不包含密钥值。原始失败、封存及预算起点保持不变。

## 实际结果

修复后的启动器正常通过归属校验，进入preflight阶段，首次实际HTTP请求开始。北京时间2026-10-21 23:51:24创建预检档案，23:51:56以failed结束。请求在等待HTTP响应头阶段超过30秒，没有HTTP状态码，也没有响应正文。

| 项目 | 实际结果 |
|---|---|
| 请求 | https://sidrune.ai/v1/responses，deepseek-v4-pro |
| 传输 | Responses，stream=false，store=false，1536输出tokens上限 |
| 请求体 | 与原冻结请求严格一致，规范化UTF-8为58186字节 |
| 请求诊断 | TimeoutError，deadline_exceeded，awaiting_headers |
| 请求耗时 | 30.031秒；配置单次时限30秒 |
| 外层监督 | 33.906秒，未触发60秒外层超时，工作进程退出2 |
| 启动命令 | PowerShell封装退出1；以结构化工作进程退出码2为诊断依据 |
| API尝试 / DFN / BO | 1 / 0 / 0 |
| 传输重试 | 0 |
| 服务商usage / 费用 | 未知；没有响应，不填成0 |
| 新RMSE、Pareto、HV | 未生成 |

原预算日志依次为start→preflight开始→API记账→preflight失败结束。closed=true、gate=false，开发阶段启动已被本地预算校验拒绝。未启动DFN、BO或新的参数评价，不能把温度/电压目标缺失补成0。

## 证据与推断边界

原始会话：`D:/Users/aa133/Desktop/LLMBO_Para/runs/g21p/20261021T155124Z_7edc2e11063a_e9e0360f/`。关键文件为terminal.json及http/region_preference_electrothermal.request.json、region_preference_electrothermal.supervision.json；没有response.json。

独立复核：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-gain-validation-20261021/runtime-bootstrap-fix-20261021/preflight-independent-audit.json`。复核了请求与冻结体一致、只记1次API、原预算起点/截止未变、失败后关闭和拒绝开发、临时唤醒状态释放。352个本轮档案文件中未发现实际密钥值，检查不输出或记录密钥。

等待响应头超时不能区分网络链路、代理、服务端排队或模型处理延迟；也不能证明密钥无效、模型无权限、Responses不兼容或Region数学设计失败。服务端认证、回复契约、模型可用性和新版Region增益均尚未验证。没有原始响应，不能推断服务商是否已完成计费或生成。

本轮没有新增产品源码、参数、Prompt、模型、测试或数据变更，未再次运行pytest。884/884、退出0是此前修复版完整软件回归的证据，不是本次真实API预检通过数；本次预检失败，Level2/3或增益验收均未推进。

按用户批准的“预检失败即停、不重试”协议，本次试验关闭。未用API/DFN上限不自动放行新的请求或恢复BO。后续如要区分延迟与协议问题，应另行明确最小诊断的请求体、时限、次数和停止条件；不能直接重复当前BO试验，也不为追求阳性修改Region公式、守卫、种子或目标尺度。
