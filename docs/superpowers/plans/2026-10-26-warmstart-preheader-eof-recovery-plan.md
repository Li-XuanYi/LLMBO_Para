# WarmStart Pre-header EOF Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved five-seed, three-arm DFN synthetic comparison despite an occasional classified pre-header TLS EOF during candidate-only WarmStart, without accepting an unbound reply or changing the numerical method.

**Architecture:** An opt-in controller policy may issue a new request after a precisely classified pre-header EOF only while fewer than eight complete initial points exist. All requests remain independently frozen, charged, archived, and audited. A fresh experiment uses a new output root and independent budget; both closed attempts remain immutable.

**Tech Stack:** Python 3.12, PyBaMM 25.10.2, pytest/JUnit, existing Windows single-thread owned-worker runner and hash-chained budget journal.

**Spec:** `docs/superpowers/specs/2026-10-26-warmstart-preheader-eof-recovery-design.md`

## Global Constraints

- No new physics, thermal model, objective, GP, EI, Region formula, LLM prompt, parameter or fitted rate.
- The old voltage workflow, full-v1 WarmStart replies, prior experiment outputs, and both closed journals remain unchanged.
- Software tests use zero real API requests and zero DFN solves. The live ceiling, only if separately approved, is 1,740 DFN / 271 API / 28,800 s, one thread, with at most three counted WarmStart requests per seed and zero HTTP-layer automatic retries.
- Use explicit files for Git staging. Never put a credential in code, config, command arguments, logs or snapshots.

## Review Focus

- A TLS EOF **after** headers or any HTTP status must stop, even if a retry allowance remains.
- A malformed reply, wrong task, stale receipt or protocol failure must stop; a failed ordinal never yields candidates.
- A classified EOF with eight already valid distinct points must select from those points without an extra API call.
- Three classified failures must stop with exactly three charged calls and zero fabricated initial points.
- A failed request followed by a valid one must remain visible to deep audit, and changing either outcome or ordinal must fail audit.

---

### Task 1: Opt-in configuration and exact failure classification

**Files:** Modify `src/llmbo_para/electrothermal_config.py` and `src/llmbo_para/electrothermal_llm.py`; test `tests/test_electrothermal_warmstart_wire.py`.

**Interfaces:** `llm.warmstart_preheader_tls_eof_continue` is an optional boolean, default false. Add a small pure predicate `is_recoverable_warmstart_preheader_eof(outcome: dict) -> bool` in `electrothermal_llm.py`; it requires failed/transport_error, `http_request_started is True`, `failure_stage=='awaiting_headers'`, `http_status is None`, `network_diagnostic == {'category':'tls_eof','cause_type':'SSLEOFError','os_errno':8}` or an equally strict documented subset that rejects other categories and post-header cases. No exception text is inspected.

- [ ] Write failing configuration and predicate tests for omitted/false/true, invalid type, full-v1/Responses rejection, exact match, and each near miss above. Run the selected tests and preserve RED JUnit and exit code.
- [ ] Implement the minimal validation and predicate. Run the same tests to GREEN; confirm omission preserves the old config digest and explicit true changes config/algorithm digests without changing data/evaluation/comparison digests.
- [ ] Commit only these files and record the commit and targeted JUnit.

### Task 2: Bounded WarmStart continuation and independent audit

**Files:** Modify `src/llmbo_para/electrothermal_llm.py` and `src/llmbo_para/electrothermal_audit.py`; test `tests/test_electrothermal_warmstart_wire.py` plus a focused audit test if needed.

**Interfaces:** `ElectrothermalLLMController.generate_warmstart()` continues its existing loop only when the new policy is true, `is_recoverable_warmstart_preheader_eof(self.last_request_outcome)` is true, fewer than `initial_count` distinct complete pairs exist, and existing request/candidate/solve/time limits allow continuation. A new `request()` call generates a fresh ordinal and binding; failed ordinals retain cost/outcome/error evidence and no binding. The auditor independently checks each transition between failed and subsequent WarmStart ordinals against the frozen configuration and prior true history.

- [ ] Write RED tests with an offline transport for EOF then valid candidates, EOF×3, nonmatching failure, sufficient existing pool, and deep audit after mutating the first failure classification, count, ordinal or bound reply.
- [ ] Implement the smallest controller and audit changes. Run the same tests to GREEN and the existing candidate-only/legacy tests; require exact charged API count, no synthetic candidates, and unchanged old behavior.
- [ ] Commit explicit files and save targeted JUnit, log and exit code.

### Task 3: Frozen software release and new independent experiment

**Files:** Create a new versioned proposal and runtime under `bo-repair-work/20261017_et_implementation/three-arm-50round-eof-policy-20261026` and a distinct output such as `runs/g26z`; adapt `scripts/run_et_three_arm_bound_validation.py`, `scripts/run_et_three_arm_validation.py` only if required to assert the new opt-in protocol. Test `tests/test_et_three_arm_validation.py`.

**Interfaces:** The new protocol fixes seeds `(376330, 633262, 789058, 609653, 362724)`, arms `bo/warmstart_only/full_llmbo_mo`, 8 initial + 50 rounds per arm, 0.5C/1C each 60 s, scales `[0.1,1.0]`, HV reference `[10,10]`, and the same GP/Region settings. It pins all five configs with the new opt-in, source/lock/runtime hashes, the two closed-journal hashes, software test evidence and the fresh approved budget. No previous initial point or API reply is copied.

- [ ] Write RED dry-run and integrity tests for missing opt-in, mixed seeds, altered cap, old output reuse, old-journal reopening, and a missing software release. Implement the minimum runner/fixture changes; run targeted tests to GREEN.
- [ ] Run the guarded full regression in the locked interpreter, one thread, no credential, zero API/DFN. Save exact test count, failures/errors/skips, exit code, JUnit, network/DFN guard counts and before/after source hashes. Fix any concrete failure and rerun until a complete passing release exists.
- [ ] Freeze a new proposal and source/runtime snapshot with explicit hashes. Dry-run it: 15 arms, 750 new rounds, API 0, DFN 0, output absent. Verify both previous budgets closed and source/worktree status clean.
- [ ] **Only after plan and new independent budget approval:** start one live run with the existing gate, phase ceilings and fail-closed behavior. No implicit restarts. On completion, independently recalculate archived voltage/temperature RMSE and fixed-space HV for all 15 arms; otherwise report the partial stage and exact charged costs without an improvement claim.
