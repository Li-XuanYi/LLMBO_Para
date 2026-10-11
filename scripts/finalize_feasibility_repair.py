"""Archive repair changes and link verified outcomes without touching historical runs."""
from datetime import datetime, timezone
import difflib
import json
import os
from pathlib import Path
import sys
for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name]="1"
workspace=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(workspace/'src'))
from llmbo_para.audit import read_json
from llmbo_para.runstore import RunStore, sha256_file

archive=workspace/'runs/feasibility-repair/20261011T070943Z_6ece33a8830b_fd10f364'
screen=workspace/'runs/feasible-initial/20261011T073201Z_8476e784ee39_cb5ca591'
closure=workspace/'runs/closure-arms/20261011T075323Z_6cfd86797632_ddf8f218'
verification=sorted((workspace/'runs/verification').glob('*/verification-summary.json'))[-1].parent
tests=(verification/'tests.txt').read_text(encoding='utf-8-sig')
assert 'Ran 55 tests' in tests and '\nOK' in tests
verify=read_json(verification/'verification-summary.json')
assert verify['overall_exit_code']==0
screen_audit=sorted((workspace/'runs/screening-audits').glob('*/audit.json'))[-1]
assert read_json(screen_audit)['passed']
small=read_json(closure/'summary.json')
plan=read_json(screen/'initial-plan.json')
preview=sorted((workspace/'runs/deployment-previews').glob('*/preview.json'))[-1]
summary={'code_checks_passed':55,'verification_directory':str(verification),'screening_directory':str(screen),
    'screening_audit':str(screen_audit),'screening_cost':plan['screening_cost'],
    'small_bo_directory':str(closure),'small_bo':small,
    'repair_actual_candidate_evaluations':202,'repair_actual_rate_solves':808,
    'real_llm_task_attempts':1,'real_llm_task_successes':0,'model_list_requests':1,
    'api_error_directory':str(workspace/'runs/closure-arms/20261011T074638Z_6debfd913c53_3f0de0a0'),
    'models_probe_directory':str(workspace/'runs/api-model-checks/20261011T074815Z_0920ab6a1674_de663a39'),
    'formal_arms':{'completed':0,'running':0,'failed':0,'pending':4},
    'pending_decisions':['replacement API model; DeepSeek unavailable','random screening total limit; approved 200 exhausted with 4/8 valid points','explicit source/XLSX transfer consent for zju'],
    'remote_upload_performed':False,'deployment_preview':str(preview),
    'note':'Code and small measured-data closure verified. WarmStart live execution and four formal ablations are not complete.'}
report=workspace/'docs/audits/feasibility-repair-2026-10-11.md'
text=f'''# 有效初始点修复与实测验证（2026-10-11）

## 结论

用户已回复“同意建议 开始修改”。批准的筛选、缓存、失败继续、审计和成本统计已实现，55 项回归检查通过。实测数据可以训练四个 GP，并完成“采集函数选六参数 → DFN → 完整网格评分/失败记录 → 继续下一步”的小闭环。

正式四组各 25 次 BO 尚未启动。随机筛选达到批准的 200 候选上限，只有 4/8 完整有效点；接口不再提供原指定 DeepSeek 模型。两项选择已向用户提出，未擅自扩大预算或切换模型。远端源码/XLSX 传输授权仍单独待确认。

## 实现

- 复用 ParameterSpace、FourRateEvaluator、RunStore、四 GP、Composite EI、原有输入预检和结果审计。新增 FeasibleInitializer 调度，不另写一套仿真或评分器。
- 根据固定几何、初始浓度和累计放电量计算理想锂库存上限；不满足必要条件的点记录后拒绝，不调用 DFN。必要条件通过不代表仿真成功。
- 随机家族维持固定种子的归一化均匀随机生成。LLM 家族保持每批 20 个建议、独立 LLM 选择/失败后补选；可补选一个点，不以随机点替代。
- 每类先审计 2 个有效点，再扩展到 8；候选、拒绝、原始仿真曲线、来源和所有请求独立归档。每类上限 200 个 DFN 候选，随机原始生成上限 20000，LLM 生成/选择上限 10/30 次。
- 接受的真实曲线复算 RMSE 后进入初始 GP，核对源记录、数据/模型签名、仿真实现哈希和固定参数化。下游保存完整缓存来源，审计不依赖原缓存路径。缓存命中不计为新求解。
- BO 使用同样的必要条件检查。失败候选消耗一次迭代，保存原因和曲线，不生成罚分标签；四 GP 继续使用已有有效数据。
- 随机断点续筛保留原 RNG 位置、有效点和累计成本，只在新目录保存新增评价。预算仍按历史加新增总量限制；提高上限尚待用户选择。
- 全部家族与四组分别统计，失败家族成本仍保留。保存按 BO 迭代及按含预筛成本的 DFN 调用数两套曲线，区分共享实际成本与各组独立运行的归属成本。

## 保持的科学设定

六参数原范围、固定孔隙率、完整四倍率实测网格、禁止外推、四 RMSE 等权平均、2.5 V 截止和既有 DFN 设置未改变。仍为 Reference/Chen2020 初始浓度、等温 298.15 K、固定电解液扩散乘数 1.5；乘数是在同一数据上预校准的临时设置。XLSX 的电流为空，使用已记录的 5 Ah 倍率推算电流；不是实测电流。温度单位仍未确认，未把 T 列接入模型。

## 实测结果与成本

| 阶段 | 结果 | 新 DFN 倍率求解 |
|---|---|---:|
| 随机预筛 | 6720 个生成点，6520 次解析拒绝；200 个候选中 4 个完整有效、196 个失败 | 800 |
| 两点 GP 启动检查 | 复用 2 个实测有效点，四 GP 训练与深度审计通过 | 0 |
| GP LLM 真实请求 | 复用 2 点；API 返回 HTTP 503 / model_not_found，未得到分组 | 0 |
| 四点＋两步 BO 小闭环 | 4 次缓存命中；2 个 BO 候选均失败，流程继续并通过深度审计 | 8 |
| 全筛选记录重算和随机序列审计 | 重算全部 200 个候选，重放全部生成序列，通过 | 0 |

本轮新实测求解共 808 次倍率调用，来自 202 次候选评价；此前严格 8 点小试、截止诊断和电解液校准保留在历史目录，不混入本轮成本。API 实际尝试 1 次分组请求、另有 1 次模型列表 GET；未得到成功的实测 LLM 回答，WarmStart 实测阶段尚未运行。

随机筛选耗时约 {plan['screening_cost']['elapsed_s']/60:.2f} 分钟，接收速度约 {plan['screening_cost']['accepted_points_per_min']:.3f} 个有效点/分钟。若接受率相近，再补 4 点经验估计约 17 分钟，波动较大，不能保证。当前没有实验在运行，等待设置确认，正式实验没有可靠 ETA。

当前最优均值 RMSE 为 {small['best_objective_v']*1000:.4f} mV，来自随机筛出的有效初始点。两步 BO 没有改进该值；这不能作为 LLM 或完整方法优于基线的证据。

## 环境、路径与复现

机器 SCP，Windows 11，工作目录 D:/Users/aa133/Desktop/LLMBO_Para；解释器 .venv-pybamm312/Scripts/python.exe，Python 3.12.10、PyBaMM 25.10.2。数值线程和 DFN 工作进程均为 1，CPU 路径；资源快照显示较高系统负载，因此随机筛选采用低于正常优先级。

- 新模板：configs/21700-feasible-ablation.json；LLM 生成/选择/分组提示词保留在 src/llmbo_para/prompts/。
- 筛选与四组调度：scripts/run_ablation_suite.py。
- 无求解审计：scripts/audit_feasible_screening.py；小闭环：scripts/check_feasible_gp.py。
- 回归与完整软件验证：[验证档案]({verification.as_posix()}/verification-summary.json)。
- 实测筛选：[初始计划]({screen.as_posix()}/initial-plan.json)。
- 200 候选审计：[审计报告]({screen_audit.as_posix()})。
- 真实 BO：[结果]({closure.as_posix()}/summary.json)。
- 全命令、控制台、失败记录及修改前源码：[修复档案]({archive.as_posix()})。

CLI 用法见 README 的 Approved feasible initialization。正式运行必须从八点完整计划开始，默认每组再做 25 次 BO。新设置写新配置并保存 SHA，不覆盖旧运行。随机续筛实现已通过确定性回归，但 800 次新上限未获批准、未执行。

## 待确认与边界

服务商模型列表返回 29 个名称，没有 deepseek-v4-flash/dsv4flash；可选的 qwen3.7-flash 或 glm-5.3-flash 已提交用户选择。不得静默更换。已询问是否把随机筛选总上限从 200 提高到 800，原始随机生成上限仍为 20000；应复用既有记录，而非重跑。

zju 的独立环境已经准备好，本轮仅在本地制作部署预览，没有连接或传输。此前自动审批拒绝源码/XLSX 上传，理由是未获得该实测数据的明确传输授权。后续还需确认将源码和该 XLSX 上传到 /home/yqt/XuanyiLi/LLMBO。
'''
with report.open('x',encoding='utf-8',newline='\n') as stream: stream.write(text)
files=[]
for folder in ('src','scripts','tests','configs','docs'):
    files.extend(file for file in (workspace/folder).rglob('*') if file.is_file() and '__pycache__' not in file.parts)
files.append(workspace/'README.md')
changes=[]
for file in files:
    relative=file.relative_to(workspace); old=archive/'source'/relative
    before=old.read_text(encoding='utf-8-sig').splitlines(keepends=True) if old.exists() else []
    after=file.read_text(encoding='utf-8-sig').splitlines(keepends=True)
    changes.extend(difflib.unified_diff(before,after,fromfile='before/'+relative.as_posix(),tofile='after/'+relative.as_posix()))
with (archive/'repair.diff').open('x',encoding='utf-8') as stream: stream.writelines(changes)
store=object.__new__(RunStore)
store.path=archive.resolve(); store.events_path=archive/'events.jsonl'
store.write_json('final-source-sha256.json',{file.relative_to(workspace).as_posix():sha256_file(file) for file in files})
store.write_json('repair-summary.json',summary)
store.finish('completed_with_failures',summary)
print(json.dumps({'report':str(report),'repair_archive':str(archive),'checks_passed':55,'formal_arms':summary['formal_arms'],'pending_decisions':summary['pending_decisions']},ensure_ascii=False))
