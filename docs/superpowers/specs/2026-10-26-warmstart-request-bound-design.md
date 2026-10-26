# Request-bound WarmStart reply contract for the five-seed electrothermal comparison

Status: proposed design for review, 2026-10-26. It addresses the documented failure in docs/audits/three-arm-50round-first-live-failure-2026-10-26.md. It changes the WarmStart reply transport contract only. The six optimization variables, physical model, objectives, GP, EI, Region formula, weights, prompts for Region, and comparison metrics remain fixed.

## Problem and choice

The current full WarmStart reply asks the model to echo six long cryptographic signatures. In the first live five-seed attempt, the fifth seed returned three complete HTTP 200 JSON replies with 16 distinct in-range candidates each, but copied a signature incorrectly every time. The strict validator rejected them, as it should under that contract. Loosening the existing validator in place would permit a stale six-dimensional reply to cross task boundaries.

A prompt-only request to copy hashes more carefully is fragile. Retroactively accepting the rejected replies would change an already failed protocol after observing the output. The chosen approach is an opt-in candidate-only reply format whose identity is bound locally to the fresh outgoing request and archived response. The old full reply format remains the default and retains its exact signature check.

## Contract and provenance

New configuration value: llm.warmstart_wire_format = candidate_only_v1. The field is optional and accepts only full_v1 or candidate_only_v1; absence means full_v1 without changing an existing configuration's canonical signature. Only electrothermal schema version 2 may opt in. Its explicit value enters the configuration and cache signature.

The outgoing request still contains schema_version 2, electrothermal_4e2t, ordered fit rates, all trusted signatures, physical parameter names/ranges/units/transforms, known conditions, current true history, and the existing two-objective task. The new WarmStart prompt asks for only an object with a candidates array; each item has exactly one parameters object with exactly the six named finite numeric values. The model is no longer asked to reproduce a signature. No free-text explanation or extra identity field is accepted.

For each fresh request, the controller freezes the canonical outgoing payload and its digest before HTTP submission. It archives the run ID, request ordinal, task, artifact path, outgoing digest, decoded candidate JSON digest, archived HTTP envelope digest, transport receipt/status, and trusted profile/config/data/rate identity in a request-bound receipt. The candidate-only decoder operates only on a successful response returned directly by that request and its matching receipt. It must reject a replayed, absent, mismatched, edited, or wrong-task receipt. The decoded candidate JSON and HTTP response envelope are archived unchanged as separate artifacts. The trusted identity is never copied from the model reply or silently substituted into that reply. Cache and initial-plan keys remain derived from the trusted local profile and signatures, not the LLM content.

The candidate parser validates exact keys, types, finiteness, individual parameter ranges, and physical mapping. Invalid candidates are screened individually and counted. Duplicate coordinates, failed temperature evaluation, and missing target pairs retain existing semantics. Only complete true pairs enter the deterministic Pareto plus Max–Min selection. Fewer than eight valid distinct selected points stops initialization; there is no zero filling or numerical fallback posing as WarmStart.

Deep audit recomputes the request, decoded reply, and HTTP envelope digests and verifies the binding receipt, budget event, task, config/data/rate signatures, selected initial-plan signature, true curves, and all cost counts. Tampering with a raw candidate, receipt, profile, parameter map, rate set, or archived temperature curve fails. A six-dimensional legacy voltage or charging reply cannot be accepted merely because it has six numbers.

## Compatibility and experiment boundary

Existing full_v1 replies and strict validator remain unchanged for old configs and tests. Existing Region action reply and Region numerical method remain unchanged. Existing single-objective voltage tasks, four-rate legacy behavior, raw experimental files, and old caches remain untouched.

The failed first live attempt stays closed at 208 DFN solves, 11 API calls and zero formal BO rounds. It supplies failure evidence only. After design and plan approval, implement with RED/GREEN tests and complete software regression, then run a clean independent five-seed experiment from zero under the new contract. All five WarmStart pools must be generated under the same format; none of the failed run's candidates or initial plans are imported. Use the same five frozen seeds, three arms, eight initial points plus 50 new rounds, two synthetic rates, fixed scales/HV space, solver/GP/Region settings, and no measured-data fitting.

A new live protocol would have a separate maximum of 1,740 DFN solves, 271 API requests and 28,800 s, single-thread and no transport retry, with the same phase caps (gate 6 API/0 DFN, initialization 15 API/240 DFN, main 250 API/1,500 DFN). It requires a separate explicit budget approval. The gate must prove one candidate-only WarmStart reply and three complete bound Region contexts with at least one nonzero tilt before DFN initialization. Failure stops and archives the partial result. The final analysis independently recomputes voltage/temperature RMSE and fixed-reference HV from archived real DFN synthetic curves and reports all five paired seed outcomes. It does not claim real measured parameter identification or parameter uniqueness.
