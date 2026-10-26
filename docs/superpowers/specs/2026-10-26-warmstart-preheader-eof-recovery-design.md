# Candidate-only WarmStart pre-header EOF recovery design

Status: proposed, not implemented. Evidence: `docs/audits/three-arm-50round-bound-tls-eof-2026-10-26.md` and the closed run `bo-repair-work/20261017_et_implementation/three-arm-50round-bound-20261026` in the main project directory.

## Decision and scope

The previous five-seed trial stopped during seed 633262 WarmStart initialization after a request failed with `SSLEOFError` before HTTP response headers. The candidate-only contract itself worked in the gate and seed 376330. There was no formal BO round, so neither RMSE nor HV gain can be inferred. The TLS peer responsible is not identified by the available evidence.

Two viable responses are (a) repeat the frozen no-retry protocol from zero, accepting the same failure mode, or (b) allow a narrowly classified new WarmStart request within its existing three-request allowance. Choose (b): it can recover a transient pre-header disconnect without changing the accepted reply, the 8-point selection rule, numerical methods, or the scientific comparison. This is resilience to an observed transport failure, not a claim to fix the upstream TLS source.

## Opt-in contract

Add `llm.warmstart_preheader_tls_eof_continue: true` to schema-version-2 electrothermal configuration. Omission/false preserves the current fail-closed behavior; omission also preserves existing configuration signatures. The explicit true value changes the configuration and algorithm signatures. It does not change the data, physical evaluation, fixed metric space, or physics cache key; those already include the parameter profile and fitted rates. It is permitted only with `warmstart_wire_format=candidate_only_v1` and Chat Completions transport. No Region or full-v1 request uses this policy.

When a candidate-only WarmStart request returns no reply, the controller may send a **new** request only if all are true:

1. The archived outcome is `failed`, reason `transport_error`, HTTP request started, failure stage `awaiting_headers`, HTTP status absent, and sanitized network category `tls_eof` with cause `SSLEOFError`.
2. No HTTP response archive or binding receipt exists for that ordinal.
3. Fewer than the required eight distinct complete true objective pairs are available; the configured candidate, solve, request, and wall-clock limits still permit another request.

The new request gets its own ordinal, frozen payload digest, HTTP archive and, if successful, request-bound reply receipt. The failed ordinal remains in the cost and audit trail and never contributes a candidate. At most three WarmStart API requests occur per seed, including failures; no additional request or solver budget is created. A second such failure may continue to the third ordinal; three failures stop. Any other transport/protocol/HTTP failure stops immediately. If at least eight complete points already exist, selection proceeds from them without a recovery request.

No hidden replay occurs in the HTTP transport. The fixed Pareto plus Max–Min selection rule, six physical parameters, two objectives, GP/EI, Region, rates, scales, fixed HV space, DFN model, initial eight points, and 50 rounds remain unchanged. Actual API/DFN costs and each failure are reported. A successful API gate does not count as an optimization observation.

## Verification and live boundary

RED/GREEN tests must cover the exact classified failure then a valid response, repeated classified failures exhausting the three-request cap, a nonmatching failure stopping, sufficient existing pool stopping, missing HTTP response/receipt for failed ordinals, unique new binding and deep audit, and default/legacy compatibility. The guarded full software regression must have exit 0, no failures/errors, no network or battery solves, and stable source/protected files.

After software review, a **new** frozen live experiment starts all five preregistered seeds from zero in a new output directory. It does not import any initial plan, evaluation or API reply from either closed attempt. The proposed independent ceiling remains **1,740 DFN solves, 271 API requests, 28,800 s**, single-thread; its existing phase ceilings remain gate 6 API/0 DFN, initialization 15 API/240 DFN, main 250 API/1,500 DFN. A candidate-only gate and three historical Region gates still precede DFN. Every API attempt counts, including classified EOF failures. Any budget breach, insufficient eight-point initialization, invalid binding, failed deep audit, or incomplete arm stops and closes the new ledger. The prior attempt's 60 DFN and 8 API remain separately disclosed as already spent; they are not credited to the new ceiling. Final RMSE/HV comparison is reported only for 15 complete audited arms.
