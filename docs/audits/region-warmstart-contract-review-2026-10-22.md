# 参考 WarmStart 审阅 Region 拒绝条件

本轮根据用户“为什么会被拒绝，请参考 WarmStart 的设计”核对实际源码及上一份 8192-token 真实回复。开始时工作树干净，HEAD 为 2c638924fbd5c68ab631dcfb955a0fc57c56e3e7。未新增 API、DFN、BO、软件评价或产品代码修改。

## 拒绝发生在哪里

这次不是服务商拒绝请求，也不是 Lift、EI 或物理守卫拒绝区域。真实请求已获得 HTTP 200、Responses completed 和有效 JSON，compact request_id 及回复 envelope 也已通过。

拒绝发生在本地 electrothermal_region_catalog.resolve_catalog_region：reason 为 417 字符，超过 catalog_region_contract 规定的 maxLength=400。该判断与坐标空间、绑定、置信度类型/范围合并，抛出通用错误 invalid catalog reply binding or scalar fields。正常控制器会将这些不同错误再次合并为 invalid_catalog_response。之前独立诊断正是在此阶段退出，没有调用优化器。

现有代码按其契约拒绝是预期行为；这并不说明该契约设计合理。400 字符是工程上的解释文本限制，没有电热模型或 BO 数学依据。

## WarmStart 的实际设计

应比较当前 schema v2 的电热 WarmStart，不能把旧 schema v1 的合同修复或重试规则混入当前无重试协议。

| 层次 | 电热 WarmStart | 当前 catalog Region |
|---|---|---|
| 任务输出 | 有身份封套的 candidates，每项仅含六个具名 parameters | 有冻结请求绑定的一个 region，含 ID、证据、置信度和强制 reason |
| 身份校验 | schema/profile/fit_rates/signatures 严格匹配，额外顶层字段拒绝 | request_id、proposal_binding、context、目录与证据身份严格匹配 |
| 候选内容 | 逐项检查具名参数、范围和重复；一项失败可以记录后继续处理同批其他项 | 单条建议，一处标量或文本条件失败就拒绝整条 |
| 最终质量 | 完整真实评价对后才进入 Pareto 层级和 Max–Min 多样性筛选 | 合法动作之后还须经过原锚点、Lift、EI 和公平性守卫 |
| 说明文字 | 没有请求或要求 reason，因此不存在理由字符数阻断候选的问题 | reason 超过 400 就阻断动作，之后却将其替换为固定标记 |

WarmStart 不是“宽松 JSON 解析”。validate_warmstart_response 严格要求五个顶层字段，generate_warmstart 也严格要求每项只有 parameters。其值得复用的原则是：让 LLM 返回必要的任务数据，宿主代码负责校验、评价、筛选和构造规范结果。

## 这次暴露出的设计问题

resolve_catalog_region 通过后将 reason 写成 structured_catalog_response，后续 apply_electrothermal_region 又只使用结构化数据和固定说明标记。原解释文字的长度和措辞不参与协方差、Lift 幅度、EI、候选选点或信任更新。

因此，一段 417 字符的说明可以使其余已匹配的动作失效，属于非决策元数据与决策校验耦合过紧。仅把 Prompt 的目标长度从 400 改为 200 可以降低出错概率，但不能消除这种设计脆弱性；一味增加 token 上限同样不能解决理由长度导致的拒绝。

## 建议的契约调整

参考 WarmStart，将下一版 Region 回复分成动作数据和诊断元数据两层；这是待审的设计建议，本轮未修改运行契约。

1. 动作层继续严格检查 completed、有限 JSON、request_id、proposal_binding、冻结上下文、kind、coordinate_space、confidence、目录 region_id 和真实历史 evidence_ids。错误绑定、未知 ID、错误类型/维度、不合规置信度仍不得准入。
2. reason 不作为必需动作字段。Prompt 主要要求返回结构化动作；如保留解释，仅作为可选诊断元数据，建议一句英文且目标不超过 200 字符。超长说明保存原文并单独记录告警，不决定动作是否有效。不能忽略任意额外动作字段，也不能从非 JSON、截断正文或 reasoning 项中提取动作。
3. 原始回复不可改写。动作由宿主校验后从冻结目录映射；展示或诊断用文本不进入 GP、Lift 或 EI。诊断层与动作层的状态分别归档，避免再次只看到一个笼统的 invalid_catalog_response。
4. 采用显式的新回复策略版本；旧默认策略、旧签名和旧审计分支保持原语义。完整请求绑定必须包含新策略，旧回复不能冒充新策略回复，不能重新标记这次历史失败为成功。
5. 新策略只解决建议是否可解析，之后仍执行现有的物理锚点和数值守卫。合同可用不代表区域能改变选点，更不代表 RMSE/HV 有增益。

这项调整不需要改变 GP、后验方差、Lift 公式、目标尺度、候选池、权重调度或热模型。详细实施计划仍应按已有审批流程先提交，再修改产品代码；本轮没有自行放宽旧解析器。

## 本轮离线证据

`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-warmstart-contract-review-20261022/offline-comparison-audit.json` 保存了以下核验，命令退出 0：

- 使用软件 fixture 和零 API/求解预算构造 WarmStart 请求，确认合同没有 reason，正常具名候选封套通过；额外加入顶层 reason 仍被拒绝。
- 读取原始 8192-token 回复，确认正式 JSON 解码通过、原 reason 为 417 字符、原目录解析器拒绝。
- 对两个独立内存副本分别提供不同的简短说明，现有解析器输出的 canonical 动作和完整 resolution 逐字节规范化一致；规范 reason 固定为 structured_catalog_response。
- 原始 HTTP 回复哈希保持不变；两个假设副本均未进入实际运行、评价、GP、缓存或 Pareto。
- 核验过程中阻断 socket/urllib 连接；新增 API/DFN/BO/软件评价均为 0，没有运行 pytest。这是源码与契约隔离核验，不是新增回归通过数或增益实验。

相关源码：electrothermal_llm.py 的 build_electrothermal_payload、validate_warmstart_response、generate_warmstart；electrothermal_region_catalog.py 的 catalog_region_contract 和 resolve_catalog_region。Prompt 对比采用 warm_start_electrothermal.txt 和 region_preference_catalog_electrothermal.txt。
