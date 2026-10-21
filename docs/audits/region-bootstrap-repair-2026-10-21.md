# Windows 虚拟环境启动器修复与受控恢复就绪检查

本记录追加真实启动结果，保留此前软件验收与封存。专用凭据已按用户授权写入Windows用户环境变量，仅记录存在性与设置结果，不回显、不写入项目、命令参数、日志或源码快照。凭据尚未经服务端验证。

## 实际启动结果

2026-10-21北京时间21:45:52启动原单次预检监督器，原10800秒总墙钟开始。启动器退出1，未超时，用时约0.734秒。错误是execute.worker中直接比较os.getppid与launcher_pid；异常发生在begin_phase、RunStore创建及HTTP请求之前。

原budget-journal.jsonl仅有一个start事件，无phase_start或charge。实际API=0、DFN=0，不能写成API认证失败或完成了预检，更没有产生新的RMSE/HV结果。原总截止时间仍为北京时间2026-10-22 00:45:52.014660，未重置。

失败记录保留于：
`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-gain-validation-20261021/runtime/`中的live-launch.json、preflight-started.json、preflight-supervisor.json、preflight-process.log及budget-journal.jsonl。

## 根因与最小修复

同一解释器的无网络/求解复现实验得到：启动器pid37064，Popen.pid17336，实际Python子进程pid41808、ppid17336。Windows虚拟环境python.exe先转发到基础Python，因此真实工作进程的直接父进程是转发器，原相等判断错误拒绝合法进程链。此前865项测试通过，但没有覆盖这条真实启动链；这是本轮新增外部启动器的问题。

原封存代码不编辑。修复候选位于同级runtime-bootstrap-fix-20261021：

- execute.py保留直接父进程校验，并只允许一层经进程快照、父pid、存活性及完整可执行路径共同验证的虚拟环境转发器；不接受任意祖先进程。
- 显式恢复适配器读取原预算日志、原启动哈希及截止时间；不创建新的全局origin或预算。新的一次60秒外层预检窗口仍受原总截止时间限制，API请求仍30秒/1536 tokens、不重试，全部限额不变。
- bootstrap-origin.json固定原封存与启动来源；候选验收后还须有绑定候选封存、原start哈希和原截止时间的bootstrap-recovery-approved.json。没有这份明确授权时，候选拒绝真实启动。
- freeze_runtime.py如实记录继承的原始计时、次数及恢复授权待定状态，修正候选封存仍显示“计时未开始”的审阅发现。

模型、数据、数值算法、GP/EI/Lift/守卫、Prompt、目标尺度及科学源指纹a98cc1890ea99d4fca5b4b9a9cd53be7b6f97cac16128ac502bd35c7349bcc90保持不变。本修复不属于新Region公式或为取得阳性而调整方法。

## 本轮验证

失败测试18项全部因启动链/恢复保护缺失失败，退出1；最小实现后18/18通过，退出0。执行器回归102/102通过，退出0。审阅发现的继承时钟报告字段另有RED1→GREEN19/19，退出0，全部网络和电池求解尝试为0。这些是不同运行，不累计冒充一个总测试数量。

完整仓库与候选回归已完成：884/884通过，失败0、错误0、跳过0，退出码0，用时1210.60秒。network_attempts=0、battery_solve_attempts=0，允许的现有非电池Simulation.solve为2次。证据在BASE/tests/gain-runtime-full-bootstrap-1021140027348394/，包括pytest.log、junit.xml、exit-code.txt、result.json；BASE为上述bo-repair-work/20261017_et_implementation。

修复候选frozen-runtime.json的SHA256为e6ada7cd9f79d9d847cacce18b78ce57972b7769b0fc9d3116f5db1ca011518d。封存绑定测试前后相同的14项执行/批准/来源/测试文件，以及实际完整结果、JUnit与调用边界；如实记录原时钟已开始、原start哈希及截止时间、未创建新时钟、API/DFN=0、恢复授权待定。独立review-bootstrap.md确认无遗留Critical/Important；Minor是增加错误转发器路径/祖先等负面测试，当前实现按静态审阅会拒绝这些情况。

## 恢复边界

原协议约定失败即停、不自动重试；本次本地启动已失败且原60秒预检窗口已结束。因此修复完成不自动重放。软件验收、独立审阅和候选封存均已完成，受控恢复的具体待审协议为候选目录controlled-recovery-protocol.json：只发送首次实际API预检，继续原512DFN/121API上限和00:45:52原总截止时间，额外次数与总墙钟均为0；请求30秒/1536 tokens，新外层窗口至多60秒且受原总截止限制，通过后按原协议继续。预检失败即停。未确认前，保持API/DFN=0。
