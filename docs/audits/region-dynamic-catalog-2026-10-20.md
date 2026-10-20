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

## 当前限制与剩余工作

A1代码与针对性软件验收已完成，独立审阅补审PASS、未解决问题0；全部GP/后验/原数值模块保持。A2目录ID实现和最终全量回归尚未完成，不声明本计划软件验收完成。历史530和A1相关114不冒充最终新全量结果。新版本真实API响应、DFN收益、参数唯一恢复和实测辨识均未验证；旧3C及既有失败/负结果保持原样。
