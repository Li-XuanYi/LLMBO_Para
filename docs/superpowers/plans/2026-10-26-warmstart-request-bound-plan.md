# Request-bound WarmStart reply implementation and five-seed revalidation plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Eliminate WarmStart failures caused solely by LLM transcription of long signatures while preserving stale-reply and cache isolation, then complete the five-seed three-arm 50-round synthetic comparison.

**Architecture:** Add an opt-in candidate-only WarmStart wire format. The host freezes and archives the outgoing request, receives the response synchronously, records a request-bound receipt, and validates candidates against trusted local configuration. Existing signed full replies remain unchanged. A fresh independent experiment uses the new format for all five seeds.

**Tech Stack:** Python 3.12, PyBaMM 25.10.2, pytest/JUnit, current Windows native worker supervisor, existing DFN–lumped thermal evaluator and ParEGO/LGBO numerical core.

**Spec:** docs/superpowers/specs/2026-10-26-warmstart-request-bound-design.md

## Global constraints

- Do not change DFN/thermal model, six parameter roles, objectives, objective scales, HV reference, GP, EI, weights, Region formula or Region Prompt. Fit only 0.5C/1C, 60 s synthetic observations; old 3C and measured data remain unused.
- Preserve old full_v1 WarmStart, schema-1 voltage task, old caches and all failed/raw experiment artifacts. The new format must be explicit and enter the config/cache signature.
- No paid API, real API, DFN or formal BO during software implementation. Live work requires a separate approved cap. Keep the key only in the dedicated environment variable, never in code, config, command arguments or logs.
- Use explicit file lists for staging. Keep the main checkout and original MO reference read-only. Keep all real execution single-thread and without transport retries.

## Review focus

1. Wrong or stale six-dimensional replies: candidate_only_v1 accepts only a fresh receipt for the current request and rejects legacy profile/config/data/rate mismatches.
2. Edited raw response or receipt: independent audit catches a response, digest, ordinal, run ID or budget-event mutation.
3. Invalid candidate among valid ones: screen it individually without making up a complete objective pair; duplicates do not inflate pool size.
4. Partial or failed temperature: no zero error and no GP/Pareto entry; initial selection requires eight complete distinct pairs.
5. Old absent wire-format field: preserve the old full_v1 signature and exact existing validator behavior.

---

### Task 1: Establish a baseline and RED tests for the contract

**Files:**
- Test: tests/test_electrothermal_warmstart_wire.py (new)
- Test: tests/test_electrothermal_llm.py
- Test: tests/test_electrothermal_config.py
- Evidence: new bounded local test directory outside tracked source

**Interfaces:**
- Planned new value: llm.warmstart_wire_format = candidate_only_v1; absence means full_v1.
- Planned new type: BoundWarmStartReply(raw, receipt), produced only by the controller after a fresh request.
- Planned new functions in electrothermal_warmstart_wire.py: freeze_warmstart_request(payload, *, run_id, ordinal) -> WarmStartRequest; bind_warmstart_response(request, decoded_reply, *, transport_status, decoded_archive_path, http_envelope_path) -> BoundWarmStartReply; decode_candidate_only_reply(reply, *, prepared, expected_request) -> list[dict].

- [ ] Save current git status, source fingerprint, old failed result/ledger hashes and a fresh baseline pytest JUnit/log/exit code without socket or battery solve access.
- [ ] Add failing tests: the archived fifth-seed-like full reply with a mistyped digest still fails full_v1; candidate_only_v1 rejects old-format or unsigned injected replies, wrong profile/rates/data/config, missing or stale receipt, altered raw response, extra keys, nonfinite/bool/out-of-range parameter values and wrong task. It accepts a fresh bound candidates-only reply with 16 distinct in-range six-parameter items.
- [ ] Run only the new tests, capture expected RED failures and exact counts/exit code before implementation.

### Task 2: Implement opt-in payload, prompt and strict candidate decoder

**Files:**
- Modify: src/llmbo_para/electrothermal_config.py
- Modify: src/llmbo_para/electrothermal_payloads.py
- Create: src/llmbo_para/electrothermal_warmstart_wire.py
- Create: src/llmbo_para/prompts/warm_start_candidates_electrothermal.txt
- Test: tests/test_electrothermal_warmstart_wire.py and tests/test_electrothermal_config.py

**Interfaces:**
- config parser accepts exactly full_v1 or candidate_only_v1 for the optional llm field, without injecting the default into old config data.
- build_warmstart_payload retains trusted outgoing identity and semantics but, for candidate_only_v1, emits a response_contract with only candidates and selects the new output-focused prompt.
- freeze_warmstart_request uses the canonical outgoing payload including unique artifact_task; reply binding includes run ID, ordinal, task, request digest, decoded reply digest, HTTP envelope digest, archive paths/status, and trusted signature digest.
- decode_candidate_only_reply verifies exact fresh binding and strict candidate schema. It never repairs a model-echoed signature or loads a cached raw reply.

- [ ] Make the RED config/payload/decoder tests pass with the minimal implementation.
- [ ] Run the old full_v1 tests and prove that the absent new field leaves the old config digest and response validator unchanged.
- [ ] Commit explicit files after targeted tests pass.

### Task 3: Integrate fresh receipt creation and independent audit

**Files:**
- Modify: src/llmbo_para/electrothermal_llm.py
- Modify: src/llmbo_para/electrothermal_audit.py
- Test: tests/test_electrothermal_llm.py
- Test: tests/test_electrothermal_audit.py
- Test: tests/test_electrothermal_warmstart_wire.py

**Interfaces:**
- ElectrothermalLLMController.request returns BoundWarmStartReply only for the explicit new WarmStart mode, after a direct completed transport response and immutable local receipt archive. Existing full_v1 and Region return values remain unchanged.
- generate_warmstart decodes through the new path only for candidate_only_v1, then continues the existing per-candidate range, cache, real evaluation, Pareto and Max–Min selection logic.
- Deep audit recomputes request/response hashes against archived bytes and cross-checks the receipt, run/ordinal/task identity, budget event and signed initial plan.

- [ ] Add RED tests for fresh request/response binding, mock-only receipt, transport failure, wrong receipt, archive mutation, swapped replies between seeds, same-dimensional old reply, duplicate candidate, failed temperature, and tampered selected-plan or cost record.
- [ ] Implement the receipt and auditor; preserve the decoded reply and HTTP envelope archives and do not synthesize an identity in the model reply.
- [ ] Pass targeted tests and commit explicit files.

### Task 4: Integrate a clean three-arm protocol and software closure

**Files:**
- Modify: scripts/run_et_three_arm_validation.py
- Modify: scripts/et_three_arm_validation_worker.py only if the new receipt interface requires it
- Modify: scripts/analyze_et_three_arm_validation.py only if new receipt fields require auditing
- Test: tests/test_et_three_arm_validation.py
- Test: tests/test_et_three_arm_worker.py
- Test: tests/test_et_three_arm_analysis.py
- Create: a new frozen disabled five-seed protocol/config set in a new experiment directory; do not edit the failed study's protocol or artifacts.

**Interfaces:**
- All five WarmStart initializations use candidate_only_v1 and independently evaluate a newly generated pool before sharing the selected eight-point plan between WarmStart-only and Full.
- BO numerical initials and all 15 arms are generated fresh. Five seeds are 376330, 633262, 789058, 609653, 362724; each arm has eight initials and 50 additional attempts. The objective and cost audit remain unchanged.
- The fresh run has a separate, initially closed protocol proposal. It cannot use the old closed budget journal or previous initial plans.

- [ ] Add RED tests for mixed wire formats across seeds, accidental import of the failed run's plan, wrong config/cache signature, no-key dry run, no API/DFN in software mode, and 15-by-50 attempt/cost accounting.
- [ ] Implement minimal runner configuration changes; use a software fake transport plus mock evaluator for the full three-arm closure and independent RMSE/HV recalculation.
- [ ] Run targeted tests and complete guarded regression; save exact passed/failed/error/skipped counts, exit code, log and JUnit. Review git diff and source fingerprint, then commit explicit files.
- [ ] Prepare source/runtime SHA manifest and dry-run evidence with zero real API/DFN.

### Task 5: Separate live approval gate and fresh synthetic comparison

**Files:** New independent experiment directory; no changes to previous raw runs.

- [ ] Submit the exact frozen protocol and fresh limits for approval: at most 1,740 DFN solves, 271 API requests, 28,800 s, single-thread, no transport retry. Phase caps: gate 6 API/0 DFN; initialization 15 API/240 DFN; main 250 API/1,500 DFN. Do not start on plan approval alone.
- [ ] After explicit budget approval, run a candidate-only WarmStart response and three distinct complete bound Region contexts as the API gate; require valid full candidate schema and at least one nonzero Region tilt. Stop on gate failure.
- [ ] Evaluate all five independent BO and WarmStart initializations; stop if any seed has fewer than eight complete true WarmStart points. Preserve all raw screening and failed/partial results.
- [ ] Run BO, BO+WarmStart, BO+WarmStart+Region in frozen order for each seed, 50 new rounds each. Stop on cap/deadline/permanent failure, three consecutive formal Region failures, audit failure, or source drift. Do not pad results or automatically retry.
- [ ] Independently recalculate voltage and temperature RMSE and fixed-space HV from archived curves; report per-seed and five-seed paired differences at equal rounds and cumulative charged DFN, Region receipt/tilt/selection change, complete Pareto parameters, exact costs and wall time. Distinguish software pass, synthetic DFN result and unstarted measured-data identification.

## Self-review and approval boundary

The failed first attempt is preserved as failure evidence and contributes zero cases to the fresh comparison. This plan does not accept its invalid replies or reset its closed ledger. The new receipt preserves strict local identity while eliminating model transcription of long hashes. Existing full_v1 behavior, old cache checks and Region math are tested as unchanged. Product-code changes and new real calls remain paused until the design/plan and separate live budget are approved.
