# 新版Region消融尝试与受控恢复（2026-10-19）

**没有完成两臂消融。** 实际累计30次真实DFN、3次API；15个不同的完整目标对，8点初始化计划验证有效，但原协议要求16个不同候选。两臂BO和Region请求均为0，没有可比较的方法RMSE/HV结果。

## 授权与实际执行

用户新批准112次DFN/23次API/1800秒：0.5C/1C各60s，真实LLM筛选16选8，共享初始化，WarmStart-only与eligible Full各20轮。原始启动北京时间20:19:07，截止20:49:07。后续人工仅授权补1个不重复候选，最多额外2次DFN，保留原总额和截止；失败不再自动恢复。原失败记录与预算未重置。

- 首次WarmStart回复格式有效，16条建议中1条重复，实际得到15个不同且完整的电压/温度目标对，消耗30次DFN。
- 第二次补足请求HTTP200、finish_reason=stop，但message.content=null，解析失败。原运行退出码1，耗时253.035秒。
- 人工恢复保留已用30次DFN/2次API，第三次请求仅需1候选。回复格式、签名与参数范围全部通过，但返回[0.42,0.5,3.16e-14,3.16e-14,45.0,0.09]，与eval-000008-ece11e37064a重复，而且该点已显示在本轮payload.history中。
- 重复点被拒绝，没有额外DFN；恢复段退出码1，耗时8.788秒，在原截止前停止。累计30/112次DFN、3/23次API；没有第四次WarmStart，也没有随机填点或改成15选8继续。

## 验证层级

- 本次启动前监督器mock测试3/3通过、退出码0；两臂各20轮软件预演通过，112次代数调用、真实API/DFN0。此前49项Region回归是前一轮记录，不作为本轮重跑数量。
- 15个真实候选的60个倍率/通道RMSE从归档曲线独立复算通过，8点计划严格签名加载通过。这验证已有初始化输出，不是两方法辨识对照成功。
- 没有完整MO summary或20轮结果；不补造完成文件，不标记完整实验deep审计通过。恢复初始化仅保留历史和请求证据，原failed及未完成状态保持。
- Region本次仍未被调用。本次失败发生在WarmStart唯一候选补足，不证明Region方法失效，也不证明LLMBO-MO优劣。没有强度/门槛/核/热模型改动。

## 证据与边界

- [原尝试](D:/Users/aa133/Desktop/LLMBO_Para/runs/ra/20261019T121908Z_cb5cad9c2b0a_779d083a)，stopped-execution-evidence保存原运行脚本/授权/日志/SHA256。
- [人工恢复](D:/Users/aa133/Desktop/LLMBO_Para/runs/rac/20261019T124539Z_eddbcefeffdb_7d59146e)，controlled-recovery-evidence保存恢复脚本、原时间锚点、成本、回复校验与SHA256。
- [60通道复算](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/eligible-ablation-20261019T121659355129Z/stopped-initialization-check.json)；[回复逐字段核验](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/eligible-ablation-20261019T121659355129Z/controlled-resume/response-verification.json)。

使用已有已知参数DFN合成观测，非实测辨识；旧3C排除保持。主工程、原XLSX、旧实验、参考工程与产品源码未改。原剩余额度不构成自动继续授权。后续若改变筛选协议或超过原截止，需要新的明确授权；本次不再恢复。
