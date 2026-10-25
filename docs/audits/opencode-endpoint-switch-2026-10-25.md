# OpenCode provider switch and connectivity test — 2026-10-25

用户将 LLMBO 的端点改为 OpenCode Go，指定模型 `deepseek-v4.1-flash`。
本轮仅完成连接配置和一次最小 API 测试，没有启动 Region、DFN 或 BO。

## 配置

- 新增 `configs/electrothermal-opencode-software-template.json`，不覆盖旧配置。
- 使用已有 `openai_chat_completions` 传输，完整端点为用户指定基地址加
  `/v1/chat/completions`：`https://opencode.ai/zen/go/v1/chat/completions`。
- 凭据只由本机专用用户环境变量 `LLMBO_OPENCODE_API_KEY` 提供；未写入配置、
  源码、命令参数或归档。其他供应商的变量没有替换。
- 模板经过严格 schema v2 校验，默认 `enabled=false`，API 和求解预算均为 0。
  保持原三倍率人工软件模板的物理、目标和优化设置；本轮不是新实验协议。
- Region 公式、Prompt、GP/EI、热模型、倍率签名和旧缓存校验没有改动。

## 实际软件测试

| 命令范围 | 测试 | 通过 | 失败 | 错误 | 退出码 |
|---|---:|---:|---:|---:|---:|
| 隔离探针检查 test_probe.py | 3 | 3 | 0 | 0 | 0 |
| 现有 test_chat_transport.py | 12 | 12 | 0 | 0 | 0 |

初次将 C/D 两盘测试放入同一 pytest 命令时，收集阶段误遍历到 Windows
受保护目录，退出码 2、收集错误 1。改为分别指定 rootdir 运行，没有修改
被测代码。原失败日志 `pytest.log`/`junit.xml` 保留，不计为通过。
最终独立日志为 `probe-pytest.log`、`chat-pytest.log`，JUnit 为
`probe-junit.xml`、`chat-junit.xml`。这 15 项是本轮定向软件验证；没有重新
运行原 1581 项全量回归，也没有把历史数量作为本轮结果。

## 实际 API 结果

新独立边界为最多 1 次 API、0 次 DFN/BO、90 秒墙钟；单次 60 秒，最多
1024 输出 tokens，thinking disabled，不重试。使用已有生产传输、脱敏存储
和 Windows Job Object 监督，父进程记账确认先于网络请求。

- 时间：北京时间 2026-10-25 13:16:58 完成。
- HTTP 401，`authentication_error` / `api_key_expired`。
- 服务端说明该密钥已经过期，需在 OpenCode Console 创建新密钥；重新登录
  不会续期旧密钥。
- 单次调用 1.719 秒，整次诊断 3.312 秒；真实入口退出码 1。
- 成本 API 1、DFN 0、BO 0，预算已关闭，受监督进程树已停止。
- 上次 sidrune 请求是 HTTP404 分组模型路由错误；本次 OpenCode 是 HTTP401
  密钥过期。供应商、模型、凭据和协议均改变，不能据此评价数值算法增益。
- 未验证完整 Region 回复、非零影响、RMSE 或 HV 增益。

证据目录：
`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/opencode-switch-20261025`。
独立真实归档：`D:/Users/aa133/Desktop/LLMBO_Para/runs/o25p`。
旧记录及封存文件均保留，未恢复此前已关闭的运行预算。

## 官方资料核对与后续

[OpenCode Go 官方文档](https://opencode.ai/v2/docs/console/go/) 当前为该模型列出
Chat Completions 协议和新的 `/inference/go/openai/v1/chat/completions` 路径。
本轮遵循用户指定的 `/zen/go` 基地址进行核验，没有自动改地址、跟随重定向
转发密钥或尝试其他模型。实际得到的 `api_key_expired` 是当前阻塞的直接证据。

下一步需有效的新 OpenCode 密钥，再核验连接和完整 Region 契约。正式
RMSE/HV 配对仍须先通过 Region 生效门槛，并使用独立有效运行预算。
