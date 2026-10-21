# Sub2API Responses 软件适配审计

2026-10-21；用户批准“软件适配与本地测试”，本轮真实API/DFN预算为0。

## 状态与范围

接口、配置、受控请求、严格返回和独立审计已实现；分阶段针对性检查通过。最终新全量与fresh-context整分支审阅待本报告后续补充，不能以历史结果代替。

工作树 `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`，分支 `codex/electrothermal-mo-20261016`。批准计划 `d991ae7`，Task1 `0c0aa6b`，Task2 `cde7083`，Task3 `852848a`。主工程、参考工程、旧实验、全局Codex配置不修改。

新增responses模块、3个测试文件和零预算模板；修改电热requests/config/controller/catalog HTTP decoder/audit及文档。不改物理模型、倍率、目标、参数、GP/EI、Lift、fair guard、信任或WarmStart选择，不放宽旧签名。

用户指定 `https://sidrune.ai/v1`、`deepseek-v4-pro`、`SUB2API_API_KEY`、Responses；POST目标 `/v1/responses`。不自动探测模型、改用Chat/其他模型，不把旧站密钥交给新域名。固定store=false、stream=false、无工具/会话/重试。thinking扩展未确认，显式设置拒绝；缺失usage为unknown。本站权限、JSON模式及真实兼容性尚未验证。

## 实际阶段测试

证据根 `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/`；下列目录均位于tests/并含pytest.log、junit.xml、exit-code.txt、result.json。

| 检查 | 实际通过/失败/错误/跳过 | 退出 | 证据目录 |
|---|---|---|---|
| 本轮新完整基线 | 669/0/0/0，725.23s | 0 | responses-baseline-1021064446479558 |
| Task1 RED | 0/45/0/0，缺新模块 | 1 | responses-wire-red-1021065930541232 |
| Task1＋旧Chat GREEN | 57/0/0/0，18.42s | 0 | responses-wire-green-1021070210208575 |
| Task2 RED | 7/13/0/0 | 1 | responses-request-red-1021070652108323 |
| Task2＋旧请求 GREEN | 96/0/0/0，43.89s | 0 | responses-request-green-1021071150042642 |
| Task3 RED | 10/13/0/0 | 1 | responses-audit-red-1021071926876517 |
| Task3首轮未通过 | 12/11/0/0 | 1 | responses-audit-green-1021072613890159 |
| Task3边界修复 | 23/0/0/0，51.53s | 0 | responses-audit-boundary-green-1021073526761616 |
| 失败一致性 RED | 0/1/0/0 | 1 | responses-audit-failure-red-1021073816292827 |
| 删除收据证据 RED | 0/1/0/0 | 1 | responses-audit-wireloss-red-1021074041080330 |
| Task3最终相关 | 210/0/0/0，240.99s | 0 | responses-audit-related-1021074253482653 |
| 模板 RED | 0/1/0/0，缺新模板 | 1 | responses-template-red-1021075127747182 |
| 集成fixture首轮 | 2/3/0/0，空候选导致初始化不足 | 1 | responses-modes-red-1021075205726755 |
| 模板＋三模式 GREEN | 5/0/0/0，18.56s | 0 | responses-modes-green-1021075302168965 |

Task3首轮发现：catalog审计要复现发送前canonical排序；mock要在HTTP边界把host tuple转成JSON list；最小context的GP占位state不能当完整state恢复。分别修正审计与fixture，保留所有失败，不放宽正式回复类型。

额外RED证实并修复：非catalog失败也要从raw reply核验协议错误；真实成本记录声称接收成功时，删除原始HTTP/正式收据并删除诊断字段仍须失败。空候选fixture的初始化不足是正确行为；mock改为按原变换返回4个合法候选后，ParEGO、WarmStart-only、Full-ID、Full-none均完成2轮软件BO并通过审计，无随机补点。

上述network_attempts与battery_solve_attempts均0。新基线另有2次既有非电池进程fixture调用，其余针对性运行0。生产请求路径fixture会记逻辑llm_request/API_calls；子进程HTTP opener是内存fake，不能把这些逻辑计数冒称真实付费请求。

## 兼容与保护

本计划外部目录 `sub2api-responses-20261021/`，独立批准快照和ledger，不写上一计划台账。保护清单复核MAIN124个文件、HEAD/status/index，以及工作树24项数值模块/Prompt、2个核心函数AST，阶段对照一致。

4份旧档案只读重放通过；120次状态恢复fit(max_sweeps=0)，超参数搜索0、网络0、DFN0；见本计划compatibility-result.json。没有宣称GP方法调用0，不重签旧记录。

OMP/OpenBLAS/MKL/NumExpr均1。仅在自有软件测试期间申请SYSTEM_REQUIRED防空闲待机，不改持久电源方案。基线lease已释放，后续runner用finally释放，交付复核全部lease状态。

## 入口及验证边界

新模板保留原软件问题、ParEGO、LLM disabled、API/DFN0。在本工作树使用当前源码进行只读校验：

```powershell
$env:PYTHONPATH = 'C:\Users\aa133\.codex\worktrees\electrothermal-refactor\LLMBO_Para\src'
& 'D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe' -X utf8 -B -m llmbo_para validate-config configs/electrothermal-sub2api-software-template.json
```

真实API需要在本地提供专用SUB2API_API_KEY，并另行审阅冻结请求与明确预算。密钥不进入参数、配置、日志或快照。此前vsllm单次预检已结束，不移作本站额度。

本次没有新真实DFN RMSE/HV结果，不验证唯一可辨识、Region增益或实测辨识。电流、温度测点/单位、初态、环境与冷却确认仍按原预检；旧3C仍排除。最终全量、审阅及封存完成后补充到本报告。
