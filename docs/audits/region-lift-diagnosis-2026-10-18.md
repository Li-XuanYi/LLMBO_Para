# Region-Lift 失效分析与工程修复（2026-10-18）

本轮针对用户要求“分析 RegionLift 不起作用的原因并优化”，复用独立工作树与 `codex/electrothermal-mo-20261016` 分支，基线 `6253ded`。原电压任务、实测数据、旧 3C、参考工程及历史实验全部保留。新付费 API 请求与 DFN 求解预算均为零。

## 结论及证据边界

旧实验 20 轮 Region 采纳为 0，主要原因是 **19 次请求传输失败**，另一次是合理的低置信度回退。这组结果不能验证 Region-Lift 能否改善 RMSE，也不能归因于均值调整公式失效。

| 实际情况 | 次数 | 解释 |
|---|---:|---|
| 读超时 | 15 | 约 30 秒；具体供应商瓶颈未知 |
| HTTP 400 | 1 | 开启 JSON 模式，但消息未出现 JSON 字样，供应商明确拒绝 |
| 连接中断 | 1 | 整体耗时 92.78 秒，原 socket timeout 未构成整体硬截止 |
| TLS EOF | 2 | 连接错误，不是热模型或目标评价失败 |
| 有效结构化建议 | 1 | confidence=0.5，低于既有 0.6 门槛，正常拒绝 |

唯一建议的区域只包含当轮 384 个候选中的 1 个，该点原 EI 为 0，plain EI 最优值约 0.16595。离线只把置信度改为 0.6/0.8/1.0，选点仍为 `same_as_plain`；降低门槛解决不了这一次问题。供应商对 G_th 的文字解释约为 0.08–0.16 W/K，实际归一化边界按 log10 反变换约为 0.0516–0.0887 W/K。代码不从自由文本偷偷改写边界。

补充直接反事实检查：保持真实回复 confidence=0.5，只在独立离线调用中临时把门槛设为0.5，仍选择 plain index=51、`same_as_plain`。生产配置仍为0.6；此检查没有改动回复、历史实验或优化观测。见 `region-lift-repair/low-confidence-counterfactual.json`。

原 20 轮 GP 标签、后验均值、标准差、Gaussian EI 与冻结上下文一致；抽样协方差对角线与预测方差的最大差约 2.5e-16。32 个人工离线区域中 1 个可在原守卫下改变选点，证明采纳路径可达。人工区域不是 LLM 回复，未产生新观测，不能作为物理 RMSE 增益。

## 实现变更

| 文件/接口 | 行为 |
|---|---|
| `llm.ChatCompletionsTransport.post` | JSON 模式在最终 system message 明确要求一个 JSON 对象；关闭该模式时不追加。解析错误使用每次请求唯一 artifact 名。 |
| `electrothermal_requests.request_controls` | v2 可选 `llm.task_options`，只允许两个电热任务及 timeout_s/max_tokens；继承但不超过全局上限，拒绝非有限值、布尔伪数、未知字段。 |
| `BoundedChatCompletionsTransport.post` | 受控 spawn 子进程执行一次真实 Chat 请求；硬截止为任务限制与剩余运行时间的较小值；只终止本次 worker，不重试。凭据仅通过环境继承，不写文件或命令参数。 |
| `ElectrothermalLLMController.request` | 每次按任务解析限制，隔离 WarmStart/Region 设置及归档目录；记录实际请求结果和分类。generic 注入明确标识不具备硬截止保证；默认和已知 Chat 注入走监督路径。 |
| `build_electrothermal_payload` | Region 历史为冻结 scalar top4、双目标极值、recent3 的稳定去重并集，最多 9 条。当前 incumbent 首位；新增计算好的归一化坐标、明确 linear/log10 公式及当轮 scalar_g。部分结果为 null 并保留诊断，不伪造目标。 |
| 英文 Region prompt | 按真实双目标与当前权重判断区域，使用明确坐标，诚实置信或弃权。未增加新的目标、核或物理模型。 |
| `MOOptimizer.step` / `apply_electrothermal_region` | ordinal>=active_until 不请求；记录 inactive 标记。宽度比较增加 1e-12 浮点容差，避免合法 .30-.27 被误拒。 |
| `MOOptimizer.summary` / `audit_electrothermal_run` | 分开统计请求尝试、响应、失败、采纳、各类回退；关联独立 outcome、payload、context 与成本事件，支持篡改检测和重放。 |

请求类别包括 timeout、deadline_exceeded、http_error、transport_error、protocol_error、configuration_error、worker_error。它们与 low_confidence、same_as_plain、outside_region 等数值判断分开记录。HTTP 已启动表示本地请求尝试进入传输层，不等价于供应商已计费；未知用量不补零。

原标准化、GP 训练标签、后验方差、协方差公式、EI、信任更新、置信度阈值、EI-gap/sigma 守卫和有界均值调整公式不变。完整 Y 与完整历史仍归档。旧六维语义、源签名与缓存校验未放宽；旧记录缺少新 outcome 时保留原回退优先次序。

历史截断的 incumbent 遗漏风险由构造的确定测试证实；实际这 20 轮原请求已经包含 incumbent，不能把这一风险写成该次运行的原因。对同一 20 轮输入的纯序列化比较：总字节数 366348→324661，约减少 11.4%，各轮 5–9 条历史且 incumbent 首位。载荷减少没有证明超时减少。

## 配置使用

旧 v2 配置不写 task_options 时继续继承全局值；schema1 仍由旧校验与流程处理。可在下一次获批实验的新配置中显式写入，例如：

```json
{
  "timeout_s": 120,
  "max_tokens": 4096,
  "task_options": {
    "warm_start_electrothermal": {"timeout_s": 120, "max_tokens": 4096},
    "region_preference_electrothermal": {"timeout_s": 30, "max_tokens": 1536}
  }
}
```

以上只是 `llm` 内的限制示例，不是启用许可。enabled、请求次数、运行墙钟与求解预算仍须单独明确；没有自动增加既有配置的超时、调用次数或费用。剩余运行时间不足时进一步缩短请求。

## 验证与审计证据

证据根目录：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation`。每个测试目录含 `pytest.log`、`junit.xml`、`result.json`、`exit-code.txt`。

| 本轮实际运行 | 结果 | 退出码 | 目录 |
|---|---|---:|---|
| 修复前完整基线 | 314/314，通过；失败/错误/跳过 0；539.14 秒 | 0 | `tests/region-repair-baseline-1018144554823188` |
| 修复后针对性回归 | 78/78，通过；失败/错误/跳过 0；106.82 秒 | 0 | `tests/region-repair-targeted-final-1018150334042689` |
| 修复后全量回归 | 357/357，通过；失败/错误/跳过 0；609.94 秒 | 0 | `tests/region-repair-full-1018152538578836` |

TDD 失败证据全部保留：JSON wire 1/2 失败、数值边界 2/2 失败、请求/载荷首轮 10/25 失败、修正夹具后的旧 payload 3/3 失败、独立 outcome/summary 3/7 失败、注入任务限制 1/1 失败。首轮针对性测试 49 通过/3 失败，其中 3 项是新夹具的浮点同分问题，已修正后在旧实现重新观察到真正的行为失败，不计作既有产品故障。

覆盖真实 spawn 监督与本地伪 HTTP：成功与脱敏、HTTP 400、HTTP 200 内外层畸形 JSON、缺凭据不 spawn、已开始 read 后整体硬截止、无孤儿 worker、任务参数隔离；覆盖真实 GP/冻结标签和归档审计。软件替身不是电热物理验证。

新增43项测试已纳入完整357项回归。上述三组通过回归的网络尝试与电池求解均为0；基线和全量分别允许旧测试中的2次非电池eSOH代数求解，不计作DFN验证。最终英文Region prompt为253词。

更详细的只读证据位于 `region-lift-repair/transport-forensics.json`、`numeric/replay-results.json`、`payload-comparison.json` 和 `baseline-payload-source.json`。`region-lift-repair/verification-index.json` 提供各次实际结果、日志/JUnit绝对路径、变更文件哈希、Git与限制；API与电池求解调用均为0。

旧 Full 与普通 BO 两组归档均由新审计器只读复核通过（`deep=false`，使用归档 GP 状态而非重新优化超参数），包括源/数据/协议指纹、曲线独立重算 RMSE、成本、冻结上下文、Gaussian EI/Region、Pareto/HV。见 `region-lift-repair/old-archive-audits.json`。这是兼容性检查，不是新一轮真实 DFN 求解。

主工程保护检查确认 HEAD=811c4c6、索引与 Method 未变，123 个受保护产品文件哈希无变化。Git status 字符串仅因先前未跟踪目录 `gp-t-212714/` 的既有访问权限问题而少一行；没有新增状态项，未更改该目录权限或删除文件。见 `workspace-protection-result.json`。

## 尚未验证及下一步最小实验

本轮只完成工程修复与软件验证，未验证供应商恢复、真实建议的采纳率或物理 RMSE 增益，未新增 DFN 验证或实测辨识。旧请求额度已用尽、旧墙钟已结束，不能续跑旧实验。

下一步可另行审批不含 DFN 的小额 API 核验：用冻结历史发送有限 Region 请求，逐项核对请求成功、契约、归一化区域、数值守卫与实际用量；每次无重试、显式独立墙钟。之后若批准真实 DFN 消融，WarmStart-only 与 Full 必须共享同一份经验证初始化计划、数据、尺度、权重顺序与数值预算，报告两项 RMSE、HV、采纳率及全部失败成本。单次测试不能证明 LLM 有效或参数唯一可辨识。
