# Five-seed bound WarmStart experiment: pre-header TLS EOF stop

Date: 2026-10-26. Status: failed closed during initialization. This is evidence about the 0.5C/1C, 60 s **DFN synthetic** comparison; it is not a measured-data result or a BO method comparison.

## Frozen release and budget

- Source commit: `79bc4d3ad23964e7e61831d3b91fb7c40a773e85`; source fingerprint: `a1b311156fe46ea6ac8beed56d15683d31c9ada0e183734a416d71412f077f71`.
- Software release: 26/26 targeted tests and 1,634/1,634 full regression tests passed, exit 0, with 0 network and 0 battery-solve attempts in the guarded regression. JUnit and exact run metadata are under `bo-repair-work/20261017_et_implementation/warmstart-bound-repair-20261026` in the main project directory.
- Frozen live protocol SHA-256: `368bcb36797ba549de68360ab2fce95cd3a19864c4d36578f7d8511410f7ef65`. Separate approved ceiling: 1,740 DFN solves, 271 API requests, 28,800 s, single thread, no transport retry. Earlier failed experiment remained closed.
- New budget journal SHA-256: `dc28dae91aabf9e9adf6dadcbfb5a9ebf4c15a9a372eba9c4d6ffe32aaae105c`; result SHA-256: `9f715cde368177d34783ee0250ff39711d934a4930e59b40faed37f0d284a154`. The hash-chain loader reports **closed**, actual **60 DFN / 8 API**. Process exit code **1**.

## Observed sequence

1. The minimal API probe, candidate-only WarmStart gate, and three distinct historical Region gates all passed (5 API, 0 DFN). Candidate gate returned 16 valid candidates; all three Region gates applied nonzero tilt.
2. Seed 376330 completed audited ordinary BO initialization (8 points, 16 DFN). Its first candidate-only WarmStart request succeeded. A later request had pre-header TLS EOF, but the first response had already yielded 14 complete true pairs, from which 8 were selected; this initialization passed deep audit (28 DFN, 2 API).
3. Seed 633262 completed audited ordinary BO initialization (8 points, 16 DFN). Its first WarmStart request failed before HTTP response headers. No HTTP response, binding receipt, candidate screening, or DFN call followed. The worker stopped; the parent closed the journal. This request was the eighth API call. No formal BO arm began; **0/750 new rounds** and **0/15 arms** completed.

The failed request's configuration and frozen payload both specify `candidate_only_v1`, `electrothermal_4e2t`, and `['0.5C','1C']`. The HTTP request archive exists. The HTTP response archive and WarmStart binding receipt do not. The sanitized HTTP error and parent supervision both report `URLError`, `SSLEOFError`, category `tls_eof`, OS errno 8, `http_status=null`, and stage `awaiting_headers`. The request started and failed after about one second, well before the 120 s timeout. A separate first-seed WarmStart request showed the same pre-header TLS EOF. The successful first-seed request and the failed second-seed request each had an 8,231-byte archived Chat body, the same model, 8,192-token ceiling, and `thinking=disabled`.

This localizes the stop to the HTTPS transport before any model reply. The evidence does **not** identify whether the peer, an intermediary, or the local TLS stack closed the connection. It does not implicate the candidate schema, Region formula, temperature objective, or GP. The current workflow intentionally stops on a failed WarmStart request under the approved no-retry protocol. A deep read-only audit of the three completed initialization runs passed.

## Scientific consequence and next decision

There is no five-seed RMSE or HV gain estimate: the formal BO comparison never started. The three completed initialization archives remain diagnostic only. Do not reuse their parameters in a new trial without changing and approving the comparison protocol. Do not reopen this journal or infer a method failure from the missing rounds.

A new, explicit protocol could start all five seeds fresh and allow a **bounded new request only for a classified pre-header TLS EOF** in candidate-only WarmStart. The failed request would count against the existing per-seed, phase, and global API ceilings; the new ordinal would have its own frozen payload and receipt. Other failures, any received HTTP response, and all Region requests would remain fail-closed. This is a transport resilience amendment, not evidence that the underlying TLS source has been fixed. It requires a new design/plan approval and a new independent live budget before implementation or testing.
