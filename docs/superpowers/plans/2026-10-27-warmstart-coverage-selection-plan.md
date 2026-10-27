# WarmStart Coverage Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in Pareto-core, global Max–Min WarmStart selector that preserves historical v1 behavior and improves the parameter coverage obtainable from the same evaluated candidate pool.

**Architecture:** Keep the current pure selector as the v1 branch and add a deterministic v2 branch. Resolve the effective rule from strict config, bind it to initialization signatures, and replay the same rule in plan verification and deep audit. Treat the five archived pools as an exploratory offline geometry check; a new real DFN comparison is a separate approval and budget.

**Tech Stack:** Python 3.12, NumPy, pytest/JUnit, PyBaMM 25.10.2 locked interpreter; Windows PowerShell, single-thread software tests.

**Spec:** `docs/superpowers/specs/2026-10-27-warmstart-coverage-selection-design.md`

## Global Constraints

- User confirmed path A and the design on 2026-10-27. The project’s existing approval process requires this plan to be reviewed before product-code edits.
- First software phase: 0 new real API requests, 0 DFN solves, 0 formal BO server jobs. Use only deterministic fixtures and the sealed five-seed archive read-only.
- Keep `pareto_maximin_v1` as the default. Omitted and explicit v1 share an initialization compatibility signature **within one source revision**; v2 differs. A changed source fingerprint legitimately changes all downstream digests, and archived runs audit against their frozen source snapshots.
- Do not change the Prompt, 16-candidate/8-initial budget, objective scales, GP, EI, Region, DFN physics, old voltage workflow, original MO reference repository, or sealed trial files.
- Stage only explicit file paths. Do not store a credential in source, command arguments, logs or snapshots.

## Review Focus

- A first Pareto layer larger than eight must use the existing front-only ordering and record its actual reduced HV; Task 1 tests this.
- Distinct physical inputs with identical objective pairs must remain eligible, while duplicate physical inputs occupy one slot; Task 1 tests both.
- Shuffling the input records, tied distances, and partial temperature failures must give deterministic, complete-only results; Task 1 tests these.
- Within one source revision, an omitted v1 rule, explicit v1 rule, and v2 rule must have the specified config/initialization digest relationships; Task 2 tests these.
- Tampering a historical or new plan’s rule, selected ID, objective scale, normalized coordinate, or selection order must fail deep audit; Task 3 tests these.

---

### Task 0: Record a fresh software baseline

**Files:** No product edits. Create evidence under `D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\warmstart-coverage-20261027\baseline`.

**Interfaces:** Locked interpreter `D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe`. Current source HEAD `a83f5ec`; previous complete guarded result is 1645/1645 at `warmstart-eof-recovery-20261026/tests/ge-warmstart-eof-full-v3`.

- [ ] Record `git status --short`, HEAD, explicit source hashes and prior JUnit/exit code; verify the existing worktree is clean before implementation.
- [ ] Run the complete suite in the locked interpreter with one-thread numerical environment and a fresh JUnit: `& 'D:\Users\aa133\Desktop\LLMBO_Para\.venv-pybamm312\Scripts\python.exe' -m pytest tests -q --junitxml=<new-baseline>/junit.xml`. Use the prior guarded offline test-launch pattern; record exit code, counts, wall time, log, network attempts and battery-solve attempts. A started test is not a passed test.
- [ ] Classify any failure as pre-existing, environment, or source-related before changing the selector. Preserve the failed run and rerun a complete baseline after an evidence-backed test-only repair if necessary.

### Task 1: Add the pure versioned selection rule

**Files:** Modify `src/llmbo_para/electrothermal_llm.py:30-64`; test `tests/test_electrothermal_llm.py`.

**Interfaces:** Extend `warmstart_selection_details(records, *, space, count: int, objective_scales, rho_aug: float = .05, rule: str = 'pareto_maximin_v1') -> dict` and `select_electrothermal_warmstart(..., rule: str = 'pareto_maximin_v1') -> tuple[str, ...]`. The v1 output remains unchanged. The v2 rule name is `pareto_core_spacefill_v2`; its selected IDs, ranks, `q`, normalized coordinates, duplicate map, steps and rule appear in the existing details structure. Distances and all ties follow the spec exactly.

- [ ] Write RED tests using six-dimensional synthetic record fixtures: v1 selects a closer lower layer while v2 selects a farther point after taking all first-layer points; v2 preserves all first-layer IDs and fixed-space HV for `|P0|≤K`; v2 improves mean pairwise parameter distance in the fixture. Include `|P0|>K`, shuffled input, duplicate parameter, equal objectives, tie, incomplete pair and unknown rule cases.
- [ ] Run the named selector tests with a fresh targeted JUnit; record failing assertions and exit code.
- [ ] Implement only the `rule` dispatch and v2 fill loop. Keep the old branch’s ordering and serialized details unchanged; do not alter Pareto/HV/quality formulas.
- [ ] Re-run selector tests and existing `test_pareto_maximin_selection_is_deterministic`; require all pass. Commit `electrothermal_llm.py` and the selector tests explicitly.

### Task 2: Bind the rule to strict configuration and initialization identity

**Files:** Modify `src/llmbo_para/electrothermal_config.py:102-127`, `src/llmbo_para/electrothermal_provenance.py:31-45,132-146`, `src/llmbo_para/electrothermal_llm.py:211-260`; test `tests/test_electrothermal_config.py`, `tests/test_electrothermal_provenance.py`, `tests/test_electrothermal_initialization.py`.

**Interfaces:** `optimization.warmstart.selection_rule` is optional with allowed values `pareto_maximin_v1` and `pareto_core_spacefill_v2`. The controller passes its effective value to Task 1. `build_electrothermal_signatures()` excludes the optional key from the `warmstart` subobject used in the initialization digest and writes the effective value to the pre-existing `selection` digest field; omitted and explicit v1 hash alike under the same source fingerprint. Historical plan verification dispatches using the archived rule and the bundle’s initialization compatibility signature.

- [ ] Write RED tests: invalid rule rejected by config; omission versus explicit v1 gives equal initialization digest but distinct config digest; v2 differs only in run/config/algorithm/initialization identities, not data/model/evaluation/comparison; v1/v2 plan import is rejected across signatures; mock WarmStart actually uses v2 and archives `rule='pareto_core_spacefill_v2'`.
- [ ] Run these named tests to observe failure with JUnit and exit code.
- [ ] Implement strict validation, effective rule forwarding and signature canonicalization. Preserve the old absent-field digest **formula** and v1 selector behavior; account for the source-fingerprint change in cross-revision comparisons. Reject unknown archived selection rule; do not infer a rule by vector dimension.
- [ ] Re-run targeted tests plus `tests/test_electrothermal_warmstart_wire.py`; require no real transport or DFN call. Commit only listed source and test files.

### Task 3: Extend audit replay and finish the software closed loop

**Files:** Modify `src/llmbo_para/electrothermal_audit.py:418-424`, `docs/Method.md:150-180`; test `tests/test_electrothermal_audit.py`, `tests/test_electrothermal_initialization.py` and a focused new `tests/test_electrothermal_warmstart_coverage.py` if existing fixtures cannot express the v2 replay clearly.

**Interfaces:** Deep audit reads the archived `rule`, checks it equals the effective config rule and replays Task 1. Imported plan verification uses the same declared rule. The software mock closed loop runs v1 and v2 from identical complete candidate pools with zero API/DFN, archives full objective pairs, and checks that all unchanged numerical interfaces still work. `Method.md` names both selection protocols without rewriting historic v1 experiment definitions.

- [ ] Write RED deep-audit tests for a valid v2 screening run and mutations of rule, selected ID/order, quality, normalized coordinate, objective scale and source objective; add a v1 historical mock run that remains auditable and an invalid/partial temperature case excluded from both selectors.
- [ ] Run these named tests to observe failure, then implement audit dispatch and documentation. Re-run to GREEN and verify the mock v1/v2 runs have the expected, equal candidate evaluation cost.
- [ ] Run focused provenance/config/selector/initialization/audit tests together. Commit the exact changed paths and preserve JUnit, log and exit code.

### Task 4: Full regression, archive replay and release evidence

**Files:** Add a bounded read-only analysis entry `scripts/analyze_warmstart_coverage_archive.py` only if needed for reproducibility, plus its fixture test; otherwise preserve the exact analysis command in the evidence folder. Save output under `D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\warmstart-coverage-20261027`, never inside the sealed five-seed archive.

**Interfaces:** The archive replay reads the five historical 16-point pools, applies both pure rules without accepting old plans into a new run, and reports initial HV, six-dimensional pairwise distance, selection IDs and cost equality. It labels all results exploratory and makes no 50-round gain claim.

- [ ] Write a fixture-level RED test for the replay analyzer if adding a script; then implement and pass it. Do not introduce a new analysis dependency.
- [ ] Re-run the full locked-interpreter suite with a fresh JUnit and offline network/DFN guards. Record exact tests/pass/fail/error/skip, exit code, guard counts, worktree status and source hashes; stop on any unexplained failure.
- [ ] Run the read-only five-pool replay; assert v1 selection IDs reproduce the sealed records, v2 initial HV equals pool HV for these five `|P0|≤8` cases, and v2 pairwise distance increases in all five. Report the observed quality cost and that downstream BO benefit is unverified.
- [ ] Commit only newly added analysis code/tests if any; save a source/hash manifest, TDD RED/GREEN evidence and final audit. Leave archived outputs immutable.

## Handoff boundary

After plan approval, use `superpowers:executing-plans` to implement natively in this worktree. The software phase does not authorize a new real API or DFN validation. A later confirmatory study must pre-register new seeds, reuse one shared real candidate pool per seed, compare v1/v2 at equal DFN and API costs, and receive its own independent budget.
