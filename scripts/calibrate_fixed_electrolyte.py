"""Small, separately archived calibration of a fixed electrolyte law.

Six decision variables remain fixed during this calibration. The selected scale
uses the same four measured curves and is a pilot model setting, not an
independently measured material property or an additional BO decision variable.
"""
from __future__ import annotations

import argparse
import ctypes
import inspect
import json
import os
from pathlib import Path
import shutil
import sys

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "src"))

from llmbo_para.config import load_json
from llmbo_para.reference_cell import chen2020_reference_parameters
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import prepare_experiment, run_fixed_candidates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    args = parser.parse_args()
    session = args.session.resolve()
    config = load_json(session / "idaklu-smoke-config.json")
    candidate = [.75, .665, 3.3e-13, 4e-14, 215., .4]
    multipliers = [1.25, 1.5, 2.0]
    plan = {"user_authorization": "保持四倍率目标，先核对并校准固定电解液设置（推荐）", "reference_session": str(session),
        "fixed_candidate": candidate, "multipliers": multipliers,
        "only_changed_fixed_property": "Electrolyte diffusivity [m2.s-1]",
        "rule": "multiplier times original Chen2020 concentration/temperature function",
        "selection": "minimum equal-weight mean four-rate RMSE among complete measured-grid cases",
        "invalid_case_policy": "retain short curves; null full objective; never extrapolate or train GP on incomplete cases",
        "scientific_scope": "same-data pilot calibration, not a measured material property; freeze before six-variable BO",
        "workers": 1, "api_calls": 0}
    stage = RunStore(workspace / "runs/electrolyte-calibration", plan,
                     command="scripts/calibrate_fixed_electrolyte.py SESSION")
    print(json.dumps({"calibration_directory": str(stage.path), "plan": plan}), flush=True)
    with (session / ("electrolyte-calibration-link-" + stage.run_id + ".json")).open("x", encoding="utf-8") as stream:
        json.dump({"calibration_directory": str(stage.path)}, stream, indent=2)
    shutil.copy2(__file__, stage.path / "calibrate_fixed_electrolyte.py")
    parameters = chen2020_reference_parameters()
    function = parameters["Electrolyte diffusivity [m2.s-1]"]
    function_file = inspect.getsourcefile(function)
    stage.write_json("reference-electrolyte-inspection.json", {
        "function": function.__module__ + ":" + function.__qualname__,
        "source_file": function_file, "source_sha256": sha256_file(function_file),
        "source": inspect.getsource(function),
        "diffusivity_at_1000mol_m3_298_15K_m2_s": float(function(1000., 298.15)),
        "fixed_scalars": {str(k): float(v) for k, v in parameters.items()
            if any(word in str(k).lower() for word in ("electrolyte", "transference", "bruggeman"))
            and isinstance(v, (int, float))}})
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load_percent", ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in ("total_physical", "available_physical", "total_pagefile", "available_pagefile", "total_virtual", "available_virtual", "available_extended_virtual")]
    memory = Memory(); memory.length = ctypes.sizeof(memory)
    okay = bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)))
    stage.write_json("resources-before.json", {"memory_query_succeeded": okay,
        "memory": {key: getattr(memory, key) for key, _ in memory._fields_},
        "disk_free_bytes": shutil.disk_usage(workspace).free, "workers": 1})
    cases = []
    for multiplier in multipliers:
        case = json.loads(json.dumps(config))
        case["status"] = "same_data_fixed_electrolyte_calibration"
        case["model"]["fixed_electrolyte_diffusivity_multiplier"] = multiplier
        label = str(multiplier).replace(".", "p")
        stage.write_json(f"config-{label}.json", case)
        report, prepared = prepare_experiment(case, base_dir=workspace)
        stage.write_json(f"preflight-{label}.json", report)
        if prepared is None:
            raise RuntimeError("calibration preflight failed: " + "; ".join(report["errors"]))
        result = run_fixed_candidates(case, stage.path / f"scale-{label}", [(None, candidate)],
                                      mode="smoke", base_dir=workspace)
        cases.append({"multiplier": multiplier, **result})
        stage.write_json(f"result-{label}.json", cases[-1])
        print(json.dumps({"calibration_completed": len(cases), "calibration_total": len(multipliers), **cases[-1]}), flush=True)
    valid = [case for case in cases if case["candidate_valid"] == 1]
    selected = min(valid, key=lambda case: case["best_objective_v"]) if valid else None
    summary = {"cases": cases, "selected": selected, "complete_four_rate_cases": len(valid),
               "invalid_four_rate_cases": len(cases) - len(valid), "api_calls": 0}
    stage.write_json("calibration-summary.json", summary)
    if selected:
        frozen = json.loads(json.dumps(config))
        frozen["model"]["fixed_electrolyte_diffusivity_multiplier"] = selected["multiplier"]
        frozen["status"] = "same_data_electrolyte_calibrated_reference_pilot"
        frozen["optimization"]["llm_enabled"] = True
        stage.write_json("frozen-pilot-config.json", frozen)
    stage.finish("completed" if selected else "completed_with_failures", summary)
    print(json.dumps({"calibration_directory": str(stage.path), **summary}, indent=2), flush=True)
    return 0 if selected else 1


if __name__ == "__main__":
    raise SystemExit(main())
