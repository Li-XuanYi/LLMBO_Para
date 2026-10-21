# Sub2API Responses 软件适配审计

2026-10-21；用户批准“软件适配与本地测试”，本轮真实API/DFN预算为0。

## 状态与范围

软件交付完成。fresh-context整分支审阅的5项Important均已按RED→GREEN修复；针对性67/67、最终全量781/781通过，失败/错误/跳过0、退出0。本站真实API、DFN和正式BO均为0，真实兼容性和科研增益未验证。

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
| 审阅修复首轮 RED | 4/8/0/0，4个关联fixture尚未复现所需旁路 | 1 | responses-review-red-1021081515348987 |
| 修正fixture后关联 RED | 0/4/0/0，独立复现WarmStart与full bounds旁路 | 1 | responses-review-link-red-1021081640805792 |
| 请求覆盖/计数 RED | 1/2/0/0 | 1 | responses-review-coverage-red-1021081721158125 |
| 审阅修复首轮 | 61/6/0/0，审计helper集合序列化错误 | 1 | responses-review-green-1021081850954004 |
| 审阅修复最终针对性 | 67/0/0/0，168.22s | 0 | responses-review-fixed-1021082157502171 |
| 最终完整回归 | 781/0/0/0，1206.71s | 0 | responses-final-verified-1021082601556621 |

首个最终全量responses-final-1021080210465198在确认审阅问题后主动中断，wrapper退出1，仅有部分pytest.log，无最终数量/JUnit/result，不记为通过；见本计划interrupted-final.json。原始active lease文件未被finally更新，保留原字节；已核查自有线程/进程退出，Windows随线程退出释放其execution-state请求。其余完成运行逐个检查released=true。

Task3首轮发现：catalog审计要复现发送前canonical排序；mock要在HTTP边界把host tuple转成JSON list；最小context的GP占位state不能当完整state恢复。分别修正审计与fixture，保留所有失败，不放宽正式回复类型。

额外RED证实并修复：非catalog失败也要从raw reply核验协议错误；真实成本记录声称接收成功时，删除原始HTTP/正式收据并删除诊断字段仍须失败。空候选fixture的初始化不足是正确行为；mock改为按原变换返回4个合法候选后，ParEGO、WarmStart-only、Full-ID、Full-none均完成2轮软件BO并通过审计，无随机补点。

上述network_attempts与battery_solve_attempts均0。新基线另有2次既有非电池进程fixture调用，其余针对性运行0。生产请求路径fixture会记逻辑llm_request/API_calls；子进程HTTP opener是内存fake，不能把这些逻辑计数冒称真实付费请求。

## 兼容与保护

本计划外部目录 `sub2api-responses-20261021/`，独立批准快照和ledger，不写上一计划台账。保护清单复核MAIN124个文件、HEAD/status/index，以及工作树24项数值模块/Prompt、2个核心函数AST，阶段对照一致。

4份旧档案只读重放通过；120次状态恢复fit(max_sweeps=0)，超参数搜索0、网络0、DFN0；见本计划compatibility-result.json。没有宣称GP方法调用0，不重签旧记录。

审阅修复后又独立完成4份旧档案重放，见compatibility-postreview-result.json：120次状态恢复fit、0次超参数搜索、网络/DFN0。新模板validate-config及preflight再次退出0，见cli-*-postreview.log与对应退出码；原记录保留。

OMP/OpenBLAS/MKL/NumExpr均1。仅在自有软件测试期间申请SYSTEM_REQUIRED防空闲待机，不改持久电源方案。基线lease已释放，后续runner用finally释放，交付复核全部lease状态。

## 入口及验证边界

新模板保留原软件问题、ParEGO、LLM disabled、API/DFN0。在本工作树使用当前源码进行只读校验：

```powershell
$env:PYTHONPATH = 'C:\Users\aa133\.codex\worktrees\electrothermal-refactor\LLMBO_Para\src'
& 'D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe' -X utf8 -B -m llmbo_para validate-config configs/electrothermal-sub2api-software-template.json
```

真实API需要在本地提供专用SUB2API_API_KEY，并另行审阅冻结请求与明确预算。密钥不进入参数、配置、日志或快照。此前vsllm单次预检已结束，不移作本站额度。

本次没有新真实DFN RMSE/HV结果，不验证唯一可辨识、Region增益或实测辨识。电流、温度测点/单位、初态、环境与冷却确认仍按原预检；旧3C仍排除。最终回归网络尝试/电池求解尝试0，另有2次既有非电池fixture调用。

## 整分支审阅及修复

审阅范围d991ae7..8784591；报告whole-branch-review.md保持原样。审阅用只读内存overlay独立复现3种篡改旁路，未改档案；另确认缺密钥审计和配置类型问题。Critical0、Important5、Minor0；执行者一次合并修复为52b98135ce7e3aa2c4dd1d4d4ac4e74416c8cd01，每项先观察失败测试，再实现并通过67项针对性测试及781项完整回归。依executing-plans不另派复审，以RED→GREEN和完整回归验收修复。

| 审阅问题 | 修复及失败测试 |
|---|---|
| WarmStart回复未关联实际评价 | 按请求/事件重放候选、筛选、重复、预算与参数；used_screening、processing_counts测试 |
| full bounds回复未关联实际区域 | 两种wire均解码、封套校验、规范化并比较轮次；used_round测试 |
| 删除完成摘要绕过审计 | 有Responses原始回复就强制重算两份摘要；hide_raw_usage测试 |
| 缺密钥安全跳过不可审计 | 仅Responses新增原因，核查无ordinal/HTTP/请求成本及跳过事件；remains_auditable测试 |
| 连接字段类型漏校验 | URL解析/环境读取前返回普通配置错误；nonstring_connection测试 |

源码指纹a98cc1890ea99d4fca5b4b9a9cd53be7b6f97cac16128ac502bd35c7349bcc90。对应future-probe-draft-a98cc1890ea9内含冻结config/payload/request-body及SHA协议；状态NOT_APPROVED_NOT_EXECUTED、API/DFN/BO均0，没有send入口。旧dbf711260bfd草案保留但不作为最终源码协议。

## 执行裁决与未验证事项

以下完整记录本计划ledger中的裁决及判断错误的代价：

1. 重用既有Windows边界guard，采用本计划独立runner/ledger并保留工作树和所有证据；若guard有缺陷则边界证据可信度受限，最终仍核对其实际计数。
2. 仅自有测试线程临时申请SYSTEM_REQUIRED，核实基线leaf PID，不改持久电源方案；若判断失误，待机可能影响时限，不能把受污染超时作模型失败。
3. store=false与本地归档共用真实HTTP边界隐私测试，不重复同一调用；若覆盖不足会漏隐私回归，保留该边界测试和原始证据。
4. 增加Responses专属正式收据以关联两任务与raw reply，不改变Chat或数学；若收据关联不足会误认证，5项审阅修复专门补齐使用链。
5. 在冻结8784591上并行执行只读审阅与首个全量，以减少墙钟；确认问题后中断旧全量、保存无结果状态，修复后重新全量。若未冻结会导致版本错配，因此最终以52b9813的新结果为准。
6. 配置类型问题虽源于既有truthiness校验，也按Important处理；修复前验证会崩溃或漏过，修复的代价仅是拒绝原本格式错误的配置。
7. 审阅未判断本站可用性、权限、thinking或JSON-mode兼容：维持未验证和0请求；离线通过仍可能遇到真实协议不兼容。
8. 审阅未判断服务端保留策略：store=false仅为请求，不能保证第三方不保留日志。
9. 审阅未判断物理DFN、RMSE/HV、可辨识性或Region增益：保持未验证，不能以软件验收作科研结论。
10. 重试、streaming、tools、sessions、WebSockets和模型发现按批准计划排除；需要这些特性的端点不受支持。
11. 全局Codex CLI设置不在范围，未修改；本适配不会配置Codex自身。
12. 审计验证归档信任根下的本地一致性，不能鉴别整套config/source/data及所有摘要均被替换的外部真实性；后者需要独立签名根。

按用户“继续使用当前受控快照和独立工作树、保留旧流程与记录”的明确要求，交付保留分支/工作树和本计划ledger，不执行清理、合并或推送。无延期Minor。

## 显式变更清单

- 新增src/llmbo_para/electrothermal_responses.py：纯wire/严格解析/摘要及受控worker。
- 修改electrothermal_requests.py、electrothermal_config.py、electrothermal_llm.py：显式路由、监督、配置门槛和正式收据。
- 修改electrothermal_region_catalog.py、electrothermal_audit.py：双协议解码与独立证据重放。
- 新增tests/test_electrothermal_responses.py、test_electrothermal_responses_requests.py、test_electrothermal_responses_audit.py。
- 新增configs/electrothermal-sub2api-software-template.json；更新llm-informed、规格、计划和本审计文档。

共14个跟踪文件，显式git add；外部证据由最终delivery-seal.json列出文件SHA，所有早期负结果保留。最终受测源码为52b9813，收尾文档提交不改src/tests/configs/锁定依赖。JUnit、pytest.log、exit-code.txt、result.json位于上述最终完整回归目录；独立ledger拷贝为progress-final.md，封存记录包含交付commit及源码指纹。工作树继续保留，不合并或推送。
