# Region 动态证据与目录契约实施审计

用户已明确批准`2026-10-20-region-dynamic-catalog-plan.md`的A1→A2软件实施。真实API/DFN预算仍0；不替换Lift公式，不修改六参数、双目标、物性或数据协议。工作树沿用electrothermal-refactor，产品基线为d3e2fa1，实施前HEAD77af49f。

## 本轮新基线

完整重跑530项通过、失败/错误/跳过0、退出0、882.65秒。证据：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/dynamic-catalog-baseline-recovered-1020100237548048/`，包含pytest.log、junit.xml、result.json及exit-code.txt。网络尝试0、真实电池solve0；允许的非电池解析fixture solve2。

首次基线因本轮外部Windows包装器缺少__main__保护而在spawn fixture中重入，已停止（exec退出1），没有完整计数/JUnit，不能记作通过。问题归类为本轮测试启动环境问题，不是产品源码回归。修复入口保护并验证__mp_main__导入不再创建测试运行后，完成上述独立新基线；原日志及所有目录保留。详见证据根目录region-dynamic-catalog-20261020/baseline-runner-interruption.json。包装器仅将既有守护runner的PLAN/LEDGER定向本计划，未放宽网络或电池边界。

## A1：动态残差证据

先新增50项测试：RED48失败/2通过、错误0、退出1，原因是新模块/新模式缺失。证据`tests/dynamic-evidence-red-1020101913411596/`。最小实现后的相关112/112通过、退出0，见`tests/dynamic-evidence-green-1020105110556739/`。

补充null有效时间网格的反例：2项RED均失败、错误0、退出1（dynamic-null-grid-red-1020105347118209），复现提前len(None)导致TypeError而非约定ValueError。最小修复后相关114/114通过、失败/错误/跳过0、退出0、96.29秒，见`tests/dynamic-evidence-final-related-1020105409264804/`。这些运行网络/电池/非电池solve均0。

审阅还纠正Prompt对“两点温度必然不可辨识”的绝对表述：稀疏样本不构成稳健趋势或唯一参数恢复的证明，但热混淆本身不强制弃权。该物理措辞由独立静态审阅核对；软件仅检查新Prompt接线/词数/签名，不能替代真实LLM行为验证。274词Prompt修订后最终相关114/114通过，失败/错误/跳过0、退出0、98.74秒，证据`tests/dynamic-evidence-reviewed-1020105652590963/`。原initial RED、null-grid RED、各GREEN和静态初审/补审均保留。

A1保留旧signed/decision接口及旧Prompt；新增dynamic_decision_v3、纯只读dynamic模块和独立Prompt。已测试独立U/T时间网格、实际起点、unknown/null、样本抽稀与全动态均值、未来记录拒绝、原后验/标签不变及联合删历史/摘要篡改。真实RMSE仍按全部原观测计算，没有删除初始点或补零。

## A2：请求绑定的有限区域目录

新增electrothermal_region_catalog.py的build_region_catalog、catalog_proposal_binding、catalog_region_contract、resolve_catalog_region及脱敏catalog_archival_json。新增catalog独立Prompt和测试；修改electrothermal_config.py、electrothermal_llm.py、electrothermal_audit.py。新配置region_proposal=catalog_v1需dynamic_decision_v3+candidate_aware_v1+fair_region_v1；原bounds_v1缺省和旧Prompt保留。候选池、标量化、GP/EI/原Lift与守卫没有改变。

host对原有eligible候选提供三种受限宽度，以稳定ID表达几何，模型仅选择ID/过去证据或none。完整专业请求另行绑定，response_contract虽排除循环hash，仍由审计独立重建逐项核对。controller只向transport传clone，私有原请求不受其改写；归档原正式回复（脱敏）、独立resolution及发生污染时的clone证据。审计从可信冻结context/历史重建，而非相信多个派生文件相互吻合。

首批56项RED49失败/7通过、错误0、退出1（region-catalog-red-1020110259926960）；扩充后61项RED54失败/7通过、错误0、退出1（region-catalog-complete-red-1020110438520756）。最小实现及旧相关回归135/135、退出0、129.18秒（region-catalog-green-1020110806896454）。

加固7项RED3失败/4通过，分别复现合法原回复遇transport污染后无法审计、正式回复未脱敏、诚实NaN失败回复在HTTP核对时误报（region-catalog-hardening-red-1020111343865399）；修复后7/7、退出0（region-catalog-hardening-green-1021014353132375）。新增自洽联合篡改测试：重算目录ID、摘要、绑定、回复、resolution及canonical矩形，先确认resolver可解析该派生组合，再确认全审计仅因独立目录重建而拒绝。

进一步对mutation证据本身篡改：4项RED3失败/1通过（region-mutation-proof-red-1021014444811968），修复异常捕获范围后相关211/211、退出0、189.05秒（region-catalog-reviewed-related-1021014520154230）。独立审阅又指出非法JSON键可能夹带token及clone内层类型未验证；新增4项RED全失败（region-catalog-review-security-red-1021014913704844），修复后4/4、退出0（region-catalog-review-security-green-1021015620807560）。全部这些针对性运行网络/电池/非电池solve均0，错误及跳过0；初审与所有失败证据均保留。

## 当前限制与剩余工作

A1/A2代码及独立任务补审已完成。A2最终相关回归215/215通过、失败/错误/跳过0、退出0、202.64秒（tests/region-catalog-final-related-1021015653783594）；包含76项新目录测试。独立初审、补审与安全关闭报告位于证据根目录task2-review*.md/json；已确认问题全部关闭。最终全量尚待完成，不将历史530或针对性结果冒充最终全量。新版本真实API响应、DFN收益、参数唯一恢复和实测辨识均未验证；旧3C及既有失败/负结果保持原样。
