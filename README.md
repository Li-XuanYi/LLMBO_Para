# LLMBO battery parameter workflow

This repository contains the reusable optimization and evaluation workflow for the research group's measured 21700-cell data. The current approved WarmStart pilot runs [scripts/run_agent_warmstart.py](scripts/run_agent_warmstart.py) with [configs/agent-success-reference-warmstart.json](configs/agent-success-reference-warmstart.json): return real rejection summaries to the parameter-generating Agent and supply two verified complete historical examples as context. Ask directly for up to four proposals per request, stop at eight new complete valid seeds or 20 new returned candidates/five requests, and retain the full prior cost chain. Reference points are not preseeded; copies and near copies are rejected. There is no LLM pool selector or random replacement. See [the current reference-assisted method](docs/agent-success-reference-warmstart.md). The earlier [40-point feedback protocol](docs/agent-rejection-warmstart.md) and [one-shot pure-prompt entry](docs/prompt-only-warmstart.md) remain reproducible. BO defaults to zero for these initialization pilots.

The supplied workbook has four rate sheets (0.5C, 1C, 2C, 3C) and headers I/U/T. I is entirely blank and no time column exists. U is measured voltage; one sample per second is confirmed. T is unused because its unit is unconfirmed and the selected model is isothermal. Reference's 5 Ah capacity gives derived currents of 2.5/5/10/15 A. These are assumptions from the selected design, not measured currents. Real-data optimization runs have completed; reliable evidence of an LLM advantage remains unresolved. The latest fresh 24-point WarmStart comparison produced zero complete four-rate candidates in both arms; [its RMSE audit](docs/audits/warmstart-rmse-comparison-2026-10-15.md) reports partial-rate scores without assigning them a joint objective.

## Environment

Use 64-bit Python 3.12.10 on the current Windows host. The minimal software runtime is pinned in requirements-py312.lock. A separate real-model environment now exists at .venv-pybamm312/Scripts/python.exe with PyBaMM 25.10.2 and CasADi 3.6.7. The implemented backend remains sequential CPU; GPU support requires implementation and numerical comparison. The synthetic demo uses no real battery solver.

From PowerShell at the repository root:

```powershell
Set-Location "D:\Users\aa133\Desktop\LLMBO_Para"
$runPython = "C:\Users\aa133\AppData\Local\Programs\Python\Python312\python.exe"
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
```

The test-and-demo command is:

```powershell
.\scripts\verify.ps1 -PythonExe $runPython
```

It runs unit tests, checks that the incomplete research template is rejected with all missing settings, executes a five-candidate synthetic optimization, reports status and independently recomputes the saved GP/Monte Carlo EI results. Each invocation creates unique folders under runs/. Configuration, source snapshots, commands, environment, input hashes, per-rate curves, errors, model states and acquisition decisions are archived. Verification saves its transcript and every command exit code. Existing runs are never overwritten.

The latest dedicated-environment verification passed 47 tests, including component failure isolation, and the five-candidate synthetic deep audit. Its archive is runs/verification/20261011T061902Z_a9b33dc5. Verification histories remain under runs/verification. The environment's 40 dependency wheels, hashes, installation report, offline command and lock are preserved in the [21700 alignment archive](runs/measured-identification/20261011T021237Z_5c536026feeb_6f940f7b/). The setup below creates a separate minimal software environment.

For a new isolated environment, run the following setup, then use the same $runPython variable for every command below:

```powershell
& $runPython -m venv .venv312
$runPython = (Join-Path (Get-Location) ".venv312\Scripts\python.exe")
& $runPython -m pip install -r requirements-py312.lock
```

The synthetic workflow can also be run directly:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) "src")
& $runPython -X utf8 -B -m llmbo_para demo --output runs/synthetic --budget 5
```

The synthetic parameter bounds and voltage offsets in this demo are software fixtures only. They must not be used as scientific cell parameters.

To inventory an input workbook without assigning scientific meaning to its columns, run:

```powershell
& $runPython -X utf8 -B -m llmbo_para inspect-workbook "C:\path\to\true_data.xlsx" --output runs/data-preflight
```

This saves a unique `inspection.json`, the source file hash, invocation and host details. It reports row counts, headers, blank counts and numeric ranges without modifying the source workbook.

Once the research configuration has real values, check it before using any data:

```powershell
& $runPython -X utf8 -B -m llmbo_para validate-config configs/research-template.json
& $runPython -X utf8 -B -m llmbo_para preflight configs/research-template.json --output runs/preflight
```

The checked-in template is intentionally incomplete, so this command currently exits with a missing-input error. The workbook reader requires explicit sheet and column mappings, refuses out-of-range interpolation, hashes the original XLSX, and records any opted-in legacy assumptions. The PyBaMM adapter uses an injected parameter-set factory so cell parameters are supplied by the research group instead of guessed by this code.

## Implemented workflow

The optimizer uses the six parameters and fixed order specified in Method v0.2, normalized linear/log10 parameter transforms, four per-rate log-RMSE Gaussian processes, the full/subset Matérn 5/2 kernel mixture with the mixture weight bounded by 0.8, and numerical Monte Carlo Composite EI over the equal-weight average of four voltage RMSEs. The current pure-prompt launcher retains the configured four GPs, per-rate screening-history reuse and completion-probability weighting when BO is explicitly requested. It verifies all eight seed curves before passing their cache to BO. The GP LLM component remains independently configurable; changing WarmStart does not change its Prompt. Its client sends only approved summaries, never raw voltage curves. Optimization and simulation workers are sequential. Legacy LLM/Sobol fallback and LLM selection/refill launchers remain available to reproduce historical experiments; they are not the current WarmStart entry.

Failed simulations keep their error text and per-rate status. They do not receive a fabricated penalty score and do not enter the GP training targets. All four rates are attempted for each candidate. Per-rate error scores use a fixed measured time grid and fail if simulated coverage would require extrapolation.

After filling an explicit experiment configuration, use one candidate before the full optimization. candidate.json must contain {"parameters": [six physical values in Method order]}.

```powershell
& $runPython -X utf8 -B -m llmbo_para smoke configs/experiment.json --parameters configs/candidate.json --output runs/smoke
& $runPython -X utf8 -B -m llmbo_para run configs/experiment.json --output runs/experiments
& $runPython -X utf8 -B -m llmbo_para status "C:\absolute\run-directory"
& $runPython -X utf8 -B -m llmbo_para audit-run "C:\absolute\run-directory" --deep --output runs/result-audits
& $runPython -X utf8 -B -m llmbo_para retry-failed "C:\absolute\run-directory" --output runs/recovery
```

The smoke command disables LLM/GP and performs four rate solves for the supplied candidate. Recovery creates a new run for failed or unfinished already-planned candidates, links original candidate IDs and preserves the original files. It does not resume unplanned future BO steps. An optional replacement configuration may change only solver settings and retry count.

LLM transport is explicit. structured_json_service accepts the existing task payload and returns candidates/groups directly. openai_chat_completions adapts the tasks into system/user messages and reads strict JSON from choices[0].message.content; configure the complete HTTPS endpoint, model, max_tokens and json_mode. There are two components and three task prompts: warm proposal generation, warm candidate index selection, and GP parameter grouping. Both paths use verified HTTPS, refuse redirects, archive sanitized request/response/HTTP diagnostics, and keep bearer credentials out of files. Truncated or non-JSON completions fail validation. The prompts remain under src/llmbo_para/prompts/; raw experimental curves are rejected from the LLM payload.

A bounded live-LLM software acceptance runner uses configs/newapi-synthetic-smoke.json: two LLM warm points plus two Sobol points, one BO iteration, CPU and five total synthetic candidates. It reads the credential using hidden input or the named process environment variable. The configured requested model is deepseek-v4-flash; preserve any different response model label in the archived evidence.

```powershell
& $runPython -X utf8 -B scripts\run_live_synthetic.py configs\newapi-synthetic-smoke.json
```

This command makes two real LLM calls with a 2048-token output cap each. All voltage data and parameters in this configuration are artificial software fixtures. Acceptance also checks that real replies were decoded, both warm proposals were accepted, and no Sobol fallback masked an API error.

The replacement API passed two real LLM calls and a five-candidate synthetic optimization on 2026-10-11; all 34 regression tests and the deep result audit passed. See [live API acceptance report](docs/audits/newapi-live-2026-10-11.md) for preserved failures, fixes, model labels, usage, environment and commands.

A later [workflow review](docs/audits/workflow-review-2026-10-11.md) confirmed the dataset's 1-second sampling interval and rechecked PyBaMM availability. It strengthened group semantics: explicit empty groups are valid abstentions; invalid all-six groups are diagnosed and cannot pass live acceptance through fallback. All 36 regression tests and the new live five-candidate acceptance passed. Scientific inputs and a compatible real PyBaMM runtime are still pending.

See the [current 21700 alignment](docs/audits/21700-reference-alignment-2026-10-11.md), [architecture and contracts](docs/architecture.md), [framework audit](docs/audits/framework-2026-10-10.md), [decisions](docs/decisions.md) and [error prevention log](docs/mistakes.md). Real four-rate solves, cached GP training and a small measured-data BO closure have been verified. The four formal 25-iteration ablations and scientific LLM effectiveness remain pending. The main workflow fits all four rates, including 3C.

## Approved feasible initialization

The frozen study template is configs/21700-feasible-ablation.json. The six bounds, fixed initial concentrations, isothermal DFN, 2.5 V cutoff, complete measured grids and provisional electrolyte multiplier 1.5 stay explicit. This template's allocation is replaced by each arm's supplied initial plan. Current PyBaMM accepts the measured voltage data with the recorded 1 s time axis and Reference-derived 5 Ah currents; those currents are assumptions, not measurements.

```powershell
$runPython = Join-Path (Get-Location) '.venv-pybamm312\Scripts\python.exe'
& $runPython -X utf8 -B scripts/run_ablation_suite.py configs/21700-feasible-ablation.json --screening-only random --output runs/screening-pilots
& $runPython -X utf8 -B scripts/run_ablation_suite.py configs/21700-feasible-ablation.json --screening-only llm --prompt-for-key --output runs/screening-pilots
```

Each family first audits two valid points, then continues toward eight, with a maximum of 200 DFN candidates. The random draw limit is 20000; WarmStart allows ten 20-proposal generation batches and thirty selection requests. A necessary lithium-inventory test prevents impossible points from consuming DFN solves. All rejects and costs remain archived. API/model/format errors fail explicitly. A failed family blocks only its own two arms. Eight verified results can be supplied via --random-plan and --llm-plan to avoid screening again; the default subsequent budget is 25 BO evaluations per arm, including failed evaluations.

The first approved random run obtained 4/8 valid points in 200 candidate evaluations (800 rate attempts), so it is not eligible to start the formal random-family arms. A continuation implementation supports --resume-random-plan and --max-screening-evaluations: it preserves the consumed RNG sequence, accepted points and cumulative cost. Raising the approved 200-candidate limit requires the pending user decision. The API currently returns 503/model_not_found for deepseek-v4-flash and its model list has no DeepSeek entry; a replacement model also requires the pending user choice.

scripts/audit_feasible_screening.py recalculates every archived label and replays the seeded draws without DFN/API calls. scripts/check_feasible_gp.py permits a separate small closure of zero to two BO steps, explicitly labeled as verification rather than a formal study. Suite archives separate actual shared preparation from each arm's standalone cost attribution and save curves against both BO iteration and cumulative DFN rate solves.

scripts/deploy_zju_ablation.py --prepare-only builds a local deployment bundle without a connection or transfer. Source/XLSX upload remains pending explicit permission after the earlier automatic-review rejection.

## Completed local ablation, 2026-10-11

Four local arms each completed eight cached valid initial observations plus 25 BO attempts, using gpt-5.6-sol for enabled LLM components. All deep audits passed. Scientific interpretation and complete costs: [local ablation audit](docs/audits/local-ablation-2026-10-11.md). The high failed-candidate rate and lack of reliable superiority evidence are reported explicitly. Config: configs/21700-local-gpt56sol-20261011.json. Historical pending-state reports remain unchanged.
