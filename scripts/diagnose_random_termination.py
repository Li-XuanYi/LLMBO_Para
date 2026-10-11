"""Replay the same eight candidates to record actual DFN termination and states."""
import json
import os
from pathlib import Path
import sys
import time
import traceback
from unittest.mock import patch

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
import numpy as np
import pybamm
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.parameters import PARAMETER_NAMES
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import build_backend, prepare_experiment

original = root / "runs/ablation-initial-cases/20261011T060922Z_c59f3bb3c662_0e08c034"
config = json.loads((original / "manifest.json").read_text(encoding="utf-8"))["config"]
records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((original / "attempts").glob("*.json"))]
store = RunStore(root / "runs/cutoff-diagnostics", {
    "purpose": "explain actual early termination; no new parameters or scientific settings",
    "original_run_directory": str(original), "original_manifest_sha256": sha256_file(original / "manifest.json"),
    "experiment": config, "candidate_count": len(records), "planned_rate_solves": 4 * len(records),
    "formal_ablation": False, "api_calls": 0, "workers": 1,
}, command=" ".join(sys.argv))
print(json.dumps({"diagnostic_directory": str(store.path), "planned_rate_solves": 4 * len(records)}), flush=True)
report, prepared = prepare_experiment(config, base_dir=root)
store.write_json("preflight.json", report)
if prepared is None:
    store.finish("preflight_failed", report)
    raise SystemExit(2)
backend = build_backend(prepared)
backend.save_parameterization(store)
base = backend.base_parameters()
factor = (float(base["Electrode height [m]"]) * float(base["Electrode width [m]"])
    * float(base["Number of electrodes connected in parallel to make a cell"])
    * float(pybamm.constants.F.value) / 3600.)
capacity_inputs = {key: float(base[key]) for key in (
    "Electrode height [m]", "Electrode width [m]", "Number of electrodes connected in parallel to make a cell",
    "Negative electrode thickness [m]", "Positive electrode thickness [m]",
    "Maximum concentration in negative electrode [mol.m-3]", "Maximum concentration in positive electrode [mol.m-3]",
    "Initial concentration in negative electrode [mol.m-3]", "Initial concentration in positive electrode [mol.m-3]")}
charges = {rate: float(np.trapezoid(prepared.series[rate].current_a, prepared.series[rate].time_s) / 3600.) for rate in RATE_ORDER}
store.write_json("capacity-bound-inputs.json", {"fixed_values": capacity_inputs, "derived_measured_discharge_ah": charges,
    "formula": "min(A*N_parallel*F/3600*L_n*eps_n*c_n_initial, A*N_parallel*F/3600*L_p*eps_p*(c_p_max-c_p_initial))",
    "meaning": "ideal inventory upper bound allowing stoichiometry 0..1, before voltage/transport restrictions; derived currents, not measured capacity"})

state_names = (
    "X-averaged negative particle stoichiometry", "X-averaged positive particle stoichiometry",
    "X-averaged negative particle surface stoichiometry", "X-averaged positive particle surface stoichiometry",
    "Negative particle surface stoichiometry", "Positive particle surface stoichiometry",
    "Electrolyte concentration [mol.m-3]",
    "X-averaged battery concentration overpotential [V]", "X-averaged battery reaction overpotential [V]",
    "X-averaged battery solid phase ohmic losses [V]", "X-averaged battery electrolyte ohmic losses [V]",
    "Battery open-circuit voltage [V]", "X-averaged battery open-circuit voltage [V]",
)
solve = pybamm.Simulation.solve
captured = {}

def observed_solve(simulation, *args, **kwargs):
    solution = solve(simulation, *args, **kwargs)
    names = set(simulation.model.variables)
    captured.update(termination=solution.termination, event_times_s=np.asarray(solution.t_event).tolist() if solution.t_event is not None else None,
        states={}, absent_state_names=[name for name in state_names if name not in names])
    for name in state_names:
        if name not in names:
            continue
        values = np.asarray(solution[name].entries, dtype=float)
        first = values[..., 0] if values.ndim else values
        last = values[..., -1] if values.ndim else values
        captured["states"][name] = {"shape": values.shape, "initial_min": float(np.min(first)), "initial_max": float(np.max(first)),
            "final_min": float(np.min(last)), "final_max": float(np.max(last)),
            "trajectory_min": float(np.min(values)), "trajectory_max": float(np.max(values))}
    if not (store.path / "model-variables.json").exists():
        store.write_json("model-variables.json", {"variables": sorted(names), "events": [event.name for event in simulation.model.events]})
    return solution

started = time.perf_counter()
outcomes = []
with patch.object(pybamm.Simulation, "solve", observed_solve):
    for index, record in enumerate(records):
        point = record["parameters"]
        n_limit = factor * base["Negative electrode thickness [m]"] * point[0] * base["Initial concentration in negative electrode [mol.m-3]"]
        p_limit = factor * base["Positive electrode thickness [m]"] * point[1] * (base["Maximum concentration in positive electrode [mol.m-3]"] - base["Initial concentration in positive electrode [mol.m-3]"])
        row = {"candidate_id": index, "parameters": point,
            "negative_initial_inventory_ah": float(n_limit), "positive_initial_acceptance_ah": float(p_limit),
            "ideal_discharge_upper_bound_ah": float(min(n_limit, p_limit)), "rates": []}
        for rate in RATE_ORDER:
            captured.clear()
            previous = next(item for item in record["rates"] if item["rate"] == rate)
            before = time.perf_counter()
            try:
                times, volts = backend.simulate(dict(zip(PARAMETER_NAMES, point)), prepared.series[rate])
                times, volts = np.asarray(times), np.asarray(volts)
                old_times = np.asarray(previous["simulation_time_s"])
                old_volts = np.asarray(previous["simulation_voltage_v"])
                comparison = {"same_shape": times.shape == old_times.shape and volts.shape == old_volts.shape,
                    "time_max_abs_difference_s": float(np.max(np.abs(times - old_times))) if times.shape == old_times.shape else None,
                    "voltage_max_abs_difference_v": float(np.max(np.abs(volts - old_volts))) if volts.shape == old_volts.shape else None}
                result = {"rate": rate, **captured, "end_s": float(times[-1]), "end_voltage_v": float(volts[-1]),
                    "initial_voltage_v": float(volts[0]), "required_end_s": float(prepared.series[rate].time_s[-1]),
                    "delivered_ah": float(prepared.series[rate].current_a[0] * times[-1] / 3600.),
                    "original_curve_comparison": comparison, "elapsed_s": time.perf_counter() - before}
                store.write_json(f"curves/candidate-{index:03d}-{rate}.json", {"time_s": times, "voltage_v": volts})
            except Exception as exc:
                result = {"rate": rate, **captured, "error_type": type(exc).__name__, "message": str(exc),
                    "traceback": traceback.format_exc(), "elapsed_s": time.perf_counter() - before}
            row["rates"].append(result)
        outcomes.append(row)
        store.write_json(f"candidate-{index:03d}.json", row)
        print(json.dumps({"completed_candidates": len(outcomes), "total_candidates": len(records),
            "ideal_discharge_upper_bound_ah": row["ideal_discharge_upper_bound_ah"],
            "rates": [{key: result.get(key) for key in ("rate", "termination", "end_s", "end_voltage_v", "message")} for result in row["rates"]]}), flush=True)
flat = [item for row in outcomes for item in row["rates"]]
errors = sum("error_type" in item for item in flat)
reproduced = sum(item.get("original_curve_comparison", {}).get("same_shape", False)
    and item["original_curve_comparison"]["voltage_max_abs_difference_v"] <= 1e-8
    and item["original_curve_comparison"]["time_max_abs_difference_s"] <= 1e-5 for item in flat)
summary = {"outcomes": outcomes, "rate_solves": len(flat), "diagnostic_errors": errors,
    "original_curves_reproduced": reproduced, "termination_counts": {name: sum(item.get("termination") == name for item in flat)
        for name in sorted({item["termination"] for item in flat if "termination" in item})},
    "derived_measured_discharge_ah": charges, "elapsed_s": time.perf_counter() - started,
    "candidate_inventory_bound_below_every_rate_requirement": sum(row["ideal_discharge_upper_bound_ah"] < min(charges.values()) for row in outcomes),
    "formal_ablation": False, "api_calls": 0}
store.write_json("diagnosis-summary.json", summary)
store.finish("completed" if errors == 0 and reproduced == len(flat) else "completed_with_failures", summary)
print(json.dumps({"diagnostic_directory": str(store.path), **{key: value for key, value in summary.items() if key != "outcomes"}}, indent=2), flush=True)
raise SystemExit(0 if errors == 0 and reproduced == len(flat) else 1)
