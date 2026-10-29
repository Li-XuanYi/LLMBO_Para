# WarmStart Quality-Gated Selection Trial Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a versioned quality-gated WarmStart selector and measure its 50-round final-HV effect against unchanged v1 and v2 on five new paired real-DFN synthetic seeds.

**Architecture:** The selector changes only how eight already evaluated candidate points are chosen. A new source-pinned three-arm supervisor acquires one 16-point pool per seed, signs three plans, delegates all formal BO to the existing worker/optimizer, and independently replays the archived curves, Pareto sets and fixed-space HV. No new GP, acquisition, Region, Prompt or thermal model is introduced.

**Tech Stack:** Python 3.12; `D:/Users/aa133/Desktop/LLMBO_Para/.venv-pybamm312/Scripts/python.exe`; PyBaMM 25.10.2; pytest/JUnit; Windows PowerShell; one process tree at a time.

**Spec:** `docs/superpowers/specs/2026-10-29-warmstart-quality-gate-design.md`. Diagnostic evidence: `docs/audits/warmstart-v2-final-hv-diagnosis-2026-10-29.md` and the sealed `runs/w27` archive.

## Global constraints and authorization

- The user selected quality-gated coverage, then requested “重启实验” after the proposed independent `1660 DFN / 15 API / 8 h` cap was shown. Record that exact authorization in the release; do not reuse the closed `w27` budget. If any requested scientific or resource bound changes, stop before live side effects.
- New seeds in run order: `[659578,564327,336546,769762,465948]`. Exclude all ten prior five-seed studies' seeds. Arm orders respectively: `v1,v2,v3`; `v2,v3,v1`; `v3,v1,v2`; `v1,v3,v2`; `v2,v1,v3`.
- One shared **real** 16-point LLM candidate pool per seed; three independently signed eight-point plans; each arm runs 50 **new** `warmstart_only` ParEGO rounds. There are 20 phases, each pool limited to 32 DFN/3 API and each formal arm to 100 DFN/0 API. Charge before side effects, stop on first failed phase, archive its partial seed.
- Reuse the pinned 0.5C/1C, 60 s real DFN synthetic observations without regenerating them. Keep fixed objective scales `[0.1 V,1 K]` and HV reference `[10,10]`; no measured XLSX or old 3C. No Region requests, transport retries, server task or extra thermal variables.
- Keep `pareto_maximin_v1` the default. v1/v2 selector outputs and old cache/plan signatures retain their meanings. New v3 receives a distinct effective-rule signature. The original worktree's later uncommitted default-rule edits are not part of this isolated branch.
- No API credential in code, protocol, command arguments, source snapshot or logs. Detect presence only before release; read dedicated user environment only at actual launch. Single-thread and one 8-hour absolute window from first side effect. A closed/failed trial is not automatically resumed.
- Five seeds, not 750 rounds, are the paired experimental units. Primary comparison is final `HV_v3−HV_v2`; `HV_v3−HV_v1` is the benchmark. Report all per-seed signs and both RMSEs. Do not tune v3 using these seeds after observing results.

## File map

- Modify `src/llmbo_para/electrothermal_config.py` and `src/llmbo_para/electrothermal_llm.py`: strict v3 name and pure gated selector branch.
- Extend `tests/test_electrothermal_llm.py`, `tests/test_electrothermal_initialization.py`, `tests/test_electrothermal_provenance.py`, and `tests/test_electrothermal_audit.py`: selection, signatures, plan import and tamper replay.
- Extend `scripts/et_warmstart_selection_paired_worker.py` with `derive_selection_plans(...)`; keep `derive_paired_plans(...)` as the exact two-arm wrapper. Its existing test remains an old-runner compatibility gate.
- Add `scripts/et_selection_trial_budget.py`: parameterized, durable hash-chain phase budget. It contains no experiment-specific source/configuration or API logic.
- Add `scripts/run_et_warmstart_quality_gate_trial.py`: frozen protocol, new seed/arm schedule, release/pin checks, source-pinned supervised worker calls, partial-result preservation, dry run, mock and live entry points. Reuse `et_three_arm_validation_worker.run_worker` and `run_lgbo_real_gain.supervise`; do not copy `MOOptimizer`.
- Add `scripts/analyze_et_warmstart_quality_gate_trial.py`: curve-derived objective/Pareto/HV replay and three-arm paired statistics; reuse the existing curve/charge analyzer where sound, but recompute full Pareto rows and fixed representative independently.
- Add `tests/test_et_warmstart_quality_gate_trial.py`: pure, mock, failure, ledger and mutation gates. Evidence under a new `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/warmstart-v3-trial-20261029/`; short live output `D:/Users/aa133/Desktop/LLMBO_Para/runs/w29/`. Preserve `runs/w27/` unchanged.

## Review focus

1. A v3 plan with forged gate, changed rule or mismatched destination signature must fail **before** formal BO.
2. Only complete true objective pairs enter the selector; duplicate physical points cannot silently fill eight slots.
3. Candidate pool expense is charged once, not once per arm; formal arms have independent GP/cache/run stores and identical weight schedules.
4. Source, observation, config, plan, curves, costs and fixed metric space are pinned; mutation must fail replay.
5. On partial pool/arm failure, `result.json` retains the seed, completed stages, current failure type and charged costs, marked incomplete; no partial result contributes to completed-gain statistics.

---

### Task 0: Freeze clean baseline and protocol proposal

**Files:** The design/plan/audit documents and a new ignored evidence directory only.

- [ ] Record clean branch status and baseline commit, interpreter/PyBaMM versions, hashes of the existing synthetic observations and prior `w27` result. Run locked-interpreter full software regression with network and battery-solve guards; save JUnit, log, counts and process exit. Diagnose failures rather than importing old pass counts.
- [ ] Generate disabled, per-seed configs from the previous locked physical template. Freeze seed/arm order, 1660/15/28800 caps, 20 phase ceilings, exact 0.5C/1C/60 s semantics, source file hashes and short output path in a credential-free protocol proposal. `--dry-run` must not create live output or read a credential.
- [ ] Commit the reviewed documents/protocol generator with explicit file paths.

### Task 1: TDD v3 selector and compatibility

**Interfaces:** Existing `warmstart_selection_details(records, *, space, count, objective_scales, rho_aug=.05, rule=...) -> dict` adds only v3 branch. `q_gate=max(q[i] for i in v1_selected_ids)`; Pareto core and distance/tie ordering match the spec. Default remains v1.

- [ ] Write failing tests: gate excludes a farther poor candidate while admitting a nearer good one; core preservation; first front >K; exact ties in distance, quality, rank, coordinates, ID; permutation invariance; log/linear normalization; partial/duplicate candidates; v1/v2 unchanged and v3 opt-in. Capture RED log/JUnit/exit.
- [ ] Implement the minimum config/selector changes. Return gate and baseline IDs in v3 evidence only; avoid adding fields to v1/v2. Run focused GREEN tests.
- [ ] Add failing plan-import and deep-audit mutation tests for v3 rule/gate/scale/parameters and cross-rule import. Implement only necessary validation fixes, then run focused regression and commit explicit files.

### Task 2: TDD three plans from one immutable pool

**Interfaces:** `derive_selection_plans(pool_run: Path, *, configs: dict[str,dict], rules: dict[str,str], out: Path) -> dict` validates one 16-record true pool and returns three signed plan paths/hashes/IDs plus one shared cost and source-file manifest. `derive_paired_plans(...)` remains the v1/v2 wrapper with its historical output shape.

- [ ] RED: three plans import only under their corresponding rule, physical/data/model signatures and original curves match, distinct initialization signatures bind each rule, v1 reproduces source selection, a forged pool/gate/cost/partial/duplicate fails. Run existing two-arm tests to pin compatibility.
- [ ] Implement a small common plan derivation function and wrapper; no source-pool rewrite and no new DFN solve. GREEN tests, deep audit and explicit commit.

### Task 3: TDD guarded three-arm supervisor

**Interfaces:** `SelectionTrialBudget.start(path, *, protocol_sha, caps, phases)` and `state/begin/require/charge/finish/counts/deadline`; `run_seed(protocol, *, seed, budget, root, source_root, software_fixture=False) -> dict`; `execute_live(...) -> dict`; `run_mock_rehearsal(...) -> dict`.

- [ ] RED: validate exact new seeds/order, three arms/50 rounds, 1660/15/28800 cap, one active phase, charge-before-call and duplicate/over-budget rejection, restart refusal, source/config/rate tampering, no credential read in dry run; failure after a pool or arm leaves a partial seed in the parent result.
- [ ] Implement frozen protocol and hash-chain budget, then supervisor using existing supervised worker. Verify one pool and three distinct plan imports, same weight sequence, independent run directories, no Region/API in formal arms. GREEN tests and explicit commit.

### Task 4: TDD independent analysis and software release

**Interfaces:** `analyze_trial(archive: Path, protocol: dict) -> dict` derives both RMSEs from each rate's archived curves, full Pareto parameter rows, symmetric representative, fixed HV and cost axis for all three arms; reports two predeclared paired contrasts and partial status.

- [ ] RED: known 2-D Pareto/HV fixture, voltage unit-scale invariance, curve/temperature/representative/plan/weight/reference/cost tampering, incomplete seed exclusion and correct five-seed statistics. GREEN analyzer.
- [ ] Run complete five-seed × three-arm × 50-round **software mock**; require 15 arms, 750 rounds, zero actual API/DFN, source pins and independent analysis. Run full locked software regression with guarded zero network/battery solves, save JUnit/log/exit; resolve any failure.
- [ ] Freeze source commit, full source snapshot, observations, configs, protocol and passing targeted/full/mock gate hashes in `software-release.json`. Review a dry-run and credential-free protocol; commit only listed source/tests/docs.

### Task 5: Execute and audit the newly authorized synthetic trial

- [ ] Preflight clean source commit, release hashes, exact authorization limits, dedicated credential presence and fresh output/ledger. Start one absolute 8-hour window and charge before each API/DFN call. If any gate fails, stop with zero or partial usage and preserve evidence; do not reset a closed budget.
- [ ] Execute the five frozen seeds in order, each with one 16-point real pool and three independent 50-round arms. Stop on the first incomplete pool/arm, API/DFN failure, deadline or audit mismatch; preserve all phases and the failing seed's partial record.
- [ ] Independently replay complete archived curves, objectives, full Pareto sets, representative points, fixed HV, source pins and ledger; report every seed's v3−v2 and v3−v1 final HV, AUC and voltage/temperature RMSE, actual API/DFN/time and software/physical/measurement validation levels. Keep v1 default if stable gain is unproved; never retune and rerun these seeds.
