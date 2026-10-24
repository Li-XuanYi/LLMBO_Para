# Region API 传输失败：本轮根因调查

日期：2026-10-24，Asia/Shanghai。起点 `17cabc2a722745379950a901fb11ea5952d0077b`，工作树干净；继续使用独立工作树和原分支。CodeGraph 沿用用户既定决定暂缓，不建索引。

本轮已执行只读源码/归档核查、凭据无关的 DNS/TCP/TLS 探测，以及内存故障注入；**真实 API 0、DFN 0、BO 0，产品及产品测试代码零修改，未运行新的 pytest 全量**。上轮 1205 项结果属于上轮，不作本轮验收。

## 已确认与尚未确认

上轮真实试验的 120 次正式 Region 请求全部失败：16 次达到 60 s 截止；104 次为 `URLError`，底层 HTTP 层记录耗时约 1.397–4.083 s，包含 worker 启动的监督耗时约 2.015–4.656 s。全部发生在取得响应头以前，没有正式回答、HTTP 状态或 usage。

因此，不能将 104 次快速失败解释为 LLM 推理慢或输出 token 不足。也不能凭 `awaiting_headers` 精确定位 DNS、代理 CONNECT、TLS、请求写入或服务端等待；这个阶段目前过粗。

源码确认的诊断信息丢失路径：

1. `HttpJsonTransport._post_json()` 捕获 urllib 异常，暂以 `message=str(exc)` 保存。
2. `HTTPArchive.write_json()/append_event()` 通过 `_public_diagnostic()` 删除所有异常自由文本和 provider body；这是既有密钥保护边界。
3. 机器可读的 `URLError.reason` 内层异常类型、`errno/winerror`、证书校验编号未事先提取，因此也不存在于 child result / supervision / controller outcome 中。
4. `_failure_kind()` 只能将整个 `URLError` 归入 `transport_error`；后续 104 次失败没有留下可区分的机器证据。

内存 opener 分别抛出 `URLError(ConnectionRefusedError(10061,...))`、`URLError(socket.gaierror(11001,...))` 和 `URLError(SSLCertVerificationError(...))`，使用真实 Responses worker、HTTPArchive、公开诊断通路，三者均丢失内层信息。**这是可复现的软件可观测性缺陷；它不是历史网络故障根因已经确定的证明。** 不通过保留原始错误文本解决。

## 当前网络检查

进程没有显式 HTTP(S)/ALL_PROXY 环境覆盖；urllib 读取 Windows 系统代理 `127.0.0.1:7897`，目标域名不在 bypass 中。当前端点 DNS 可解析，代理监听可连接；系统代理 CONNECT＋TLS 和直接 TLS 均通过默认证书验证，分别约 0.297 s / 0.609 s，TLSv1.3。没有发送 API GET/POST、没有 bearer 凭据、没有调用模型列表或修改代理。

这些只证明检查时的握手正常，不能证明历史代理稳定、完整 POST 正常或 26 kB 的实际 Region 能在 60 s 内生成完整答案。旧成功预检请求体约 13.5 kB，正式首轮约 26.3 kB；大小和历史内容不同，小请求成功不能替代完整 Region 验收。

## 修复边界和验证顺序

先补充有严格枚举及类型约束的内层错误机器字段，打通 transport → archive → worker → supervision → controller → audit；不保存原始异常或敏感代理地址文本。保持旧文件没有这些字段时的兼容性，不冒用旧缓存签名。

在新有限预算中核验完整冻结请求。如果确认是超时，受控比较同一请求的 60 s / 120 s，只有完整且绑定正确的答复才通过；延长超时不是预先认定的根因修复。如果出现已分类的 DNS、代理、证书或服务端故障，保留分类并停止，依据证据实施最小修复；禁止凭猜测绕过代理、关闭证书校验、增加供应商扩展、换模型或端点。

Region 验收分三层：

- 传输/契约：完整 HTTP 200 / Responses completed / 严格 JSON / 原 request_id 和上下文绑定正确；三个固定真实历史上下文均通过。
- 方法实际参与：至少一个真实 `kind=region`、正 confidence 的回复，在对应冻结 GP 上产生非零有限 mean tilt；真实标签、原方差、incumbent 不变，Gaussian EI 可独立复算。`none` 是合法弃权，不算 tilt，也不算传输失败；不能伪造动作以满足门槛。
- 研究增益：以上通过后，新的共享初始化、配对种子与同等预算下比较 Plain/WarmStart-only 和 Full，记录真正收到/有效/tilt/改变选点与 RMSE/HV。有效动作不保证增益，负结果保留。

## 证据和审批

新证据根：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/api-transport-repair-20261024/`。

- `investigation.json`：旧失败分类和时间汇总；旧 seal SHA256 `11caf15ae045ea26d95c4afbc39f68c0b2f7d1865b8183c512a82ee94db1c45c`。
- `credential-free-network-probe.json`：两条路由的当前 TLS 结果，API/DFN 0。
- `characterize_diagnostic_loss.py`、`diagnostic-loss-characterization.json` 和 `offline-*`：真实 worker 通路的三类离线注入，使用无效测试凭据及内存 opener，没有真实请求。

旧 `lgbo-real-gain-20261023` 及 `runs/g23r` 均不修改、不续跑。新软件修复与真实实验的具体审批见 `docs/superpowers/plans/2026-10-24-region-transport-repair-validation-plan.md`。按用户既定要求，计划提交审阅后暂停，批准后才修改产品代码及运行真实 API/DFN。
