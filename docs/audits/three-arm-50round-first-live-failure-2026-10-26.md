# Five-seed, three-arm 50-round first live attempt: stopped during WarmStart initialization

Date: 2026-10-26. Status: failed closed; no formal BO rounds ran. This is a synthetic DFN–lumped-thermal experiment on 0.5C and 1C, 60 s per rate. It is not measured-data identification.

## Frozen run and actual outcome

- Source worktree HEAD: 66498786e6f2841edf49e42fbdbdf2798820b3bc; numerical core fingerprint: b101a433b054dca8931c6c59c31bfce0fe2cf752d8cf0636dc88766e3459c231.
- Protocol SHA-256: 7256f3d1affdead2e3ce2b6f6903ccad33d77e72ac7b795853454d0dd895abb2. Limits: 1,740 DFN solves, 271 API requests, 28,800 s. Single-thread, no automatic transport retry. A failure with fewer than eight valid WarmStart initials stops the entire study.
- API gate passed: one minimal request and three different complete Region contexts; all four received valid bound replies, including a nonzero tilt. No DFN solve was used in the gate.
- Seeds 376330, 633262, 789058, 609653: each produced eight complete numerical BO initials and a complete 16-candidate WarmStart screening pool, selected to eight points with deep audit passing. Seed 362724: eight complete numerical BO initials; WarmStart did not yield a valid candidate.
- The fifth WarmStart sent three requests. Each returned HTTP 200, a complete JSON object, and 16 distinct named candidates within the configured parameter bounds. The three full replies were rejected before candidate evaluation because the LLM echoed the signed data hash incorrectly. The third reply also echoed the algorithm hash incorrectly. The original strict validator correctly rejected these mismatches; it was not a solver, temperature, Region, GP, or acquisition failure.
- The actual validator was run offline against each archived reply and rejected all three with "stale or mismatched electrothermal response". As a diagnostic only, replacing the echoed signature dictionary with the trusted outgoing request signature made the same validator return 16 candidates each time. No archived reply, objective, signature, or code was altered.
- Parent exit code: 1; status failed; phase initialization; main cases: 0/15; formal BO rounds: 0/750. Actual costs: 208 DFN solves and 11 API requests (gate 4 API; initialization 208 DFN and 7 API). The hash-chained budget ledger is closed. No RMSE/HV gain conclusion is possible from this attempt.

## Root cause and boundary

validate_warmstart_response requires exact equality of the entire response identity dictionary with prepared.signatures. build_warmstart_payload asks the model to reproduce several long digest strings in the JSON response. The synchronous transport and JSON decode succeeded; the model changed characters in a digest while generating otherwise syntactically valid replies. Candidate validity is a separate check and had not run. Removing signature validation globally would let same-dimensional stale replies or old six-parameter caches cross task boundaries, so that is not an acceptable fix.

The warnings printed by PyBaMM were nonfatal FutureWarnings. The first four seeds' evaluations completed and their deep audits passed. The fifth seed's replies were not promoted to an initial plan and were not used for fitting.

## Evidence and preservation

Evidence root: D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\three-arm-50round-20261026.

- result.json SHA-256 3f5c75b77b8996a83cb5c83fedafc51edebcbaa825ce05ee10654aced5d5bf00.
- budget-journal.jsonl SHA-256 6fbb60e2bf7b542c03fb8ab872e8df453c0aa921a7a4b948f2ad21f607d5a205; closed at 208/11.
- live-protocol.json SHA-256 7256f3d1affdead2e3ce2b6f6903ccad33d77e72ac7b795853454d0dd895abb2.
- Fifth seed raw replies and diagnostics: D:\Users\aa133\Desktop\LLMBO_Para\runs\g26x\seed-362724-warmstart-init\20261026T121405Z_a86591c1cca0_9e21a11e\http, plus events.jsonl, warmstart-selection.json, and terminal.json in that run directory.
- Software release before the attempt: 1,620 passed, zero failed/error/skipped, exit 0; JUnit and log under three-arm-50round-20261026\tests\ge-three-arm-full. This is software evidence, not a completed physical comparison.

The original run remains immutable. A new reply contract and a fresh independent experiment protocol require review before product-code changes or new real calls.
