# OpenCode API 实测记录

用户已授权使用其临时密钥做一次接口/流程测试。本轮先进行最小请求，未上传实测电池记录，未启动真实电池求解。

## 结果

接口网络可达，但当前无法完成模型生成，带真实 LLM 的优化闭环没有执行。

| 探测 | 模型 | HTTP | 服务端具体结果 |
|---|---|---:|---|
| 免费模型最小探测 | big-pickle | 403 | FreeTierError：免费层只能在 OpenCode 应用内使用 |
| 直接 API 低价模型探测 | glm-5.3-flash | 402 | Upstream request failed: Insufficient account funds |

HTTP 403 的首份自动摘要将其概括为凭证被拒，后续读取具体错误确认是免费模型使用范围限制；原摘要不覆盖，修正保存在同目录 diagnosis-followup.json。HTTP 402 明确报告上游账户余额不足，不能进一步断言是用户账户还是服务商上游账户的问题。

完成 2 次 HTTP 探测，成功模型生成 0 次，失败 2 次；当前运行 0、排队 0。完整流程未启动，无法给出真实 LLM 流程的速度或 ETA。每次仅请求 32 个最大输出 token，不自动重试；失败请求是否计费应以服务端账单为准。

## 请求与环境

- 依据 [OpenCode Zen 官方文档](https://opencode.ai/docs/zen/) 核对端点和模型；使用 HTTPS POST https://opencode.ai/zen/v1/chat/completions。
- 唯一用户消息为简短连通性测试，要求返回 JSON {"ok":true}；不包含项目源码、科研数据或电池参数建议。
- 机器 SCP，Windows；工作目录 D:\Users\aa133\Desktop\LLMBO_Para。
- 解释器 C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe，Python 3.12.10。
- 第一次沙箱内无凭证 GET /zen/v1/models 因 WinError 10013 被阻止；执行审批允许后完成上述两次 HTTP POST。未通过关闭 TLS 校验或伪装 OpenCode 客户端规避限制。
- 凭证通过隐藏交互输入，仅留在各进程内存；命令行、源码、配置和归档均不包含凭证。请求认证头不保存，服务端错误文本保存前脱敏。两个进程均已退出。

## 归档位置

- 免费模型：runs/api-probes/20261011T004258Z_92e338fd0ee7_c7c2858b/
- 普通模型：runs/api-probes/20261011T004429Z_ea3e222c9334_55aaa06a/

每个目录包含 manifest.json、源码快照、request.json、脱敏 http-error.json、probe-summary.json、terminal.json，以及诊断补充。旧运行和科研模板不改写。

执行命令：

```powershell
Set-Location "D:\Users\aa133\Desktop\LLMBO_Para"
$runPython = "C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe"
& $runPython -X utf8 -B scripts\probe_opencode.py --model big-pickle
& $runPython -X utf8 -B scripts\probe_opencode.py --model glm-5.3-flash
```

首个命令用于重现已观察到的免费层限制，余额问题解决后不应把它作为普通 API 接入路径。日常探测脚本默认已改为普通 API 模型；每次调用创建新目录，凭证可交互输入或由 LLMBO_OPENCODE_API_KEY 进程环境变量提供。

## 后续条件

先让 API 服务确认余额及上游额度，或提供另一个有效的 API base URL/模型。恢复后先重复一条最小生成，再接入聊天接口的 messages/choices 格式，运行两次 LLM 请求配合少量合成候选的闭环。

现有主框架的 structured_json_service 传输是自定义协议，不能仅把主页或聊天端点填入旧配置。余额修复后仍需增加相应格式桥接并测试；本轮没有把失败探测或 Sobol 回退冒充真实 LLM 成功。
