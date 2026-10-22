# LGBO numerical controls: stopped software batch

## Status

Approved plan: [numerical controls before Prompt v2](../superpowers/plans/2026-10-22-lgbo-numerical-prompt-plan.md), approved as e11838f. Stage A **incomplete**; Stage B **not started**. No claim of Region gain or lack of gain can be made from this batch.

Worktree: `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`, branch `codex/electrothermal-mo-20261016`. Protected main and reference projects were not modified.

## Actual evidence

Evidence root: `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-numerical-prompt-20261022/`.

- Fresh baseline: **955 passed, 0 failed/errors/skipped**, exit 0, 1363.91 seconds. Log and JUnit: sibling `tests/np-baseline-1022123518607723/{pytest.log,junit.xml}`; result JSON in that directory records boundary network/battery attempts 0 and two allowed nonbattery algebraic simulations.
- Runner RED: 33 failures, 0 collection errors; required entry absent. Seal test separately RED 1/1. Initial implementation had one test fixture error (terminal status belongs to `terminal.json`, while manifest remains `created`); fixed the fixture without changing that archive contract.
- Runner/related GREEN: **47/47**, exit 0, `tests/np-runner-green2-1022130403558727/`. Real network/battery attempts 0.
- Task 1 commit: `8e3f726ecddb6d744b30d7376fa120c89adb4b5a`; created runner, software config and tests only. Product source fingerprint stayed `054f0a7ca110a23640a802055516b9734c536d17d68192c7a53fa27949e8ccb8`.
- Dry-run validated four cells × three seeds × two arms; no output directory or evaluations created.
- One formal `--execute` invocation. It evaluated **16 fresh software candidates / 32 rate calls**, selected eight with the existing Pareto/Max–Min rule and passed the initialization deep audit. The first BO run failed during source snapshot creation, before BO evaluation or GP fitting. **0 completed cases, 0 BO rounds**, all 24 cases explicitly missing, HV/RMSE comparison unavailable. Exit 1.
- `stage-a/{protocol.json,summary.json,worker-failure.json,stage-a-seal.json,software-costs.jsonl}`, `stage-a-cli.log`, `stage-a-cli-exit-code.txt`, and `failed-stage-a-seal-verification.json` preserve the failure and verified hashes. Boundary: network 0, battery solves 0. All inputs are four-second algebraic software observations at 0.5C/1C; no real API, DFN, measured fit or old 3C.

## Cause and repair

The new runner nested the full scientific case ID beneath an already long evidence root. The first missing Prompt snapshot path was **268 characters**. Initialization had a shorter directory and succeeded. `path-diagnosis.json` preserves exact paths and lengths.

Classification: **introduced by this runner's archive layout under the existing Windows path constraint**. This is not an existing model/Region failure or evidence about optimization quality.

Repair is limited to the research runner: deterministic disk directories `r00`–`r23`, `init`, a case-ID map through the index, and a preflight over actual source snapshot filenames and the longest Region response filename. Unsafe roots are rejected before creating a batch or evaluating candidates. Source/Prompt, optimizer, physical model, GP, EI, fixed mock rectangle and selection policy stay unchanged. Two new tests first failed for the missing layout/preflight; subsequent regression evidence is recorded in the execution ledger and final test report.

Post-repair related regression: **57/57**, exit 0, no failures/errors/skips, `tests/np-final-related-1022142642791843/`. This includes existing MO/provenance/LGBO workflow tests. The path regression initially exposed a test-only Windows separator assumption in `source-sha256.json`; it now normalizes archive keys without changing the existing store.

One independent read-only review found tuple/list summary sealing and cooperative per-run deadline problems, plus understated stage timing. All were reproduced before repair. The runner now compares canonical scientific JSON, retains objective-tamper rejection, and extends the existing owned pipe protocol with parent-enforced workflow phases. Both blocking and late-return fixtures terminate within the per-run limit with no next case or surviving process. Separate stage/case clocks retain complete timing; an actual two-case software unit fixture verifies 33 synthetic clock units for initialization and both cases, versus 11 per case. Workflow exceptions close their phase before archiving a known failure. These pytest fixtures are not additional executions of the formal 24-case experiment.

Review: `final-review.md` in the evidence root; RED/GREEN results are in the execution ledger. No second review or experimental retry was performed.

## Final verification of this partial delivery

Code repair commit: `9b7f4b0f33a0424ae1fedb476ac41386bef1050c`.

| Check | Tests | Passed | Failures | Errors | Skips | Exit |
|---|---:|---:|---:|---:|---:|---:|
| Fresh baseline | 955 | 955 | 0 | 0 | 0 | 0 |
| Final related regression | 57 | 57 | 0 | 0 | 0 | 0 |
| Final full regression | 999 | 999 | 0 | 0 | 0 | 0 |

Final full test duration: **1792.84 seconds**. Evidence directory:
`D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/np-final-full-1022142918208570/`.
Files: `pytest.log`, `junit.xml`, `exit-code.txt`, `result.json`. JUnit counts were independently checked against the result JSON. Boundary network/battery attempts both zero; two existing nonbattery algebraic PyBaMM simulations were allowed. Pytest software/mock fixtures are separate from formal experiment costs.

`closure.json` and `workspace-final.json` record an exact match of all 124 protected main files, old numerical/Prompt hashes and LGBO tilt AST to Task0. Product source fingerprint remains `054f0a7ca110a23640a802055516b9734c536d17d68192c7a53fa27949e8ccb8`. All 444 files in the original incomplete seal were rechecked without modification. Old voltage behavior remains covered by the passing full suite; no source/model/Prompt edits occurred in this delivery.

The selected eight points' archived predictions were independently rescored, with results in `initialization-only-RMSE.{json,csv}`. The fixed equal-weight representative has **F_U=0.05415334424957664 V, F_T=0.24916451270262385 K**. These are initialization-only errors on the four-second algebraic fixture, not results of twenty BO rounds, real DFN or measured identification.

`recovery-preflight/index.json` contains 24 prepared configurations: all pass existing strict initialization checks, share one initialization-compatibility signature and have 24 distinct algorithm signatures. No re-signing, objective evaluation or execution occurred. Repaired archive preflight predicts a maximum path of 250 characters for the proposed new output. `controlled-recovery-protocol.json` remains **approved=false**: reuse the original eight selected points with at most 480 new candidate evaluations / 960 software calls, cumulative caps496/992, a new3600-second supervised window, one thread and API/DFN0, no retry. Original failure and expired window remain preserved.

Execution decisions and costs: reuse the Windows guarded adapter with a new ledger (adapter maintenance), retain all workspaces/evidence/worktree per user instruction (disk use), and extend the owned supervisor only in the research script during the source freeze (duplicate supervisor maintenance). No deferred minor findings; the timing finding was upgraded because complete cost reporting is required, then fixed by RED→GREEN.

Task1 and this runner repair are complete. Task2 remains stopped/incomplete; Tasks3–4 and full-plan Task5 remain unfinished. Successful local regression is not a completed gain experiment. Method and old LLM documentation were not rewritten to imply a v2 implementation.

The failed batch is not overwritten, resumed or re-signed. Its selected initialization remains bound to its actual source and original screening costs. It may only be reused after the existing strict plan/hash/curve checks and explicit authorization for a controlled recovery.

## Remaining work

The approved stop rule says “任一运行未完成/审计失败或总预算耗尽即停止本批次，不开启后续case、不转入Stage B、不重置计数”. Therefore no automatic recovery and no Prompt v2 implementation follow this failure.

Unspent candidate/call allowance is at most **480 / 960**. It is not a new or automatically renewed run permission. A concrete recovery would retain the failed archive, reuse the verified eight selected points, run the same 24 cases under a new supervised time window, and preserve cumulative 496/992 caps. Prompt v2 remains conditional on a completed and sealed Stage A. Any real API/DFN confirmation still needs a separate protocol; present budget remains zero.
