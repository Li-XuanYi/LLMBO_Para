# 完整 Region 超时：传输阶段调查

2026-10-24；检查起点 `89b236e8a32a2b4a707d37b5f91ba4d1ae763a22`，原独立工作树干净。
本次仅调查和准备待审设计/计划，产品代码及产品测试未修改。没有恢复已关闭的试验。

保护重查最初发现主目录`tests/test_informed.py`相较上次快照变化；随后又观察到
主目录的`workflow.py`、`informed.py`、`llm.py`和`informed_audit.py`变化，主HEAD/
index仍相同。这表明主目录正在独立改动，不能假定它静止或推断编辑者身份。
本任务未写这些文件，原样保留，只从独立工作树加载产品源码。
两个只读核验先后因“仍与旧快照相同”和“只有一个偏差”的假设触发断言，脚本/
失败记录保留；改为记录所有当前偏差，不恢复用户文件。这些不是产品测试失败。
独立工作树的数值/Prompt/AST与参考目录单独核验，不能冒称主目录124项都与旧
快照相同。后续正式执行前重新捕获保护边界，外部并行编辑单独归因，不回写主目录。

## 已有事实与本次发现

上一轮已实现可选 `reasoning.effort` 并完成1441项全量回归；那是上一轮的结果，
不是本次新跑的测试。实际最小请求4.594秒成功；完整Region在120.031秒硬截止，
`none`实际发送，HTTP状态及usage未知。两次请求后按协议关闭，0DFN/BO。
来源：[已封存报告](responses-reasoning-control-validation-2026-10-24.md)。

本次只读取系统代理配置的安全摘要，确认HTTP/HTTPS代理均为本机回环地址的
HTTP代理，端口7897，没有代理用户名/密码。未变更代理、TLS、环境或凭据。
这只能说明本机路由配置，不证明代理服务存活、可达或承担了上一次故障。

实际Python3.12标准库调用顺序为：到代理的DNS/TCP连接 → CONNECT → 目标TLS
握手 → 发送请求 → 读取源站状态行/响应头 → 读取响应体。`urllib`的
`open()`包含上述多个阶段，产品只有在它返回后才写 `llm_http_headers_received`。
`BoundedChatCompletionsTransport._archived_progress()`仅检查该事件，缺失时默认为
`awaiting_headers`。因此这个标签不是“已经上传并等待模型”的证据。
依据：[CPython3.12源码](https://github.com/python/cpython/blob/3.12/Lib/http/client.py)。

## 本次实际离线验证

证据根：
`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-transport-stages-20261024`。

`offline_stage_characterization.py`使用实际 `HttpJsonTransport`、urllib和http.client，
仅替换HTTPS连接工厂为内存socket/TLS上下文。禁止实际DNS、socket connect和
connect_ex；读取上次完整请求的归档body，实际序列化为26337字节，包含新增none。
不是此前不含reasoning控制的26304字节请求。

|注入位置|当前监督器可见阶段|验证|
|---|---|---|
|DNS/TCP连接|awaiting_headers|通过|
|代理CONNECT响应|awaiting_headers|通过|
|TLS握手|awaiting_headers|通过|
|请求body发送|awaiting_headers|通过|
|源站状态行读取|awaiting_headers|通过|
|源站响应头读取|awaiting_headers|通过|
|响应体读取|reading_body|通过|
|完整成功控制|HTTP200、JSON及完整body/Content-Length一致|通过|

实际8个场景、8通过、0失败，进程退出0；真实socket尝试0、API0、DFN0、BO0。
这是离线特征验证，不是pytest全量回归、TLS验证、真实Region成功或物理验证。
结果：`offline-stage-result.json`；事件：`cases/*/events.jsonl`；日志/退出码另存。
脚本及所用CPython模块、历史wire文件的SHA在结果中记录；没有保存请求鉴权头。

## 选择与仍未知事项

当前没有证据证明token许可不足、none被网关执行、模型拒绝JSON或Region公式错误。
最小请求成功不能证明完整请求链路稳定；同样不能把本地代理认定为根因。

推荐先对完整冻结请求采样实际HTTP子进程的等待栈：Python官方
`faulthandler.dump_traceback_later`只记录文件/函数/行号，不输出局部变量或源码，
可区分CONNECT、TLS、sendall、源站读取等等待位置。30秒抽样只能定位当时等待，
不能据此伪造DNS/TLS精确耗时或首字节时间。应在finally取消计时后关闭文件，
不启用会打印鉴权/请求体的HTTP debuglevel。
[Python3.12文档](https://docs.python.org/3.12/library/faulthandler.html)。

随后仅改变同一完整请求的stream字段进行预注册对照。DeepSeek原生Responses
文档支持SSE；收到 `response.completed`中的完整response后才可沿用原JSON和
Region绑定校验。created、增量、保活或EOF均不算成功。该支持是上游事实，
Sidrune是否转发并及时输出仍须实测，SSE不保证减少生成时间。
[Responses流式协议](https://api-docs.deepseek.com/guides/responses_api/)。

上游还说明等待时可能发送空行或SSE保活，十分钟未开始推理可关闭连接；这不是
120秒完成承诺，也不证明第三方代理/网关会及时转发保活。
[保活说明](https://api-docs.deepseek.com/quick_start/rate_limit/)。

候选修复采用**显式SSE接收能力＋完整完成校验**，保留原非流式默认；不压缩历史、
改Prompt、增加token/请求超时、切模型/端点/代理或修改LGBO公式。若实际卡在
CONNECT/TLS/上传，先停止并据阶段证据修复该层，不能声称SSE解决了它。

## 待审交付

[短设计](../superpowers/specs/2026-10-24-region-stream-transport-design.md)与
[实施计划](../superpowers/plans/2026-10-24-region-stream-transport-plan.md)给出字段、
解析/归档/审计契约、失败测试、真实门槛及后续配对协议。
当前只是作者建议，没有把新设计标成用户已批准。原阶段预算不续用。

推荐一次批准软件及分阶段独立上限：66API/256DFN/10800秒，其中API-only诊断
最多6次/900秒；门槛不通过则余下DFN/API全部不启动。具体固定序列及一次比较臂
截止后可继续的例外见计划；没有自动重试、无限尝试或保证正增益。
