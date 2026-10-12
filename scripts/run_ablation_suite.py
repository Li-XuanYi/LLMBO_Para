"""Bounded paired feasible initialization, then four independent LLM ablations."""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import sys
import time
import traceback

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "src"))
from llmbo_para.ablation import ARMS, arm_config
from llmbo_para.audit import audit_run, read_json
from llmbo_para.config import load_json
from llmbo_para.evaluation import FourRateEvaluator
from llmbo_para.feasibility import InventoryGate
from llmbo_para.initialization import FeasibleInitializer, ScreeningBudget, validated_cached_results
from llmbo_para.runstore import RunStore, digest_value, sha256_file
from llmbo_para.workflow import ExperimentFailure, build_backend, build_llm, prepare_experiment, run_experiment, run_status


class ArchivedRequest:
    """Each request owns immutable prompt, HTTP trace and terminal artifacts."""
    def __init__(self, client, store):
        self.client, self.store = client, store

    def __getattr__(self, name):
        attribute = getattr(self.client, name)
        if not callable(attribute):
            return attribute
        def call(*args):
            try:
                result = attribute(*args)
                self.store.finish("completed", {"task": name})
                return result
            except Exception as exc:
                self.store.finish("failed", {"task": name, "error_type": type(exc).__name__, "message": str(exc)})
                raise
        return call


def screen_family(template, source, suite, base_dir, *, budget=None, resume_plan=None, artifact_root=None):
    budget = budget or ScreeningBudget()
    config = deepcopy(template)
    config["optimization"].update(llm_enabled=source == "llm", llm_warm_start_enabled=source == "llm", llm_gp_groups_enabled=False)
    screening_root = Path(artifact_root) / "screening" if artifact_root is not None else workspace / "runs/feasible-initial"
    request_root = Path(artifact_root) / "requests" if artifact_root is not None else workspace / "runs/initial-requests"
    store = RunStore(screening_root, {"experiment": config, "source": source, "budget": asdict(budget),
                     "resume_evidence": {"path": str(resume_plan.resolve()), "sha256": sha256_file(resume_plan)} if resume_plan else None},
                     data_hashes={config["data"]["path"]: config["data"]["sha256"]} if config["data"]["kind"] == "xlsx" else {},
                     command="bounded feasible initialization " + source)
    try:
        report, prepared = prepare_experiment(config, base_dir=base_dir)
        store.write_json("preflight.json", report)
        if prepared is None:
            raise ValueError("screening preflight failed: " + "; ".join(report["errors"]))
        backend = build_backend(prepared)
        fingerprint = None
        if hasattr(backend, "save_parameterization"):
            backend.save_parameterization(store)
            fingerprint = digest_value(read_json(store.path / "parameterization.json")["values"])
        if prepared.workbook:
            target = store.path / "inputs/raw.xlsx"
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(prepared.workbook, target)
            if sha256_file(target) not in prepared.input_hashes.values():
                raise ValueError("screening workbook snapshot changed")
        inputs = {rate: asdict(row) for rate, row in prepared.series.items()}
        store.write_json("input-series.json", inputs)
        store.write_json("input-series-sha256.json", {"sha256": digest_value(inputs)})
        gate = InventoryGate.from_parameters(backend.base_parameters(), prepared.series) if hasattr(backend, "base_parameters") else None
        evaluator = FourRateEvaluator(prepared.space, backend, max_rate_attempts=config["optimization"]["max_rate_attempts"], event_callback=store.append_event)

        def factory(stage, index, context):
            request = RunStore(request_root, {"experiment": config, "stage": stage, "index": index, "context": context},
                               command=f"LLM initialization {stage} {index}")
            if hasattr(backend, "save_parameterization"):
                backend.save_parameterization(request)
            client = build_llm(config, request, prepared=prepared)
            client.context.update(context)
            store.append_event({"type": "llm_request_archive", "stage": stage, "index": index, "path": str(request.path)})
            return ArchivedRequest(client, request)

        def checkpoint(plan, path):
            checked = validated_cached_results(config, prepared.series, plan, path)
            if len(checked) != 2:
                raise ValueError("two-point checkpoint failed")
            store.write_json("two-point-checkpoint-audit.json", {"passed": True, "labels_recomputed": 2,
                "parameters": plan["parameters"], "cost": plan["screening_cost"], "continue_to": 8})
            print(json.dumps({"source": source, "two_point_checkpoint_passed": True, **plan["screening_cost"]}), flush=True)

        initializer = FeasibleInitializer(config, prepared.space, prepared.series, evaluator, store, gate=gate, source=source,
            llm_factory=factory if source == "llm" else None, parameterization_fingerprint=fingerprint, checkpoint_callback=checkpoint, budget=budget)
        if resume_plan:
            initializer.restore_random(read_json(resume_plan), resume_plan)
        plan = initializer.run()
        print(json.dumps({"screening_directory": str(store.path), **plan["screening_cost"]}), flush=True)
        return plan, store.path / "initial-plan.json"
    except Exception as exc:
        if not (store.path / "terminal.json").exists():
            failure = {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
            store.write_json("screening-failure.json", failure)
            store.finish("failed", failure)
        exc.screening_directory = str(store.path)
        raise


def cost_curve(outcome, initial):
    path = Path(outcome["result"]["run_directory"])
    records = [read_json(file) for file in sorted((path / "attempts").glob("*.json"))]
    cost = initial["screening_cost"]
    solves, best, rows = cost["rate_solve_attempts"], None, []
    count = len(initial["parameters"])
    events = [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    arm_api = sum(row["type"] == "llm_http_started" for row in events)
    for index, record in enumerate(records):
        if not record.get("cache_provenance"):
            solves += sum(len(rate["attempts"]) for rate in record["rates"])
        if record["valid"]:
            best = min(best, record["objective_v"]) if best is not None else record["objective_v"]
        rows.append({"logical_candidate": index+1, "bo_iteration": max(0, index+1-count),
            "attributed_cumulative_rate_solves": solves, "initial_screening_api_requests": cost["api_requests"],
            "attributed_cumulative_candidate_evaluations": cost["candidate_evaluations"]+max(0,index+1-count),
            "attributed_cumulative_api_requests": cost["api_requests"]+arm_api,
            "valid": record["valid"], "best_objective_v": best})
    return rows


def plot_cost_curves(suite, outcomes):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    plotted = 0
    for outcome in outcomes:
        file = suite.path / ("cost-curve-" + outcome["arm"] + ".json")
        if not file.exists():
            continue
        rows = read_json(file)
        rows = [row for index, row in enumerate(rows) if index == len(rows)-1 or rows[index+1]["bo_iteration"] != 0]
        if not rows:
            continue
        y = [row["best_objective_v"]*1000 for row in rows]
        axes[0].plot([row["bo_iteration"] for row in rows], y, label=outcome["arm"])
        axes[1].plot([row["attributed_cumulative_rate_solves"] for row in rows], y, label=outcome["arm"])
        plotted += 1
    for axis in axes:
        axis.set_ylabel("Best mean four-rate RMSE (mV)")
        axis.grid(alpha=.25)
        if plotted:
            axis.legend(fontsize=8)
    axes[0].set_xlabel("BO candidate evaluation after initialization")
    axes[1].set_xlabel("Attributed DFN rate solves, including all screening")
    axes[1].set_title("Standalone cost; shared preparation counted for each arm", fontsize=9)
    if plotted:
        figure.savefig(suite.path / "ablation-curves.png", dpi=180)
        figure.savefig(suite.path / "ablation-curves.svg")
    plt.close(figure)


def main():
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        ctypes.windll.kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        ctypes.windll.kernel32.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        if not ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000):
            raise ctypes.WinError()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    parser.add_argument("--bo-iterations", type=int, default=25)
    parser.add_argument("--output", type=Path, default=Path("runs/ablations"))
    parser.add_argument("--artifact-root", type=Path, help="Keep screening, LLM requests and arm runs below this directory")
    parser.add_argument("--screening-only", choices=("random", "llm"))
    parser.add_argument("--random-plan", type=Path)
    parser.add_argument("--llm-plan", type=Path)
    parser.add_argument("--resume-random-plan", type=Path)
    parser.add_argument("--max-screening-evaluations", type=int, default=200)
    parser.add_argument("--prompt-for-key", action="store_true", help="Read API key invisibly; never save it")
    args = parser.parse_args()
    template = load_json(args.config)
    if args.bo_iterations < 1:
        parser.error("BO iterations must be positive")
    if args.prompt_for_key:
        import getpass
        os.environ[template["llm"]["api_key_env"]] = getpass.getpass("LLM API key (hidden, environment only): ")
    budget = ScreeningBudget(max_evaluations=args.max_screening_evaluations)
    protocol = {"template": template, "screening": asdict(budget), "bo_iterations": args.bo_iterations,
        "arms": ARMS, "workers": 1, "paired_sets": True, "pilot_checkpoint": 2,
        "screening_only": args.screening_only, "external_api_summary_consent": True,
        "source_data_remote_transfer": "managed by caller", "no_random_llm_substitution": True,
        "artifact_root": str(args.artifact_root.resolve()) if args.artifact_root else None}
    suite = RunStore(args.output, protocol, command=" ".join(sys.argv))
    suite.write_json("study-plan.json", protocol)
    print(json.dumps({"suite_directory": str(suite.path), "state": "preparing_initial_sets"}), flush=True)
    started = time.perf_counter()
    families, failures, outcomes, family_costs = {}, {}, [], {}
    for source in ("random", "llm"):
        if args.screening_only and args.screening_only != source:
            continue
        try:
            existing = args.random_plan if source == "random" else args.llm_plan
            if existing:
                initial = read_json(existing)
                check_config = deepcopy(template)
                check_config["optimization"].update(llm_enabled=False, llm_warm_start_enabled=False, llm_gp_groups_enabled=False)
                report, prepared = prepare_experiment(check_config, base_dir=args.config.resolve().parent)
                if prepared is None:
                    raise ValueError("cached family preflight failed: " + "; ".join(report["errors"]))
                validated_cached_results(template, prepared.series, initial, existing)
            else:
                initial, existing = screen_family(template, source, suite, args.config.resolve().parent, budget=budget,
                    resume_plan=args.resume_random_plan if source == "random" else None, artifact_root=args.artifact_root)
            family_costs[source] = initial["screening_cost"]
            evidence = suite.write_json(source + "-initial-plan.json", initial)
            if initial.get("source") != source or not initial.get("complete") or len(initial["parameters"]) != 8:
                raise ValueError("bounded initialization did not obtain eight complete valid points; inspect screening archive")
            families[source] = (initial, evidence)
        except Exception as exc:
            failures[source] = {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
            if hasattr(exc, "screening_directory"):
                failures[source]["screening_directory"] = exc.screening_directory
                terminal = read_json(Path(exc.screening_directory) / "terminal.json")["summary"]
                family_costs[source] = terminal
            suite.write_json(source + "-initialization-failure.json", failures[source])
    if args.screening_only:
        summary = {"screening_only": args.screening_only, "complete": args.screening_only in families,
            "screening_cost": family_costs,
            "families": {key: str(value[1]) for key, value in families.items()}, "failures": failures,
            "elapsed_s": time.perf_counter()-started, "formal_arms_completed": 0, "formal_arms_pending": 4}
        suite.write_json("study-summary.json", summary)
        suite.finish("completed" if summary["complete"] else "failed", summary)
        print(json.dumps(summary), flush=True)
        return 0 if summary["complete"] else 1
    for name, warm, groups in ARMS:
        source = "llm" if warm else "random"
        if source not in families:
            outcome = {"arm": name, "execution_completed": False, "execution_blocked": True, "error": failures[source],
                "status": {"completed_candidates": 0, "successful_candidates": 0, "failed_candidates": 0, "pending_candidates": 8+args.bo_iterations}}
        else:
            initial, evidence = families[source]
            config = arm_config(template, initial, evidence, warm_start=warm, gp_groups=groups, bo_iterations=args.bo_iterations)
            suite.write_json("config-" + name + ".json", config)
            suite.append_event({"type": "ablation_arm_started", "arm": name})
            try:
                arm_root = args.artifact_root / "arms" if args.artifact_root else workspace / "runs/ablation-arms"
                result = run_experiment(config, arm_root, base_dir=args.config.resolve().parent, command="paired ablation " + name)
                audit_started = time.perf_counter()
                audit = audit_run(result["run_directory"], deep=True)
                outcome = {"arm": name, "execution_completed": audit["passed"], "result": result, "deep_audit": audit,
                    "deep_audit_elapsed_s": time.perf_counter()-audit_started,
                    "status": run_status(result["run_directory"]), "attributed_initial_screening_cost": initial["screening_cost"]}
                suite.write_json("cost-curve-" + name + ".json", cost_curve(outcome, initial))
            except ExperimentFailure as exc:
                outcome = {"arm": name, "execution_completed": False, "error": str(exc), "run_directory": exc.run_directory,
                    "status": run_status(exc.run_directory)}
            except Exception as exc:
                outcome = {"arm": name, "execution_completed": False, "error_type": type(exc).__name__, "error": str(exc),
                    "status": {"completed_candidates": 0, "successful_candidates": 0, "failed_candidates": 0, "pending_candidates": 8+args.bo_iterations}}
        outcomes.append(outcome)
        suite.write_json("outcome-" + name + ".json", outcome)
        suite.append_event({"type": "ablation_arm_finished", **outcome})
        print(json.dumps(outcome), flush=True)
    summary = {"outcomes": outcomes, "elapsed_s": time.perf_counter()-started,
        "planned_logical_candidates": 4*(8+args.bo_iterations),
        "unique_screening_cost": family_costs,
        "cost_note": "Shared screening counted once; per-arm curves attribute full standalone screening cost including failures. Cache hits incur no new solves.",
        "completed_arms": sum(row["execution_completed"] for row in outcomes),
        "blocked_arms": sum(row.get("execution_blocked", False) for row in outcomes)}
    summary["new_arm_rate_solves"] = sum(row["status"].get("rate_solve_attempts",0) for row in outcomes)
    summary["unique_screening_rate_solves"] = sum(row.get("rate_solve_attempts",0) for row in family_costs.values())
    summary["actual_rate_solves_including_linked_screening"] = summary["new_arm_rate_solves"]+summary["unique_screening_rate_solves"]
    for name in ("completed_candidates", "successful_candidates", "failed_candidates", "pending_candidates"):
        summary[name] = sum(row["status"][name] for row in outcomes)
    summary["failed_arms"] = len(ARMS)-summary["completed_arms"]-summary["blocked_arms"]
    summary["all_four_arms_completed"] = summary["completed_arms"] == 4
    plot_cost_curves(suite, outcomes)
    suite.write_json("study-summary.json", summary)
    suite.finish("completed" if summary["all_four_arms_completed"] else "completed_with_failures", summary)
    print(json.dumps({"suite_directory": str(suite.path), **summary}), flush=True)
    return 0 if summary["all_four_arms_completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
