"""Compare the Reference notebook's scoring domain with the current evaluator."""
import json
import os
from pathlib import Path
import sys

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
import numpy as np
from scipy.interpolate import interp1d
from llmbo_para.metrics import rmse
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import prepare_experiment

original = root / "runs/ablation-initial-cases/20261011T060922Z_c59f3bb3c662_0e08c034"
notebook = root / "Reference/LLAMBO-master/P2D.ipynb"
method = Path("D:/DOC/LLMBO_Battery_Parameter_Identification_Method_v0_2.md")
config = json.loads((original / "manifest.json").read_text(encoding="utf-8"))["config"]
store = RunStore(root / "runs/design-audits", {
    "purpose": "attribute random-start failure to physical termination versus scoring/initialization policy",
    "original_run_directory": str(original), "experiment": config,
    "reference_notebook_sha256": sha256_file(notebook), "method_sha256": sha256_file(method),
    "battery_solves": 0, "api_calls": 0, "formal_ablation": False,
}, command=" ".join(sys.argv))
report, prepared = prepare_experiment(config, base_dir=root)
store.write_json("preflight.json", report)
if prepared is None:
    store.finish("preflight_failed", report)
    raise SystemExit(2)
cells = json.loads(notebook.read_text(encoding="utf-8"))["cells"]
reference_code = "\n\n".join(f"# Notebook cell {index}\n" + "".join(cells[index]["source"]) for index in (2, 3, 4))
with (store.path / "reference-relevant-code.py").open("x", encoding="utf-8") as stream:
    stream.write(reference_code)
with (store.path / "method-v0-2.md").open("xb") as stream:
    stream.write(method.read_bytes())
results = []
for path in sorted((original / "attempts").glob("*.json")):
    record = json.loads(path.read_text(encoding="utf-8"))
    rates = []
    for item in record["rates"]:
        series = prepared.series[item["rate"]]
        times, volts = np.asarray(item["simulation_time_s"]), np.asarray(item["simulation_voltage_v"])
        interpolator = interp1d(series.time_s, series.voltage_v, kind="linear", fill_value="extrapolate")
        reference_on_simulation_times = interpolator(times)
        partial_mse = float(np.mean((volts - reference_on_simulation_times) ** 2))
        rates.append({"rate": item["rate"], "simulation_end_s": float(times[-1]), "measured_end_s": series.time_s[-1],
            "duration_coverage_fraction": float(times[-1] / series.time_s[-1]),
            "reference_style_simulation_grid_mse_v2": partial_mse,
            "reference_style_simulation_grid_rmse_v": float(np.sqrt(partial_mse)),
            "reference_style_neg_mse_score": -partial_mse,
            "current_full_measured_grid_rmse_v": item["rmse_v"], "current_full_grid_valid": item["valid"],
            "reference_extrapolation_was_needed_here": bool(times[0] < series.time_s[0] or times[-1] > series.time_s[-1])})
    results.append({"candidate_record": path.name, "parameters": record["parameters"], "rates": rates})
store.write_json("partial-score-comparison.json", {"candidates": results,
    "scope": "apply Reference's per-curve scoring expression to stored curves; Reference's original optimizer fits 1C, not the current four-rate joint objective",
    "not_for_gp_training": True})
example = {"observed_time_s": [0., 1., 2., 3., 4.], "observed_voltage_v": [4.2, 4., 3.8, 3.6, 3.4],
    "short_simulation_time_s": [0., 1.], "short_simulation_voltage_v": [4.2, 4.]}
example["reference_style_rmse_v"] = rmse(example["observed_voltage_v"][:2], example["short_simulation_voltage_v"])
example["duration_coverage_fraction"] = .25
example["meaning"] = "zero error on the available prefix does not establish agreement over the missing 75% of the discharge duration"
store.write_json("short-prefix-counterexample.json", example)
flat = [row for result in results for row in result["rates"]]
summary = {"reference_style_finite_partial_scores": sum(np.isfinite(row["reference_style_simulation_grid_mse_v2"]) for row in flat),
    "current_full_grid_valid_scores": sum(row["current_full_grid_valid"] for row in flat),
    "curve_count": len(flat), "reference_voltage_cutoff_v": 2.5, "current_voltage_cutoff_v": 2.5,
    "original_reference_primary_fitting_rate": "1C", "current_fitting_rates": list(prepared.series),
    "physical_termination_replay_evidence": str(root / "runs/cutoff-diagnostics/20261011T063629Z_da91a5ddd2f4_9a7e2394"),
    "actual_battery_solves_this_audit": 0, "api_calls": 0,
    "main_finding": "Physical voltage termination is expected for poor parameter candidates; the blocking condition is strict full-grid rejection plus random initialization without enough-valid-data recovery. Reference instead scores the available simulation grid and uses a fixed exception penalty.",
    "unresolved_model_match": "21700 format alone does not verify fixed Chen2020 parameter/current compatibility; workbook current is blank and currents are derived from Reference 5 Ah",
    "method_gap": "The supplied method specifies full-curve RMSE and omits fake failure labels, but does not define a zero-valid-initialization recovery policy",
    "core_llm_gp_effectiveness": "not tested by the failed initialization; GP/BO had no valid training set"}
summary = {key: value.item() if isinstance(value, np.generic) else value for key, value in summary.items()}
assert summary["reference_style_finite_partial_scores"] == 32 and summary["current_full_grid_valid_scores"] == 0
store.write_json("design-audit-summary.json", summary)
store.finish("completed", summary)
print(json.dumps({"audit_directory": str(store.path), **summary}, ensure_ascii=False, indent=2))
