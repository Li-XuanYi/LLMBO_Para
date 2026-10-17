# Stage C 软件验收（2026-10-18）

新增electrothermal_llm.py、两份约250词英文Prompt和electrothermal_audit.py；接入独立MOOptimizer与workflow。只复用ARD Matérn后验、Sobol、现有安全HTTP传输和纯数学区域机制，没有启用额外核、先验、目标或热模型。

全量回归：{'tests': 301, 'failures': 0, 'errors': 0, 'skipped': 0, 'passed': 301}，退出码0；pytest.log、junit.xml、exit-code.txt、result.json位于D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\tests\C-full-1017163512706421。边界：{'network_attempts': 0, 'battery_solve_attempts': 0, 'allowed_nonbattery_simulation_calls': 2}。C3专项15/15通过。最初两次C1验收命令误写不存在的可选旧测试路径，退出码4、0测试；已修正为实际test_chat_transport.py并通过，未当作产品失败或成功测试计数。

WarmStart按Pareto层级、平衡质量、参数maximin和稳定ID决定选择；全部24种排列与预算不足均测试。WarmStart-only/Full共享同一曲线核验初始化计划，导入0新求解/0新WarmStart请求。Region使用同轮后验协方差、Gaussian EI和冻结上下文；方差、真实Y及训练标签不变；错误、弃权、低置信度和失效守卫回退plain EI。采纳且新评价才更新信任。

独立审计从原始曲线重算两类RMSE、参数映射、签名、历史标签/GP/EI、Region/信任、Pareto/HV与成本。温度档案任意采样点受完整内容指纹保护。专项发现并修复了HTTP重试档案名冲突、真实JSON tuple/list签名差异、共享计划BO评价ID受初始化计数影响及未观测曲线点篡改漏检；相应红/绿证据均保留。

本轮实际API0；真实DFN尚待最终审阅后执行已批准12次合成预算。三模式通过软件合成与mock接口，不构成LLM真实效果、参数唯一性或实测辨识证据。旧schema1/旧四倍率缓存和电压目标继续由旧路径处理。

最小实测验证：确认真实电流轨迹/时间、T单位及测点、初态、环境与共同冷却；确认C/G范围和固定几何/扩散活化能来源；冻结R3配置、数据hash、尺度和HV参考点。先验证一个物理候选覆盖全部选中观测，再另批等预算多种子三路线对照。可靠3C另建R4配置和归档，不改旧文件或混合HV成绩。
