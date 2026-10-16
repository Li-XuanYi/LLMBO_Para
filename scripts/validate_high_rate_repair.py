"""Matched electrolyte controls and mesh checks using the existing DFN evaluator.

This is same-data calibration validation, not a new BO/LLM comparison or an
independent identification of electrolyte material properties.
"""
from __future__ import annotations

import argparse
import contextlib
from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pybamm

from llmbo_para.metrics import RATE_ORDER
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import prepare_experiment, run_fixed_candidates
from resource_snapshot import snapshot

STATE_NAMES = (
    "Electrolyte concentration [mol.m-3]",
    "X-averaged battery concentration overpotential [V]",
    "X-averaged battery reaction overpotential [V]",
    "X-averaged battery solid phase ohmic losses [V]",
    "X-averaged battery electrolyte ohmic losses [V]",
    "Battery open-circuit voltage [V]",
    "Negative particle surface stoichiometry",
    "Positive particle surface stoichiometry",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "configs/21700-high-rate-repair.json")
    parser.add_argument("--candidate", type=Path, default=ROOT / "configs/21700-high-rate-repair-candidate.json")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/high-rate-repair")
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    if config["optimization"]["llm_enabled"]:
        raise ValueError("This validation must not invoke an LLM")
    if config["model"]["fixed_electrolyte_diffusivity_multiplier"] != 1.5:
        raise ValueError("This matched protocol validates the previously approved multiplier 1.5")
    transport = [.75, .665, 3.3e-13, 4e-14, 215., .4]
    nominal_in_bounds = [.75, .665, 3.3e-14, 4e-15, 215., .2]
    cases = [
        ("transport-original", transport, 1., 20),
        ("transport-calibrated", transport, 1.5, 20),
        ("nominal-in-bounds-original", nominal_in_bounds, 1., 20),
        ("identified-original", candidate["parameters"], 1., 20),
        ("identified-calibrated", candidate["parameters"], 1.5, 20),
        ("identified-mesh40", candidate["parameters"], 1.5, 40),
        ("identified-mesh60", candidate["parameters"], 1.5, 60),
    ]
    protocol = {
        "purpose": "Diagnose 2C/3C cutoff, validate calibrated configuration and an existing identified candidate",
        "user_scope": "Analyze and fix high-rate fitting; retain full observed grid, six bounds, 2.5 V cutoff; reuse approved electrolyte calibration",
        "config": config, "candidate_provenance": candidate,
        "cases": [{"name": n, "parameters": p, "electrolyte_multiplier": a, "mesh": m} for n, p, a, m in cases],
        "pilot_gate": "Both transport cases produce audited finite trajectories, calibrated case covers all four curves",
        "numerical_gate": "Identified candidate covers all rates on mesh20/40/60; mesh40->60 RMSE difference <= 0.001 V for every rate",
        "planned_rate_solves": 28, "parallel_workers": 1, "api_calls": 0,
        "scientific_limits": "Same workbook used for earlier calibration/identification and this validation. Not held-out prediction, not proof of unique physical parameters. Current and temperature assumptions remain in config.",
    }
    store = RunStore(args.output, protocol, command=subprocess.list2cmdline([sys.executable, *sys.argv]),
                     source_revision=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip())
    for path in (args.config, args.candidate, Path(__file__)):
        target = store.path / "inputs" / path.name
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(path, target)
    print(json.dumps({"run_directory": str(store.path), "planned_rate_solves": 28}), flush=True)
    with (store.path / "stdout.log").open("x", encoding="utf-8") as out, (store.path / "stderr.log").open("x", encoding="utf-8") as err:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            started = time.perf_counter()
            records = {}
            summaries = []
            try:
                store.write_json("resource-before.json", snapshot())
                preflight, prepared = prepare_experiment(config, base_dir=args.config.resolve().parent)
                store.write_json("preflight.json", preflight)
                if prepared is None:
                    raise ValueError(f"Preflight failed: {preflight['errors']}")
                prepared.space.validate(candidate["parameters"])
                store.write_json("protocol-input-hashes.json", {"config": sha256_file(args.config), "candidate": sha256_file(args.candidate), **prepared.input_hashes})
                solve = pybamm.Simulation.solve
                for index, (name, point, alpha, mesh) in enumerate(cases):
                    local = deepcopy(config)
                    local["model"]["fixed_electrolyte_diffusivity_multiplier"] = alpha
                    local["model"]["mesh_points"] = {k: mesh for k in local["model"]["mesh_points"]}
                    if mesh > 20:
                        local["model"]["solver"].update(rtol=1e-8, atol=1e-8)
                    captured = []

                    def observed_solve(simulation, *pos, **kw):
                        solution = solve(simulation, *pos, **kw)
                        states = {}
                        arrays = {"time_s": np.asarray(solution["Time [s]"].entries)}
                        for variable in STATE_NAMES:
                            values = np.asarray(solution[variable].entries, dtype=float)
                            if not np.all(np.isfinite(values)):
                                raise ValueError(f"Nonfinite internal state: {variable}")
                            arrays[variable] = values
                            states[variable] = {"trajectory_min": float(values.min()), "trajectory_max": float(values.max()),
                                "final_min": float(values[..., -1].min()), "final_max": float(values[..., -1].max())}
                        rate = RATE_ORDER[len(captured)]
                        folder = store.path / "states"
                        folder.mkdir(exist_ok=True)
                        np.savez_compressed(folder / f"{name}-{rate}.npz", **arrays)
                        captured.append({"rate": rate, "termination": str(solution.termination), "states": states})
                        return solution

                    with patch.object(pybamm.Simulation, "solve", observed_solve):
                        summary = run_fixed_candidates(local, store.path / "cases" / name, [(None, point)], mode="smoke", base_dir=args.config.resolve().parent)
                    record_path = next((Path(summary["run_directory"]) / "attempts").glob("*.json"))
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    records[name] = record
                    if any(r["failure_kind"] not in (None, "voltage_cutoff", "coverage_shortfall") for r in record["rates"]):
                        raise RuntimeError(f"Unexpected simulation failure in {name}; see archived attempts")
                    if len(captured) != 4:
                        raise RuntimeError(f"Missing internal-state captures in {name}")
                    store.write_json(f"states/{name}.json", captured)
                    row = {"case": name, "electrolyte_multiplier": alpha, "mesh": mesh, **summary,
                           "rates": [{key: r.get(key) for key in ("rate", "rmse_v", "t_end_s", "t_required_s", "termination", "failure_kind")} for r in record["rates"]]}
                    summaries.append(row)
                    for r in record["rates"]:
                        s = prepared.series[r["rate"]]
                        if r["valid"]:
                            predicted = np.asarray(r["aligned_voltage_v"])
                            assert abs(np.sqrt(np.mean((predicted - s.voltage_v)**2)) - r["rmse_v"]) < 1e-12
                            np.savetxt(store.path / f"{name}-{r['rate']}.csv", np.column_stack([s.time_s, s.voltage_v, predicted, predicted-s.voltage_v]), delimiter=",",
                                       header="time_s,measured_voltage_v,simulated_voltage_v,residual_v", comments="")
                    done = 4 * (index+1)
                    elapsed = time.perf_counter()-started
                    progress = {"completed_rate_solves": done, "running": 0, "pending": 28-done, "execution_errors": 0,
                                "coverage_failures": sum(not q["valid"] for p in records.values() for q in p["rates"]),
                                "solves_per_min": done*60/elapsed, "eta_s": (28-done)*elapsed/done, "latest": row}
                    store.append_event({"type": "case_finished", **progress})
                    print(json.dumps(progress), flush=True)
                    if index == 1:
                        passed = record["valid"] and len(records) == 2
                        store.write_json("pilot-gate.json", {"passed": passed, "rate_solves": 8})
                        if not passed:
                            raise RuntimeError("Matched pilot failed; remaining cases were not launched")
                numerical = {}
                for i, rate in enumerate(RATE_ORDER):
                    a, b = records["identified-mesh40"]["rates"][i], records["identified-mesh60"]["rates"][i]
                    valid = a["valid"] and b["valid"] and records["identified-calibrated"]["rates"][i]["valid"]
                    numerical[rate] = {"all_meshes_cover": valid,
                        "rmse_change_v": abs(a["rmse_v"]-b["rmse_v"]) if valid else None,
                        "max_curve_difference_v": float(np.max(np.abs(np.asarray(a["aligned_voltage_v"])-b["aligned_voltage_v"]))) if valid else None}
                passed = all(v["all_meshes_cover"] and v["rmse_change_v"] <= .001 for v in numerical.values())
                store.write_json("numerical-check.json", {"passed": passed, "rates": numerical, "note": "A finite mesh sensitivity check, not proof of asymptotic convergence"})
                store.write_json("comparison.json", summaries)
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                fig, axes = plt.subplots(2, 2, figsize=(12, 8), constrained_layout=True)
                for ax, rate in zip(axes.flat, RATE_ORDER):
                    series = prepared.series[rate]
                    ax.plot(series.time_s, series.voltage_v, color="black", label="Measured", linewidth=1.5)
                    for case, label in (("nominal-in-bounds-original", "Reference (sigma_p=0.2)"), ("identified-original", "Identified / original electrolyte"), ("identified-mesh60", "Identified / calibrated electrolyte")):
                        row = records[case]["rates"][RATE_ORDER.index(rate)]
                        ax.plot(row["simulation_time_s"], row["simulation_voltage_v"], label=label, linewidth=1.2)
                    ax.set(title=rate, xlabel="Time (s)", ylabel="Voltage (V)")
                    ax.grid(alpha=.2)
                axes[0, 0].legend(fontsize=8)
                fig.savefig(store.path / "comparison.png", dpi=180)
                fig.savefig(store.path / "comparison.svg")
                plt.close(fig)
                result = {"passed": passed, "completed_rate_solves": 28, "pending": 0, "execution_errors": 0,
                    "coverage_failures": sum(not q["valid"] for p in records.values() for q in p["rates"]),
                    "api_calls": 0, "elapsed_s": time.perf_counter()-started,
                    "validated_parameters": candidate["parameters"], "validated_summary": summaries[-1]}
                store.write_json("result.json", result)
                store.finish("completed" if passed else "completed_with_failures", result)
                print(json.dumps(result), flush=True)
            except BaseException as exc:
                failure = {"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc(),
                           "completed_cases": len(summaries), "elapsed_s": time.perf_counter()-started}
                store.write_json("failure.json", failure)
                store.finish("interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", failure)
                raise
    print(json.dumps({"run_directory": str(store.path), **result}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
