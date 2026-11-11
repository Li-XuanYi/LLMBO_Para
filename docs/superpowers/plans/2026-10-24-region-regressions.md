# Region regression fixes

> Execute inline using test-driven-development and executing-plans. The user authorized all three reviewed fixes and a full regression run.

**Goal:** Fix the three reproducible Region issues from this chat without changing the optimization objective or adding dependencies.

**Architecture:** Keep Region as acquisition-time guidance. Compare positive EI values in log space and conservatively reject unsupported zero-EI changes. Reject out-of-range numbers before float conversion. Reconstruct the entire archived LLM request from configuration, archived inputs, and past observations, sharing the production request/context builders.

**Tech stack:** Python 3.12, NumPy, pytest, existing `.venv-pybamm312`.

## Tasks

- [x] Add failing tests in `tests/test_informed.py` for tiny/zero EI, huge JSON integers, continued optimization after invalid responses, and request tampering (including repair attempts).
- [x] Fix EI guards and numeric validation in `src/llmbo_para/informed.py`; run targeted tests.
- [x] Share deterministic request/context construction between `llm.py`, `workflow.py`, and `informed_audit.py`; reject unknown, missing, or altered request fields; run all Region tests.
- [x] Run the entire pytest suite, inspect the final changes, and report exact results.

## Review focus

- Both EI values are positive but below 1e-12: enforce the real log-gap.
- Original EI is zero: retain the plain selection without nonfinite JSON diagnostics.
- Confidence or bounds contain positive/negative integers exceeding float range: report ValueError and retain bounded repair/fallback.
- Request context includes future observations, altered fixed conditions, or extra fields: reject the archive.
- Schema-repair requests contain extra data or altered feedback: reject them while accepting legitimate repair and transport-error archives.

## Execution ledger

- Existing working tree contains unrelated user changes; edit the current checkout and preserve them.
- CodeGraph is initialized, but broad symbol queries include archived test-run source snapshots; implementation uses the identified live source files.
- RED: targeted regression run produced 13 expected failures (6 numeric validation cases, 2 EI cases, 3 workflow cases, and 2 audit cases).
- GREEN: `python -m pytest tests/test_informed.py tests/test_single_objective.py -q --tb=short` passed all 34 tests.
- Full suite: `.venv-pybamm312/Scripts/python.exe -m pytest -q --tb=short` passed all 228 tests in 243.68 seconds; no failures or skips were reported.
- Independent read-only final review found no important issues. A separate zero-alternative probe verified finite JSON diagnostics and retention of the plain candidate.
- Final scope: unrelated working-tree changes are preserved. Underlying EI approximation, optimization efficacy, and live service behavior are outside these three fixes; the existing numerical and transport tests remain in the passing full suite.
