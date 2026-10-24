# Responses 推理控制修复与真实诊断

2026-10-24。批准依据为设计/计划提交 `4138597` 及用户对该具体问题的
“批准所有的API次数调用”答复；按问题中的明确上限解释为本次5API、0DFN、
0BO、720秒，不是无限调用。测试及实际执行源码提交为
`2c7ced1016d599043ac1d5baddc39ef4055a5f2f`。

**软件实现与回归通过，真实完整Region仍超时，transport_ready=false。**
没有启动DFN、BO或RMSE/HV对照，没有形成优化增益结论。

## 原因与修复边界

已证实的代码缺口是Responses请求没有显式内部推理控制，而Chat的
`thinking=disabled`不能直接用于该接口。上游DeepSeek文档描述默认thinking开启、
默认effort为high，并定义Responses原生 `reasoning.effort`；这不证明第三方网关
的转发实现。[Thinking说明](https://api-docs.deepseek.com/guides/thinking_mode/)、
[Responses协议](https://api-docs.deepseek.com/api/create-response/)。

本轮补入可选、全局、schema2/Responses限定的 `llm.reasoning_effort`，仅接受
`none/low/high/max`，映射到 `reasoning: {"effort": value}`。缺失保持旧请求，显式
null、Chat/schema1、任务级effort覆盖或混用Chat thinking均拒绝。配置是唯一
控制源，不继承注入客户端隐藏值。配置、serializer、controller、spawn、监督、
outcome和独立审计贯通；旧初始化/缓存不改签、不放宽。

原调查的538、26304、74234字节内存HTTP framing测试未发现本地截断或
Content-Length不一致；它没有测试真实TLS/代理。旧成功与失败负载长度重叠，
不能将长度单独认定为根因。新真实结果又表明：**补上none仍不足以使完整请求
在120秒内返回。** 缺少服务端阶段计时，尚不能区分代理/上传、网关排队、上游
生成等待或网关未执行none；不能称为已解决外部根因。

没有响应头或完成计量，不能把本次失败写成输出token不足、模型拒绝JSON、
Region公式缺失或方法无效。请求字段已发送不等于服务端执行；缺失reasoning
usage保持unknown，完整合法JSON不因缺失或正数usage而被拒绝。

## 实际软件测试

|验证|测试|通过|失败|错误/跳过|退出码|
|---|---:|---:|---:|---:|---:|
|本轮新基线 ge-re-baseline|1336|1336|0|0/0|0|
|控制贯通针对性 GREEN|166|166|0|0/0|0|
|审计及兼容针对性 GREEN|106|106|0|0/0|0|
|审阅修正针对性 GREEN|97|97|0|0/0|0|
|首次完整 ge-re-final-full|1433|1427|6|0/0|1|
|导入隔离修复联合 GREEN|154|154|0|0/0|0|
|最终完整 ge-re-final-full-r2|1441|1441|0|0/0|0|

针对性集合重叠，不累加为独立总数。新增三个测试文件共105项：控制31、审计17、
诊断57。各阶段均保存观察到的RED；其中两次测试构造错误也保留并明确标注，
没有当成产品缺陷。最终完整用时2179.23秒，软件网络尝试和电池solve均0；
两次允许的非电池PyBaMM测试调用与DFN分开记录。

首次完整的五项失败由本轮测试观察器提前导入模块引起：旧测试重载
`run_lgbo_real_gain`后，缓存的 `_owned_bootstrap` 不再是canonical对象，Windows
spawn发生PicklingError。修复为观察器构造后恢复模块缓存和sys.path；真实pickle
及owned进程测试覆盖该路径。另一项为既有orphan即时存活断言的一次失败，
当时监督记录为owned_tree_stopped=true；未修改旧进程管理或旧测试，单独复测和
最终完整均通过。其根因未被确定，不将其写成已修复的产品缺陷。

首次失败、旧manifest、入口、源码与测试快照均保留。第二轮使用独立r2归档；
放行检查只接受严格的匹配attempt，拒绝任意路径、部分测试、旧失败结果、
解释器/依赖漂移及源码/输入漂移。最终完整确实观察到实际入口、保护依赖和环境。

证据根：
`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-timeout-root-cause-20261024`。

- 最终日志：`tests/ge-re-final-full-r2/pytest.log`。
- 最终JUnit：`tests/ge-re-final-full-r2/junit.xml`。
- 退出码及统计：同目录`exit-code.txt`、`result.json`。
- 测前观察：同目录`manifest-before.json`和根目录`runtime-before-final-r2.json`。
- 完整放行记录：`software-release.json`；诊断前已验证通过，未使用历史绿色结果。
- 旧真实c01归档只读深审计通过，0API/DFN。深审计会重新拟合GP，不能标成仅
  from_state恢复：补充计量审计实际记录20次fit、80个超参数搜索sweep；首次同路径
  深审计另有20次fit。`legacy-compatibility-counted-audit.json`保存计量和通过结果。
  完整软件套件中的GP拟合未另行累计，不将其记为0。

## 实际API结果

端点固定 `https://sidrune.ai/v1/responses`，模型 `deepseek-v4-pro`。
每次8192输出许可、非流式、store=false、单线程、无重试。凭据仅由专用环境变量
读取，没有写入命令、配置、日志或源码快照。原代理与默认TLS保持。

|阶段|控制|结果|耗时|计量|
|---|---|---|---:|---|
|p0最小JSON|none|HTTP200，完整合法回复|4.594s|input360/output26/total386，reasoning unknown|
|p1完整原上下文0|none|deadline_exceeded，awaiting_headers，无HTTP响应|120.031s|全部usage unknown|
|p2省略对照、p3/p4|未执行|按第一条完整none失败停止规则关闭|—|没有虚构计量|

实际2次记账、2次HTTP开始、1份HTTP回复；外层启动总耗时134.962秒，退出码1。
两次owned树均已停止。预算hash账本closed=failed；剩余3次没有续用或重置。
`comparator_equal_except_reasoning=false`在此次结果中表示对照未执行，不表示发现
请求体差异。没有执行A/B，因而也没有effort的因果时序比较。

独立归档审计通过仅表示记录一致，**不表示传输验收通过**：正式完整Region回复0、
实际tilt0、独立冻结GP恢复0、超参数拟合0、DFN0、BO0、新真实目标对0。
本轮没有RMSE或HV增益数据。所有未知计量均保留unknown，没有补零。

原始记录位于 `D:/Users/aa133/Desktop/LLMBO_Para/runs/r24eff`；证据根另存
`diagnostic-result.json`、`actual-launch.json`、`budget.jsonl`、
`live-diagnostic-audit.json`。原始HTTP回复沿用现有脱敏/归档规则，不主动提取、
展示或解释推理文本。请求体哈希使用规范化JSON哈希；历史context/request/signatures
保持原身份，实际新源码、控制和批准由独立probe元数据绑定，不作为新BO数据。

## 代码与保护

改动：`electrothermal_config.py`、`electrothermal_requests.py`、
`electrothermal_responses.py`、`electrothermal_llm.py`、
`electrothermal_audit.py`、`electrothermal_lgbo_audit.py`；新增独立
`scripts/run_responses_reasoning_diagnostic.py`和三个测试文件。
`request_controls`、原生请求构造器/transport和controller贯通可选控制；两个独立
审计器重建并核对控制；`run_diagnostic`、`ProbeBudget`、`RuntimeObservation`
负责本次API-only入口、记账和放行。没有向旧Optimizer增加多目标逻辑。

源代码提交依次为`1a3d63f`、`5dd4e71`、`52f7509`、`3a39f94`、`2c7ced1`。
文档交付提交晚于已关闭的实际诊断；受测、执行代码身份仍明确指向`2c7ced1`及
已封存入口，不将后续文档HEAD冒称为另一次完整软件测试。
分支`codex/electrothermal-mo-20261016`，原独立工作树保留。
GP/EI、Region数值公式、Prompt、物理模型、参数范围、倍率和原始实验均未改动。
主工程124文件、参考55文件、固定数值/Prompt/AST及原index/status检查保持；
90文件旧源码快照完整。旧2751项seal全部匹配；旧644项中641匹配，3项是批准修复
导致的活动工作树文件漂移，旧seal及全部封存条目未改写。不能称旧644活动路径全部匹配。

## 执行裁定与剩余工作

沿用Windows原生守卫/账本，代替技能的bash辅助脚本；代价是维护与核验证据的责任。
保留工作树、账本和正负记录，不合并/推送/清理；代价是磁盘占用。明确批准的活动
源码修复优先于旧seal对活动路径的笼统不可变措辞，保留可重放旧快照；代价是旧状态
不能继续从当前活动路径直接复现。后续完整测试按严格r2/r3记录，保留失败版本；
代价是多一层放行选择，已有负例覆盖。

独立fresh-context审阅的两个Important和一个升级为Important的保护依赖遗漏已修正；
修正过程以TDD及最终完整回归收尾，没有重复审阅，没有延期minor。
对审阅排除项的裁定：网关内部行为仍未知；真实回复/tilt必须经过真实门槛；
绿色针对性不代替完整放行；本次不作因果/RMSE/HV/BO结论；未全面审阅无关旧实现，
以原行为保护和完整回归界定范围。代价分别为服务语义未决、可能仍未ready、
验证时间、增益未回答和无关既有缺陷未获认证。

下一项可审阅工作应先加入DNS/连接/TLS/上传/首字节阶段计时，再按网关支持情况
单独设计SSE观测，以区分服务等待的位置；不是继续盲增token或改Region公式。
本轮未实现/启动该候选方向，未恢复旧BO窗口，也未自动申请或消耗新预算。
