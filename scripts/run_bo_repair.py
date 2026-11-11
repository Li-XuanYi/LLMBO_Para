"""Portable single-host P0 runner. No SSH, uploads, LLM calls or auto formal runs."""
import os
for _name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[_name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"

import argparse
from dataclasses import asdict
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"src"))
from llmbo_para.audit import audit_run, read_json
from llmbo_para.feasibility import simulation_signature
from llmbo_para.runstore import RunStore, digest_value, sha256_file
from llmbo_para.workflow import prepare_experiment, run_experiment, run_fixed_candidates, ExperimentFailure, run_status

ARM_SETTINGS = {
    "A_original": None,
    "B_local": {"training_data":"complete", "candidate_policy":"local"},
    "C_joint": {"training_data":"complete", "candidate_policy":"global", "feasibility_weighting":True},
}


def arm_settings(d_strategy):
    settings = dict(ARM_SETTINGS)
    settings["D_partial"] = {**settings["B_local" if d_strategy == "local" else "C_joint"], "training_data":"per_rate"}
    return settings


def resources(output):
    existing = Path(output).resolve()
    while not existing.exists(): existing = existing.parent
    result = {"machine":platform.node(), "platform":platform.platform(), "cwd":str(Path.cwd()),
        "python_executable":sys.executable, "logical_cpus":os.cpu_count(),
        "disk_free_bytes":shutil.disk_usage(existing).free, "worker_count":1,
        "threads":{name:os.environ[name] for name in ("OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","OMP_NUM_THREADS")}}
    if Path("/proc/meminfo").is_file():
        memory = dict(line.split(":",1) for line in Path("/proc/meminfo").read_text().splitlines())
        result["memory_available_bytes"] = int(memory["MemAvailable"].split()[0])*1024
        result["load_average"] = list(os.getloadavg())
    return result


def check_dependencies():
    result, errors = {}, []
    for name in ("numpy","scipy","pybamm","pybammsolvers","casadi","openpyxl","et_xmlfile"):
        try: result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            errors.append("missing dependency: "+name)
    pins = {}
    for line in (ROOT/"requirements-research.lock").read_text(encoding="utf8").splitlines():
        if "==" in line and not line.startswith("#"):
            name, version = line.split("=="); pins[name.lower().replace("_","-")] = version
    for name, version in result.items():
        expected = pins.get(name.lower().replace("_","-"))
        if expected != version: errors.append(f"dependency mismatch: {name} installed={version} expected={expected}")
    return result, errors


def load_config(workbook=None):
    config = read_json(ROOT/"configs/bo-repair-21700.json")
    if workbook: config["data"]["path"] = str(Path(workbook).resolve())
    # Overrides below are the only BO factors; template physics remains fixed.
    if config["optimization"]["llm_enabled"] or config["llm"]["endpoint"] is not None:
        raise ValueError("P0 runner requires both LLM components disabled and no endpoint")
    return config


def initial_points(config):
    file = ROOT/"configs/bo-repair-initial-points.json"
    evidence = read_json(file)
    from llmbo_para.config import parameter_space_from_config
    space = parameter_space_from_config(config)
    points = [list(space.validate(p)) for p in evidence["parameters"]]
    if len(points) != 8 or len({tuple(p) for p in points}) != 8 or evidence["source"] != "random":
        raise ValueError("P0 comparison needs the exact eight distinct random-family vectors")
    return points, {"path":str(file),"sha256":sha256_file(file),"source_plan_sha256":evidence["source_plan_sha256"],
        "historical_screening_cost":evidence["historical_screening_cost"],"prior_candidate_evaluations":evidence.get("prior_candidate_evaluations",0)}


def prepare_initial(config, output):
    """Re-solve once, then export through the existing strict cache validation path."""
    points, origin = initial_points(config)
    report, prepared = prepare_experiment(config, base_dir=ROOT/"configs")
    if not report["ready"]: raise ValueError("; ".join(report["errors"]))
    result = run_fixed_candidates(config, output, list(enumerate(points)), mode="smoke", base_dir=ROOT/"configs", source_info=origin)
    directory = Path(result["run_directory"])
    if result["candidate_valid"] != 8:
        raise ExperimentFailure("Initial re-evaluation did not validate all eight points. Diagnose the archived feedback; do not substitute or rescreen silently.", directory, "completed_with_failures")
    sources = sorted((directory/"attempts").glob("*.json"))
    plan = {"source":"random", "parameters":points, "evaluations":[read_json(p) for p in sources],
        "evaluation_sources":[{"path":str(p.resolve()),"sha256":sha256_file(p)} for p in sources],
        "screening_directory":str(directory), "simulation_signature":simulation_signature(config, prepared.series),
        "parameterization_fingerprint":digest_value(read_json(directory/"parameterization.json")["values"]),
        "complete":True, "origin":origin,
        "screening_cost":{"candidate_evaluations":8,"rate_solves":result["rate_solve_attempts"],"elapsed_s":result["elapsed_s"],"api_requests":0}}
    # This directory is new. Exported files are immutable just like RunStore files.
    path = directory/"initial-plan.json"
    RunStore._create_json(path, plan)
    return path, result


def configure_arm(config, plan_path, iterations, settings):
    config = json.loads(json.dumps(config)); plan_path = Path(plan_path).resolve(); plan = read_json(plan_path)
    options = config["optimization"]
    tuning = {key:value for key,value in options.pop("bo_repair", {}).items()
        if key not in {"training_data","candidate_policy","feasibility_weighting"}}
    if settings is not None: options["bo_repair"] = {**tuning,**settings}
    options.update(initial_candidates=plan["parameters"], initial_candidates_source="random",
        initial_candidates_evidence={"path":str(plan_path),"sha256":sha256_file(plan_path)},
        warm_start_llm_points=0,sobol_points=8,total_candidate_budget=8+iterations,
        llm_enabled=False,llm_warm_start_enabled=False,llm_gp_groups_enabled=False)
    return config


def validate_formal_evidence(file, config, plan_path, d_strategy):
    """Formal budget is opt-in and requires a matching successful small comparison."""
    evidence = read_json(file)
    plan_path = Path(plan_path).resolve()
    if evidence.get("kind") != "bo_repair_smoke" or evidence.get("iterations",100) > 5:
        raise ValueError("formal run requires a P0 smoke report (at most five iterations)")
    if evidence.get("initial_plan_sha256") != sha256_file(plan_path) or evidence.get("d_strategy") != d_strategy:
        raise ValueError("smoke evidence uses different initial data or D strategy")
    report, prepared = prepare_experiment(config, base_dir=ROOT/"configs")
    if not report["ready"]: raise ValueError("formal data/environment preflight failed")
    if evidence.get("simulation_signature") != simulation_signature(config, prepared.series):
        raise ValueError("smoke evidence uses different physics or observations")
    for name, settings in arm_settings(d_strategy).items():
        row = evidence["arms"].get(name,{})
        if not row.get("audit_passed") or not row.get("run_directory"):
            raise ValueError("smoke arm incomplete or failed audit: "+name)
        directory = Path(row["run_directory"])
        if not audit_run(directory)["passed"]: raise ValueError("smoke artifacts no longer pass audit: "+name)
        expected = configure_arm(config, plan_path, evidence["iterations"], settings)
        archived = read_json(directory/"manifest.json")
        if archived["config_sha256"] != digest_value(expected):
            raise ValueError("smoke BO settings differ from requested formal setup: "+name)
        # Source snapshot must match the current code, including optimization policies.
        for rel, digest in read_json(directory/"source-sha256.json").items():
            rel = rel.replace("\\","/")
            if rel.startswith("src/") and sha256_file(ROOT/rel) != digest:
                raise ValueError("source changed since the smoke run: "+rel)
        if name in {"B_local","D_partial"} and row.get("bo_candidate_valid",0) < 1:
            raise ValueError("smoke has not shown new complete candidates in "+name)


def run_suite(config, plan_path, output, *, iterations=5, d_strategy="local", formal=False, smoke_report=None):
    if formal:
        if iterations != 25 or smoke_report is None: raise ValueError("formal mode requires exactly 25 iterations and --smoke-report")
        validate_formal_evidence(smoke_report, config, plan_path, d_strategy)
    elif not 1 <= iterations <= 5:
        raise ValueError("smoke budget must be between one and five BO iterations")
    variants = arm_settings(d_strategy)
    store = RunStore(output, {"kind":"bo_repair_formal" if formal else "bo_repair_smoke", "iterations":iterations,
        "d_strategy":d_strategy,"initial_plan_sha256":sha256_file(plan_path),"arms":variants}, command=" ".join(sys.argv))
    started = time.perf_counter(); rows = {}
    reports = {}
    try:
        # All four configurations/cache hashes are checked BEFORE the first solve.
        for name, settings in variants.items():
            reports[name], prepared = prepare_experiment(configure_arm(config,plan_path,iterations,settings), base_dir=ROOT/"configs")
        store.write_json("all-arm-preflight.json", reports)
        if any(not r["ready"] for r in reports.values()):
            raise ValueError("one or more arms failed preflight; see all-arm-preflight.json")
        store.write_json("resources.json", resources(output))
        for name, settings in variants.items():
            store.append_event({"type":"arm_started","arm":name})
            try:
                # Flat sibling runs keep Windows paths short; comparison.json owns the mapping.
                result = run_experiment(configure_arm(config,plan_path,iterations,settings), Path(output)/"arms",
                    base_dir=ROOT/"configs", command=" ".join(sys.argv)+" arm="+name)
                rows[name] = result
            except ExperimentFailure as exc:
                partial = [read_json(p) for p in sorted((Path(exc.run_directory)/"attempts").glob("*.json"))]
                rows[name] = {"status":exc.status,"run_directory":exc.run_directory,"error":str(exc),"audit_passed":False,
                    "candidate_completed":len(partial),"candidate_valid":sum(r["valid"] for r in partial),
                    "candidate_failed":sum(not r["valid"] for r in partial),"candidate_pending":8+iterations-len(partial),
                    "new_candidate_evaluations":sum(not r.get("cache_provenance") for r in partial),
                    "rate_solve_attempts":sum(len(q["attempts"]) for r in partial if not r.get("cache_provenance") for q in r["rates"])}
            elapsed = time.perf_counter()-started
            progress = {"completed":sum(r.get("audit_passed",False) for r in rows.values()),
                "error":sum(not r.get("audit_passed",False) for r in rows.values()),"running":0,"pending":4-len(rows),
                "arms_per_min":len(rows)*60/elapsed,"eta_minutes":(4-len(rows))*elapsed/max(len(rows),1)/60}
            store.append_event({"type":"suite_progress","arms":rows,**progress})
            print(json.dumps({"arm":name,**progress},ensure_ascii=False),flush=True)
        _, prepared = prepare_experiment(config, base_dir=ROOT/"configs")
        result = {"kind":"bo_repair_formal" if formal else "bo_repair_smoke", "iterations":iterations,"d_strategy":d_strategy,
            "initial_plan_sha256":sha256_file(plan_path),"simulation_signature":simulation_signature(config,prepared.series),
            "arms":rows,"shared_initial_cost":read_json(plan_path)["screening_cost"],
            "new_bo_candidate_evaluations":sum(r.get("new_candidate_evaluations",0) for r in rows.values()),
            "new_bo_rate_solve_attempts":sum(r.get("rate_solve_attempts",0) for r in rows.values()),
            "elapsed_s":time.perf_counter()-started,"api_requests":0}
        store.write_json("comparison.json",result)
        ok = all(r.get("audit_passed") for r in rows.values())
        store.finish("completed" if ok else "completed_with_failures",result)
        return {"comparison_path":str(store.path/"comparison.json"),"passed":ok,**result}
    except BaseException as exc:
        diagnostic = {"error":str(exc),"traceback":traceback.format_exc(),"arms":rows}
        store.write_json("failure.json",diagnostic); store.finish("interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",diagnostic)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("preflight","prepare","smoke","formal","status"))
    parser.add_argument("--workbook",help="Exact true_data.xlsx; must match configured SHA-256")
    parser.add_argument("--output",default=str(ROOT/"bo-repair-work/remote"))
    parser.add_argument("--initial-plan",help="Path returned by prepare on THIS host with current source hashes")
    parser.add_argument("--iterations",type=int,default=5)
    parser.add_argument("--d-strategy",choices=("local","joint"),default="local")
    parser.add_argument("--smoke-report")
    parser.add_argument("--allow-formal",action="store_true")
    parser.add_argument("--run-directory",help="Existing arm for read-only status")
    args = parser.parse_args(argv)
    if args.mode == "status":
        if not args.run_directory: parser.error("status requires --run-directory")
        print(json.dumps(run_status(args.run_directory),ensure_ascii=False,indent=2)); return 0
    config = load_config(args.workbook)
    store = RunStore(args.output, {"kind":"bo_repair_command","mode":args.mode,"experiment":config},command=" ".join(sys.argv))
    try:
        report, _ = prepare_experiment(config, base_dir=ROOT/"configs")
        dependencies, errors = check_dependencies()
        report["errors"].extend(errors); report["ready"] = report["ready"] and not errors
        report["dependencies"] = dependencies; report["resources"] = resources(args.output)
        report["initial_vectors"] = initial_points(config)[1]
        store.write_json("preflight.json",report)
        print(json.dumps({"preflight_directory":str(store.path),"ready":report["ready"],"errors":report["errors"]},ensure_ascii=False),flush=True)
        if not report["ready"]:
            store.finish("preflight_failed",report); return 2
        if args.mode == "preflight":
            store.finish("completed",report); return 0
        if args.mode == "prepare":
            plan, summary = prepare_initial(config,args.output)
            result = {"initial_plan":str(plan),"summary":summary}
        else:
            if not args.initial_plan: raise ValueError("smoke/formal requires --initial-plan from prepare")
            if args.mode == "formal" and not args.allow_formal: raise ValueError("formal mode requires explicit --allow-formal")
            result = run_suite(config,args.initial_plan,args.output,iterations=args.iterations,d_strategy=args.d_strategy,
                formal=args.mode=="formal",smoke_report=args.smoke_report)
        store.write_json("result.json",result); store.finish("completed" if result.get("passed",True) else "completed_with_failures",result)
        print(json.dumps(result,ensure_ascii=False,indent=2)); return 0 if result.get("passed",True) else 1
    except BaseException as exc:
        failure = {"error":str(exc),"traceback":traceback.format_exc()}
        store.write_json("failure.json",failure); store.finish("interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",failure)
        if isinstance(exc,KeyboardInterrupt): raise
        print(json.dumps({"error":str(exc),"record":str(store.path)},ensure_ascii=False)); return 1


if __name__ == "__main__":
    raise SystemExit(main())
