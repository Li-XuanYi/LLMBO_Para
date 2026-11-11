"""Fresh eight-point BO versus WarmStart+GP-LLM, with 25 BO evaluations each.

Reuse the production screening, optimizer and curve audit; never import an old
parameter diagnosis as an initial point. All paths are nested in a new RunStore.
"""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from dataclasses import asdict
import getpass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
os.environ["MPLBACKEND"] = "Agg"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run, read_json
from llmbo_para.config import load_json
from llmbo_para.initialization import ScreeningBudget
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import build_transport, prepare_experiment, run_experiment, run_status
from resource_snapshot import snapshot
from run_ablation_suite import screen_family, cost_curve, plot_cost_curves


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--bo-iterations", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20261014)
    parser.add_argument("--max-screening-evaluations", type=int, default=200)
    parser.add_argument("--resume-random-plan", type=Path, help="Continue the same fresh random sequence after a saved screening budget stop")
    parser.add_argument("--output", type=Path, default=ROOT / "runs/two-arm-comparisons")
    parser.add_argument("--proxy", default="http://127.0.0.1:7897")
    parser.add_argument("--prompt-for-key", action="store_true")
    args = parser.parse_args()
    if args.bo_iterations < 1:
        parser.error("bo-iterations must be positive")
    if args.proxy:
        from urllib.parse import urlsplit
        parsed = urlsplit(args.proxy)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error("proxy must be an HTTP(S) URL without credentials")
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            os.environ[name] = args.proxy
    template = load_json(args.config)
    template["data"]["path"] = str((args.config.resolve().parent / template["data"]["path"]).resolve())
    template["optimization"].update(seed=args.seed, total_candidate_budget=8 + args.bo_iterations,
        warm_start_llm_points=0, sobol_points=8, llm_informed_enabled=False)
    if (template["model"].get("initial_state_mode") != "parameterization"
        or template["optimization"].get("surrogate_mode") != "per_rate"
        or template["optimization"].get("bo_repair", {}).get("completion_model") != "standardized_linear_cv"):
        parser.error("requires the agreed fixed-state four-GP linear-completion configuration")
    key_env = template["llm"]["api_key_env"]
    supplied_key = False
    if args.prompt_for_key and not os.environ.get(key_env):
        os.environ[key_env] = getpass.getpass("OpenCode credential (hidden; memory only): ")
        supplied_key = True
    budget = ScreeningBudget(max_evaluations=args.max_screening_evaluations)
    protocol = {"study": "fresh_BO_vs_WarmStart_GP_LLM", "experiment": template,
        "arms": ["BO", "LLMBO"], "initial_valid_points_per_arm": 8,
        "bo_iterations_per_arm": args.bo_iterations, "screening_budget_per_arm": asdict(budget),
        "seed": args.seed, "workers": 1, "proxy": args.proxy,
        "cost_accounting": "all fresh screening including failures plus 25 BO evaluations; cache copies cost zero",
        "history_policy": "only each arm's own fresh screening, including partial rate labels; no older runs",
        "small_case_gate": "two valid initial points independently rescored before screening continues",
        "limits": "one seed; descriptive end-to-end comparison, no statistical significance claim",
        "external_summary_consent": True, "random_substitution_for_llm": False}
    if args.resume_random_plan:
        protocol["resume_random_plan"] = {"path": str(args.resume_random_plan.resolve()), "sha256": sha256_file(args.resume_random_plan)}
    suite = RunStore(args.output, protocol, command=subprocess.list2cmdline([sys.executable, *sys.argv]))
    suite.write_json("study-plan.json", protocol)
    suite.write_json("input-config.json", {"path": str(args.config.resolve()), "sha256": sha256_file(args.config)})
    print(json.dumps({"suite_directory": str(suite.path), "stage": "preflight"}), flush=True)
    started = time.perf_counter()
    outcomes = []
    with (suite.path / "stdout.log").open("x", encoding="utf-8", buffering=1) as out, (suite.path / "stderr.log").open("x", encoding="utf-8", buffering=1) as err:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                resources = snapshot()
                suite.write_json("resources/before.json", resources)
                if resources.get("memory_available_bytes", 4e9) < 1024**3 + 256 * 1024**2 or resources["disk_free_bytes"] < 2e9:
                    raise RuntimeError("insufficient memory/disk headroom for serial experiment")
                screens = {}
                for arm, source in (("BO", "random"), ("LLMBO", "llm")):
                    screen = deepcopy(template)
                    # Fresh screening has no cached initial plan yet. History is
                    # enabled only for the subsequent arm with its verified plan.
                    screen["optimization"].update(reuse_screening_history=False,
                        llm_enabled=source == "llm", llm_warm_start_enabled=source == "llm", llm_gp_groups_enabled=False)
                    report, prepared = prepare_experiment(screen)
                    suite.write_json(f"preflight/screen-{arm}.json", report)
                    if prepared is None:
                        raise ValueError(f"{arm} preflight: " + "; ".join(report["errors"]))
                    screens[arm] = screen
                probe_settings = {**template["llm"], "max_tokens": 128}
                probe = RunStore(suite.path / "connectivity", {"llm": probe_settings, "data_sent": "none"}, command="minimal authorized model connectivity probe")
                reply = build_transport(probe_settings, probe).post({"task": "connectivity_probe",
                    "instructions": 'Return only the JSON object {"ok":true}.', "purpose": "connectivity"})
                if reply != {"ok": True}:
                    raise ValueError("connectivity probe returned unexpected JSON")
                probe.finish("completed", {"response": reply})
                suite.append_event({"type": "connectivity_passed"})

                for arm, source in (("BO", "random"), ("LLMBO", "llm")):
                    resources = snapshot()
                    suite.write_json(f"resources/before-screen-{arm}.json", resources)
                    if resources.get("memory_available_bytes", 4e9) < 1024**3 + 256 * 1024**2 or resources["disk_free_bytes"] < 2e9:
                        raise RuntimeError("insufficient memory/disk before " + arm)
                    suite.append_event({"type": "arm_started", "arm": arm, "stage": "screening"})
                    plan, plan_path = screen_family(screens[arm], source, suite, ROOT,
                        budget=budget, artifact_root=suite.path / "initialization" / arm,
                        resume_plan=args.resume_random_plan if source == "random" else None)
                    suite.write_json(f"initial-plan-{arm}.json", plan)
                    if not plan.get("complete") or len(plan["parameters"]) != 8:
                        raise RuntimeError(arm + " did not obtain eight valid points within the saved screening budget")
                    config = arm_config(template, plan, plan_path, warm_start=source == "llm", gp_groups=source == "llm", bo_iterations=args.bo_iterations)
                    config["status"] = f"fresh_two_arm_{arm}_8_initial_{args.bo_iterations}_bo"
                    suite.write_json(f"config-{arm}.json", config)
                    report, prepared = prepare_experiment(config)
                    suite.write_json(f"preflight/optimization-{arm}.json", report)
                    if prepared is None:
                        raise ValueError(arm + " optimization preflight: " + "; ".join(report["errors"]))
                    suite.append_event({"type": "arm_stage", "arm": arm, "stage": "BO", "bo_iterations": args.bo_iterations})
                    result = run_experiment(config, suite.path / "optimization" / arm,
                        command=f"fresh {arm}: eight valid initial points plus {args.bo_iterations} BO updates")
                    directory = Path(result["run_directory"])
                    audit = audit_run(directory, deep=True)
                    suite.write_json(f"deep-audit-{arm}.json", audit)
                    if not audit["passed"]:
                        raise RuntimeError(arm + " deep curve/source audit failed")
                    records = [read_json(file) for file in sorted((directory / "attempts").glob("*.json"))]
                    if (len(records) != 8 + args.bo_iterations or sum(bool(r.get("cache_provenance")) for r in records) != 8
                        or result["new_candidate_evaluations"] != args.bo_iterations or result["rate_solve_attempts"] != 4 * args.bo_iterations):
                        raise RuntimeError(arm + " budget/cache ledger does not match protocol")
                    outcome = {"arm": arm, "execution_completed": True, "result": result,
                        "status": run_status(directory), "initial_plan": str(plan_path), "initial_plan_sha256": sha256_file(plan_path),
                        "screening_cost": plan["screening_cost"], "deep_audit_passed": True}
                    suite.write_json(f"outcome-{arm}.json", outcome)
                    suite.write_json(f"cost-curve-{arm}.json", cost_curve(outcome, plan))
                    outcomes.append(outcome)
                    suite.append_event({"type": "arm_finished", **outcome})
                    print(json.dumps({"arm": arm, "best_rmse_mV": result["best_objective_v"] * 1000,
                        "bo_valid": result["bo_candidate_valid"], "bo_total": args.bo_iterations}), flush=True)
                plot_cost_curves(suite, outcomes)
                summary = {"outcomes": outcomes, "completed_arms": len(outcomes), "running_arms": 0,
                    "execution_errors": 0, "pending_arms": 0, "bo_updates_completed": 2 * args.bo_iterations,
                    "screening_candidate_evaluations": sum(x["screening_cost"]["candidate_evaluations"] for x in outcomes),
                    "actual_rate_solves": sum(x["screening_cost"]["rate_solve_attempts"] + x["result"]["rate_solve_attempts"] for x in outcomes),
                    "elapsed_s": time.perf_counter() - started, "eta_minutes": 0}
                suite.write_json("resources/after.json", snapshot())
                suite.write_json("study-summary.json", summary)
                suite.finish("completed", summary)
                return 0
            except BaseException as exc:
                message = str(exc)
                trace = traceback.format_exc()
                key = os.environ.get(key_env)
                if key:
                    message, trace = message.replace(key, "[REDACTED]"), trace.replace(key, "[REDACTED]")
                failure = {"error_type": type(exc).__name__, "message": message, "traceback": trace,
                    "elapsed_s": time.perf_counter() - started, "completed_arms": len(outcomes)}
                suite.write_json("failure.json", failure)
                suite.finish("interrupted" if isinstance(exc, KeyboardInterrupt) else "failed", failure)
                print(json.dumps(failure), flush=True)
                return 1
            finally:
                if supplied_key:
                    os.environ.pop(key_env, None)


if __name__ == "__main__":
    raise SystemExit(main())
