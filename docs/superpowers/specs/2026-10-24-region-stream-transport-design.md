# 完整 Region 的等待诊断与显式 SSE 接收设计

状态：待审；起点89b236e。继续原独立工作树/分支，软件、真实调用均须按本计划
获批后执行。用户要求先确认完整Region返回并生效，再测试RMSE/HV。
依据：[本次调查](../../audits/region-transport-stages-investigation-2026-10-24.md)。

## 意图与方案选择

上轮none已发送仍无响应头。本次离线8场景证明现有awaiting_headers标签覆盖
多个网络阶段，不能据它定位服务器推理。推荐两个有顺序的动作：完整请求等待栈
采样，随后同一冻结请求的非流式/SSE对照；SSE是待验证候选修复。

替代方案是继续增加timeout/token，或压缩Prompt/历史。前者没有当前根因证据，
后者改变LLM可见信息；本次均不选。自定义整套DNS/TCP/TLS连接器可产生精确计时，
但会复制标准库网络逻辑；先用不改变请求的原生栈采样，足以确定主要等待层。
这些是作者建议，尚未获得本设计审批。

## 最小配置及传输接口

schema2且 `llm.transport="openai_responses"`允许全局可选布尔
`llm.responses_stream`。缺失保持原body的stream=false；显式false也发送false，
显式true发送true。null、数字、字符串、schema1、Chat、task_options中的该字段
拒绝。禁用LLM也执行配置校验，但不读取凭据/联网。

`responses_request_body(...,reasoning_effort=None,responses_stream=None)`及
Responses/BoundedResponses构造器增加同名keyword。Python接口None仅表示未配置，
配置JSON null仍非法。配置是唯一真源；注入客户端的隐藏stream不得被继承。
全局值用于WarmStart及Region，不增加任务级覆盖。显式配置的字段和值贯穿
request_controls、controller clone、owned spec、supervision/outcome和审计。

保持instructions/input/text.format/max_output_tokens/store=false及reasoning完全
相同，只切stream。继续同端点、模型、代理、证书验证、8192许可、120秒硬截止。
保活/增量不延长单次或运行截止；无fallback协议猜测、自动重试或新依赖。
配置/算法签名自然包含该字段；缺省旧body与缓存规则保持，历史初始化不改签。

## 接收、归档及独立审计

`HttpJsonTransport`只提取一个内部 `_read_response(response,*,task,redact)`钩子；
默认保持原1MiB JSON读取/脱敏行为。Responses仅在显式true时覆盖钩子，以独立
`electrothermal_sse.py`解析SSE，避免复制鉴权、Request、NoRedirect、TLS和错误处理。

接收必须满足：HTTP成功且content-type为text/event-stream；UTF8增量解码、CRLF/
LF、空行分隔及多行data正确；允许注释保活，累计实际读取字节最多1MiB、最多4096
语义事件，不因分块大小/注释重置限额。SSE event字段若存在须与data.type一致；
data包含非负整数sequence_number，严格递增。只接受版本化Responses事件类型，
工具事件/未知事件明确拒绝。原生有限JSON规则保持。

只有收到 `response.completed` 且其中完整response通过原
`decode_responses_json`，再通过原Region wire binding，才可返回动作。不能拼接
delta来补造最终JSON；不能把HTTP200、created/in_progress、output_text增量、
注释、[DONE]或无终止EOF当完成。failed/incomplete/error保留失败事实和计量。
解析器在有效终止事件后结束读取，不为等网络EOF延长请求；不声称检查了尚未读取
的尾部。缺失usage为unknown，none控制不作为服务端执行证明。

流式运行归档 `http/<task>.stream.jsonl`：依次保存脱敏后的原生事件及必要SSE
envelope/顺序信息；这是原始HTTP流的结构化归档，不另行提取或解释推理文字。
完成后现有response.json保存终止response作为派生产物。失败时部分stream保留；
硬截止造成末行截断只能用于失败诊断。敏感字段和实际key依照原HTTP规则递归脱敏，
不使用debuglevel、不输出请求/Authorization或推理文本。

独立审计从stream事件重建完整终止response，再重放旧JSON/wire/动作与数值审计；
不能只信派生response或completed标志。缺/改终止、次序、身份、stream配置或
supervision/outcome、部分流伪报成功均可检测。旧非流式归档按原契约，不要求补流。
仅允许公开进度字段：是否流式、语义事件数、已知事件类型、首次事件/完整耗时；
没有观测到的值保留unknown，不将headers_complete叫首字节。

## 等待栈观测

独立验证入口在**实际HTTP owned子进程**启动请求后每30秒用faulthandler采样，
而非采样只会等待子进程的外层父进程。只记录文件/函数/行号；finally取消timer后
关闭文件，父截止仍负责停止owned树。以局部HTTPArchive观察器复用原生产worker，
单进程内恢复被替换引用，不改变HTTP/请求体，不预加载破坏Windows spawn的canonical
模块。基于真实堆栈报告当时阶段，不能给抽样间隔推导出精确阶段时长。

## 真实验收门槛与比较协议

独立总上限66API、256DFN、10800秒，首次实际请求前开始唯一绝对总钟，预留30秒
清理；软件基线/TDD/全量在总钟启动前完成。诊断另限6API/0DFN/900秒，但受同一总钟。
先最小非流式，再完整ctx0非流式，再ctx0/ctx1/ctx2流式，最后预注册ctx0流式重复；
序列详细停机条件见实施计划。固定重复不是失败重试；除比较臂的限定截止例外，
任何失败停止。原预算均已关闭，不续用或从0抹去旧成本。

通过门槛为：四次完整流式回复（其中三个不同历史context），均完成、绑定、动作
合法；冻结GP重放证明原标签/状态/方差未变，EI与独立公式一致；至少一次实际
tilt_applied且max_abs_shift>1e-12。报告EI变化和selection_changed，不强迫改变
选点，不伪造confidence或抬高强度来通过。none动作合法但单独不足以过生效门槛。
栈和流式事实不等于服务端内部原因被证明，四次通过也不是稳定性统计保证。

只在门槛通过且有剩余额度时，复用已封存0.5C/1C、60秒合成观测，按原八个参数
坐标重新实评16次solve，形成当前源码/配置下的新共享初始化计划。旧计划只用于
提供坐标与可追溯身份，绝不改签冒充新计划。Plain和Full共用同一新计划；两个
模式数值骨干、权重调度、尺度及GP拟合预算一致，差异只在Region。预留种子
1709/3253/5501，每臂8初始化＋20轮；总计新增240次solve/60次Region请求。

固定scales=[0.1V,1K]、HV空间F/scales、ref=[10,10]、ideal=[0,0]、rho=0.05，
循环权重[[0.8,0.2],[0.2,0.8],[0.5,0.5]]，512全局/8局部候选、4 GP sweeps、
局部radius=0.2。每轮从已有完整真实Y重建全部标签/标准化/incumbent/GP/EI；失败
无新增有效目标也如此。全程单线程数值计算、无传输重试，连续3次正式请求失败
停止整个比较；合法弃权与失败分别计量。试验次序按种子交替臂先后，全部负结果保留。

## 科学结论与保护

先分别报告传输完成、实际均值/EI作用及选择是否改变，再报告各种子的RMSE/HV
曲线与终值。每个推荐参数点同时报告其FU/FT，分别最小的FU和FT不可冒称同一点。
从归档电压/温度曲线独立复算RMSE、从真实完整目标对重算固定空间HV；partial结果
保留诊断、不补零、不进入GP/Pareto。三种子给描述性配对结果，不保证增益或删负例。
若无增益，先区分未完成传输、合法弃权、零倾斜、未改排序和区域质量，不自动追加
预算/改Prompt、核、热模型或Region公式。

保留旧schema1四倍率电压与旧缓存签名、原始XLSX、旧3C及全部旧记录；本次比较不
使用旧3C或实测。物理输入/测点/边界仍待确认。主工程、原算法参考、旧seal及
封存入口/源码快照只读；活动工作树未来获批修复前复制旧版本并记录允许漂移清单。
当前交付仅设计与计划，不称超时已修复或DFN/实测增益已完成。
