# Sub2API Responses transport design

状态：用户已批准本规格/计划的软件实施；本文件不批准真实 API、DFN 或 BO。2026-10-21 用户明确选择“将它用于 LLMBO 的新 API 端点”。

## 范围与来源

沿用电热 4E+2T、多目标算法、动态证据及区域 ID 目录，只增加电热 schema v2 的 HTTP Responses 适配。设计基线 HEAD 为 `4a2baca273d5cc132340000f16da5ec7bba9ddcc`，已有 Chat 流程及旧封存档案保持。主工程、参考工程和用户的 Codex 全局配置不修改。

用户提供的目标连接：base URL `https://sidrune.ai/v1`；模型必须保持 `deepseek-v4-pro`；鉴权只使用 `SUB2API_API_KEY`。按其 `wire_api="responses"`，项目 POST 目标为 `https://sidrune.ai/v1/responses`。新站可用性、模型权限及协议细节尚未通过网络确认。

规划阶段仅编写规格与计划；按用户此前审批流程，收到“批准软件适配与本地测试”后已进入软件实现。软件实现额度仍为真实 API 0、DFN 0；模型发现、鉴权测试及后续 BO 均另行明确预算。

## 项目配置映射

电热 `llm` 增加可选 `transport`，缺省解释为现有 `openai_chat_completions`，不回填旧配置、不改变旧配置摘要；新枚举 `openai_responses` 只在 schema v2 使用。未知枚举必须拒绝，schema v1 不新增此枚举。

项目片段（软件适配已实现；下列禁用设置不授权真实调用）：

```json
{
  "enabled": false,
  "transport": "openai_responses",
  "endpoint": "https://sidrune.ai/v1/responses",
  "api_key_env": "SUB2API_API_KEY",
  "model": "deepseek-v4-pro",
  "max_tokens": 1536,
  "timeout_s": 30.0,
  "json_mode": true,
  "region_wire_format": "compact_v1"
}
```

`max_tokens` 保持项目字段名，在 Responses 线上映射成 `max_output_tokens`，范围和任务级上限仍按原校验。`enabled=false`、API/DFN 预算 0 保持模板不发生真实调用；执行实验需要独立的获批运行配置。

Codex 的 `review_model`、`requires_openai_auth`、`supports_websockets`、`model_catalog_url` 和 `features` 不直接导入项目 schema。这里的 `model` 是 LLM 模型，不是 PyBaMM 的物理模型 provider。固定使用用户指定模型，不自动访问 `/models`、切换模型或回退到旧站。用户的 `disable_response_storage=true` 映射到请求中的固定 `store=false`；本地审计归档仍保留。第三方是否保存服务日志不能据此断言。

## Responses 请求与严格返回

新传输重用现有 `HttpJsonTransport` 的 HTTPS、无重定向、环境密钥、1 MiB 限制和脱敏；不新增 SDK 或依赖。

构造请求：`model` 原值；`instructions` 为当前版本 Prompt 加现有 JSON 模式提醒；`input` 为排除 instructions 的原 wire payload 的 JSON 文本；`max_output_tokens` 为本次冻结上限；`text.format={"type":"json_object"}`（仅 json_mode=true）；固定 `stream=false`、`store=false`。不启用工具、会话续接、previous_response_id、WebSocket、自动模型发现或任何重试。Region compact 的 request_id/proposal_binding/catalog_digest 算法不变。

未取得新站 thinking 扩展的证据，不把旧 Chat 的 `thinking=disabled` 静默翻译成 Responses 参数。首版 Responses 禁止显式 global/task thinking 设置，发请求前报配置错误；未设置时不发送 thinking/reasoning 扩展，也不宣称已关闭推理。任务 tokens 上限包含服务端推理耗用时，未完成输出仍按失败处理。

只接受 `status="completed"`、无 error/incomplete_details、恰好一个已完成的 assistant message、恰好一个非空 `output_text` 内容。允许其他 `reasoning` output item，但不将其解释为答案、证据或 JSON；不支持未知 output item、工具调用、refusal、多 assistant message、多文本片段、截断、排队、失败、空输出、非对象或非法 JSON。解析后的对象继续通过现有 WarmStart 或 Region 严格封套。不能从 choices、顶层便利 output_text 或 reasoning 文本补救 Responses 的缺失正式答案。

完成摘要保留真实 response_status，不能把 Responses 归档改写成 Chat choices/finish_reason。input_tokens/output_tokens/total_tokens 及 output_tokens_details.reasoning_tokens 只接受真实非负整数；缺失记 unknown，不推断为 0。已有 Chat 摘要格式不变。

## 监督、审计与兼容

沿用本次已有历史预算、请求预留、单次 owned-process 硬截止和运行总截止。每次已发请求只记一次成本；失败不重试、不偷偷走 Chat 或旧站。密钥不可进入配置、源码、参数、日志或快照，不向 sidrune 转发旧 vsllm 密钥。

Controller 仅按新配置选择传输。禁用 LLM 或 API 额度为 0 时，任何 factory、HTTP 和模型发现均不触发。新 endpoint/model/transport 进入现有配置与算法签名；不重签旧评价/初始化以伪装新源码，旧缓存校验不放宽。

审计从配置和冻结 payload 重建最终 Responses 请求，核对 endpoint/model/请求 controls/store=false/instructions/input，然后独立解析原始 HTTP response、正式 JSON、compact 绑定、目录 ID/none、resolution、监督诊断和成本。失败回复也必须重放，不能只审计成功结果。旧 Chat 档案继续按旧协议读取，不凭 raw response 的外形猜测传输。

Responses 的 payload、outcome 与请求成本必须逐次覆盖；存在原始回复时，完成摘要为必需证据，不能通过删除摘要绕过核验。WarmStart 按请求及事件顺序关联正式候选、无效候选筛选、重复候选缓存、评价参数和预算计数；只有完整目标对进入既有选择池。bounds 的 full/compact 回复均与实际轮次使用的规范区域关联。缺少专用密钥的跳过不产生请求或成本，仍可审计；不为审计读取历史密钥值。启用连接的 endpoint、model、api_key_env 必须先通过非空字符串校验。

新传输不能影响真实 Y、GP 标签/后验、EI、Lift、fair guard、信任更新、参数或工况。相同正式 JSON 在两个协议下应得到相同 canonical proposal 和 Region 数值行为。

## 验收和边界

软件验收：新 serializer/parser、spawn 监督、密钥与禁用边界、配置隔离、两任务/三模式 mock 闭环、成功与失败篡改审计、旧档案只读重放和全量回归。先新基线，逐任务 RED→GREEN；记录实际数量、退出码、日志和 JUnit，不引用上轮 669 作为新结果。

真实 API 验收：专用密钥就绪、另行获批明确预算后执行冻结请求；可以合法返回 none。本站 API 请求数当前为 0，可用性仍未验证。

真实 DFN/实测验收不属于此传输改动。更换服务、模型或协议不构成 Region 的 RMSE/HV 增益证据。后续比较需新签名、共享初始化和独立预算，保留全部正负结果。

## 官方协议资料（2026-10-21 已读取）

- [OpenAI Docs：迁移到 Responses](https://developers.openai.com/api/docs/guides/migrate-to-responses)：两种协议的请求/回复结构不同，store=false 和结构化输出字段需对应迁移。
- [OpenAI Docs：JSON mode](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses)：Responses 使用 text.format；JSON 模式本身不能替代应用 schema 校验。

资料仅支撑客户端目标协议，不证明第三方网关已实现相同行为。

软件验收已完成：受测产品提交52b9813，全量781/781、失败/错误/跳过0、退出0；真实API/DFN0。完整正负结果、审阅修复及边界见本轮sub2api-responses审计。本站真实兼容性仍未验证。
