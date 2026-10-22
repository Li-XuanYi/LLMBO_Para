# Region 输出额度提高到 8192：真实单次验证

用户在 1536-token 诊断后明确要求提高准许额度。本轮选用现有代码已经允许的 8192 输出 tokens，并提前说明只重放一次完整 Region 请求：120 秒请求上限、150 秒外层上限、API 1、DFN/BO/GP 均为 0、不重试。没有将该请求扩展为新的 BO 或恢复已关闭的旧试验。

## 实际修改与结果

本次只在独立验证请求中将 max_output_tokens 从 1536 改为 8192。原始 payload、Prompt、模型、端点、代理、compact_v1、JSON object、stream=false、store=false、120 秒请求时限均保持不变。产品源码、默认配置、冻结实验配置和旧缓存没有改写。

| 项目 | 1536-token 原诊断 | 8192-token 本次验证 |
|---|---|---|
| HTTP | 200 | 200 |
| 请求耗时 | 24.906 秒 | 103.094 秒 |
| Responses 状态 | incomplete | completed |
| 未完成原因 | max_output_tokens | 无 |
| 正式回答 | 非 JSON | 有效 JSON，850 字符 |
| input tokens | 28199 | 28199 |
| output tokens | 1536 | 8192 |
| 紧凑请求绑定 | 未完成，未进入该层校验 | 通过 |
| Region 最终准入 | 否 | 否：reason 417 字符超过 400 |

因此，1536-token 上限确实触发了此前的截断，提高后这一次已生成完整 JSON。当前仍不能称 Region 契约整体通过：正式 JSON 的 reason 长度为 417，超过原契约 maxLength=400，严格解析器继续正确拒绝。没有把传输完成写成优化成功。

服务商报告本次 input/output/total tokens 为 28199/8192/36391。缺失 reasoning token 明细，不能从正式回答只有 850 字符反推其余 tokens 的用途，也不能仅因 output_tokens 恰等于上限就否定服务端报告的 completed 状态。费用仍未知。单次结果不证明 8192 对所有后续请求都足够或稳定。

## 剩余拒绝条件的离线隔离

原始回复与 compact 请求绑定一致，恢复后的 envelope 与原始正式 JSON 一致。对独立内存副本，仅将 reason 换成一个短的诊断占位说明，现有 resolve_catalog_region 就能完成目录、证据、边界和身份校验。这只用于定位拒绝条件，不是接受经修补的真实回复。

原始 HTTP 回复文件、完整正式回答和真实失败状态保持不变。副本结果没有进入运行结果、GP、缓存或 Pareto 集，没有调用仿真或选点。当前源码仍严格保留 reason<=400 的契约。

下一项最小软件修复应在 Prompt 中明确要求 reason 为一句简短英文、目标不超过 200 字符，为现有 400 字符上限留余量；保留原有硬校验、绑定和失败回退。该修复尚未在本轮实现或验证。输出预算已在本次协议中显式提高，后续实验应使用新的签名配置，不能改写旧冻结配置。

## 执行、退出与审计

机器可读协议：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-output-budget-8192-20261022/protocol.json`，SHA-256 为 4175647181895be24853c426243bb15eeccd462de9bb7b4478eba9f1d4792d44。

实际 run：`runs/20261022T011455Z_0e7a9e8a962d_8b8766ec/`，位于上述协议目录内；原始请求、回复和传输监督证据位于 http/。

- 实际 HTTP 开始 1 次，API 保守记账 1 次；DFN/BO/GP/重试均为 0。
- 请求 103.094 秒，总运行 105.764 秒，没有触发外层超时；临时唤醒状态已释放。
- 传输监督状态 completed，但独立目录契约阶段失败；工作进程退出 2，PowerShell 命令退出 1，最终试验 closed=true。
- independent-audit.json 复核唯一请求字段差异、完整 JSON、绑定、reason 限长、原回复未变、旧试验未变、主工程与源码保护及实际密钥未进入档案。
- 首次协议材料生成因公开授权说明误用被凭据守卫保留的 authorization 字段名而在本地退出 1；改用 authorization_basis 后准备成功。此错误发生在 API 启动前，没有变更或绕过凭据守卫。

本轮没有产品或测试代码变更，未运行 pytest。新增证据为一次真实 API 验证及离线隔离审计，没有新 RMSE、HV、Region 增益、真实 DFN 或实测辨识结果。执行完成后已停止，没有追加请求。
