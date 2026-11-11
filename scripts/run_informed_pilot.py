"""Small single-GP + LLM regional-guidance pilot, reusing existing screening."""
from __future__ import annotations
import argparse
from copy import deepcopy
import getpass
import json
import os
from pathlib import Path
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
for name in ("OMP_NUM_THREADS","OPENBLAS_NUM_THREADS","MKL_NUM_THREADS"):
    os.environ[name]="1"
os.environ["PYBAMM_DISABLE_TELEMETRY"]="true"

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run, read_json
from llmbo_para.config import load_json
from llmbo_para.initialization import ScreeningBudget
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import prepare_experiment, run_experiment
from run_ablation_suite import screen_family
from resource_snapshot import snapshot


def main(*, mode="informed"):
    parser=argparse.ArgumentParser(description=__doc__ if mode=="informed" else "Four-GP pilot with verified screening history and completion-weighted EI")
    parser.add_argument("config",type=Path)
    parser.add_argument("--initial-plan",type=Path,help="Verified existing screening plan; retain original screening cost")
    parser.add_argument("--initial-source",choices=("llm","random"),default="llm",help="Used only for fresh screening")
    parser.add_argument("--bo-iterations",type=int,default=2)
    parser.add_argument("--max-screening-evaluations",type=int,default=200)
    parser.add_argument("--max-warm-batches",type=int,default=10)
    parser.add_argument("--max-selection-requests",type=int,default=30)
    parser.add_argument("--output",type=Path,default=ROOT/("runs/informed-pilots" if mode=="informed" else "runs/4gp-repair-pilots"))
    parser.add_argument("--prompt-for-key",action="store_true",help="Hidden memory-only input; never put credentials in arguments")
    parser.add_argument("--proxy",help="Optional local HTTP proxy, e.g. http://127.0.0.1:7897")
    args=parser.parse_args()
    if args.bo_iterations < 1:
        parser.error("bo-iterations must be positive")
    template=load_json(args.config)
    if mode=="informed" and (template["optimization"].get("surrogate_mode")!="single_objective" or not template["optimization"].get("llm_informed_enabled")):
        parser.error("configuration must explicitly enable single_objective and llm_informed_enabled")
    if mode=="screening_history" and (not args.initial_plan or template["optimization"].get("surrogate_mode")!="per_rate"
        or not template["optimization"].get("reuse_screening_history") or template["optimization"].get("llm_informed_enabled")
        or not template["optimization"].get("bo_repair",{}).get("feasibility_weighting")):
        parser.error("four-GP repair requires an explicit verified plan, per_rate mode, history reuse and completion weighting")
    if template["data"]["kind"]=="xlsx":
        template["data"]["path"]=str((args.config.resolve().parent/template["data"]["path"]).resolve())
    if args.proxy:
        from urllib.parse import urlsplit
        proxy=urlsplit(args.proxy)
        if proxy.scheme not in {"http","https"} or not proxy.hostname or proxy.username or proxy.password or proxy.query or proxy.fragment:
            parser.error("proxy must be an HTTP(S) URL without inline credentials")
        for name in ("HTTP_PROXY","HTTPS_PROXY","http_proxy","https_proxy"):
            os.environ[name]=args.proxy
    key_env=template["llm"]["api_key_env"]
    supplied_key=False
    if args.prompt_for_key and not os.environ.get(key_env):
        os.environ[key_env]=getpass.getpass("API credential (hidden; process memory only): ")
        supplied_key=True
    session=RunStore(args.output,{"run_kind":"single_gp_informed_pilot" if mode=="informed" else "four_gp_history_completion_pilot","experiment":template,
        "bo_iterations":args.bo_iterations,"initial_plan":str(args.initial_plan.resolve()) if args.initial_plan else None,
        "initial_source_if_fresh":args.initial_source,"proxy":args.proxy,
        "not_a_formal_efficacy_study":True},command=" ".join([sys.executable,*sys.argv]))
    console=(session.path/"console.log").open("x",encoding="utf-8",buffering=1)
    class Tee:
        def __init__(self,stream):self.stream=stream
        def write(self,value):
            self.stream.write(value); console.write(value); return len(value)
        def flush(self):self.stream.flush(); console.flush()
    original_stdout,original_stderr=sys.stdout,sys.stderr
    sys.stdout,sys.stderr=Tee(sys.stdout),Tee(sys.stderr)
    print(json.dumps({"session_directory":str(session.path),"stage":"preflight"}),flush=True)
    try:
        resources=snapshot(); session.write_json("resource-before.json",resources)
        if resources.get("memory_available_bytes",4e9)<2e9 or resources["disk_free_bytes"]<2e9:
            raise RuntimeError("insufficient free memory/disk for bounded serial pilot")
        if args.initial_plan:
            plan_path=args.initial_plan.resolve(); plan=read_json(plan_path)
        else:
            screen=deepcopy(template)
            screen["optimization"]["llm_informed_enabled"]=False
            budget=ScreeningBudget(target=8,max_evaluations=args.max_screening_evaluations,
                max_warm_batches=args.max_warm_batches,max_selection_requests=args.max_selection_requests)
            plan,plan_path=screen_family(screen,args.initial_source,session,args.config.resolve().parent,
                budget=budget,artifact_root=session.path/"initialization")
        if not plan.get("complete") or len(plan["parameters"])!=8:
            raise ValueError("pilot requires a complete eight-point screening plan")
        session.write_json("initialization-provenance.json",{"path":str(plan_path),"sha256":sha256_file(plan_path),
            "reused":bool(args.initial_plan),"source":plan["source"],"attributed_screening_cost":plan["screening_cost"]})
        config=arm_config(template,plan,plan_path,warm_start=plan["source"]=="llm",
            gp_groups=mode=="screening_history" and template["optimization"].get("llm_gp_groups_enabled",False),bo_iterations=args.bo_iterations)
        if mode=="informed":
            config["optimization"].update(llm_enabled=True,llm_informed_enabled=True)
        config["status"]=("single_gp_informed_small_pilot_" if mode=="informed" else "four_gp_history_completion_small_pilot_")+("cached_initialization" if args.initial_plan else "fresh_initialization")
        session.write_json("experiment-config.json",config)
        report,prepared=prepare_experiment(config,base_dir=args.config.resolve().parent)
        session.write_json("preflight.json",report)
        if prepared is None:
            raise ValueError("preflight failed: "+"; ".join(report["errors"]))
        result=run_experiment(config,session.path/"optimization",base_dir=args.config.resolve().parent,
            command=mode+"; eight initial points then "+str(args.bo_iterations)+" BO evaluations")
        audit=audit_run(result["run_directory"],deep=True)
        session.write_json("deep-audit.json",audit)
        if not audit["passed"]:
            raise RuntimeError("deep audit failed; see saved diagnostic")
        session.write_json("resource-after.json",snapshot())
        session.write_json("result.json",result)
        session.finish(result["status"],result)
        print(json.dumps(result,ensure_ascii=False,indent=2),flush=True)
        return 0
    except BaseException as exc:
        # Only sanitized public exception types reach the controller report;
        # transport diagnostics already store redacted provider messages.
        failure={"error_type":type(exc).__name__,"message":str(exc)}
        key=os.environ.get(key_env)
        if key:
            failure["message"]=failure["message"].replace(key,"[REDACTED]")
        session.write_json("failure.json",failure)
        session.finish("interrupted" if isinstance(exc,KeyboardInterrupt) else "failed",failure)
        print(json.dumps({"session_directory":str(session.path),"status":"failed",**failure}),flush=True)
        return 1
    finally:
        sys.stdout,sys.stderr=original_stdout,original_stderr
        console.close()
        if supplied_key:
            os.environ.pop(key_env,None)


if __name__=="__main__":
    raise SystemExit(main())
