# Region 无解释动作回复：软件实现与验收（2026-10-22）

状态：获批软件实施已完成，最终完整回归通过；真实 API、DFN 与 RMSE/HV 增益尚未验证。

## 授权、工作树与版本

用户已批准计划 fb17ce58cc393cabe57e460b70f6e86dc49058da 的软件实施和本地测试。真实 API、DFN、正式 BO 和服务器任务预算均为 0。继续使用 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`，分支 `codex/electrothermal-mo-20261016`。

本轮在当前代码上重新执行完整软件基线，然后 TDD 实施两个任务。Task 1 提交 bfd71af7dd82d2279ae273090a124c703c93dc17；最终 Task 2 提交及完整显式变更清单见交付封存和 Git 历史。最终测试源码指纹为 `9fe153b49f840a8090bc9341d6c15d559d52205eecf93545a86690a41354524e`。

所有证据位于：

`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-action-reply-20261022/`

审批时的设计和计划保持原字节，避免改写历史审批封存；当前完成状态记录在本报告及 `.superpowers/sdd/2026-10-22-region-action-reply-plan/progress.md`。

## 已实现的接口与文件

| 文件 | 修改及接口 |
|---|---|
| `src/llmbo_para/electrothermal_region_wire.py` | 在现有 `region_wire_format`、`region_wire_payload`、`decode_region_wire` 中新增 `compact_action_v2`；使用独立请求绑定版本，签名不变。 |
| `src/llmbo_para/electrothermal_requests.py` | 任务传输的格式校验接纳同一显式版本，两种受监督生产 worker 继续调用统一 decoder。 |
| `src/llmbo_para/electrothermal_config.py` | 新格式仅允许既有 catalog/dynamic/candidate-aware/fair 组合，旧缺省行为不变。 |
| `src/llmbo_para/electrothermal_llm.py` | `build_electrothermal_payload` 选择独立动作 Prompt；在 proposal binding 前加入版本 marker。数值函数未变。 |
| `src/llmbo_para/llm.py` | 现有 Chat 紧凑 JSON 序列化分支接纳新版本，旧两种线上请求字节保持。 |
| `src/llmbo_para/prompts/region_preference_action_electrothermal.txt` | 独立英文 Prompt，只要求目录动作 JSON，无需解释或分析。 |
| `src/llmbo_para/electrothermal_audit.py` | `audit_electrothermal_run(..., deep=True)` 按归档版本选择 Prompt，从原始 HTTP 重建并独立核验动作与数值记录。 |
| `configs/electrothermal-sub2api-action-software-template.json` | 新禁用模板，保留旧模板物理和人工数据定义；LLM 关闭，API/DFN 预算 0。 |
| `tests/test_region_action_wire.py` | 43 个动作契约、旧字节、配置、绑定、元数据与严格校验测试。 |
| `tests/test_region_action_audit.py` | 28 个离线生产 worker、回退、深审计篡改、模板和软件路线测试。 |
| `docs/llm-informed.md` | 仅追加新模式、兼容元数据、预算与验收边界说明。 |
| 本报告 | 本轮实际结果及证据索引。 |

线上必需字段仍为 request_id 和 region。region 包括 kind、coordinate_space、confidence、proposal_binding；kind=region 还需 region_id 和 evidence_ids。reason 不再必需，Prompt 明确要求不生成解释。若仍附带 reason，在完整回复通过原生有限 JSON 校验后，仅忽略这个兼容元数据；原始 HTTP 保留。未知动作字段、旧坐标、错误证据、绑定、类型、无效 ID、截断或非 JSON 仍拒绝。

宿主补入固定接口标记 `reason=structured_catalog_response`，继续走原目录解析器及数值守卫。它不是模型解释。新模式进入配置、算法、请求和 proposal 绑定，旧回复和旧缓存不跨版本重签或自动复用。

## 实际测试结果

| 运行 | 测试/通过/失败/错误/跳过 | 退出码 | JUnit time（秒） | 日志/JUnit 所在目录 |
|---|---|---|---|---|
| action-baseline | 781/781/0/0/0 | 0 | 1437.96 | `action-baseline-1022013812538683` |
| action-wire-red | 43/6/37/0/0 | 1 | 12.86 | `action-wire-red-1022020348657308` |
| action-wire-green | 43/43/0/0/0 | 0 | 6.69 | `action-wire-green-1022020617094195` |
| action-wire-related | 225/225/0/0/0 | 0 | 169.62 | `action-wire-related-1022020703940961` |
| action-audit-red | 28/1/27/0/0 | 1 | 122.49 | `action-audit-red-1022021436295886` |
| action-audit-red-corrected | 3/2/1/0/0 | 1 | 31.20 | `action-audit-red-corrected-1022021902356394` |
| action-audit-green | 28/28/0/0/0 | 0 | 203.51 | `action-audit-green-1022022036090205` |
| action-full | 852/852/0/0/0 | 0 | 1739.06 | `action-full-1022022746906455` |

各表行目录均位于 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/`，分别含 `pytest.log`、`junit.xml`、`exit-code.txt`、`result.json`。时间列与证据索引的 elapsed_s 使用 JUnit testsuite 的 time 统计；pytest 终端的本轮全量摘要为 1697.96 秒，基线摘要为 1428.49 秒，计时范围不同，不将两者混作同一墙钟值。

最终全量：852/852 通过，失败/错误/跳过均为 0，退出码 0；网络尝试 0、电池求解尝试 0，既有非电池数学 fixture Simulation 调用 2。

表中各行是独立运行，不相加冒充一次完整回归。781 是本轮新跑基线，历史 884 不用于本次结果。

Task 1 RED 的 37 个失败对应尚未实现的新模式/标记。Task 2 首次 RED 的 27 个失败中有 2 个是新测试作者混淆文件 SHA 与嵌入语义 plan SHA；修正测试以分别校验两者后，先独立重跑三路线，观察到预期的归档 Prompt 不一致失败（1 失败、2 通过），再实施产品修改。未通过降低缓存或签名校验解决它。所有负结果保留。

每次日志、JUnit、退出码、边界计数、实际源码指纹和耗时由 `test-evidence-index.json` 索引。全量结果必须同时匹配 JUnit 与退出码。相关测试 225 项及 Task 2 的 28 项已被最终全量覆盖，不重复计数。

新增测试在生产 Chat/Responses 子进程中只替换 HTTP 边界，保留真实编码、受监督进程、超时、解析、控制器和归档路径，子进程禁止 socket。响应为人工构造，调用计为 mock，API/DFN 为 0。这是软件证据，不是真实供应商测试。全量中既有的两个非电池数学 Simulation fixture 不属于 DFN 求解，边界计数另列。

新模板 CLI `preflight` 已执行，退出码 0，`ready=true`，`paid_api_calls_made=0`；见 `cli-preflight.log` 与 `cli-preflight-exit-code.txt`。模板默认 parego、LLM disabled；8192 tokens/120 秒只是全局及 Region 请求上限，WarmStart 为 4096/120 秒，实际还受剩余运行预算限制；没有加入 provider thinking 扩展。

## 兼容、审计与独立审阅

full_v1/compact_v1 的真实请求字节摘要分别保持 `7e042560150ab4ef3bbdab980debf61d4602af1128ff5ae25af4819bfa5cce57` 和 `3f9313405f6ab97738c10212d0ed00b60019070500c2b5e5558f186fb1a0a6c4`。旧模式缺少或超长 reason 仍按旧契约拒绝。WarmStart 的请求和 Pareto＋Max–Min 规则保留。

原 GP、标签、后验方差、Lift、Gaussian EI、信任更新、候选池、公平守卫、尺度、HV、物性和热模型未修改。保护审计核对主工程 HEAD/状态/索引/源码测试配置、旧数值模块及 Prompt 字节和两个数值函数 AST。单独执行旧冻结运行器的原 `pinned()`，明确得到 `current product source is not frozen for phase`；71 个旧运行器/记录文件字节未变，API/DFN/BO 均为 0，见 `old-runtime-pin-check.json`。此兼容检查不加入完整 pytest 数量。旧闭合实验、失败和计划审批封存逐文件核对，未重标旧失败。

深审计测试分别篡改 wire、Prompt、权重、尺度、目录、原始绑定/ID/证据和 canonical 几何，均应被拒绝。兼容 reason 的缺失、417 字符及更长文本不改变规范动作。

独立只读审阅未发现 Critical/Important 问题，批准以最终全量通过为条件；见 `final-review.md`。保留一个 Minor：数值等价 fixture 尚未显式断言 accepted Region 或非零 Lift，因此不能将该对照独自作为活跃 Lift 的覆盖证明，也不能推断增益。此项作为可选测试增强延后，未改变产品行为。

## 执行裁决

1. 复用现有受控 Windows runner 和短 basetemp，建立本计划独立入口/账本；旧 runner/记录不改。风险：可能继承 runner 限制，通过边界计数和实际 JUnit 对照约束。
2. 遵守用户保留全部证据的要求，保留工作树及本计划 scratch，不执行技能默认清理。代价：占用本地存储。
3. 在忽略 reason 前检查整个回复的 JSON 原生类型及有限值，避免兼容元数据绕过校验。代价：原本也无效的非 JSON 回复继续回退。
4. 额外触及 `llm.py` 的紧凑序列化 selector，使新格式真实走紧凑编码。代价：增加一个传输文件；旧线上字节摘要测试约束回归。
5. 在源码冻结且针对性测试通过后并行进行整体只读审阅与全量回归；最终交付仍要求两项均通过。代价：审阅当时尚无全量结果，不以审阅代替全量。
6. 设计/计划保留审批时原字节，以本报告及 ledger 记录执行状态，避免破坏历史封存。代价：查看当前进度需读取交付报告。
7. 按用户既定要求保留开发分支和工作树，不执行集成或发布。代价：主工程不会自动获得本轮变更。

## 验证边界与下一步

软件接口修复、软件测试、真实 API 契约、DFN 合成增益和实测辨识分别验收。本轮未发出真实 API、未运行 DFN、未进行正式 BO；真实 provider 是否稳定按动作契约回复、耗时/截断是否改善、RMSE/HV 是否增益，均尚未验证。动作简化不压缩本轮历史或目录输入，不保证消除大输入导致的延迟。

本轮不使用旧 3C。倍率集合仍由配置及签名驱动；新模板的 0.5C/1C/2C 是人工软件 fixture，不能当作实测条件。实测仍需确认电流、温度测点及单位、初态和冷却条件。后续真实验证需独立有限预算，并保留成功与负结果；本报告不授权自动恢复任何已关闭试验。

最终保护检查、已知专用密钥缺失扫描及所有本轮证据哈希见 `protection-check.json`、`delivery-seal.json`，可使用本目录 `audit_delivery.py verify` 离线核对封存。配置和日志不包含专用密钥；测试只使用人工 fixture。
