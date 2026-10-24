# Region 超时：第二轮根因调查

检查起点 `83c173b2705f52f7e3529e1f80d7fdd3a3e660d7`，原独立工作树干净。沿用用户暂缓 CodeGraph 的决定，没有建索引。主工程及原方法参考目录只读；上一轮请求窗口保持关闭。

本轮完成源码、归档、官方协议核查和内存 socket 探针，**真实 API0、DFN0、BO0，产品及产品测试零修改，没有运行本轮 pytest**。历史1336项不是本轮新测试。

## 新发现：未控制默认内部推理

已确认的软件事实：`responses_request_body()` 没有生成 `reasoning`；实际成功/失败请求也均省略该字段。`ResponsesTransport` 当前拒绝 Chat 风格的 `thinking='disabled'`，配置层也拒绝 Responses thinking 映射。Prompt 的“不要解释、只返回JSON”只约束期望的最终答案，不能代替协议控制。

2026-10-24读取的 DeepSeek 官方 [Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/) 说明默认启用 thinking、默认强度 high；官方 [Responses 参数](https://api-docs.deepseek.com/api/create-response/) 提供 `reasoning.effort` 的 `none/low/high/max`，其中 none 用于关闭 thinking，输出上限同时包含可见与推理 tokens。

因此形成更具体的假说：**完整电热任务触发未受控的默认推理，非流式返回使其延迟表现为客户端截止前没有响应。** 这是待验证假说，不是 Sidrune 根因已确定。Prompt和模型内容可能同时影响延迟。

[Sidrune公开接入指南](https://docs.sidrune.ai/user-guide/getting-started) 确认 `/v1/responses` 路径，没有找到它对该模型 reasoning 字段的转发承诺。公开 Sub2API [锁定版本8fa67d4的桥接代码](https://github.com/Wei-Shaw/sub2api/blob/8fa67d477d6651a744754392a8982ea589c26ae6/backend/internal/pkg/apicompat/chatcompletions_responses_bridge.go) 也不足以证明 Sidrune 部署或 DeepSeek thinking 关闭语义；不能把公开参考实现当作本站事实。

## 工作/失败样本比较

|样本|实际发送字节|结果|
|---|---:|---|
|新最小请求|538|8.797秒，HTTP200/completed|
|旧成功Region预检|13531|47.125秒，完整合法回复|
|新完整Region|26304|60.016秒，无响应头，硬截止|
|唯一受控重放|26304|120.031秒，同样截止|

按实际 `json.dumps(body,ensure_ascii=False).encode('utf8')` 复算。四者的字段集合、模型、JSON模式、8192输出许可和stream/store=false相同；旧成功Region与失败完整请求的instructions相同，均276词。新d1/d2字典完全一致；旧正式首轮与新d1的input解析后逐字段相同，没有历史内容丢失。

旧120次失败存在时间分段：先16次60秒截止，再104次约2.015–4.656秒快速URLError。两类请求长度高度重叠：截止24436–29744B，快速错误22281–32172B。不能用长度解释所有故障，更不能用本次超时反推旧URLError的内层原因。

## 离线排查

新证据根：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-timeout-root-cause-20261024`。

`local_wire_characterization.py` 调用实际 `HttpJsonTransport`、urllib和http.client，仅将HTTPS连接替换为内存 socket，所有真实socket连接均拦截：

|请求|发送正文|Content-Length|正文逐字节一致|
|---|---:|---:|---|
|最小|538|538|是|
|完整Region|26304|26304|是|
|更大 framing探针|74234|74234|是|

探针退出0，外部网络尝试/API/DFN均0；没有TLS或真实代理验证，不是新增HTTP服务可用性证据。它未发现本地JSON截断、固定16KiB上限或Content-Length不匹配。

首次辅助探针因替换标准库全局类影响其super引用而出现TypeError；将替换点改为HTTPSHandler的连接工厂后通过。这是一次诊断脚本构造错误，不是产品失败，没有修改产品来绕过。结果见 `local-wire-characterization.json`。

## 结论与最小修复选择

已证实的修复对象是 **Responses适配缺少显式推理控制**；是否解释真实超时，需要同一完整冻结请求的“省略/none”比较。先补一个可选控制，不默认改变旧配置，不隐式翻译Chat thinking，不自动切换档位。

优先保留完整历史与当前LGBO Prompt，以免同时改变输入信息和推理模式造成混杂。压缩残差视图、SSE和更长超时均暂不叠加。若新字段不被网关支持/执行，明确记录并停止，不自动尝试low、换模型或改代理。

`awaiting_headers`仍是粗粒度状态，不能定位DNS/握手/上传/排队/生成。既没有正文，也没有usage，故Token不足、模型拒绝、JSON解析或Region公式错误都不能被当成当前超时的确定原因。

具体待审设计与计划：`../superpowers/specs/2026-10-24-responses-reasoning-control-design.md`、`../superpowers/plans/2026-10-24-responses-reasoning-control-plan.md`。产品修复及新真实预算尚未批准，不调用旧窗口余量。
