# 成功案例参考与拒绝反馈初始化

2026-10-15 用户确认继续0.5C、1C、2C、3C（没有4C），允许下一轮新增最多20个返回候选和5次生成请求，提供已核验成功案例作参考，不预置有效起点。仍要求原参数范围、完整时段、禁止外推；本轮BO0。

`scripts/run_agent_warmstart.py` 共用原运行器，显式选择 `configs/agent-success-reference-warmstart.json`。每次最多4点，真实验证后继续向Agent反馈非法参数、库存和截止原因；优先在成功案例邻域对失败点作小幅可解释修订，不通过程序夹紧数值，也不缩小物理参数范围。

两条历史案例均与当前数据/物理签名及源码一致，四倍率完整，平均RMSE为45.474和45.015mV。它们只进入上下文，不能当成新初始缓存。完整照抄或归一化距离低于现有0.001阈值的近似复制均拒绝并占候选预算。全部新8点必须由Agent另行提出、真实仿真通过；达到目标立即停止，否则任一上限到达便报告不足。

父链24点纯提示词+40点Agent反馈的全部64个返回候选、57个DFN候选、228次倍率求解和11次API继续累计。每个父计划及曲线都逐层校验；已有拒绝和完整观测保留到下一轮，避免只保留最近一轮而丢失早期记录/成本。两个成功参考的8次历史倍率求解另列，其更早的参数搜索成本没有被冒充为零，因此本轮不是从零开始的公平消融。

新增预算只计算本轮返回的候选；非法、重复、近重复及库存拒绝均占额度，空响应/协议错误占请求次数。没有LLM候选池选择、随机补位、初始状态修改、截止时间缩短或外推。

```powershell
Set-Location "D:\Users\aa133\Desktop\LLMBO_Para"
& ./.venv-pybamm312/Scripts/python.exe -B scripts/run_agent_warmstart.py --settings configs/agent-success-reference-warmstart.json --preflight-only --output runs/agent-reference-preflight
& ./.venv-pybamm312/Scripts/python.exe -B scripts/run_agent_warmstart.py --settings configs/agent-success-reference-warmstart.json --prompt-for-key --output runs/agent-reference
```

CPU串行，Python3.12.10/PyBaMM25.10.2，仍用Reference/Chen2020固定初始浓度、电解液扩散倍率1.5及推算电流2.5/5/10/15A。API使用已指定OpenCode模型和代理，发送已批准的摘要；密钥隐藏输入，不落盘。

每次输出到唯一目录，旧运行不覆盖。离线诊断、测试、命令和后续结果在 `bo-repair-work/20261015_agent_guidance_audit/` 保存。真实接口/仿真启动前必须通过配置、历史、成功参考和主机资源检查。

本次实际使用4次请求、16个返回候选，真实评价12点，取得8个完整有效新起点后提前停止。最佳四倍率平均RMSE44.941mV，BO仍为0。见 [实验结果与完整成本审计](audits/agent-success-reference-pilot-2026-10-15.md)。
