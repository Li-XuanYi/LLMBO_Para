"""Small local diagnostic of the requested eight random starts; no GP or API."""
import json
import os
from pathlib import Path
import sys
for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from llmbo_para.ablation import random_initial_points
from llmbo_para.config import load_json, parameter_space_from_config
from llmbo_para.runstore import RunStore
from llmbo_para.workflow import run_fixed_candidates
config = load_json(root / "configs/21700-reference-calibrated-pilot.json")
config["optimization"].update(llm_enabled=False, llm_warm_start_enabled=False, llm_gp_groups_enabled=False)
points = random_initial_points(parameter_space_from_config(config), 8, config["optimization"]["seed"])
parent = RunStore(root / "runs/ablation-initial-diagnostics", {"purpose": "verify requested random initial set can support a GP before remote scaling",
    "ablation_result": False, "config": config, "parameters": points, "api_calls": 0}, command="scripts/check_ablation_initial_feasibility.py")
parent.write_json("requested-random-initial-points.json", {"parameters": points, "seed": config["optimization"]["seed"]})
print(json.dumps({"diagnostic_directory": str(parent.path), "candidate_count": 8}), flush=True)
result = run_fixed_candidates(config, root / "runs/ablation-initial-cases", [(index, point) for index, point in enumerate(points)], mode="smoke")
parent.write_json("feasibility-result.json", result)
parent.finish("completed" if result["candidate_valid"] >= 2 else "completed_with_failures", result)
print(json.dumps({"diagnostic_directory": str(parent.path), **result}, indent=2), flush=True)
