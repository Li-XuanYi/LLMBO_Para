# Implementation decisions and unresolved research inputs

This file distinguishes the implementation behavior from scientific choices still owned by the research group.

Cutoff attribution review (2026-10-11): Reference scores voltage at each candidate's simulation times, so early-ending curves retain finite partial scores; the current fixed full-grid evaluator rejects them. Method v0.2 excludes fabricated failure labels but leaves zero-valid-initialization recovery unspecified. The current real-data protocol therefore needs an explicit feasibility/recovery policy before judging LLM/GP performance. See [design attribution audit](audits/cutoff-design-attribution-2026-10-11.md). Software framework acceptance is distinct from a completed measured-data identification.

Latest state (2026-10-11): measured data are 21700, using Reference's DFN/Chen2020 design and the separately calibrated fixed electrolyte multiplier 1.5. The current request supersedes the earlier 20-point initialization: four ablation arms, eight initial points each, then 25 BO updates. The user approved the specified API summaries. A local eight-random-point diagnostic produced zero complete four-rate observations; initialization feasibility policy awaits the user's decision. Automatic review separately requires explicit source/workbook transfer approval before deployment to zju. See the [ablation protocol and audit](audits/ablation-zju-2026-10-11.md). Earlier dated statements below remain as decision history.

| Area | Implemented behavior | Research input still required |
|---|---|---|
| Cell | Current data are 21700; Reference uses Chen2020 and 5 Ah | Full laboratory make/model is not separately recorded; old template is historical |
| Search variables | Six image ranges in Method order; particle diffusivity mapping confirmed; feasible active maxima 0.75/0.665 | Independent parameter identifiability validation |
| Dataset | XLSX hash and four sheets preserved; 1 s interval confirmed | Preserve derived-current source labels; T unit remains unknown |
| Comparison | All four full measured grids; RMSE only for complete coverage; no extrapolation | Independent validation data for scientific acceptance |
| Battery model | Reference initial concentrations retained; single-thread IDAKLU; fixed electrolyte diffusivity scaled by 1.5 after separate pilot calibration | Same-data calibration is provisional; verify fixed setup independently |
| Search | Four independent rate GPs, frozen per-rate log-RMSE standardization, full/subset Matérn 5/2 mixture, Composite EI; four arms with 8 valid initial + 25 BO attempts; bounded prescreening approved | Real-data screening acceptance and measured ablation outcomes |
| LLM | Two independently switched components; WarmStart uses generation and selection tasks, GP enhancement uses parameter grouping; limited summary disclosure approved | Successful measured-data execution and validation; no scientific benefit established yet |
| Compute | One worker; deterministic CPU path | GPU library/device compatibility; optional acceleration must be compared against CPU numerics before production |
| Output | Unique run directory, immutable attempt records, append-only events and run manifest; selected remote root /home/yqt/XuanyiLi/LLMBO | Explicit source/workbook transfer permission after automatic review rejected deployment; long-term retention policy |

The first supplied workbook has SHA-256 `6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7`. Its four sheets are `0.5C`, `1C`, `2C`, and `3C`, and the observed headers are `I`, `U`, `T`; `I` is blank and no time column is present. It therefore fails strict measured-input preflight. The four voltage columns contain 6781, 3409, 1714 and 1139 numeric samples, respectively. The workbook's `T` column interpretation is unconfirmed (observed numeric ranges are 24.4–28.3, 24.7–32.9, 23.6–44.5187 and 24.4–25.0). The implementation does not infer capacity or current from the 18650 format.

The read-only inventory is preserved at `runs/data-preflight/20261010T141957Z_7f16e533a792_5118fd63/inspection.json`; its sibling manifest stores the command, machine/runtime, and workbook hash.

CodeGraph indexing was explicitly deferred at the user's direction. The implementation reused the reusable optimization concepts in `Reference/LLAMBO-master`, while avoiding its incompatible battery notebook/API assumptions and keeping `Reference/` unchanged.

## Framework implementation authorization and configuration evolution

2026-10-11 clarification: the user confirmed one sample per second and said T should be temperature, with its unit still unconfirmed. The cell is known only as 18650; capacity, full cell model, laboratory parameterization and parameter bounds are not yet available. Store this clarification under data/metadata/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/. The library lookup found no PyBaMM in the project Python 3.12 runtime; default Python 3.14 has an old build that cannot load Chen2020. Official library sets need a cell match before scientific use. See [current workflow review](audits/workflow-review-2026-10-11.md).

The user's later request to build and audit the complete framework supersedes the Stage0-only restriction for this implementation round. It does not supply scientific cell values or authorize a paid API request. The missing Architecture v0.1 was replaced by the user's instruction to use Method v0.2, and the current implementation contract is documented in [architecture.md](architecture.md).

The original true_data.xlsx was copied without modification into data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx. origin.json retains its original WeChat storage path and digest. The research template now references this canonical local copy relative to the config directory; I is explicitly mapped while its blank values still prevent a real run. Time and temperature meanings remain unresolved.

The old template's unused global initial-condition fields were replaced by conditions_by_rate. New settings explicitly select data units, discharge sign, model version, five mesh sizes, Casadi safe solver tolerances and step limit, numerical thread count, and transient retry budget. Old configurations and source are preserved in the framework audit baseline and historical run manifests.

The implementation deliberately uses the existing NumPy exact GP rather than adding an unverified GPU/BoTorch stack. The learned kernel weight is now optimized over its full permitted interval. Fixed standardization and actual simulated labels are checked by the result audit. Actual LLM endpoints must implement the documented structured JSON contract; a generic chat API URL is insufficient.

Method 3.6 comparison algorithms, ablations, repeated-study orchestration and the separate three-rate/3C holdout protocol are a later study layer. The current completed scope is the reusable main-method framework and its reproducibility/audit/recovery interfaces. Real scientific acceptance still requires the lab inputs and a real four-rate PyBaMM smoke run.

2026-10-11 latest correction supersedes the earlier 18650 interpretation: the unchanged workbook is measured 21700 data, and the user selected Reference/P2D.ipynb's DFN/Chen2020 physical design. Image ranges are preserved separately from Reference's older bounds. Reference uses its initial concentrations through solve() without initial_soc. The adapter now supports explicit initial_state_mode=parameterization and requires null SOC to preserve this behavior; explicit_soc remains available. No notebook is executed and Reference remains unchanged.

The dedicated Python 3.12 environment now contains pinned PyBaMM 25.10.2 and resolved wheel hashes, with telemetry disabled and one numerical thread. Local inspection confirms Reference capacity 5 Ah, fixed porosities 0.25/0.335, isothermal 298.15 K and 2.5 V cutoff. Image D_e notation and active-fraction bounds exceeding fixed-porosity feasibility require scientific clarification before activating a real run. See the [21700 alignment audit](audits/21700-reference-alignment-2026-10-11.md). This round accepts environment and interfaces, with zero real battery solves.

Subsequent user confirmation resolved both questions. The subsequent real smoke exposed numerical Casadi event-root failure and, after IDAKLU recovery, genuine early cutoff at high rates. The user chose to keep the four-rate target and calibrate fixed electrolyte settings. Multipliers 1.25, 1.5, 2.0 were tested at one fixed six-parameter point; all covered the four measured grids, with mean RMSE 71.37, 67.50 and 80.75 mV. Scale 1.5 is frozen before six-variable BO. It was selected using the same workbook and is not a measured material property or a seventh BO variable. No six-variable bounds, currents, porosities, temperatures or cutoff were changed in this calibration. The real API pilot was blocked by the network sandbox, followed by an automatic approval rejection of the summary disclosure; no provider answer was received. See [calibration audit](audits/21700-electrolyte-calibration-2026-10-11.md).

## Feasible initialization repair, 2026-10-11

- The user approved docs/proposals/feasible-initialization-2026-10-11.md by replying 同意建议 开始修改. Eight initial points now means eight complete valid four-rate evaluations, acquired under the explicitly bounded and fully charged screening policy. Historical strict-eight results remain unchanged.
- A necessary lithium-inventory bound rejects points without a solver call. It does not certify feasibility. Random draws remain seeded uniform draws; WarmStart remains LLM generation of 20 and separate selection/refill, with no random substitution. Each family is capped at 200 DFN candidates; random raw draws at 20000; LLM generation/selection at 10/30 requests.
- Two valid points trigger a curve/score/provenance audit before continuing to eight. Existing accepted results feed the paired arms without repeat DFN calls. BO failures consume an iteration and do not enter GP targets. Cache lineage, actual solver cost and standalone screening attribution are separate.
- Scientific settings and six bounds are unchanged by this repair. The source/XLSX transfer to zju still needs the explicit permission requested after automatic review rejected it.

## Local execution approval, 2026-10-11

The user selected local execution and explicitly agreed to qwen3.7-flash and a cumulative random screening limit of 800, retaining the prior 200 evaluations and four valid points. The random raw-draw limit remains 20000. The LLM family retains its original 200-candidate, 20-proposal batch, 10-generation/30-selection limits. Both families target eight valid points, followed by four paired ablation arms with 25 BO attempts each. One CPU worker and one numerical thread; no remote operations are planned. New configuration: configs/21700-local-qwen-20261011.json. Old settings and results remain historical records.

## Completed local four-arm study, 2026-10-11

Qwen's real probe returned AllocationQuota.FreeTierOnly. The user explicitly selected gpt5.6sol, mapped to the provider-listed gpt-5.6-sol; the new configuration and response identities are archived. Random screening reached 8/8 after 387 cumulative evaluations; WarmStart reached 8/8 after 28 evaluations and seven API requests. All four arms completed 25 BO attempts and passed deep audits. See docs/audits/local-ablation-2026-10-11.md. Historical decisions above are retained; no remote operations occurred.
