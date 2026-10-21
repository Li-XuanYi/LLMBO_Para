# Region 增益复核与真实试验就绪检查

2026-10-21。当前产品52b9813、文档基线1aeb802，工作树初始干净。用户要求验证增益并在未增益时修复；本轮先完成可在零真实资源下完成的诊断、输入/协议冻结与预检。未启动真实API/DFN，不把离线选点改变写成收益。

## 已有真实结果

封存的2026-10-20三种子101/211/307试验，Full与共享WarmStart-only逐轮重合，ΔHV=[0,0,0]。平衡同参U/T分别为：101的1.888375mV/0.01464393K；211的1.629396mV/0.02895670K；307的0.582166mV/0.02209940K。它检验的是d90b93f旧signed_residual版本，不是后续A1/A2和新Responses模型。

旧60轮中17轮无eligible，43次请求有29个正式回复、10个HTTP402、4次超时；26次合法none、2个超宽区域、1个合法但未胜同场Plain的区域。不能概括为“公式没执行”或“全部网络失败”。旧结果、预算及封存未改。

## 本轮零资源容量诊断

外部根目录：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-gain-validation-20261021/`。

使用当前host目录构造器，在旧真实记录的6个冻结上下文上，只替换为明确标mock的矩形建议：固定种子101/211/307、第3/18轮；目录宽度为既有min_width的1/2/4倍，confidence固定[.62,.8,.95]。不修改原始档案、参数、GP/标签/方差、信任或守卫，不评价反事实真值；不在发现正例后提前停搜。

实际81个mock对照（27区域×3置信度），其中6个改变选点、75个被fair Plain基线拒绝。6个上下文中仅307第3轮存在正例；两个上下文无eligible因而没有目录。confidence=.62/.8/.95分别改变1/2/3个，均有27个对照。这是有限构造结果，不能将6/81当作LLM采纳率、真实改善概率或全局容量定理。

6个none控制保持Plain；所有context、GP、mean/std及标签前后哈希一致，恢复预测与旧归档mu/std/EI逐值符合1e-12容差。实际99次直接恢复/Cholesky、GP.fit方法调用0、网络/电池/其他Simulation.solve尝试均0。退出0，用时10.969秒，见offline-capacity-final/report.json、trials.jsonl及SHA。

诊断入口先失败两次：第一次numpy数组不能直接JSON摘要；第二次内层from_state触发被禁止的fit初始化路径。保留两份入口快照/日志/退出1，改用list摘要和显式无fit恢复后成功；未放宽产品、模型或守卫。失败尝试不计入成功81个对照。

## 冻结后续输入与预检

两份真实DFN禁用配置预检通过：0.5C/1C、60秒、当前A1/A2、Responses/deepseek-v4-pro，显式LLM disabled、API/DFN0。只复用既有真实DFN合成观测与八个历史坐标；新阶段必须重新求解候选曲线。

预检请求另用新解析软件fixture生成：8个初始化＋4轮纯软件ParEGO，24次解析software_call，0个真实API/DFN；审计通过。从一个过去历史完整的冻结上下文得到30项目录，冻结请求体58186 UTF-8字节，store/stream均false。没有为取得非空目录放宽门槛。六项离线契约检查通过；它们是本轮脚本断言，不是新pytest全量，且不证明本站权限/兼容性或RMSE增益。

该入口先被严格配置校验拒绝（初始计数与WarmStart计数不符），修正后又遇Windows深目录快照的WinError3；分别保留失败日志/快照。最终使用独立短路径bo-repair-work/gp1021-region-probe保存fixture，未放宽配置或删除失败。成功报告位于region-api-probe-final，两个失败目录原样保留。

完整双阶段有限协议见../experiments/2026-10-21-region-gain-validation-protocol.md；最终机器协议proposal/protocol-final.json，SHA256 bbef38e8c11d8729a1651b1e9ac1afd4e684982bf9bd73635abcdb75bd9534fb。诊断/确认种子分开；未增益最多一次有证据、TDD与完整回归的当前范围修复，随后独立确认，不追选正结果。

## 当前阻塞与准确结论

SUB2API_API_KEY在进程和用户环境中均未配置（仅检查是否存在，未读取或输出值）。旧运行已终止、额度不可恢复；新真实试验需按具体有限协议取得预算。外部监督器也须先完成本地TDD和冻结，之后才允许真实预检。

本轮结论是：当前目录与原公式有有限选点容量，尚无新版真实RMSE/HV增益证据。没有证据支持为了取得阳性而加大confidence、放宽fair守卫或改目标。新真实API/DFN为0；当前没有新的实测识别或唯一可辨识结论。历史781/781是上一软件交付的结果，本轮未重跑或冒称新测试结果。

本轮产品源码、测试、配置和Method未改，仅新增本审计和验证协议文档；主工程及旧档案保护、最终提交/证据SHA由外部readiness-seal.json记录。当前阶段不启动付费请求或正式BO，等待专用凭据及有限预算。
