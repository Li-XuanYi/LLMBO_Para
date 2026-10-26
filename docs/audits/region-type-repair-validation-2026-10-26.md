# Region type compatibility and20-round paired validation — 2026-10-26

The fixed JSON-format metadata bug is repaired. The completed synthetic comparison does **not** show a mean HV gain.

## Software change and verification

- Source commit: `ea445fa6c00c75a4721d6ad0571624d94f9ea8e0`; branch `codex/electrothermal-mo-20261016`.
- Product change: only `src/llmbo_para/electrothermal_lgbo_wire.py`, accepting optional native-string `type=json_object` without changing reply binding, region validation, raw archives or the outbound contract. Unknown fields and all other metadata values remain rejected.
- Added19 boundary cases; observed RED4failed/15passed before implementation. Baseline wire suite80passed. Targeted repaired suite106passed.
- Complete guarded regression:1600passed/0failed/0errors/0skipped, exit0; source/protected files stable, sockets0, battery solves0 (two explicitly permitted non-battery fixtures).
- Additional isolated entry/native checks19passed and independent RMSE/HV checks6passed, exits0. These are separate commands, not a historical test count.
- All five previously archived real replies decode offline after repair; the original rejection records were preserved. Fresh-context source review found no issues.

## Registered comparison

0.5C/1C, each60seconds, existing real-DFN-generated synthetic observations. Eight identical physical coordinates were reevaluated under the repaired source to create a fresh strict-signed shared plan. Plain/Full each received8initial points plus20new BO rounds for seeds1709/3253/5501. No WarmStart API, measured fitting, old3C, Prompt/formula/kernel/physical changes or automatic retries. Plain is ParEGO with the shared initialization and Region disabled; this isolates Region, not the total benefit of LLM WarmStart.

HV space `[F_U/0.1V,F_T/1K]`, fixed reference `[10,10]`. Both errors below come from the same equal-weight augmented-Tchebycheff Pareto representative per case.

| Seed | Plain HV | Full HV | ΔHV | Plain U mV | Full U mV | Plain T K | Full T K |
|---|---:|---:|---:|---:|---:|---:|---:|
|1709|99.75957717|99.83821450|+0.07863733|5.621693|2.055081|0.02495969|0.02821369|
|3253|99.75749479|99.79637872|+0.03888393|2.482558|1.152888|0.03890435|0.00884345|
|5501|99.84536838|99.64753067|-0.19783771|2.786110|4.146369|0.01035610|0.05533974|

Three-seed means: voltage RMSE 3.630120→2.451446mV (-32.47%); temperature RMSE 0.02474005→0.03079896K (+24.49%); HV 99.78748011→99.76070796, mean ΔHV=-0.02677215 (-0.02683%).

Two HV gains were outweighed by seed5501. Its20Region requests all returned valid actions, all20tilts were nonzero and five selected candidates changed. Thus the negative result in that seed cannot be attributed to the fixed type rejection or failed transport; it reflects the sampled search path under the existing Region rule. This does not establish a universal failure or statistically reliable gain from three seeds.

## Runtime and audit evidence

- Minimal plus three distinct complete Region API contexts passed binding and independent frozen-GP/EI checks; all three had nonzero tilt and one changed selection before DFN was released. GP training state and original variance were preserved.
- Formal Region requests60:59valid,59nonzero tilts,14changed selections. One seed1709 round20 request failed with RemoteDisconnected while awaiting headers and fell back to plain EI. No reply-schema failure. It was not retried. An interim commentary initially called it a validation rejection; the subsequent diagnostic correction and this report identify the actual transport failure.
- Three genuine Region replies in this new run contained `type=json_object` and were successfully decoded.
- All six cases completed20rounds and deep audits. Independent curve recomputation checked168complete archived records (including reused initialization across arms),336rate-specific voltage/temperature RMSE pairs and six complete HV histories.120new-round objectives are exported in round-rmse.csv.
- New costs:64API/256DFN, execution exit0. Old closed paired-campaign14API/66DFN remain separate; cumulative78API/322DFN. Shared initialization was evaluated16DFN times, then240DFN for120BO candidates; six cases reused the strict eight-point plan.
- Eleven owned process trees stopped cleanly; previous280sealed files unchanged. No credentials in artifacts.
- Software acceptance and real DFN synthetic acceptance completed. Measured-data identification remains unperformed: current, temperature measurement semantics, initial conditions and cooling require confirmation. Sixty-second sparse/coarse synthetic data and three optimizer seeds do not demonstrate parameter uniqueness or general LLM efficacy.

## Artifacts

Evidence root: `D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation/region-type-repair-20261026`.
Runs: `D:/Users/aa133/Desktop/LLMBO_Para/runs/g26t`.
Source fingerprint: `b101a433b054dca8931c6c59c31bfce0fe2cf752d8cf0636dc88766e3459c231`.

JUnit/logs: tests/ge-type-full/junit.xml and pytest.log/result.json; entry-junit.xml/entry.log; analysis-junit.xml/analysis-tests.log. Live: protocol.json, budget-journal.jsonl, result.json, execution.log/execution-exit.txt.
Independent results: comparison.json, paired.csv, cases.csv, curve-rmse.csv, round-rmse.csv, hv-convergence.csv, pareto-parameter-sets.json, final-audit.json and PNG/SVG figures.
