"""Archive the uncalibrated Reference design and run one four-rate diagnostic.

This preserves the original physical baseline, whose 3C cutoff is known to be
too early for this workbook. Use the separately calibrated pilot configuration
for the subsequent small LLMBO run; do not treat this diagnostic as a fitted set.
"""
from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import shutil
import sys
import traceback

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "src"))

from llmbo_para.config import load_json
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.parameters import PARAMETER_NAMES
from llmbo_para.runstore import RunStore
from llmbo_para.workflow import ExperimentFailure, prepare_experiment, run_fixed_candidates


def main():
    config = load_json(workspace / "configs/research-template.json")
    config.update(cell_id="research-group-measured-21700-reference-Chen2020", cell_format="21700", nominal_capacity_ah=5.0,
                  status="confirmed_reference_design_small_diagnostic_run")
    limits = ((.2, .8), (.2, .8), (1e-16, 1e-12), (1e-16, 1e-12), (100, 300), (.2, .8))
    for name, (low, high) in zip(PARAMETER_NAMES, limits):
        config["parameters"][name].update(lower=low, upper=high)
    config["physical_constraints"]["fixed_porosity"] = {"negative": .25, "positive": .335}
    for condition in config["conditions_by_rate"].values():
        condition.update(initial_soc=None, initial_temperature_k=298.15, ambient_temperature_k=298.15, voltage_cutoff_v=2.5)
    config["data"].update(path=str((workspace / "configs" / config["data"]["path"]).resolve()),
                          legacy_assumed_1s=True, sample_period_s=1.0, discharge_current_sign=1)
    config["model"].update(parameterization_id="Reference-Chen2020", parameter_values_factory="llmbo_para.reference_cell:chen2020_reference_parameters",
                           pybamm_version="25.10.2", options={"thermal": "isothermal"}, initial_state_mode="parameterization",
                           mesh_points={key: 20 for key in ("x_n", "x_s", "x_p", "r_n", "r_p")},
                           solver={"name": "IDAKLUSolver", "rtol": 1e-6, "atol": 1e-6, "dt_max": 60.0, "num_threads": 1},
                           fixed_electrolyte_diffusivity_multiplier=1.0)
    config["optimization"].update(seed=20261011, warm_start_llm_points=2, sobol_points=2, total_candidate_budget=5,
                                  candidate_pool_size=64, composite_ei_draws=64, gp_sweeps=2, llm_enabled=True)
    config["llm"] = load_json(workspace / "configs/newapi-synthetic-smoke.json")["llm"]
    baseline = (.75, .665, 3.3e-14, 4e-15, 215., .2)
    session = RunStore(workspace / "runs/measured-identification", {"run_kind": "confirmed_21700_real_smoke_then_small_llmbo",
        "scientific_confirmation": {"source": "user reply: 同意", "particle_solid_diffusivity": True, "fixed_porosity_filter": True},
        "experiment": config, "smoke_candidate": baseline, "production_study": False}, command="scripts/prepare_reference_21700.py")
    print(json.dumps({"session_directory": str(session.path), "state": "preflight"}), flush=True)
    session.write_json("experiment-config.json", config)
    session.write_json("smoke-candidate.json", {"parameters": baseline,
        "selection": "Chen2020 nominal values; positive conductivity raised from 0.18 to the user's lower bound 0.2"})
    session.write_json("execution-settings.json", {"working_directory": str(workspace), "python": sys.executable,
        "numerical_threads": 1, "workers": 1, "gpu_backend": "cpu", "raw_data_sent_to_llm": False,
        "sample_period_s_source": "user confirmed 1 second", "current_source": "derived from Reference 5 Ah capacity; not measured",
        "current_by_rate_a": dict(zip(RATE_ORDER, (2.5, 5., 10., 15.))),
        "bounds_source": "user image; user confirmed particle diffusivity mapping and fixed-porosity filtering",
        "initial_state": "Reference initial concentrations; no initial_soc reset", "thermal_policy": "Reference isothermal 298.15 K; T column unused",
        "numerical_solver": "explicit IDAKLU single thread; controlled comparison agreed with Casadi at low rates and avoided its event-root failure",
        "maximum_initial_live_llm_requests": 2, "diagnostic_candidate_budget": 5,
        "next_step": "inspect smoke coverage and voltage before any LLM call or broader search"})
    class Memory(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load_percent", ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in ("total_physical", "available_physical", "total_pagefile", "available_pagefile", "total_virtual", "available_virtual", "available_extended_virtual")]
    memory = Memory(); memory.length = ctypes.sizeof(memory)
    okay = bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)))
    session.write_json("resource-observation.json", {"memory_query_succeeded": okay, "memory": {key: getattr(memory, key) for key, _ in memory._fields_},
        "disk_free_bytes": shutil.disk_usage(workspace).free, "workers": 1})
    smoke_config = json.loads(json.dumps(config)); smoke_config["optimization"]["llm_enabled"] = False
    session.write_json("smoke-config.json", smoke_config)
    report, prepared = prepare_experiment(smoke_config, base_dir=session.path)
    session.write_json("preflight-smoke.json", report)
    if prepared is None:
        session.finish("preflight_failed", report)
        print(json.dumps(report, ensure_ascii=False), flush=True)
        return 2
    try:
        result = run_fixed_candidates(smoke_config, session.path / "smoke", [(None, baseline)], mode="smoke", base_dir=session.path)
        session.write_json("smoke-result.json", result)
        print(json.dumps({"session_directory": str(session.path), **result}, indent=2), flush=True)
        return 0 if result["candidate_valid"] == 1 else 1
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        if isinstance(exc, ExperimentFailure):
            failure["run_directory"] = exc.run_directory
        session.write_json("smoke-failure.json", failure)
        print(json.dumps({"session_directory": str(session.path), **failure}), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
