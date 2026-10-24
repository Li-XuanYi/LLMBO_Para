# Region 传输修复与分阶段验证：2026-10-24

诊断、审计和软件发布检查的缺陷已修复，完整软件回归通过；**真实完整 Region 回复仍超时，尚未确认实际 tilt，本轮未启动 DFN 或 RMSE/HV 配对。** 不将软件通过、小请求成功或回退数值闭环写成 Region 增益。

## 执行身份与范围

- 分支：`codex/electrothermal-mo-20261016`；独立工作树：`C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`。
- 用户批准计划 `b204050bced0328fd743eb50fe3c7f35b1657aca`；实现提交 `9b01a15`、`e03f058`，一次独立审阅修复 `4b6842d99053e87161ee76df9aaa57242404d4b8`。
- 实际受测科学源码指纹：`d181b386ea2fec4600a918caaa638ad4c020c926cbd53c827b071562751264c1`。
- 冻结入口：证据根 `runtime/7aebaff6f904380f/run_region_transport_validation.py`；该入口 SHA256 `ff57bae617668a23d786c4abe788b4b426e1c0b48eedb1d9558cd632d017ed46`。
- 证据根 E：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/api-transport-repair-20261024`。
- 新真实记录：`D:/Users/aa133/Desktop/LLMBO_Para/runs/t24r`。旧 `runs/g23r` 和旧 seal 保留。
- 端点 `https://sidrune.ai/v1/responses`、模型 `deepseek-v4-pro`；凭据只从专用环境读取，不入命令、代码或归档。未修改 Codex 配置、系统代理、证书校验、Prompt、GP/EI/Region 公式或热模型。

## 软件实现与接口

| 文件 | 接口及变化 |
|---|---|
| `src/llmbo_para/http_diagnostics.py` | 新增 `transport_error_fields`、`public_network_diagnostic`：最多四层有界异常解包，固定枚举及有限整数，不保存异常文本；未知内部异常保留 unknown。 |
| `src/llmbo_para/llm.py` | HTTP 异常归档前提取安全机器原因。请求 body 和 HTTPS 行为不改。 |
| `src/llmbo_para/electrothermal_requests.py` | 监督结果保留合法机器字段；硬截止只继承已开始请求的实际已归档原因，不继承无关旧错误。 |
| `src/llmbo_para/electrothermal_llm.py` | controller/outcome 保留同份安全字段。真实标签、原方差和数学实现不改。 |
| `src/llmbo_para/electrothermal_audit.py` | 独立比较 HTTP error／supervision／outcome；按已验证源码能力区分新证据与旧记录；篡改、全删和错误类型均被发现。 |
| `scripts/run_region_transport_validation.py` | 新独立 dry-run 默认入口；持久总账、阶段门槛、一次受控重放、跨 Full 臂连续失败停止、源码/输入/共享初始化绑定、owned-tree 清理。全量结果必须绑定实际受测的运行入口。 |
| `tests/test_http_diagnostics.py`、`tests/test_network_diagnostic_audit.py`、`tests/test_region_transport_validation.py` | 新增安全字段、真实离线 worker、篡改、预算、门槛、冻结 GP/EI、原生 mock 20轮、共享初始化与受测入口漂移覆盖。 |

计划允许等价测试组织，故新覆盖集中在上述三份职责清楚的测试中，没有向旧测试堆入重复覆盖。旧六维缓存／回复校验未放宽，旧电压接口保留；全量旧测试通过是软件兼容证据，不是新物理或实测验证。

## 本轮真实软件结果

| 运行 | 数量 | 通过 | 失败 | 错误 | 跳过 | 退出码 |
|---|---:|---:|---:|---:|---:|---:|
| 新基线 `ge-net-baseline` | 1205 | 1204 | 1 | 0 | 0 | 1 |
| 同源码失败节点单独复跑 `ge-net-baseline-repro` | 1 | 1 | 0 | 0 | 0 | 0 |
| 最终审阅复现 `ge-net-review-red` | 11 | 6 | 5 | 0 | 0 | 1 |
| 最终针对性验收 `ge-net-review-final-targeted` | 131 | 131 | 0 | 0 | 0 | 0 |
| **最终完整回归 `ge-net-final-full-r1`** | **1336** | **1336** | **0** | **0** | **0** | **0** |

基线失败为既有 `test_genuine_pre_response_failures_need_no_formal_reply[invalid_http_json-chat]` 的 60秒软件 fixture 截止耗尽。该节点在未修改源码时独立通过，最终完整回归也通过；归为既有时间敏感 fixture／运行条件问题，不隐藏基线负结果，不改变产品截止以绕过。

最终 pytest 1847.69秒，守卫总耗时1855.99秒；网络尝试0、电池 solve0，两次已允许的非电池 fixture 调用。源码、受保护文件及冻结入口在全程不变；测试前后观察被写入真实结果，并由发布检查精确匹配，不用旧绿色结果放行新启动器。

最终证据：

- 日志：E`/tests/ge-net-final-full-r1/pytest.log`。
- JUnit：E`/tests/ge-net-final-full-r1/junit.xml`。
- 实际结果与退出码：同目录 `result.json`、`exit-code.txt`。
- 软件所有正负运行索引：E`/software-results.csv`，不把重复运行数量累计为独立测试数量。
- 独立审阅与逐项裁定：E`/final-review.md`。两项 Important 均经 RED→GREEN 修复；没有 Critical、Minor 或第二次审阅。

三份旧真实归档的深审计通过；独立审计按历史 sweeps 重新拟合了60次 GP，这是验证成本，不是 BO/DFN；冻结 Region 生效重放使用 `from_state`，不搜索超参数。最初辅助脚本把深审计搜索数误断言为0，已纠正脚本并记录实际成本，没有改产品规避。

## 真实 API 的实际结果

获批独立上限256 DFN／66 API／10800秒，诊断阶段最多6 API／900秒。实际窗口北京时间 **14:34:26—14:37:44**，本轮实际 **3 API／0 DFN／0 BO轮**。受控重放机会已用，诊断门槛未过后窗口按协议关闭；剩余上限不等于允许继续请求。

|阶段|请求|截止|实际耗时|结果|
|---|---|---:|---:|---|
|d0|最小 Responses JSON|60秒|8.797秒|HTTP200、`completed`、JSON完整|
|d1|第一个完整历史 Region|60秒|60.016秒|`deadline_exceeded`，`awaiting_headers`，无HTTP状态|
|d2|同一冻结请求唯一受控重放|120秒|120.031秒|同样等待响应头超时，无完整回复|

d0 实际 usage 为输入358、输出26、合计384 tokens。d1/d2 没有收到回复，实际 usage 为 unknown；三次都允许最多8192输出 tokens，不能把许可上限当成实际消耗。

两个完整请求的 body 字典完全一致，规范化 SHA256 均为 `c7e79c55aee432a5617fc76741da48b36d3ff71a52e500a404a9706161e1e7f1`；唯一改变是本地等待上限。每个完整 body 按原 JSON 编码为26304字节，input为21787字节；最小 body为538字节。按规范化字段计，history为15532字节，其中动态残差字段值累计9820字节。详细分解在 E`/final-integrity.json`。

这证明小请求的模型／鉴权／Responses 通路在本次可用，以及当前完整请求在60/120秒内均未收到响应头。**不能据此定位为 Token 不够、LLM拒绝、JSON解析错误、Region公式失效，或确定哪个网络/服务组件阻塞。** `awaiting_headers` 是请求开始后的粗粒度阶段，不证明该次连接已完成握手；没有收到 HTTP头／正文，无法区分连接握手、服务排队、生成延迟、代理缓冲等原因。历史快速 URLError 的内层原因也不能被本次超时反向重构。

独立总账在第一次实际 API 前启动，失败请求仍计账。三份 supervisor 均确认 owned tree 停止，保持唤醒的租约已释放。HTTP档省略或脱敏鉴权值，密钥未归档。进程最终退出码1，属于真实诊断门槛失败，不是1336项软件回归失败。

## Region 与增益结论

三个完整上下文／至少一个非零 tilt 的门槛没有达到；实际没有可解析 Region、没有真实 API tilt 验证、没有新求解或配对优化。因此 **本轮 RMSE/HV 增益不可用**，不复用旧值冒充新结果，不为制造结果运行 Plain 回退或耗尽余量。

未执行的后续协议仍为0.5C/1C、60秒、八点重新评价和三种子 Plain／Full 各20轮；旧3C、实测辨识与服务器任务均未运行。没有对热参数唯一可辨识、LLM有效或实测效果作新结论。

## 后续最小修复方向（未实施、未获真实执行授权）

先针对完整请求的延迟定位，不改 Region 数学。可优先审阅一个紧凑 LLM 请求视图：保留完整真实历史在本地 GP/归档，只向 LLM 提供有明确单位的关键残差摘要，减少重复历史字段，保留参数、权重、尺度、Pareto与绑定。现有字节分解说明它值得验证，但尚不能证明输入长度导致超时；不得直接删除残差信息、改签旧请求或宣称压缩有效。

若仍需识别“等待生成”与“等待传输”，应另外核实端点是否支持带严格总截止的流式 Responses，再审阅独立诊断设计；流式首块不等于完整合法回复。本轮按批准约定保持 `stream=false`，没有加入未经验证的供应商字段、改代理、关闭证书校验或延长到120秒以上。

新配置／Prompt视图或传输设计需要按既定审批流程形成具体计划；本次没有自动恢复、替换模型、扩大预算或回退无关工程整理。

## 保护与封存

主工程124项、参考工程55项保护清单及主工程 HEAD/status/index 均与轮前一致。旧交付 seal SHA256 `11caf15ae045ea26d95c4afbc39f68c0b2f7d1865b8183c512a82ee94db1c45c` 下2751个文件再次逐一验证不变。当前科学源码与完整回归结果一致。

E`/final-integrity.json`、`summary.json`、`trial-analysis.json`、`budget-journal.jsonl`、`execution-exit.json` 和 `supervision/` 保存实际结果；最终交付清单 `delivery-seal.json` 独立生成，排除自身。保留主工程用户修改、旧记录、当前工作树和本轮全部正负证据，不合并、不推送、不清理。
