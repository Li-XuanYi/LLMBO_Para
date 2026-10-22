# Region API 独立诊断结果：输出限额与正式回复格式失败

用户明确批准 protocol.json（SHA-256 eec425cdea87e9dab1cf59276eb72d585086b0baa3f9462b8d30ac92492ebe44）的独立诊断：API 最多 2 次、DFN/BO/GP 均为 0、210 秒，先最小请求，通过后才发送原冻结 Region 请求，不重试，完成或失败均停止。原试验保持关闭，原截止和计数没有改变。

## 实际执行

北京时间 2026-10-22 09:07 启动，整个诊断耗时 34.563 秒，实际 HTTP 开始事件 2 次，无重试，DFN 0、BO 0、GP 拟合 0。两步均沿用 sidrune.ai/v1/responses、deepseek-v4-pro 和当前系统代理，没有绕过代理、更换模型或读取模型列表。

| 项目 | 最小请求 | 完整 Region 请求 |
|---|---|---|
| 规范化请求体 | 442 字节 | 58186 字节，与原冻结体一致 |
| 单次上限 | 60 秒 | 120 秒 |
| 受监督请求耗时 | 4.109 秒 | 24.906 秒 |
| 外层耗时 | 6.828 秒 | 27.718 秒 |
| HTTP | 200 | 200 |
| Responses 状态 | completed | incomplete |
| 正式文本 | 严格 JSON：{"ok":true} | 4583 字符，非 JSON |
| 原始未完成原因 | 无 | max_output_tokens |
| input / output tokens | 338 / 27 | 28199 / 1536 |
| 工作进程退出码 | 0 | 2 |
| 契约结果 | 通过 | unfinished_completion，拒绝 |

总体诊断状态为 failed、closed=true；脚本请求退出码 2，经 PowerShell 管道呈现为命令退出 1。没有触发外层超时，两个阶段的临时唤醒状态均已释放。

两步都通过原有受监督进程机制执行。最小探针是通用 Responses 请求，直接复用既有 _responses_request_worker 和 run_with_deadline；没有为探针放宽优化器的两个任务白名单。完整 Region 使用原 BoundedResponsesTransport 和 compact_v1，实际请求体逐字节规范化核对一致。

## 可以确定的原因

本次最小请求证明该请求下的端点、凭据、模型和正式 Responses JSON 通路可以工作。完整请求也已收到 HTTP 200，因此本次失败发生在回复内容校验阶段。服务端明确返回 incomplete、incomplete_details.reason=max_output_tokens，报告 output_tokens=1536，恰好达到批准上限；正式文本是解释性文字，没有形成 JSON。

解析器首先按 Responses 顶层未完成状态拒绝，未将解释性文字或截断内容转成有效 Region。没有区域进入 BO，也没有运行 Lift、GP 拟合或 EI 选点。因此这次不能用来判断 Region 数学公式是否正确实现或是否有优化增益。

服务商没有给出 reasoning token 明细，不能声称 1536 个 tokens 全部用于推理。两次 usage 汇总为 input 28537、output 1563、total 30100；费用未知。原始 reasoning 项的内容不用于本报告或算法输入。

本次排查缩小了问题范围，但不能推断上次 30 秒超时的唯一原因，也不能证明代理在所有请求中稳定。小请求成功不等于大请求契约有效。

## 后续修复应满足的要求

1. 先处理最终 JSON 生成问题。保持 completed、有限 JSON、请求绑定、区域目录和证据校验；不从解释性文字、截断回答或 reasoning 项中抢救 Region。
2. 对 compact 传输制定单独的软件修复方案：减少重复的历史、候选和目录描述，使用确定性映射保持完整候选目录、物理语义、冻结上下文与证据身份。当前请求仍有 28199 个输入 tokens，不能将小探针的延迟代表 Region 延迟。
3. 任何新的 wire 版本、Prompt 或输出策略须显式版本化、绑定完整原始上下文，并通过陈旧回复、篡改绑定、错误 ID 和非 JSON 的失败测试；不能放宽旧缓存签名。
4. 未确认该端点支持的 reasoning 或严格 schema 控制，不擅自增加 provider 扩展字段。单纯增加超时不能解决本次明确的 max_output_tokens 失败；增加输出上限也需要新的有限调用协议。
5. 软件修复完成后，先另行验证完整契约；只有真实请求契约稳定通过、且有独立 DFN/BO 预算时，才恢复配对增益验证。

上述为根据本次证据确定的修复要求，本轮没有实现新的 wire、Prompt、provider 控制或算法。没有新的 RMSE、HV、Pareto、物理验证或实测辨识结果。

## 审计与保留

根目录：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-transport-diagnostic-20261022/`。

- 小请求：`runs/minimal/20261022T010709Z_6ce618d860dd_df3900a8/`。
- 完整请求：`runs/region/20261022T010715Z_e8eecc95f30e_11a62bc1/`。
- 原始 HTTP 请求、回复和监督记录位于各 run 的 http/；provider 原始回复保留，没有改写未完成状态。
- approval.json、live-launch.json、逐步 reserved/result/supervisor 文件及 terminal.json 保留新授权、独立计时、保守记账和停止证据。
- independent-live-audit.json 独立核对两份请求、两次 HTTP 事件、真实 usage、严格拒绝、旧日志、源码和主工作区保护；651 个本轮文件未包含实际密钥，核验不输出密钥。

本轮没有修改产品或测试代码，没有运行 pytest。此前 884 项回归仍属于上一修复版；本次是真实 API 诊断两步中一通过、一失败。Level 2 DFN 验证、Level 3 实测验收和 Region 增益验收均未推进。
