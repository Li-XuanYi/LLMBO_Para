# P0 修复后的本地与 ZJU 运行

本轮只修改代码、运行离线测试与人工问题验证。没有连接 ZJU、上传文件、调用 LLM 或运行真实 DFN。远端 Linux 环境尚未实测，必须在目标机器执行 preflight。

## 把代码带到远端

本地修改不会自动出现在您 clone 的仓库中。先把本轮修改和新增文件提交、推送到您的仓库，再在远端 clone/pull 对应提交。不要使用 `git add .` 把历史 deliverables 或数据一起提交。可用本轮交付的源码包直接传递代码；源码包不包含数据、凭据、虚拟环境或历史结果。

`data/raw/` 和 `runs/` 被 Git 忽略。您需自行把 XLSX 放到远端，并保留文件原样；不能仅凭 clone 得到它。旧 runs 无需传输。本轮把原随机族的 8 个参数向量保存在 `configs/bo-repair-initial-points.json`，没有把旧仿真曲线当作新缓存。

在本机 WSL 中执行 `ssh zju`；以下命令在登录后的 ZJU 终端执行。工作目录约定为 `/home/yqt/XuanyiLi/LLMBO`。仓库 URL 和实际 XLSX 路径由您填写。

```bash
cd /home/yqt/XuanyiLi
git clone <您的仓库URL> LLMBO
cd /home/yqt/XuanyiLi/LLMBO
python3.12 -m venv .venv
source .venv/bin/activate
export OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 OMP_NUM_THREADS=1
export PYBAMM_DISABLE_TELEMETRY=true PYTHONUTF8=1
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p "bo-repair-work/setup-$STAMP"
python -m pip install -r requirements-research.lock -r requirements-test.lock \
  --log "bo-repair-work/setup-$STAMP/pip.log"
python -m pip freeze > "bo-repair-work/setup-$STAMP/freeze.txt"
python -X utf8 -B -m pytest -q \
  --basetemp="bo-repair-work/setup-$STAMP/pytest-temp" \
  --junitxml="bo-repair-work/setup-$STAMP/pytest.xml" \
  > "bo-repair-work/setup-$STAMP/pytest.log" 2>&1
```

测试通过后再启动实测辨识。脚本会从当前项目的 `src/` 导入代码，不要求安装 editable package。Python 必须是 3.12；安装失败时不要悄悄替换 PyBaMM 或数值库版本，保存 pip 日志后定位平台/镜像/版本原因。

## 先检查，再评价初始点

例如将数据放在 `data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx`。

```bash
WORKBOOK="$PWD/data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx"
sha256sum "$WORKBOOK"
python -X utf8 -B scripts/run_bo_repair.py preflight --workbook "$WORKBOOK"
python -X utf8 -B scripts/run_bo_repair.py prepare --workbook "$WORKBOOK"
```

SHA-256 应为 `6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7`。preflight 不调用 DFN。它检查数据、配置、核心依赖、线程设置和初始向量；报告写入新的 `bo-repair-work/remote/<运行ID>/`。

`prepare` 会真实评价固定的 8 个初始向量，合计 32 次倍率求解，独立记录这笔共同成本。必须 8 个都完整覆盖四倍率才能继续；出现失效则保留所有轨迹和诊断，不自动替换初始点。它打印当前机器上的 `initial_plan` 路径。设置为下文的 `PLAN`。

评价实现源码已变化，因此旧预筛缓存会按原有源码指纹校验被拒绝。这是预期行为，不能删除校验绕过。新 plan 也依赖当前主机上的原始记录路径；移动目录、修改源码或物理配置后应重新验证/准备，不能直接复制 plan 当作可移植缓存。

## 四组小规模真实对照

```bash
PLAN="/home/yqt/XuanyiLi/LLMBO/bo-repair-work/remote/<prepare运行ID>/initial-plan.json"
python -X utf8 -B scripts/run_bo_repair.py smoke \
  --workbook "$WORKBOOK" --initial-plan "$PLAN" --iterations 5 --d-strategy local
```

四组按顺序执行，各自复用上述 8 个经当前代码验证的初始评价，再做 5 次 BO。

| 组 | 候选与评分 | GP 训练数据 |
|---|---|---|
| A_original | 原全局 Sobol 池、原 Composite EI | 完整四倍率有效点 |
| B_local | 局部/全局混合池、原 Composite EI | 完整四倍率有效点 |
| C_joint | 原全局池、EI × 联合完成概率近似 | 完整四倍率有效点 |
| D_partial | 与 B 相同的策略（本命令） | 各倍率自己的有效点 |

`--d-strategy joint` 则让 D 与 C 使用相同策略。应在查看初步证据后明确选择并固定；local 是便于先检查闭环的默认选项，尚非真实 DFN 中的优胜结论。

全部使用 64 个候选、64 次 MC、2 次 GP 坐标搜索、同一初始集/种子/物理配置/评价预算。5 次 BO 的四组新增成本最多为 80 次倍率求解（重试次数仍为 1）；加共同初始评价为 112 次。此前取得初始参数的历史预筛成本另列在参数来源文件中，不把它隐藏为零。

局部池默认 48 个局部候选加 16 个全局候选，归一化半径 0.02；每第 5 次**实际评价**强制全局探索。边界靠拒绝采样处理，不截断参数，也不改原始物理边界。连续 3 次局部成功扩大半径，连续 2 次明确覆盖失败缩小半径；含数值错误的评价不用于收缩。

每个候选的轨迹、RMSE、失败类别、训练样本 ID、GP 状态、原 EI、完成概率、实际评分、候选来源、全局配额和半径反馈都保存。某组出错会记录失败并继续其余组；`comparison.json` 给出整组结果，单组 `events.jsonl` 给出候选与倍率进度。部分失败任务必须先定位原因，不能把失败组从比较中删掉。

## 检查结果与正式预算

```bash
python -X utf8 -B scripts/run_bo_repair.py status --run-directory "<某组运行目录>"
```

查看 `comparison.json` 中各组的 `bo_candidate_valid`、`gp_training_counts`、`initial_best_objective_v`、`best_objective_v`、`rate_solve_attempts` 和 `audit_passed`。有效率提升不等于电压拟合精度提升。保存具体失败轨迹后再判断物理截止与数值失效。

小试结束后才考虑 25 次 BO。正式入口要求明确开关、同设置的小试报告、通过审计且 B/D 至少得到 1 个新完整有效点。

```bash
SMOKE="<上一步打印的comparison_path>"
python -X utf8 -B scripts/run_bo_repair.py formal \
  --workbook "$WORKBOOK" --initial-plan "$PLAN" --iterations 25 \
  --d-strategy local --smoke-report "$SMOKE" --allow-formal
```

这是新运行，从同一 8 个初始点评价缓存开始，每组再做 25 次；不会把小试的 5 次接在前面冒充相同预算。四组新增为 100 个候选/400 次倍率求解。共同初始成本在报告中引用一次，arm 的 cache_hits 不计为新增 DFN 成本；与小试累计核算时也不能重复计算已经执行的 prepare。

本入口关闭两个 LLM 组件，不需要 API 密钥。普通 BO 的有效反馈闭环得到真实小试支持之后，再单独恢复 LLM 四组消融。P1 的 GP 超参数与 MC 改进尚未混入本轮。

## 回滚

从配置移除 `optimization.bo_repair` 即恢复全局候选池、原 EI 与完整四倍率 GP 数据集；新反馈字段仅增强日志。不要把不同配置的结果写到同一运行目录。需要完全恢复代码时，使用本轮源码差异和 `bo-repair-work/<本地记录ID>/before/`，不要覆盖历史 runs。
