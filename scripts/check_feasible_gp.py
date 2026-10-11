"""Small real-data closure using verified initial curves; never a formal ablation."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time
for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(workspace / "src"))
from llmbo_para.ablation import ARMS, arm_config
from llmbo_para.audit import audit_run, read_json
from llmbo_para.runstore import RunStore
from llmbo_para.workflow import run_experiment, ExperimentFailure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config",type=Path)
    parser.add_argument("plan",type=Path)
    parser.add_argument("--bo-iterations",type=int,default=0)
    parser.add_argument("--gp-llm",action="store_true")
    parser.add_argument("--prompt-for-key",action="store_true")
    args = parser.parse_args()
    if args.bo_iterations < 0 or args.bo_iterations > 2:
        parser.error("small closure permits zero to two new BO evaluations")
    template = read_json(args.config); plan = read_json(args.plan)
    if args.prompt_for_key:
        os.environ[template["llm"]["api_key_env"]] = getpass.getpass("API credential (hidden): ")
    config = arm_config(template,plan,args.plan,warm_start=plan["source"]=="llm",gp_groups=args.gp_llm,bo_iterations=args.bo_iterations)
    config["status"] = "real_data_small_closure_not_formal_ablation"
    store = RunStore(workspace / "runs/gp-readiness",config,command=" ".join(sys.argv))
    try:
        result = run_experiment(config,workspace / "runs/closure-arms",base_dir=args.config.resolve().parent,command="small real-data GP closure")
        started = time.perf_counter(); audit = audit_run(result["run_directory"],deep=True)
        store.write_json("closure-result.json",result)
        store.write_json("deep-audit.json",{**audit,"elapsed_s":time.perf_counter()-started})
        summary = {"passed":audit["passed"],"result_directory":result["run_directory"],"cache_hits":result["cache_hits"],
            "new_rate_solves":result["rate_solve_attempts"],"candidate_failed":result["candidate_failed"],"bo_iterations":args.bo_iterations,"gp_llm":args.gp_llm}
        store.finish("completed" if audit["passed"] else "failed",summary)
        print(json.dumps({"readiness_directory":str(store.path),**summary}),flush=True)
        return 0 if audit["passed"] else 1
    except Exception as exc:
        failure={"error_type":type(exc).__name__,"message":str(exc)}
        if isinstance(exc,ExperimentFailure): failure["run_directory"]=exc.run_directory
        store.finish("failed",failure)
        print(json.dumps({"readiness_directory":str(store.path),**failure}),flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
