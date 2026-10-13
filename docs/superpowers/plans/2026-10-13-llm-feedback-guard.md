# LLM feedback and GP prior guard implementation plan

> Implement task by task with executing-plans and test-driven-development. Preserve all previous run artifacts.

**Goal:** repair the WarmStart selection contract, supply true per-rate evaluation feedback, and gate LLM GP priors by forward predictive performance.
**Architecture:** existing DFN, six-dimensional domain, four-rate mean RMSE, candidate pool and Composite EI remain unchanged. Feedback and GP guard have opt-in switches. New tests may use explicitly labelled replay of archived real LLM replies; replay is never a fresh LLM call.
**Tech Stack:** existing Python 3.12, NumPy GP, pytest, PyBaMM 25.10.2; no new dependencies.
**Spec:** user-approved three-part design in the current conversation.

## Global constraints
- Base c5d0f2d4af36dc37040e5d9f20dfdeab9ecdcf78; isolated branch codex/llm-feedback-guard-20261013 in bo-repair-work/fg-code.
- Do not alter six bounds, 2.5 V cutoff, initial concentrations, temperature, electrolyte multiplier, four rate grids or weights.
- No fake failed-rate RMSE, extrapolation, truncated reference data, secret logging, unapproved API retry or overwritten history.
- Count every actual API request, failed simulation and cache source. Keep the 8-valid-initial plus 20-BO evaluation convention.
- Keep the current GP/EI fitting budget in the primary comparison; defer ARD priors, kernel evolution and selector replacement.

## Review focus
- Valid JSON with wrong business fields must not pass or silently become random candidates.
- Partial-rate feedback must retain true labels but never disclose raw curves or label a generated proposal as evaluated.
- Guard validation must exclude the initial labels shown to the LLM and predict before receiving each new result.
- Every selected GP and prediction must be reconstructible from earlier data and archived model states.
- Archived-reply replay must hash-match its source and the actual initial observations; no credentials means no new API call.

## Task 1: bounded selection repair
Files: llm.py/config.py/workflow.py/initialization.py; tests/test_llm_feedback_guard.py.
- [ ] Write and run failing tests: wrong schema, counts, duplicate/bool/out-of-range indices, exhaustion and immutable provenance.
- [ ] Add selection_max_attempts (legacy default 1; new run value 3), exact validator and format-only corrections.
- [ ] Count correction calls against the actual selection/API budget, including failures; no network retries.
- [ ] Run targeted/full regression and commit separately.

## Task 2: actual feedback
Files: new llm_feedback.py; initialization.py/config.py plus tests.
- [ ] Test true complete/partial-rate RMSE, null incomplete J, finite scalar-only summaries and chronological provenance.
- [ ] Add opt-in warm_start_feedback; retain complete successes and bounded recent partial/failure feedback.
- [ ] Derive necessary volume-fraction bounds using the existing inventory coefficients; do not alter sampling constraints.
- [ ] Restore feedback and generated/evaluated states on resume, preserving costs and immutable sources.
- [ ] Verify the off-switch retains the old behavior; commit.

## Task 3: predictive prior guard
Files: new gp_prior_guard.py; optimizer.py/config.py/workflow.py/audit.py, optional surrogate helper.
- [ ] Test pre-predicted post-initialization labels only, invalid-label exclusion, conservative fallback and no lookahead.
- [ ] Fit ordinary and fixed-group mixed GPs on the same per-rate labels with identical numerical budgets.
- [ ] Save both means and observation variances before simulation; score Gaussian NLPD in frozen transformed units.
- [ ] Prefer ordinary GP until 5 new valid rate labels. Admit mixed GP only if mean paired NLPD gain > 0.05 + 1 standard error. These fixed engineering thresholds are not a significance claim.
- [ ] Keep the proposed group fixed; an inactive branch is the ordinary fitted kernel with lambda=0, not an unexplained erased group.
- [ ] Audit shadow states, chronological score ledger and active choices independently; add tampering tests.

## Task 4: verify and continue
- [ ] Run the full suite and synthetic workflow tests; preserve failing logs and report any failure.
- [ ] Add strict, explicit archived-group replay if live credentials remain unavailable; validate original request/observations and hash.
- [ ] Run one new 20-round guarded DFN comparison with matching initial points and the archived G-new reply, against completed B0/G-new (do not repeat old arms).
- [ ] Run W-new/Full only with available credentials, or report the blocker and a verified continuation entrypoint.
- [ ] Persist code, checksummed evidence and report in the Windows project; do not leave unique results only in /dev/shm.
