"""Small paper checkpoints and a separately labelled historical BO continuation.

Uses existing DFN, cache validation, four-GP optimizer, archive and deep audit.
No new LLM calls. Full measured grids and no extrapolation remain mandatory.
"""
from __future__ import annotations
import argparse
import ctypes
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

for variable in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[variable] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
os.environ["MPLBACKEND"] = "Agg"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import numpy as np
import pybamm
from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run, read_json
from llmbo_para.feasibility import simulation_signature
from llmbo_para.initialization import validated_simulation_sources
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.runstore import RunStore, digest_value, sha256_file
from llmbo_para.screening_history import validate_record
from llmbo_para.workflow import prepare_experiment, build_backend, run_fixed_candidates, run_experiment
from resource_snapshot import snapshot
from validate_high_rate_repair import STATE_NAMES

LATEST = ROOT / "runs/4gp-repair-pilots/20261014T031242Z_fb8d62c97102_d9fcceff/optimization/20261014T031254Z_5feb094d6fdd_9f4a8d67"
OLD_PILOT = ROOT / "runs/method-pilots/20261013T141910Z_298bf451e758_9fa0aac0"
OLD_BEST = ROOT / "runs/high-rate-repair-cli/20261013T135909Z_ed9ec91493cd_83f20943"
PAPER = [.705, .664, 4.40e-14, 4.96e-14, 238., .545]


def process_memory():
    """Current/peak working set of this process, never enumerate other apps."""
    from ctypes import wintypes
    class Counters(ctypes.Structure):
        _fields_=[('cb',wintypes.DWORD),('PageFaultCount',wintypes.DWORD)]+[(name,ctypes.c_size_t) for name in (
            'PeakWorkingSetSize','WorkingSetSize','QuotaPeakPagedPoolUsage','QuotaPagedPoolUsage',
            'QuotaPeakNonPagedPoolUsage','QuotaNonPagedPoolUsage','PagefileUsage','PeakPagefileUsage')]
    counters=Counters();counters.cb=ctypes.sizeof(counters)
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.GetCurrentProcess.restype=wintypes.HANDLE
    psapi=ctypes.WinDLL('psapi',use_last_error=True)
    psapi.GetProcessMemoryInfo.argtypes=[wintypes.HANDLE,ctypes.POINTER(Counters),wintypes.DWORD]
    if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(counters),counters.cb):raise ctypes.WinError()
    return {'working_set_bytes':counters.WorkingSetSize,'peak_working_set_bytes':counters.PeakWorkingSetSize}


def residual_summary(record, series):
    rows = []
    for row in record["rates"]:
        source = series[row["rate"]]
        t, measured = np.asarray(source.time_s), np.asarray(source.voltage_v)
        item = {k: row.get(k) for k in ("rate", "valid", "rmse_v", "t_end_s", "t_required_s", "failure_kind", "termination", "solver_error_type")}
        item["shortfall_s"] = max(0., t[-1] - row["t_end_s"]) if row["t_end_s"] is not None else None
        item["measured_final_v"] = float(measured[-1])
        if row["simulation_voltage_v"]:
            item["simulation_final_v"] = row["simulation_voltage_v"][-1]
        if row["valid"]:
            st, sv = np.asarray(row["simulation_time_s"]), np.asarray(row["simulation_voltage_v"])
            assert st[0] <= t[0] and st[-1] >= t[-1]
            voltage = np.interp(t, st, sv)
            error = voltage - measured
            rmse = float(np.sqrt(np.mean(error ** 2)))
            assert abs(rmse - row["rmse_v"]) < 1e-12
            assert np.allclose(voltage, row["aligned_voltage_v"], rtol=0, atol=1e-12)
            tail = t >= .9 * t[-1]
            item.update(rmse_mV=1000*rmse, mae_mV=float(1000*np.mean(np.abs(error))),
                final_error_mV=float(1000*error[-1]),
                early90_rmse_mV=float(1000*np.sqrt(np.mean(error[~tail]**2))),
                tail10_rmse_mV=float(1000*np.sqrt(np.mean(error[tail]**2))),
                tail_sse_fraction=float(np.sum(error[tail]**2)/np.sum(error**2)))
        rows.append(item)
    return {"parameters": record["parameters"], "valid": record["valid"],
            "objective_mV": record["objective_v"]*1000 if record["valid"] else None, "rates": rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bo-iterations", type=int, default=2)
    parser.add_argument("--output", type=Path, default=ROOT/"runs/reference-continuation")
    args = parser.parse_args()
    if not 1 <= args.bo_iterations <= 5:
        parser.error("This bounded pilot supports one to five new BO evaluations")
    config = read_json(ROOT/"configs/21700-4gp-linear-completion.json")
    config["data"]["path"] = str((ROOT/"configs"/config["data"]["path"]).resolve())
    config["optimization"].update(llm_enabled=False, llm_warm_start_enabled=False,
        llm_gp_groups_enabled=False, llm_informed_enabled=False, reuse_screening_history=False)
    protocol = {"purpose": "constraint-valid paper parameter checkpoints, full-tail verification, historical continuation",
        "experiment": config, "paper_project_order": PAPER, "paper_source": "manuscript1.pdf page 7 Table 3, LLMBO-3.5",
        "checkpoint_multipliers": [1., 1.5], "known_best_source": str(OLD_BEST),
        "bo_iterations": args.bo_iterations, "api_calls": 0, "parallel_workers": 1,
        "planned_new_rate_solves": 13+4*args.bo_iterations,
        "not_a_fair_ablation_arm": True, "continuation_semantics": "reuse all compatible observations; refit GP states and restart local neighborhood at known best, not a bitwise process resume"}
    store = RunStore(args.output, protocol, command=subprocess.list2cmdline([sys.executable,*sys.argv]))
    shutil.copy2(__file__, store.path/"controller.py")
    print(json.dumps({"session_directory":str(store.path), "planned_new_rate_solves":protocol["planned_new_rate_solves"]}), flush=True)
    started = time.perf_counter()
    with (store.path/"stdout.log").open("x",encoding="utf-8",buffering=1) as out, (store.path/"stderr.log").open("x",encoding="utf-8",buffering=1) as err:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                resources = snapshot(); store.write_json("resource-before.json",resources)
                # First measure one serial 1C solve; never expand without measured headroom.
                reserve=1024**3
                if resources.get("memory_available_bytes",4e9)<reserve+256*1024**2 or resources["disk_free_bytes"]<2e9:
                    raise RuntimeError("Insufficient free RAM/disk for bounded serial pilot")
                memory_before=process_memory()
                report, prepared = prepare_experiment(config)
                store.write_json("preflight.json",report)
                if prepared is None: raise ValueError(str(report["errors"]))
                prepared.space.validate(PAPER)
                signature = simulation_signature(config,prepared.series)
                latest_series = read_json(LATEST/"input-series.json")
                assert digest_value(latest_series) == digest_value({r:asdict(s) for r,s in prepared.series.items()}), "Input-series content differs"

                # Verify the actual old picture/CSV candidate separately.
                old_run = Path(read_json(OLD_PILOT/"analysis.json")["optimization_directory"])
                old_best = min((read_json(p) for p in sorted((old_run/"attempts").glob("*.json")) if read_json(p)["valid"]),key=lambda r:r["objective_v"])
                for row in old_best["rates"]:
                    csv = np.loadtxt(OLD_PILOT/f"best-{row['rate']}.csv",delimiter=",",skiprows=1)
                    s=prepared.series[row["rate"]]
                    assert np.array_equal(csv[:,0],s.time_s)
                    assert np.allclose(csv[:,1],s.voltage_v,rtol=0,atol=1e-14)
                    assert np.allclose(csv[:,2],row["aligned_voltage_v"],rtol=0,atol=1e-14)
                picture = residual_summary(old_best,prepared.series)
                picture["image_sha256"] = sha256_file(OLD_PILOT/"best-fit.png")
                picture["csv_values_match_original_curves"] = True
                store.write_json("specified-picture-verification.json",picture)

                # A 1C-only probe precedes the four-rate checkpoints.
                original = deepcopy(config); original["model"]["fixed_electrolyte_diffusivity_multiplier"] = 1.
                store.write_json("one-c-probe/config.json",original)
                backend=build_backend(prepare_experiment(original)[1]); backend.save_parameterization(store)
                trace=backend.simulate(dict(zip((s.name for s in prepared.space.specs),PAPER)),prepared.series["1C"])
                t,v = map(np.asarray,trace)
                assert len(t)>1 and np.all(np.isfinite(v)) and np.all(np.diff(t)>0)
                probe={"parameters":PAPER,"rate":"1C","time_s":t,"voltage_v":v,
                    "termination":trace.termination,"required_end_s":prepared.series["1C"].time_s[-1],
                    "full_coverage":bool(t[0]<=0 and t[-1]>=prepared.series["1C"].time_s[-1]),"rmse_v":None}
                if probe["full_coverage"]:
                    probe["rmse_v"]=float(np.sqrt(np.mean((np.interp(prepared.series["1C"].time_s,t,v)-prepared.series["1C"].voltage_v)**2)))
                store.write_json("one-c-probe/result.json",probe)
                store.append_event({"type":"one_c_probe_complete","full_coverage":probe["full_coverage"]})
                memory_after=process_memory();resource_after_probe=snapshot()
                growth=max(0,memory_after['peak_working_set_bytes']-memory_before['peak_working_set_bytes'])
                required=reserve+max(256*1024**2,3*growth)
                memory_gate={'before':memory_before,'after':memory_after,'resources_after_probe':resource_after_probe,
                    'one_c_peak_growth_bytes':growth,'required_free_bytes':required,
                    'policy':'one GiB reserve plus max(256 MiB, three times observed 1C peak growth); serial solves only',
                    'passed':resource_after_probe['memory_available_bytes']>=required}
                store.write_json('one-c-probe/memory-gate.json',memory_gate)
                if not memory_gate['passed']:raise RuntimeError('1C completed; insufficient measured headroom for four-rate cases')

                known = read_json(OLD_BEST/"summary.json")["best_parameters"]
                cases=[("paper-original",PAPER,1.),("paper-calibrated",PAPER,1.5),("known-best-replay",known,1.5)]
                case_runs, case_records, case_summaries = [],{},[]
                solve=pybamm.Simulation.solve
                for name,point,multiplier in cases:
                    current_resource=snapshot();store.write_json(f'resources/{name}-before.json',current_resource)
                    if current_resource['memory_available_bytes']<required:raise RuntimeError('Free-memory reserve fell before '+name)
                    local=deepcopy(config); local["model"]["fixed_electrolyte_diffusivity_multiplier"]=multiplier
                    store.write_json(f"resolved-configs/{name}.json",local)
                    captured=[]
                    def observed_solve(simulation,*pos,**kw):
                        solution=solve(simulation,*pos,**kw)
                        rate=RATE_ORDER[len(captured)]
                        arrays={"time_s":np.asarray(solution["Time [s]"].entries)}; stats={}
                        for variable in STATE_NAMES:
                            values=np.asarray(solution[variable].entries,dtype=float)
                            assert np.all(np.isfinite(values)), variable
                            arrays[variable]=values
                            stats[variable]={"min":float(values.min()),"max":float(values.max()),
                                "final_min":float(values[...,-1].min()),"final_max":float(values[...,-1].max())}
                        folder=store.path/"states";folder.mkdir(exist_ok=True)
                        np.savez_compressed(folder/f"{name}-{rate}.npz",**arrays)
                        captured.append({"rate":rate,"termination":str(solution.termination),"states":stats})
                        return solution
                    with patch.object(pybamm.Simulation,"solve",observed_solve):
                        result=run_fixed_candidates(local,store.path/"checkpoints"/name,[(None,point)],mode="smoke")
                    run=Path(result["run_directory"]); record=read_json(next((run/"attempts").glob("*.json")))
                    if len(captured)!=4:raise RuntimeError("Missing internal-state capture: "+name)
                    if any(q["failure_kind"] not in (None,"voltage_cutoff","coverage_shortfall") for q in record["rates"]):
                        raise RuntimeError("Unexpected solver/data failure in "+name)
                    store.write_json(f"states/{name}.json",captured)
                    case_runs.append(run);case_records[name]=record
                    case_summaries.append({"name":name,"electrolyte_multiplier":multiplier,"run_directory":str(run),**residual_summary(record,prepared.series)})
                    store.append_event({"type":"checkpoint_complete","name":name,"valid":record["valid"],"new_rate_solves":1+4*len(case_runs)})
                store.write_json("checkpoint-comparison.json",case_summaries)
                replay=case_records["known-best-replay"]
                expected=read_json(OLD_BEST/"summary.json")["best_objective_v"]
                if not replay["valid"] or abs(replay["objective_v"]-expected)>1e-8:
                    raise RuntimeError("Known 45.474 mV point did not reproduce; continuation not launched")

                # Collect existing original records through their verified run archives.
                initial_plan=read_json(LATEST/"inputs/initial-plan.json")
                source_runs={Path(initial_plan["screening_directory"]),OLD_BEST,old_run}
                catalog=read_json(LATEST/"screening-history/catalog.json")
                source_runs.update(Path(segment["directory"]) for segment in catalog["segments"])
                for session in sorted((ROOT/"runs/4gp-repair-pilots").iterdir()):
                    source_runs.update(p for p in (session/"optimization").glob("*") if (p/"summary.json").exists())
                source_runs.update(case_runs[1:])
                pool=RunStore(store.path/"historical-pool",{"experiment":config,"purpose":"verified cache aggregation, no simulation"},command="aggregate verified original observations")
                unique={};aliases=[];provenance=[];actual_records=actual_solves=api_calls=0
                elapsed=0.
                expected_fp=digest_value(read_json(case_runs[-1]/"parameterization.json")["values"])
                for run in sorted(source_runs):
                    m=read_json(run/"manifest.json");c=m["config"].get("experiment",m["config"])
                    raw=read_json(run/"input-series.json") if (run/"input-series.json").exists() else latest_series
                    from llmbo_para.evaluation import DischargeSeries
                    ss={r:DischargeSeries(**s) for r,s in raw.items()}
                    if simulation_signature(c,ss)!=signature:raise ValueError("Incompatible historical simulation signature: "+str(run))
                    fingerprints,index_hash=validated_simulation_sources(run)
                    if digest_value(read_json(run/"parameterization.json")["values"])!=expected_fp:
                        raise ValueError("Historical fixed parameterization differs: "+str(run))
                    local_count=0
                    for path in sorted((run/"attempts").glob("*.json")):
                        record=read_json(path)
                        if record.get("cache_provenance"):continue
                        validate_record(record,config,prepared.series)
                        actual_records+=1;actual_solves+=sum(len(q["attempts"]) for q in record["rates"])
                        elapsed+=sum(q["elapsed_s"] for q in record["rates"]);local_count+=1
                        key=tuple(record["parameters"])
                        source={"path":str(path.resolve()),"sha256":sha256_file(path)}
                        if key in unique:
                            first=unique[key][0]
                            if first["valid"]!=record["valid"] or (record["valid"] and abs(first["objective_v"]-record["objective_v"])>1e-8):
                                raise ValueError("Repeated parameters give conflicting results")
                            aliases.append({"retained":unique[key][1],"duplicate":source})
                        else:unique[key]=(record,source)
                    if (run/"events.jsonl").exists():
                        api_calls+=sum(json.loads(line).get("type")=="llm_http_started" for line in (run/"events.jsonl").read_text().splitlines() if line.strip())
                    provenance.append({"run_directory":str(run),"original_records":local_count,"simulation_source_sha256":fingerprints,
                        "source_manifest_sha256":index_hash,"manifest_sha256":sha256_file(run/"manifest.json")})
                # WarmStart generation requests live outside the screening ledger.
                api_calls+=initial_plan["screening_cost"]["api_requests"]
                accepted=[];accepted_sources=[]
                for index,(record,source) in enumerate(unique.values()):
                    copied=pool.save_attempt(index,1,record)
                    if sha256_file(copied)!=source["sha256"]:
                        # JSON formatting may differ; archive source bytes to preserve the original hash.
                        copied.write_bytes(Path(source["path"]).read_bytes())
                    if record["valid"]:
                        accepted.append(record);accepted_sources.append({"path":str(copied),"sha256":sha256_file(copied)})
                failures=len(unique)-len(accepted)
                unique_solves=sum(sum(len(q["attempts"]) for q in r["rates"]) for r,_ in unique.values())
                cost={"source":"history","target":len(accepted),"accepted":len(accepted),"pending":0,
                    "candidate_evaluations":len(unique),"physical_rejections":failures,"analytical_rejections":0,
                    "rate_solve_attempts":unique_solves,"api_requests":api_calls,"elapsed_s":elapsed,
                    "generated_draws":len(unique),"batches":0,"selection_requests":0,"simulation_elapsed_s":elapsed,
                    "cost_semantics":"unique retained observations; actual duplicate solves and original generation costs separately recorded"}
                lineage={"source_runs":provenance,"record_sources":[s for _,s in unique.values()],"deduplicated_aliases":aliases,
                    "actual_original_candidate_evaluations_in_source_runs":actual_records,"actual_rate_solves_in_source_runs":actual_solves,
                    "screening_generation_cost":initial_plan["screening_cost"],"historical_api_requests":api_calls,"new_simulations_for_aggregation":0}
                pool.write_json("pool-lineage.json",lineage)
                plan={"source":"history","parameters":[r["parameters"] for r in accepted],"evaluations":accepted,
                    "evaluation_sources":accepted_sources,"simulation_signature":signature,"parameterization_fingerprint":expected_fp,
                    "screening_directory":str(pool.path),"screening_cost":cost,"prior_candidate_evaluations":0,"complete":True,
                    "continuation_provenance":{"purpose":"historical diagnostic, not ablation","lineage_sha256":sha256_file(pool.path/"pool-lineage.json")}}
                plan_path=pool.write_json("initial-plan.json",plan)
                pool.finish("completed",{"unique_observations":len(unique),"valid":len(accepted),"failed":failures,"new_solves":0})
                continuation=arm_config(config,plan,plan_path,warm_start=False,gp_groups=False,bo_iterations=args.bo_iterations)
                continuation["optimization"]["reuse_screening_history"]=True
                continuation["status"]="historical_data_continuation_four_gp_no_new_llm"
                store.write_json("continuation-config.json",continuation)
                ready,prep=prepare_experiment(continuation);store.write_json("continuation-preflight.json",ready)
                if prep is None:raise ValueError(str(ready["errors"]))
                initial_best=min(r["objective_v"] for r in accepted)
                if initial_best>expected+1e-8:raise RuntimeError("Known incumbent lost from continuation")
                store.append_event({"type":"continuation_started","cached_valid":len(accepted),"failed_history":failures,"initial_best_v":initial_best})
                result=run_experiment(continuation,store.path/"optimization",command="historical continuation, two new BO updates, zero new LLM requests")
                audit=audit_run(result["run_directory"],deep=True);store.write_json("continuation-deep-audit.json",audit)
                if not audit["passed"]:raise RuntimeError("Continuation deep audit failed")
                opt=Path(result["run_directory"]);records=[read_json(p) for p in sorted((opt/"attempts").glob("*.json"))]
                best=min((r for r in records if r["valid"]),key=lambda r:r["objective_v"])
                bo=[r for r in records if not r.get("cache_provenance")]
                diagnostics={"best":residual_summary(best,prepared.series),"new_bo":[residual_summary(r,prepared.series) for r in bo]}
                store.write_json("continuation-diagnostics.json",diagnostics)
                from matplotlib import pyplot as plt
                fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
                for ax,rate in zip(axes.flat,RATE_ORDER):
                    s=prepared.series[rate];ax.plot(s.time_s,s.voltage_v,color="black",label="Measured")
                    for name,record in [("Old pilot 48.060 mV",old_best),("Paper / original electrolyte",case_records["paper-original"]),("Paper / calibrated electrolyte",case_records["paper-calibrated"]),("Continuation best",best)]:
                        row=next(q for q in record["rates"] if q["rate"]==rate)
                        ax.plot(row["simulation_time_s"],row["simulation_voltage_v"],label=name,lw=1.1)
                    ax.set(title=rate,xlabel="Time (s)",ylabel="Voltage (V)");ax.grid(alpha=.2)
                axes[0,0].legend(fontsize=7);fig.savefig(store.path/"fit-comparison.png",dpi=180);fig.savefig(store.path/"fit-comparison.svg");plt.close(fig)
                fig,axes=plt.subplots(2,2,figsize=(11,7),constrained_layout=True)
                for i,rate in enumerate(("0.5C","1C")):
                    s=prepared.series[rate];t=np.asarray(s.time_s);v=np.asarray(s.voltage_v);tail=t>=.9*t[-1]
                    axes[0,i].plot(t[tail],v[tail],color="black",label="Measured")
                    for name,record in [("Old pilot",old_best),("Known 45.474 mV",replay),("Continuation best",best)]:
                        row=next(q for q in record["rates"] if q["rate"]==rate);voltage=np.asarray(row["aligned_voltage_v"])
                        axes[0,i].plot(t[tail],voltage[tail],label=name)
                        axes[1,i].plot(t[tail],1000*(voltage-v)[tail],label=name)
                    axes[0,i].set(title=rate+" final 10% time",ylabel="Voltage (V)")
                    axes[1,i].set(xlabel="Time (s)",ylabel="Simulated minus measured (mV)")
                    axes[1,i].axhline(0,color="black",lw=.7)
                for ax in axes.flat:ax.grid(alpha=.2)
                axes[0,0].legend(fontsize=8);fig.savefig(store.path/"tail-check.png",dpi=180);fig.savefig(store.path/"tail-check.svg");plt.close(fig)
                for row in best["rates"]:
                    s=prepared.series[row["rate"]]
                    np.savetxt(store.path/f"best-{row['rate']}.csv",np.column_stack([s.time_s,s.voltage_v,row["aligned_voltage_v"]]),
                        delimiter=",",header="time_s,measured_voltage_v,simulated_voltage_v",comments="")
                store.write_json("resource-after.json",snapshot())
                elapsed=time.perf_counter()-started
                final={"completed_checkpoints":3,"one_c_probe_completed":1,"new_bo_completed":len(bo),
                    "new_bo_valid":sum(r["valid"] for r in bo),"new_bo_failed":sum(not r["valid"] for r in bo),
                    "new_rate_solves":13+result["rate_solve_attempts"],"api_calls":0,"running":0,"pending":0,
                    "initial_best_mV":initial_best*1000,"best_mV":best["objective_v"]*1000,"improvement_mV":1000*(initial_best-best["objective_v"]),
                    "historical_unique_candidates":len(unique),"historical_actual_rate_solves":actual_solves,
                    "optimization_directory":str(opt),"deep_audit_passed":True,"elapsed_s":elapsed,
                    "new_rate_solves_per_min":(13+result["rate_solve_attempts"])*60/elapsed,"eta_s":0}
                store.write_json("result.json",final);store.finish("completed",final)
            except BaseException as exc:
                failure={"type":type(exc).__name__,"message":str(exc),"traceback":traceback.format_exc(),"elapsed_s":time.perf_counter()-started}
                store.write_json("failure.json",failure);store.finish("failed",failure)
                raise
    print(json.dumps({"session_directory":str(store.path),**final},ensure_ascii=False,indent=2),flush=True)
    return 0


if __name__=="__main__":
    raise SystemExit(main())
