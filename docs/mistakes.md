# Error and correction log

| Date (UTC) | Error found | Cause | Correction and prevention |
|---|---|---|---|
| 2026-10-10 | First PowerShell file-read command used Bash-style brace expansion and failed to parse | Shell syntax differed from the assumed command form | Read explicit paths as a PowerShell array; keep commands native to the configured shell |
| 2026-10-10 | First unit run failed while creating XLSX files and run logs in the system temporary folder | Sandbox permits writes in the repository, but Python's redirected system Temp path was not writable | Unit fixtures now request temp directories under the repository; durable verification logs also stay under `runs/` |
| 2026-10-10 | First Sobol fixture expected two wrong coordinates in dimension six | The hand-calculated expected vector used an incorrect bit combination | Corrected the fixture to the XOR-based direction-number result and retained prefix/chunk-consistency checks |
| 2026-10-10 | First workbook legacy test asserted an assumption in the wrong field | It checked an assumption label in the first text item rather than `current_source` | Assert `current_source` separately and check the recorded sample-period assumption explicitly |
| 2026-10-10 | Code review found the GP output standardization was being recalculated after every new candidate | `_fit_models` refit each rate's log-RMSE mean and scale on the entire growing history, changing the target coordinate system mid-run | Freeze the four transforms on the initial valid data and reuse them for every later GP update; a regression test adds new data and checks the values remain fixed |
| 2026-10-10 | Two early patch submissions were rejected before modifying files because the patch termination marker was missing | Patch envelope was malformed | Submit complete, smaller patches and inspect the workspace after applying them |
| 2026-10-10 | Environment inspection initially targeted system-wide package discovery and a CIM query that the restricted host denied | Python was launched without its user package path and system inventory access was restricted | Inspect through the selected Python 3.12 executable and read-only Windows APIs; record only values actually observed |

When a validation error occurs, its original output and exit code are kept in the verification run folder. Corrections do not replace previous run directories.

## Overall framework audit, 2026-10-10

The pre-change implementation and supplied specifications were copied to an immutable runs/framework-audit/ directory before repairs. Seven defects were reproduced against that archived source with the current regression cases; an analytical Composite EI reference case already passed.

| Reproduced defect | Cause and correction |
|---|---|
| Initial Sobol allocation consumed 32 sequence points for 2 requested points | The unused tail of a generated batch was discarded. Draw only consumed points; test prefix and sequence index. Candidate-pool screening now keeps a separate seen set. |
| Mixture weight could not reach zero | A bounded logit search narrowed the allowed effective range. Optimize the bounded scalar directly, including both 0 and 0.8. |
| Short failed simulation curves disappeared | Coverage checking raised before arrays were attached to the error record. Capture arrays before validation and retain them on failure. |
| Legacy fallback did not always require the discharge-current sign | Naming a current column incorrectly bypassed the explicit-sign condition. Require the sign whenever compatibility mode is enabled. |
| Partially missing current was replaced by a constant | A generic missing-value check treated partial gaps like an entirely absent current trace. Only entirely blank current can use approved fallback; reject partial gaps. |
| Nested raw arrays could be sent as residual summaries | The grouping payload lacked a scalar-only whitelist. Validate allowed statistic names, finite numbers and four-rate RMSEs before transport. |
| An optimizer object could silently append a second experiment | No lifecycle guard existed. Each optimizer instance is single-use; every experiment requires its own archive. |

Additional corrections from the interface audit: the JSON template is now wired to actual data and simulation conditions; lab porosity must match the search constraint; source/configuration/GP/EI records are complete enough to recompute results; recovery writes to a new run; unsupported GPU/concurrency options are rejected. The original README test command dropped a backslash through JavaScript string escaping; the checked-in command now uses the literal PowerShell path.

The first completed status report preferred its last progress snapshot for speed, which excluded the final GP update. Completed status now uses the terminal summary's complete elapsed time, and a test compares the two values.

Final documentation review found that generic python commands could select the host's default Python 3.14 after optional virtual-environment setup. Every README CLI example now uses the same explicit $runPython interpreter variable; the directly reproducible verification command uses the verified Python 3.12 executable.

## Live API probe, 2026-10-11

The first probe treated any HTTP 403 as credential rejection. Reading the archived error body showed FreeTierError: this free model can only be used inside OpenCode. The diagnosis now distinguishes the provider's explicit error and does not infer invalid credentials from 403 alone. The original run remains unchanged except for an added correction artifact. A second ordinary-model request returned HTTP 402 with an upstream insufficient-funds message; no unchanged retries or fallback success claims were made. See [API test report](audits/api-connectivity-2026-10-11.md).

For the replacement API, the supplied shorthand dsv4flash returned model_not_found under its SVIP (distributor) group. An authenticated model catalog returned deepseek-v4-flash and deepseek-v4.1-flash; the former passed a minimal generation test while the response self-reported the latter. Save both requested and reported labels; do not silently treat them as identical scientific model versions.

The minimal probe declared the application's User-Agent but the first integrated client inherited Python's default header. Both real tasks then received HTTP 403 / error code 1010, and the optimizer legitimately fell back to Sobol. The live acceptance harness marked that session failed despite its five successful synthetic evaluations. The client now declares the same truthful application identifier as the successful probe; a protocol regression checks the header. Failed histories and raw diagnostic bodies are preserved for comparison. A successful numeric optimization alone is insufficient evidence that the LLM integration worked.

During this implementation, one regression fixture used exact equality after a floating-point normalization round trip. The observed difference was below 1e-14; the fixture now uses that explicit tolerance. Its failed test log is retained. One patch attempt evaluated PowerShell variable syntax as JavaScript template interpolation; another combined a delete and add for the same file, which the patch tool rejected. Both failed before changing files. Updates now use a single update operation and raw text without JavaScript interpolation.

The repaired live session accepted both real LLM warm points and completed five synthetic candidates with a passing deep audit; its archived Warm Start wire body is identical to the failed session's body. The source diff and repair lineage are saved with the successful run. Inspecting saved GP states also confirmed that parameter groups reached the kernel: three nonempty groups selected zero mixture weight, and fixed-hyperparameter likelihood checks favored zero over the tested positive weights. Do not claim LLM benefit from a successful interface test. An initial evidence read guessed a nonexistent gp.py; file inventory identified the existing surrogate.py, which was then reused. See [replacement API acceptance report](audits/newapi-live-2026-10-11.md).

## Workflow review and semantic acceptance, 2026-10-11

- An archival launch command nested two PowerShell here-strings and failed to parse before inspection started. Archive command text independently and invoke a separate literal-path script. The corrected inspection completed.
- External requests were initially launched inside the restricted network sandbox and both failed locally with WinError 10013. Check network execution requirements before calling the API; the same bounded command succeeded with approved network access. Preserve local socket errors separately from provider HTTP errors.
- Four returned parameter groups contained all six parameters. The optimizer correctly used full kernels, but the acceptance runner counted the filtered empty groups as successful responses. Record original semantic validation reasons and require them to pass; distinguish explicit abstention from invalid fallback. Strengthened prompts and constraints, added two regressions, passed all 36 tests, and reran both real tasks. The final response explicitly abstained for all four rates, which does not prove scientific benefit.
- Broad combined reads included historical archive file inventories and caused output truncation. Keep inspection scoped to named current files and request only the relevant ranges.
- One report patch contained an incomplete context line for decisions.md and was rejected before changing files. Split report creation from unrelated edits and verify every patch context.

All failed histories, corrections and final evidence are linked in the [workflow review report](audits/workflow-review-2026-10-11.md).

## 21700 Reference alignment, 2026-10-11

- The initial-state validation test called an unimported helper and omitted the validation import. Its first run failed with NameError. Reuse self.small_config() and import the validator explicitly. The failed verification at runs/verification/20261011T022203Z_4ade7656/ remains; all 38 tests then passed in both selected environments.
- Planning initially named official PyPI, while the actual pip index was the Aliyun mirror. Record actual download URLs and hashes. A cache-disabled dry run downloaded wheels to temporary storage, causing a second download for archival. Future resolution should retain a project-local pip cache. All 40 wheel files are now saved and installed offline with required hashes.
- A broad inventory and combined source read again caused truncation. Limit reads to named files and relevant sections. A report patch also mistook architecture.md content for README context and was rejected without changes. Split edits by actual file and verify exact context before applying patches. These repeat earlier inspection/patch errors and are explicitly recorded.
- Reference's example positive fraction exceeds 1 minus fixed positive porosity; a 2C-labelled cell also contains a 1C sheet/experiment. Preserve both findings. Resolve the physical domain before using examples as candidates and inspect actual experiment text rather than copying titles.

## Real DFN and fixed electrolyte calibration, 2026-10-11

- A diagnostic assumed every failed simulation had arrays and called len(None). Preserve null arrays for solver failures, and use explicit empty-list fallback only for reporting. The corrected diagnosis is archived; physical coverage failures retain their actual short arrays.
- A prompt filename and a reference-cell patch context were guessed incorrectly. Both failed without mutation. Inspect the named file and exact context before editing; do not invent version suffixes.
- A new regression imported read_json from runstore, where it does not exist. Verification 20261011T040715Z_1803465e failed on import. Use the existing json.loads(Path.read_text()) pattern; corrected verification 20261011T040750Z_7308eeb4 passed 41 tests.
- Deep nesting of calibration archives exceeded Windows path limits while copying source, before any solve. Retain the failed archives with terminal markers and link the replacement under the shorter runs/electrolyte-calibration root. Keep further stage roots shallow and connect them through immutable JSON links.
- The measured pilot preflight required the transient credential before the runner collected it. Preserve the failed zero-solve session. Allow only the known missing-credential error at the first check, collect the hidden credential, then rerun the full preflight before any API or solve.
- The first measured pilot hit sandbox WinError 10013. Its planned fallback consumed four Sobol candidates, all physically invalid, so no GP could fit. Diagnose the HTTP record before attributing this to LLM quality. The network-enabled retry was then rejected by automatic approval review for unapproved data-derived summary disclosure. Do not bypass it; request explicit payload approval and continue local work.
- Smaller Casadi time steps did not fix the event-root failure. The controlled IDAKLU comparison matched valid low-rate curves within 0.03 mV and exposed the actual high-rate cutoff. Solver recovery does not authorize inventing missing curve values.
- Raising particle diffusivities/conductivities did not resolve the original 3C transport limitation. Inspect concentration and overpotential states and a finer mesh before changing scientific settings; user authorization preceded the separate fixed-electrolyte calibration.
- A text-mode Windows copy changed the frozen config's LF newlines to CRLF, so semantic settings matched but the file SHA-256 differed. The first local final audit correctly failed the byte-equality check. Preserve that source snapshot and copy bytes directly; save both hashes and semantic comparison before rerunning the audit.

## Four-arm remote preparation, 2026-10-11

- The restricted Windows environment denied WSL access with E_ACCESSDENIED. Preserve the error and use the approved WSL execution path; do not mistake it for a remote SSH authentication failure.
- Remote Python could not create a normal venv because ensurepip was absent. The failed environment and output remain archived. Create an isolated venv with --without-pip and use the existing system pip's --python target; save Linux wheels/hashes and install offline without sudo or global package changes.
- Automatic review rejected source/XLSX upload despite the remote experiment request, requiring explicit dataset transfer authorization. No upload ran. Keep API-summary consent separate from SSH workbook-transfer consent and ask the specific unresolved permission.
- Eight legal random parameter vectors produced zero complete four-rate labels. Inspect all 32 stored early-cutoff curves, do not fabricate scores or silently add feasible seeds. Discuss prescreening versus strict failed initialization before scale-up. Preserve diagnostic costs separately from formal ablation costs.
- The first suite implementation would abort all four arms when shared WarmStart generation failed and treated a failed deep audit as completed. Isolate component-dependent failures, continue independent arms, record all four outcomes and require the deep audit to pass. Add a regression covering both failure paths.

## Random-point cutoff explanation, 2026-10-11

- The original adapter retained curves but omitted Solution termination/events and internal states. A coverage error alone could not establish why the solver stopped. Replay the same frozen cases through the existing adapter with a diagnostic observer and preserve the actual event/state records separately. All 32 cases reproduced and hit the minimum-voltage event.
- A diagnostic lookup again guessed a nonexistent script filename. The read failed without mutation. Reuse the actual file names returned by inventory; the existing calibration script supplied the relevant archival/preflight pattern. This repeats the earlier filename-guessing error and is recorded explicitly.

## Cutoff design attribution, 2026-10-11

- Framework/synthetic acceptance was described too broadly relative to measured-data readiness. The supplied method and implementation lacked a defined recovery policy for zero valid initial labels. Qualify software acceptance, explicitly document the unresolved real-data protocol, and do not attribute an initialization block to LLM/GP effectiveness before either is evaluated.
- Reference's available-simulation-grid score differs from the fixed complete-measured-grid objective. Verify the actual interpolation direction and scoring domain before explaining why Reference can produce a numeric score for an early-ending curve. Preserve the comparison and do not silently train on partial scores as if they were full RMSEs.

## Feasibility repair, 2026-10-11

- The first cache regression compared tuple-rich in-memory dataclasses with JSON lists and rejected identical saved records. Preserve verification 20261011T072759Z_b83cd37d; normalize accepted records by reading the immutable JSON before comparisons. Corrected verification 20261011T072907Z_3ed2bdd1 passed 53 tests.
- apply_patch rejected a patch that deleted and added the same path in one invocation. No files changed in that rejected patch; perform those operations sequentially.
- CIM host resource queries were denied by the restricted Windows environment. Use read-only native memory/system-time counters and archive the snapshot; do not infer an idle host. The snapshot showed approximately 86% CPU and 85% memory load, so retain one below-normal-priority CPU worker.
- The first priority adjustment omitted explicit 64-bit Windows HANDLE types and failed before any solve. Preserve random-screening-console.txt, specify HANDLE argument/result types, then retry with a new log. The following preflight caught a staging configuration with zero Sobol points and no supplied initial set. Correct the template allocation to eight before the first real solve; preserve the failed zero-solve stage.

- A real group request failed with HTTP 503/model_not_found: deepseek-v4-flash is no longer routed for this account. The subsequent models-list GET returned 29 models and no DeepSeek/dsv4flash entry. Preserve both records and request a model choice; do not silently switch the scientific experiment to another model.
- The first long screening process was still using its loaded code while source files were edited. Its final traceback consulted the newer file text, so the displayed source line did not match the loaded instruction. The run's source snapshot preserves the executed revision. Finish or use isolated frozen source before future edits to an active experiment runner.
- The random pilot exhausted 200 candidate evaluations with four valid points. Retain all 800 rate attempts and 6720 raw draws; do not reset the seed or screening cost when extending a budget. The continuation path replays the consumed RNG sequence, validates the original curves and implementation hashes, and adds only new attempts under a separate directory.

- 2026-10-11 local-study preparation: used the metadata key authorization for a human approval note; RunStore correctly rejected that reserved credential-like field before creating a run. The configuration and decision entry already written were retained. Renamed the note to user_approval_record and resumed without rewriting the existing configuration. No API request or DFN solve occurred in the failed preparation.
