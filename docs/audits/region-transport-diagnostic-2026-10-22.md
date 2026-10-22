# Region API 超时后的最小诊断准备

本轮重新核查独立工作树：开始时 HEAD 为 5827ab2，工作区干净，仍在 codex/electrothermal-mo-20261016。产品源码指纹保持 a98cc1890ea99d4fca5b4b9a9cd53be7b6f97cac16128ac502bd35c7349bcc90。没有修改算法、Prompt、模型、物性、实验数据或旧配置。

## 已知结果与本地线索

上一真实预检在等待响应头时超过 30 秒，没有 HTTP 状态或响应正文；原协议明确“预检失败即停、不重试”。原日志仍为四条事件，计数 API 1 / DFN 0、关闭状态不变；北京时间 2026-10-22 00:45:52 的原总截止已经过去。未用次数不代表可以重新开始请求或继续 BO。

当前进程未设置 HTTP_PROXY、HTTPS_PROXY、ALL_PROXY、NO_PROXY。生产传输使用 urllib.request.build_opener(NoRedirect())，默认代理处理仍从 Windows 系统设置解析出 http/https/ftp 代理 127.0.0.1:7897。该端口当前由 verge-mihomo 监听。本地检查没有发送外部请求，没有变更代理设置。这说明实际链路包含本机代理，不能证明代理失效，也不能区分代理、上游排队和模型生成时延。

## 待批准的独立诊断

准备目录：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-transport-diagnostic-20261022/`。

机器可读规格为 protocol.json，SHA-256 为 eec425cdea87e9dab1cf59276eb72d585086b0baa3f9462b8d30ac92492ebe44；approved_by_user=false。本次仅提交协议和冻结请求材料，尚未启动新的运行入口或真实请求。

| 项目 | 约束 |
|---|---|
| 独立总上限 | API 最多 2 次，DFN 0，BO 0，GP 拟合 0，总墙钟 210 秒 |
| 端点 / 模型 | https://sidrune.ai/v1/responses / deepseek-v4-pro |
| 认证 | 仅从 SUB2API_API_KEY 读取；密钥不进入文件或命令参数 |
| 网络路径 | 保持当前 urllib 系统代理；不绕过代理，不更换端点，不列举模型 |
| 共同请求设置 | Responses，stream=false，store=false，JSON object，1536 输出 tokens，不添加未经确认的 thinking 字段 |
| 第一步 | 442 字节的最小请求，只要求返回 {"ok":true}；单次 60 秒，外层最多 75 秒 |
| 第二步 | 仅第一步完整通过后发送原冻结 Region 请求；规范化请求体 58186 字节；单次 120 秒，外层最多 135 秒 |
| 停止条件 | 任一步失败立即停止；无论整体成功或失败均不继续 DFN 或 BO；传输重试 0 |
| 旧试验 | 不修改旧日志，不重置旧计数或截止，不恢复旧试验 |

最小请求须实际收到 HTTP 200、正式 Responses completed 消息，并严格解码为 {"ok":true}，同时核对原始归档与解析结果。完整请求须额外通过既有请求绑定、区域目录和证据校验；合法 kind=none 属于契约通过，不是 Region 有增益。

每次请求在派发前保守记账，失败和崩溃不退还次数；另行记录实际 HTTP 开始事件。归档保留阶段耗时、状态码、正式回复或失败、监督进程退出结果。缺失 usage/费用保持 unknown。

这两次请求的长度与超时不同，结果只能缩小连通性、协议和处理时延的排查范围，不能作为代理或请求长度影响的因果比较。最小请求通过不能替代 Region 契约通过；两者通过也不能替代配对消融或增益验证。

## 本轮离线核验

offline-preparation-audit.json 记录：最小请求小于 1 KB，完整 Region 请求与旧冻结请求严格一致；产品源码、主工作区受保护文件和旧预算日志均未改变；专用用户环境变量存在，新材料未包含实际密钥。准备时显式阻断 socket/urllib 外部连接，新增 API / DFN / BO 均为 0。preparation-seal.json 记录本次材料的文件哈希。

首次材料生成命令因误将 canonical_json 返回的 bytes 再作 encode 而退出 1，尚未写入请求材料；改为直接 len 后，第二次命令退出 0。该本地准备错误保存在 preparation-attempt-1.json，不属于 API 失败或产品回归。没有新增产品或测试代码，本轮未运行 pytest；此前 884 项回归属于上一修复版证据，不记为本轮测试通过数。没有新的 RMSE、HV、Pareto 或物理验证结果。

本地材料和离线核验已经完成。新的真实诊断需得到上述有限次数与时限批准，原因来自用户先前批准的“预检失败即停、不重试”运行约定及原截止已经到期。
