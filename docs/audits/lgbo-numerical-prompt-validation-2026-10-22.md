# LGBO numerical controls and Prompt v2 validation

## Scope and status

Approved original plan e11838f: numerical 2×2 controls first, then separate Prompt enhancement; real API/DFN budgets zero. Approved controlled recovery reused the verified eight selected initial points after the first batch's Windows path failure. Main and reference checkouts and prior records are preserved.

StageA is complete/sealed. StageB request/evidence interfaces and optimizer/audit integration are implemented. Independent review is complete, with its one Important finding fixed through RED/GREEN. The final full regression passed1092/1092, with0 failures/errors/skips and exit0. The earlier999 passing tests cover only the runner repair before the v2 code.

Active worktree: `C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para`; branch `codex/electrothermal-mo-20261016`. New evidence root: `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/lgbo-numerical-recovery-20261022/`. Earlier failure/partial delivery root `lgbo-numerical-prompt-20261022/` stays read-only.

## StageA result and scientific limits

- Same sixteen actually evaluated software proposals selected eight through the existing Pareto/Max–Min rule; unselected points never entered GP history. Recovery did not evaluate initialization again.
- All24 runs ×20 BO attempts and25 deep audits completed, exit0. New480 candidate evaluations/960 rate calls plus old16/32 gives cumulative496/992. Sealed10164 files independently checked. Total through sealing153.8224411s. Network/DFN0.
- Four-second algebraic software observations at0.5C/1C; not real DFN, measured data, or an LLM proposal experiment. Fixed region[.3,.8]^6,c=.65. Source `054f0a7ca110a23640a802055516b9734c536d17d68192c7a53fa27949e8ccb8`.

|Full−Plain fixed-space HV|seed17|seed41|seed59|Mean|
|---|---:|---:|---:|---:|
|G016_S0|0.035729500|-0.028314312|-0.038124899|-0.010236570|
|G512_S0|-0.008703839|-0.024439138|-0.028741284|-0.020628087|
|G016_S4|0.004040358|-0.000748040|0.000010961|0.001101093|
|G512_S4|-0.000003917|-0.004037225|0.001227342|-0.000937933|

Eight pairs negative, four positive; no stable mock Region gain. Increasing GP fitting0→4 improved all12 within-arm/seed HV comparisons; density effects were mixed. Full changed selection53/240 rounds. Small pools had no in-box candidate107/120 rounds, dense pools had5–10; all480 selected points were outside the box. Covariance tilt can legitimately select outside the rectangle; selection change or coverage alone is not improvement.

An independent data analysis recomputed all24 HV and2688 archived channel curves, agreeing with stored HV exactly and RMSE within5.6e-17. Fixed same-parameter representative pairs: none of12 improved both RMSE, two worsened both, ten traded off; temperature error worsened in eight. BO fit means S0/S4 were0.566/12.138ms; audit refits were recorded separately. See `numerical-interpretation.{md,json}` and per-case/round CSVs in the new root. Three seeds sharing one initialization support conditional descriptive conclusions, not significance or identifiable physical parameters.

G512_S4 was specified before results and remains the software template setting. It was not chosen by picking the best mock Full result.

## StageB implementation and source lifecycle

`electrothermal_region_context.weighted_objective_evidence` provides native finite two-objective validation, exact bottleneck ties and unrounded g. `lgbo_v2` adds only these explanatory history fields and its200–300word English Prompt. v1 scientific payload/Prompt golden hashes preserve old content under fixed host identities.

Single method dispatch extends config, wire, bounded requests, controller, optimizer and audit. Wire version/action fields, mean tilt, Gaussian EI, GP labels/variance, candidate algorithm, weights and scalarization do not change. Old source plans/replies are not re-signed or accepted by matching dimension. Same-source v1/v2 initialization compatibility remains strict.

Independent audit derives q/active/g from curve-verified historical Y and the frozen context without calling the explanation producer. Fault injection showed the pre-fix self-comparison incorrectly accepted all three wrong producer outputs; independent checks now reject them. Source/Prompt fingerprint changed to `99f313ee7aeb6e478b2d2ef9250075fb5d81ff6cfd251e8e00da1a0559004077`; software test plans were created under the actual new source. The StageA seal retains its old source. `stage-b-source-boundary.json` records this boundary.

## Actual test evidence

|Check|Result|Exit|Evidence directory under sibling tests/|
|---|---|---:|---|
|Original fresh baseline|955 pass,0 fail/error/skip|0|np-baseline-1022123518607723|
|Runner repair full suite before StageB|999 pass,0 fail/error/skip|0|np-final-full-1022142918208570|
|Recovery contract RED|2 fail,0 error|1|nr-reuse-red-1022150400671950|
|Recovery related GREEN|59 pass,0 fail/error/skip|0|nr-reuse-green-1022150541174865|
|Stage3 RED|29 fail,1 old golden pass,0 error|1|nr-weighted-red-1022151755589184|
|Stage3 final related GREEN|117 pass,0 fail/error/skip|0|nr-task3-final-1022152205335775|
|Stage4 RED|37 fail,0 error|1|nr-workflow-red-1022152609945929|
|Independent producer audit RED|3 fail because audit incorrectly passed|1|nr-independent-red-1022152909198419|
|Stage4 combined GREEN|142 pass,0 fail/error/skip|0|nr-workflow-green1-1022153021866566|
|Final review accounting RED|9 fail,0 error|1|nr-final-accounting-red-1022155249270191|
|Final review accounting GREEN|9 pass,0 fail/error/skip|0|nr-final-accounting-green-1022155326953556|
|Final runner related suite|70 pass,0 fail/error/skip|0|nr-final-runner-related-1022155408278974|
|Final complete suite including v2 and review repair|1092 pass,0 fail/error/skip|0|nr-final-full-1022155542640637|

Each test directory preserves pytest.log, junit.xml, exit-code.txt and result.json; real network/battery attempts0. Software/mock test fixtures are separate from the bounded formal experiment. New tests cover same-action numerical equality, round13, weight refresh after failed temperature pairs, two offline production workers, malformed/incomplete/binding failures, missing decoded HTTP archives, genuinely absent replies, and scientific/Prompt/temperature tampering.

Final regression ran against commit `a51b15cb06be35ad91f37015d75c07ff03560f0a` and source `99f313ee7aeb6e478b2d2ef9250075fb5d81ff6cfd251e8e00da1a0559004077`; only delivery documentation changed afterward. Pytest reported1705.60s; JUnit suite time1710.720s includes its own session timing. All1092 counts and exit0 were independently checked against JUnit, result.json and exit-code.txt. Boundary: network_attempts0, battery_solve_attempts0, allowed_nonbattery_simulation_calls2 (existing algebraic models, not battery/DFN).

Exact final evidence paths:

- [pytest.log](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/nr-final-full-1022155542640637/pytest.log)
- [junit.xml](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/nr-final-full-1022155542640637/junit.xml)
- [result.json](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/nr-final-full-1022155542640637/result.json)
- [exit-code.txt](D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/tests/nr-final-full-1022155542640637/exit-code.txt)

Failure classification: the fresh baseline had no failures. RED failures were deliberate reproductions before implementation/audit repair. The first formal batch's Windows path failure was introduced by the new research runner and repaired, not a DFN/physical failure; that failed batch remains sealed. No unresolved baseline, environment or introduced failure remains in this final software suite.

## Commits, interfaces and unchanged boundaries

|Commit|Change|
|---|---|
|8e3f726|factorial runner/config/tests|
|9b7f4b0|short paths, canonical seal, hard workflow deadlines and timing|
|e0e7e53|partial delivery evidence preserving stopped batch|
|5e26399|strict controlled recovery within remaining480/960|
|fa0ad77|completed numerical results including negatives|
|a3d45fc|weighted evidence, v2Prompt and request/version dispatch|
|864ba0d|optimizer integration, independent audit and v2template|
|96f55f2|method, validation boundaries and future draft protocol|
|a51b15c|preserve prior and persisted cost lower bounds after hard worker stop|

Public research runner interfaces: ablation_protocol, make_case_config, run_software_ablation, recovery_protocol, summarize_numerical_ablation; default CLI dry-run, optional recovery-spec. Native configuration/data/parameter/physical model interfaces and legacy Optimizer are unchanged. New helper/version routing and independent audit are described in Method and llm-informed.

The complete explicit change list, branch, final commit and clean Git status are recorded in `final-git.json` in the new evidence root. It groups the research runner/config/tests, the new weighted-context module and v2Prompt, version routing/audit changes, the v2 software template, tests, and the three documentation areas. `closure.json`, `workspace-delivery.json`, `ledger-final.md` and `delivery-seal.json` preserve the final completion/protection state and hashes of all evidence and the referenced test outputs. The old partial delivery root and StageA archives are retained unchanged.

No additional kernel, thermal model, physical free variable, objective, trust/catalog or Region guard was introduced. R_fit remains configurable; current software study R2 does not change proposed research R3 or later reliableR4. Existing schema1 four-rate voltage tasks and old caches remain intact.

## Independent review and protected records

One fresh read-only review of the recovery/v2 changes found Critical0, Important1, Minor0. The Important issue was missing aggregate prior/cumulative costs when a supervisor hard-stopped a recovery worker before its summary. Nine tests first failed on missing prior_costs, then passed after the fix. Extended coverage includes case/total timeouts, EOF, process failure, missing/complete/truncated ledgers and preservation of existing worker summary/seal. On termination the supervisor reports trusted prior costs and the persisted new/cumulative lower bound, explicitly costs_complete=false; it does not certify that an incomplete ledger is exact. No re-review or StageA experiment rerun was performed. The successful StageA seal remains unchanged.

Both v1/v2 CLI software preflights returned exit0 without evaluation/network/battery calls. Importing the actual old-source initialization plan under the new source was rejected by strict signature checks. Main HEAD/status/index and124 protected file hashes match the pre-plan snapshot. Old Prompt bytes, numerical modules, legacy Region/trust ASTs and lgbo_mean_tilt AST are unchanged, except the intended mo_optimizer version dispatch covered by numerical-parity tests. Fixed physical mappings, dependencies and lock files have no changes. The old delivery529-file seal, failed-stage444-file seal and completed-stage10164-file seal all verify. Checks and CLI logs are in the new evidence root.

Decisions, in order: reuse the Windows-native guarded tools (adapter maintenance cost); preserve evidence/worktree per the user's no-cleanup instruction (disk cost); extend the research script's owned-pipe supervisor while StageA numerical source was frozen (duplicate supervision maintenance); retain the reviewer-declined real Prompt/DFN/measured-effect questions outside this zero-budget scope (real gains/regressions remain unknown). No deferred Minor findings.

## Remaining validation

Software contracts and identical-action behavior are not real Prompt effectiveness. Level2 real DFN and real API confirmation were not run here; Level3 measured identification remains blocked by actual current/time, temperature unit/measurement position, initial state and cooling conditions, with bad old3C excluded. Thermal bounds/fixed-property sources still need research confirmation for measured fitting.

A future draft with G512_S4 and held-out seeds101/131/167 is stored only in the new evidence root. It requires separate source pinning, concrete input/preflight and budget approval; present API/DFN permission remains zero. Negative outcomes and existing archives must be retained. No merge, push, worktree cleanup or experiment deletion is performed.
