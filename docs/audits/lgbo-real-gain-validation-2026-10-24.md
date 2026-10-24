# LGBO 工程整理前后真实 API＋DFN 合成对照

日期：2026-10-24。执行依据：已获用户批准的计划 `e9c030d`，`docs/superpowers/plans/2026-10-23-lgbo-real-gain-rollback-plan.md`。本报告记录实际结果；原计划中的待批准/零成本文字保留为历史，批准凭据单独归档。

**结论：九组主对照均完成，各 20 轮；三个种子中 Plain、Old Full、New Full 的选点、真实目标和最终指标逐项相同。未观察到工程整理引入的劣化，按预先约定持平保留，不启动第四种子、不回退。正式 Region 请求全部失败并回退 Plain EI，因此有效 Region 的增益仍未验证。**

## 1. 实际版本、范围和运行条件

工作树：`C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`；分支 `codex/electrothermal-mo-20261016`。主工程的原始 HEAD `811c4c699fa3a82fcd64060d71e2bd21c075383c` 和未提交修改保留。

|臂|产品版本|实际流程|
|---|---|---|
|Plain|`1363c6393039bd3ed8b1fd6a382e496828744840`|共享八点初始化＋普通 ParEGO / Gaussian EI，无 Region 请求|
|Old Full|`40a8c54f299db6f7b1bf3b9ecd45c7ab5e263ca1`|整理前 LGBO v2；Region 失败均回退 Plain EI|
|New Full|`1363c6393039bd3ed8b1fd6a382e496828744840`|整理后相同方法和 Prompt；Region 失败均回退 Plain EI|

仅使用 0.5C/1C、每工况 60 s 的已有真实 DFN 合成观测。人工恒流 2.5/5 A、环境 298.15 K、初温 300.15 K；这些是合成协议，不是实测条件的确认。PyBaMM 25.10.2、DFN＋集总热、Chen2020 和固定物性保持。电压观测网格 `[0,30,60] s`，温度网格 `[0,20,60] s`；不使用旧 3C，不生成新观测、不运行实测辨识。

旧/新源码分别对同一八个参数坐标重新求解，形成独立严格签名的初始化计划；不复用旧目标或回复、不改签缓存。三臂均为八点初始化＋20 次 BO，种子 `1709,3253,5501`，按计划平衡执行顺序。未调用 WarmStart API，不检验 WarmStart 生成能力。

所有臂共享候选预算 `global_pool_size=512/local_pool_size=8`、`gp_sweeps=4`、局部半径 0.2，单线程、不重试。固定目标尺度 `[0.1 V,1 K]`、`rho=0.05`、计划中三组权重和零误差理想点；HV 在 `Y/scales` 中使用参考点 `[10,10]`。每轮保持已有历史、冻结上下文和重新拟合语义。本轮没有修改产品代码、Prompt、Region 公式或热模型。

当前产品源码指纹 `0680445e62986e3ef61ce5e3ccf6952df3c31c5b0969fcc917679d384a446b9b`；旧 Git 归档实际指纹 `b9e8bac78c6c41ad6ebc7efbf7cfec0df14b8f30d072a70ba8a1eae4173c497a`。实际导入来源和各版本签名逐运行归档，保留 LF 归档和 CRLF 检出的区别。

## 2. 实际 RMSE / HV

以下每行在三个臂中完全相同。每次运行按固定均衡标量选一个 Pareto 折中参数，再报告该同一参数的两个误差；不将两个独立极小值拼接成一个结果。完整 Pareto 参数另行交付。

|种子|电压 RMSE `F_U`（mV）|温度 RMSE `F_T`（K）|HV|
|---|---:|---:|---:|
|1709|5.6216932018|0.0249596863|99.7595771693|
|3253|2.4825580963|0.0389043511|99.7574947902|
|5501|2.7861095385|0.0103561004|99.8453683753|
|三种子均值|3.6301202789|0.0247400459|99.7874801116|

New−Old、New−Plain 和 Old−Plain 的逐种子 HV / 折中 RMSE 差均为零；整个 20 轮的参数坐标和真实目标也相同。独立二维矩形面积复算九次 HV 均一致。HV 的参考面积为 100，不能将接近 100 解读为实测辨识精度百分比。

预先回退判据要求至少两个种子出现一致劣化、平均方向一致，并由第四种子复现。当前劣化种子数 0，`needs_confirmation=false/revert=false`。保留工程整理；没有运行备用确认，也没有执行 git revert。

## 3. API 与 Region 的实际参与情况

一次新建、诚实标记为软件上下文的预检成功：HTTP 200，响应完成，绑定和动作契约通过，47.125 s。该预检不参与选点或 DFN 评价。

正式 120 次 Region 请求：

|结果|次数|
|---|---:|
|读取响应头阶段超过截止时间|16|
|读取响应头阶段传输错误 `URLError`|104|
|收到完整正式回复|0|
|有效动作 / 实际均值调整 / 改变选点|0 / 0 / 0|
|回退 Plain EI|120|

全部正式错误都没有 HTTP 状态或响应正文。公共脱敏日志不足以区分 DNS、代理、TLS 或服务端连接故障；不能据此声称服务端拒绝、token 不足、Prompt 不合法或 Region 数学公式错误。正式请求 60 s、输出上限 8192 tokens；没有传输重试、自动换模型或端点。失败请求的实际 token 使用量未知，不按上限虚报费用。

**本次“增益为零”由实际全部回退路径产生，不能当成有效 Region 不优于 Plain 的实验结论，也不能据此宣称 LLMBO-MO 增益通过。** 真实 API 可用性是后续有效消融的前提；本次协议已关闭，不自动追加试验。

## 4. 成本、时间和隔离

|项目|实际 DFN solve|实际 API 启动|
|---|---:|---:|
|API 预检|0|1|
|旧/新源码各重新评价八点|32|0|
|九组主对照共 180 个新候选|360|120|
|合计|392|121|
|备用确认|0|0|

主对照初始化导入缓存命中 72 次，预筛拒绝 0，缓存拒绝 0，失败 solve 0；新候选评价没有缓存替代。初始化 16 个候选和主对照 180 个候选分开归因；完整真实目标对进入优化，未补零。实际 HTTP 启动不等于服务端已经收到请求。

真实阶段北京时间 2026-10-24 00:55:04 启动，01:50:00 完成，约 54 分 57 秒，退出码 0；未超过 472 DFN / 161 API / 三小时总上限。12 个拥有的进程树均验证停止，空闲抑制已释放。之后的静态复算、报告和封存不再发送 API 或执行 DFN；不延长真实试验窗口。

## 5. 软件验收与科学验收分层

|验证|本轮实际结果|退出码|
|---|---|---:|
|新鲜全量基线|1158 通过，失败/错误/跳过均 0|0|
|启动器最终定向测试|47 通过，失败/错误/跳过均 0|0|
|最终锁定版本全量回归 `ge-rg-final-full-r2`|1205 通过，失败/错误/跳过均 0|0|
|真实 DFN 合成运行深审计|11 个运行通过|0|
|归档曲线离线独立复算|268 份记录、1072 个逐倍率误差分量一致|0|
|HV 独立复算|9 / 9 一致|0|

软件测试进程禁止网络和电池 DFN 求解；两个已有的非电池 ODE 测试单独允许。RED / GREEN 过程和中间测试全部保留。第一次 `ge-rg-final-full` 为冻结补丁前的 1203 通过记录，不作为最终发布证据；最终接受的结果是源码保持冻结的 1205 项 `r2`。

软件验收通过、DFN 合成闭环通过；有效 Region 的科学增益尚未验证。实测层未执行，电流时序、温度单位和测点、初始状态及冷却条件仍需科研确认。60 s 稀疏合成数据不证明参数唯一可辨识、长期预测、实测拟合或统计显著优势。

## 6. 工程改动与审阅裁定

本轮产品源文件零修改。新增研究文件：

- `scripts/run_lgbo_real_gain.py`：显式预算、绝对截止、严格输入/来源冻结、父子进程记账、Windows 进程树监督和预先固定的回退判据。
- `scripts/lgbo_real_gain_worker.py`：隔离导入两个实际版本、真实评价与 API、严格初始化、独立指标和审计出口。
- `tests/test_lgbo_real_gain.py`：47 个失败后实现的研究入口测试；包括错误预算、来源混用、输入篡改、截止、崩溃后孤儿进程和完整软件闭环。
- 本报告。计划和旧记录保持。

研究实现提交 `bb3079c`；冻结输入修复及最终测试版本 `ca405a8`。未修改原参考工程；主工程的 HEAD、index、状态和 124 个受保护文件未变，原参考工程 55 个源码文件未变，旧交付 seal 的 86＋16 文件重新核验一致。

一次 fresh-context 审阅发现 Important 3 / Critical 0 / Minor 0，均经失败测试修复，最后完整回归通过；没有第二轮审阅。裁定及成本：

1. 使用原生 Windows ledger / 守卫代替 bash skill 脚本，并按用户要求保留工作树和证据；维护和磁盘成本增加。
2. 旧版采用确切 LF Git 归档，新版采用实际检出字节并各自新签名；换行差异是潜在归因因素，用运行时 Prompt 和实际数值轨迹一致性约束，不冒用历史指纹。
3. 父进程 RPC 在 HTTP / solve 开始前记账；非 daemon 隔离 worker 允许受监督的库子进程；增加调度复杂度，已用真实 spawn 软件闭环和硬截止验证。
4. 公共诊断隐藏服务端自由文本，因此对 401/403/404/503 保守终止；可能对暂时性 503 提前停止，避免不可用通道持续花费。此次没有这些状态。
5. 必须使用 Windows kill-on-close Job Object，处理根进程崩溃后仍存活的后代；启动器不提供较弱跨平台 live 降级。
6. 旧/新源码及 harness 独占冻结，开始请求、结果、确认和最终判定前核验；增加磁盘及哈希成本。
7. 同一来源冻结修复延伸至科学配置、坐标和首次初始化文件 SHA，禁止按臂重新计算后认可污染；因此增加一次完整回归。

工具更正：一次只读导入遗漏 bytecode 禁用，曾在旧工具目录创建单个 `__pycache__` 文件；已精确恢复旧目录，并将本次自建文件和恢复证据移至本轮归档，未改变旧记录内容。后续导入先禁止 bytecode。没有延后处理的审阅小问题。

## 7. 可检查的证据

归档根目录：`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/`。

- [批准及预算](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/approval.json)、[结论](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/main-decision.json)、[独立最终审计](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/final-audit.json)、[关闭记录](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/experiment-closed.json)。
- [每臂指标](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/case-RMSE-HV.csv)、[逐倍率 RMSE](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/representative-per-rate-RMSE.csv)、[逐轮指标](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/round-RMSE-HV.csv)、[完整 Pareto 参数](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/Pareto-parameters.csv)。
- [HV 图](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/HV-trajectories.png)、[RMSE 图](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/RMSE-by-seed.png)；同目录有 PDF、Pareto 图和归档原曲线图。
- [基线日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/tests/ge-rg-baseline/pytest.log)、[基线 JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/tests/ge-rg-baseline/junit.xml)。
- [最终回归日志](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/tests/ge-rg-final-full-r2/pytest.log)、[最终 JUnit](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/tests/ge-rg-final-full-r2/junit.xml)、[退出码和统计](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-real-gain-20261023/tests/ge-rg-final-full-r2/result.json)。
- 实际运行根目录 `D:/Users/aa133/Desktop/LLMBO_Para/runs/g23r/`：`p` 预检、`i0/i1` 初始化、`c00`—`c08` 九组主对照；保留请求、失败、原始曲线、签名、逐轮冻结上下文和深审计。对应源 pin、Windows 监督和记账链另在证据根目录。
- `delivery-seal.json` 覆盖本轮证据与实际运行文件，`seal-verification.json` 记录封存后逐文件复核；不包含凭据。报告完成后不自动恢复任何 API/DFN 工作。
