"""Real measured-cell WarmStart v3.1, followed by 20 BO steps if 8 valid points exist.

Only the compact WarmStart generator prompt differs from the current GP guard
code. The existing LLM candidate selector and ordinary GP/BO remain unchanged.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import traceback

for key in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[key] = "1"
os.environ["PYTHONUTF8"] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run
from llmbo_para.config import configuration_errors, load_json
from llmbo_para.initialization import ScreeningBudget
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import prepare_experiment, run_experiment
from run_ablation_suite import screen_family


def initial_diversity(space, parameters):
    import numpy as np
    x = np.asarray([space.normalize(p) for p in parameters], dtype=float)
    if len(x) < 2:
        return {"count": len(x), "average_pairwise_distance": None, "min_pairwise_distance": None,
                "normalized_range": (np.ptp(x, axis=0).tolist() if len(x) else [])}
    ds = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=-1)
    upper = ds[np.triu_indices(len(x), 1)]
    return {"count": len(x), "average_pairwise_distance": float(upper.mean()),
            "min_pairwise_distance": float(upper.min()),
            "normalized_range": np.ptp(x, axis=0).tolist()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true",
                        help="Validate settings/data and prompt hashes without network or simulation")
    parser.add_argument("--max-screening-evaluations", type=int, default=120)
    parser.add_argument("--max-warm-batches", type=int, default=20)
    parser.add_argument("--max-selection-requests", type=int, default=45)
    parser.add_argument("--bo-iterations", type=int, default=20)
    args = parser.parse_args()
    if args.bo_iterations != 20 or args.max_screening_evaluations < 8:
        parser.error("This trial is fixed to 20 BO updates and requires screening capacity for 8 valid points")
    if args.max_screening_evaluations > 120 or args.max_warm_batches > 20 or args.max_selection_requests > 45:
        parser.error("This pilot may only reduce its explicit screening/API caps")
    source = args.source_config.resolve()
    template = deepcopy(load_json(source))
    if template["run_kind"] != "research" or template["model"]["provider"] != "pybamm":
        parser.error("Only the approved measured-cell DFN configuration is allowed")
    # Only enable existing feedback and strictly bounded selector-format correction.
    template["llm"]["warm_start_feedback"] = True
    template["llm"]["selection_max_attempts"] = 3
    template["llm"].pop("parameter_groups_replay", None)
    template["optimization"].pop("gp_prior_guard", None)
    # Screening and downstream ordinary BO will explicitly disable LLM GP groups.
    template["optimization"].update(llm_enabled=True, llm_warm_start_enabled=True, llm_gp_groups_enabled=False)
    problems = configuration_errors(template)
    if problems:
        raise ValueError("invalid research configuration: " + "; ".join(problems))
    prompt = ROOT / "src/llmbo_para/prompts/warm_start.txt"
    selector = ROOT / "src/llmbo_para/prompts/warm_start_select.txt"
    fingerprint = {"source_revision": __import__("subprocess").check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip(),
        "warm_start_sha256": sha256_file(prompt), "warm_start_words": len(prompt.read_text(encoding="utf-8").split()),
        "selector_sha256": sha256_file(selector)}
    if args.check_only:
        import importlib.metadata
        data = Path(template["data"]["path"])
        actual_data_hash = sha256_file(data) if data.is_file() else None
        result = {"check_only": True, "llm_api_calls": 0, "dfn_solves": 0,
            "data_exists": data.is_file(), "data_hash_matches": actual_data_hash == template["data"]["sha256"],
            "pybamm_version": importlib.metadata.version("pybamm"),
            "parameter_count": len(template["parameters"]), "rates": template["rates"],
            "bo_iterations": args.bo_iterations,
            "max_screening_evaluations": args.max_screening_evaluations,
            "max_warm_batches": args.max_warm_batches,
            "max_selection_requests": args.max_selection_requests,
            **fingerprint}
        print(json.dumps(result, ensure_ascii=False), flush=True)
        if not result["data_hash_matches"]:
            raise RuntimeError("workbook mismatch; real experiment refused")
        return
    key_env = template["llm"]["api_key_env"]
    if not os.environ.get(key_env):
        raise RuntimeError(f"live LLM credential {key_env} not present; no API/DFN call initiated")
    if not Path(template["data"]["path"]).is_file():
        raise FileNotFoundError("verified measured workbook is unavailable")
    target = args.output_root.resolve()
    target.mkdir(parents=True, exist_ok=True)
    budget = ScreeningBudget(target=8,
        max_evaluations=args.max_screening_evaluations,
        max_warm_batches=args.max_warm_batches,
        max_selection_requests=args.max_selection_requests)
    protocol = {"source_config": str(source), "source_config_sha256": sha256_file(source),
        "prompt_version": "compact_v3.1", "components": {
            "new_warm_start_prompt": True, "new_feedback_context": True,
            "selector_prompt_unchanged": True, "gp_llm_groups_enabled": False,
            "gp_guard_enabled": False, "bo_algorithms_unchanged": True},
        "screening_budget": asdict(budget), "bo_iterations": args.bo_iterations,
        "comparison": "Historical W-old and B0 are descriptive, not isolated prompt-only controls",
        **fingerprint}
    suite = RunStore(target / "controller", protocol, command="new compact WarmStart v3.1 + 20 BO")
    suite.write_json("study-plan.json", protocol)
    try:
        preflight, prepared = prepare_experiment(template, base_dir=source.parent)
        suite.write_json("preflight.json", preflight)
        if not preflight["ready"] or prepared is None:
            raise RuntimeError("scientific preflight failed: " + "; ".join(preflight["errors"]))
        # The historical source is untouched; new screening owns its immutable records.
        plan, plan_file = screen_family(template, "llm", suite, source.parent,
            budget=budget, artifact_root=target / "work")
        if not plan["complete"] or len(plan["parameters"]) != 8:
            raise RuntimeError("screening budget reached before obtaining 8 complete valid points")
        diversity = initial_diversity(prepared.space, plan["parameters"])
        metrics = {"screening_cost": plan["screening_cost"], "initial_diversity": diversity,
                   "initial_best_J_mV": min(row["objective_v"] for row in plan["evaluations"]) * 1000}
        suite.write_json("initial-metrics.json", metrics)
        config = arm_config(template, plan, plan_file, warm_start=True, gp_groups=False,
            bo_iterations=args.bo_iterations)
        config["status"] = "warmstart_compact_v31_8_valid_plus_20_BO"
        suite.write_json("bo-config.json", config)
        outcome = run_experiment(config, target / "work" / "arms", base_dir=source.parent,
            command="compact WarmStart v3.1 new real 20-step DFN BO")
        audited = audit_run(outcome["run_directory"], deep=True)
        if not audited["passed"]:
            raise RuntimeError("deep audit failed: " + "; ".join(audited["issues"]))
        final = {"screening": metrics, "new_bo_candidate_evaluations": outcome["new_candidate_evaluations"],
            "new_bo_valid": outcome["bo_candidate_valid"], "final_J_mV": outcome["best_objective_v"] * 1000,
            "best_by_rate_mV": {r: v * 1000 for r, v in outcome["best_rmse_v"].items()},
            "bo_result": outcome, "deep_audit": audited, "source_revision": fingerprint["source_revision"],
            "prompt_sha256": fingerprint["warm_start_sha256"]}
        suite.write_json("trial-result.json", final)
        suite.finish("completed", final)
        print(json.dumps({"status": "completed", "suite_dir": str(suite.path),
            "screening_candidate_evaluations": plan["screening_cost"]["candidate_evaluations"],
            "initial_best_J_mV": metrics["initial_best_J_mV"],
            "final_J_mV": final["final_J_mV"], "new_bo_valid": final["new_bo_valid"],
            "deep_audit_passed": audited["passed"]}, ensure_ascii=False), flush=True)
    except Exception as exc:
        diagnostic = {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        suite.write_json("failure.json", diagnostic)
        suite.finish("failed", diagnostic)
        print(json.dumps({"status": "failed", "suite_dir": str(suite.path),
            "error_type": type(exc).__name__, "message": str(exc)}, ensure_ascii=False), flush=True)
        raise


if __name__ == "__main__":
    main()
