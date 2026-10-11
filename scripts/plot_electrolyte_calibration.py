"""Plot archived fixed-electrolyte calibration cases; perform no new solves."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import sys

workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "src"))
from llmbo_para.audit import audit_run
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.runstore import RunStore, sha256_file


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("calibration", type=Path)
    args = parser.parse_args()
    calibration = args.calibration.resolve()
    summary = read(calibration / "calibration-summary.json")
    stage = RunStore(workspace / "runs/calibration-figures", {"calibration_directory": str(calibration),
        "summary_sha256": sha256_file(calibration / "calibration-summary.json"), "new_solver_calls": 0},
        command="scripts/plot_electrolyte_calibration.py " + str(calibration))
    os.environ["MPLCONFIGDIR"] = str(stage.path / "matplotlib-cache")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "savefig.dpi": 240})
    parent = Path(read(calibration / "manifest.json")["config"]["reference_session"])
    baseline = read(parent / "transport-smoke-result.json")
    input_series = read(Path(summary["selected"]["run_directory"]) / "input-series.json")
    labels = ["Reference scale 1.0 (incomplete 3C)", "Scale 1.25", "Scale 1.5 (selected)", "Scale 2.0"]
    colors = ["#777777", "#0072B2", "#D55E00", "#009E73"]
    cases = [baseline] + summary["cases"]
    records = [read(Path(case["run_directory"]) / "attempts/candidate-000000-attempt-001.json") for case in cases]
    metrics = []
    figure, axes = plt.subplots(2, 2, figsize=(11.2, 7.2), layout="constrained")
    csv_path = stage.path / "voltage-curves.csv"
    with csv_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream); writer.writerow(("rate", "source", "time_s", "voltage_v"))
        for axis, rate in zip(axes.flat, RATE_ORDER):
            observed = input_series[rate]
            axis.plot(observed["time_s"], observed["voltage_v"], color="#111111", lw=1.9, label="Measured")
            writer.writerows((rate, "measured", t, v) for t, v in zip(observed["time_s"], observed["voltage_v"]))
            for label, color, record in zip(labels, colors, records):
                result = next(item for item in record["rates"] if item["rate"] == rate)
                t, v = result["simulation_time_s"], result["simulation_voltage_v"]
                axis.plot(t, v, color=color, lw=1.35, ls="--" if "1.0" in label else "-", label=label)
                writer.writerows((rate, label, time, voltage) for time, voltage in zip(t, v))
                metrics.append({"rate": rate, "source": label, "valid": result["valid"],
                                "rmse_v": result["rmse_v"], "time_end_s": t[-1], "voltage_end_v": v[-1]})
            axis.set(title=rate, xlabel="Time (s)", ylabel="Terminal voltage (V)", ylim=(2.4, 4.22))
            axis.grid(alpha=.2)
    axes[0, 0].legend(fontsize=8, loc="lower left")
    figure.suptitle("Fixed electrolyte calibration: same six parameters, four measured targets\n"
                    "Current inferred from Reference 5 Ah; same-data pilot calibration", fontsize=13)
    for extension in ("png", "pdf", "svg"):
        figure.savefig(stage.path / ("four-rate-electrolyte-calibration." + extension))
    plt.close(figure)
    figure, axes = plt.subplots(3, 1, figsize=(10.4, 8.2), sharex=True, layout="constrained")
    axes[0].plot(input_series["3C"]["time_s"], input_series["3C"]["voltage_v"], color="#111111", lw=1.8, label="Measured")
    internal = []
    for folder, label, color in (("state-check-unscaled", "Reference scale 1.0", "#777777"),
                                  ("state-check", "Scale 1.5 (selected)", "#D55E00")):
        data = np.load(calibration / folder / "3c-internal-state.npz")
        time = data["time_s"]
        axes[0].plot(time, data["voltage_v"], color=color, lw=1.5, label=label)
        axes[1].plot(time, data["Electrolyte concentration [mol.m-3]"].min(axis=0), color=color, lw=1.5)
        axes[2].plot(time, data["X-averaged concentration overpotential [V]"], color=color, lw=1.5)
        internal.append({"case": label, **{key: read(calibration / folder / "3c-internal-state.json")[key]
                         for key in ("termination", "time_end_s", "voltage_end_v", "statistics")}})
    axes[0].set_ylabel("Terminal voltage (V)"); axes[0].legend(loc="lower left")
    axes[1].set_ylabel("Minimum electrolyte\nconcentration (mol m$^{-3}$)")
    axes[1].axhline(0, color="#222222", lw=.7, ls=":")
    axes[2].set(ylabel="Concentration\noverpotential (V)", xlabel="Time (s)")
    for axis in axes:
        axis.grid(alpha=.2)
    figure.suptitle("3C transport diagnosis: same six parameters and numerical settings", fontsize=13)
    for extension in ("png", "pdf", "svg"):
        figure.savefig(stage.path / ("3c-fixed-electrolyte-state-comparison." + extension))
    plt.close(figure)
    audits = [{"multiplier": case["multiplier"], **audit_run(case["run_directory"], deep=True)} for case in summary["cases"]]
    result = {"metrics": metrics, "internal_state": internal, "calibration_audits": audits,
              "all_calibration_audits_passed": all(item["passed"] for item in audits), "new_solver_calls": 0}
    stage.write_json("comparison-and-audits.json", result)
    stage.finish("completed" if result["all_calibration_audits_passed"] else "failed", result)
    print(json.dumps({"figure_directory": str(stage.path), "all_calibration_audits_passed": result["all_calibration_audits_passed"]}), flush=True)


if __name__ == "__main__":
    main()
