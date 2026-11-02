# 四组消融结果与独立复核（2026-11-02）

**结论：WarmStart有平均RMSE收益，但尚无稳定的前十轮多目标收益；当前Region没有稳定的附加增益。**

## 执行与核验

源版本 f22e3ae。实际开始 2026-11-01T13:50:13.326439+08:00，结束 2026-11-01T18:50:29.684044+08:00，耗时 5.005 h。

5个种子 × 4组 × 50轮，20/20组完成，共1000轮BO；另有10个16点初始化池。实际2320次DFN、505次API（5次WarmStart、500次Region）。主试验和报告退出码均为0。

本次独立复核全部曲线RMSE、固定指标空间HV、候选来源、共享初始化/权重和累计账本：107个源码哈希、30阶段全部通过，与原analysis.json完全一致；新增API/DFN均为0。

工况为0.5C/1C各60s的真实DFN合成观测。电压和温度RMSE来自同一个对称折中Pareto代表点；HV包含初始化池全部16个实评点，GP只导入选中的8点。HV空间固定为(F_U/0.1,F_T/1)，参考点(10,10)，上界100。所有均值与配对比较均以5个种子为单位。

## 前十轮与第五十轮

|轮次|方法|电压RMSE(mV)|温度RMSE(K)|HV|
|---:|---|---:|---:|---:|
|0|BO|6.011556|0.04691095|99.425593|
|0|BO+WarmStart(v3)|4.098420|0.04631091|99.364916|
|0|BO+Region|6.011556|0.04691095|99.425593|
|0|LLMBO(v3+Region)|4.098420|0.04631091|99.364916|
|1|BO|6.011556|0.04691095|99.523075|
|1|BO+WarmStart(v3)|4.098420|0.04631091|99.373771|
|1|BO+Region|6.011556|0.04691095|99.520798|
|1|LLMBO(v3+Region)|4.098420|0.04631091|99.373771|
|3|BO|6.011556|0.04691095|99.596066|
|3|BO+WarmStart(v3)|4.144990|0.04122101|99.382711|
|3|BO+Region|5.901077|0.04117672|99.538584|
|3|LLMBO(v3+Region)|4.144990|0.04122101|99.382673|
|5|BO|6.011556|0.04691095|99.596142|
|5|BO+WarmStart(v3)|4.656918|0.03168840|99.445845|
|5|BO+Region|5.187593|0.05005573|99.549306|
|5|LLMBO(v3+Region)|4.144990|0.04122101|99.404790|
|10|BO|5.523481|0.03226557|99.624235|
|10|BO+WarmStart(v3)|3.800987|0.03987408|99.585517|
|10|BO+Region|5.634468|0.03521952|99.609743|
|10|LLMBO(v3+Region)|3.747092|0.03976102|99.494570|
|20|BO|3.527741|0.02791081|99.671474|
|20|BO+WarmStart(v3)|3.207686|0.03468799|99.675995|
|20|BO+Region|3.129438|0.03562080|99.739686|
|20|LLMBO(v3+Region)|4.019137|0.03039770|99.671249|
|50|BO|2.630533|0.02462925|99.806589|
|50|BO+WarmStart(v3)|2.081234|0.02206292|99.843555|
|50|BO+Region|1.989105|0.03105050|99.828747|
|50|LLMBO(v3+Region)|1.970324|0.02308938|99.797183|

预注册主要早期终点为梯形平均AUC_HV(0..10)，单位与HV相同；不是只比较第10轮。下表RMSE轨迹AUC为补充描述指标，并非新增主要终点。

|方法|前十轮HV AUC|电压轨迹平均RMSE(mV)|温度轨迹平均RMSE(K)|
|---|---:|---:|---:|
|BO|99.584710|6.066890|0.03844411|
|BO+WarmStart(v3)|99.442376|4.376768|0.03715084|
|BO+Region|99.556752|5.683810|0.04156706|
|LLMBO(v3+Region)|99.418631|4.038530|0.04161950|

## 配对差值

差值=前者−后者。HV正值为改善；RMSE负值为改善。逐种子差值保存在paired-summary.csv。

|检查点|配对|电压差(mV)|温度差(K)|HV差|HV改善种子|
|---|---|---:|---:|---:|---:|
|AUC_0_10|BO+WarmStart(v3) − BO|-1.690122|-0.00129326|-0.142334|1/5|
|AUC_0_10|BO+Region − BO|-0.383080|+0.00312295|-0.027957|2/5|
|AUC_0_10|LLMBO(v3+Region) − BO+WarmStart(v3)|-0.338238|+0.00446865|-0.023744|2/5|
|AUC_0_10|LLMBO(v3+Region) − BO+Region|-1.645280|+0.00005244|-0.138121|0/5|
|AUC_0_10|LLMBO(v3+Region) − BO|-2.028360|+0.00317539|-0.166078|0/5|
|10|BO+WarmStart(v3) − BO|-1.722494|+0.00760851|-0.038718|1/5|
|10|BO+Region − BO|+0.110987|+0.00295395|-0.014492|2/5|
|10|LLMBO(v3+Region) − BO+WarmStart(v3)|-0.053895|-0.00011306|-0.090947|2/5|
|10|LLMBO(v3+Region) − BO+Region|-1.887376|+0.00454150|-0.115173|1/5|
|10|LLMBO(v3+Region) − BO|-1.776389|+0.00749545|-0.129665|2/5|
|50|BO+WarmStart(v3) − BO|-0.549299|-0.00256633|+0.036966|3/5|
|50|BO+Region − BO|-0.641429|+0.00642125|+0.022158|3/5|
|50|LLMBO(v3+Region) − BO+WarmStart(v3)|-0.110911|+0.00102647|-0.046372|2/5|
|50|LLMBO(v3+Region) − BO+Region|-0.018781|-0.00796111|-0.031564|2/5|
|50|LLMBO(v3+Region) − BO|-0.660209|-0.00153987|-0.009406|2/5|

## Region确实生效，但未显示稳定性能收益

500次Region请求中，474次有效动作/非零tilt，104轮改变了选点。前10轮的100次Region请求全部有效，其中26轮改变选点，所以前10轮负增益不能归因于传输失败。全部26次传输失败按协议回退；其中24次为种子162634的BO+Region在响应头前TLS EOF，另2次为种子513225的LLMBO远端断开。失败轮完整保留在主分析中，不删掉。按归档network_diagnostic逐项分类见region-diagnostics.json。

应区分action_valid、tilt_applied和selection_changed。旧summary字段accepted与选点变化对应，不能把其余有效回复叫做校验失败。

LLMBO自身有248/250次有效tilt，而第50轮HV仍只有2/5优于WarmStart-only，因此不能把缺乏增益仅归因于传输。五个LLM初始化池各16个点全部来自真实LLM回复，没有Sobol补点。组间配对结果衡量整个策略；没有求解未选择的反事实点，不能据单轮反馈断言该轮Region比plain候选更好。

## 可以与不可以得出的结论

- WarmStart：第10轮电压误差低于BO，但温度误差更高，HV和主要早期HV AUC均落后。第50轮两个平均RMSE均更低，HV均值领先0.036966，仅3/5种子领先；是有限的平均收益，不能声称稳定加速双目标收敛。
- Region-only：第50轮电压更低，但温度更高；HV均值小幅领先，3/5种子领先。没有跨两种初始化的稳定正收益。
- Region加到WarmStart上：第10轮和第50轮HV均值分别下降0.090947和0.046372，后者仅2/5种子改善。当前不支持默认叠加Region优于WarmStart-only。
- 完整LLMBO：第50轮折中代表点两个平均RMSE均低于BO，但整条Pareto前沿HV略低。代表点质量和Pareto覆盖是不同指标，不能互相替代。
- 初始LLM池代表点电压较好而HV较低，提示单点质量与前沿覆盖存在差别；该现象不足以证明Prompt片面追求电压或公式漏掉温度。
- n=5且只有60s合成窗口；不作显著性、普适有效、参数唯一可辨识或实测成功结论。没有修改Prompt/Region公式、筛除负结果或因表现不佳重跑。

后续应先分析双目标前沿覆盖与Region选点贡献，再用预留种子作独立确认。这里仅汇报和审计，不启动新实验或更改已冻结方法。

## 证据

- 原始试验：`D:\Users\aa133\Desktop\LLMBO_Para\runs\f1101`
- 复核与图表：`D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\fourarm-results-review-20261102`
- verification.json / recomputed-analysis.json：独立重放证明。
- summary-statistics.json / paired-summary.csv / all-rounds.csv：全部统计、逐种子差值与逐轮曲线。
- region-diagnostics.json / initialization-composition.json：动作、回退与候选来源。
- four-arm-curves.png / four-arm-curves.pdf：前十轮和全五十轮均值曲线。

[完整逐轮CSV](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/fourarm-results-review-20261102/all-rounds.csv) · [配对统计CSV](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/fourarm-results-review-20261102/paired-summary.csv) · [复核证明](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/fourarm-results-review-20261102/verification.json)

![四组前十轮与全五十轮曲线](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/fourarm-results-review-20261102/four-arm-curves.png)
