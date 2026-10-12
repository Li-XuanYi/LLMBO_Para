"""Offline archived-label reconstruction and artificial P0 comparison; no DFN/API."""
import os
for _name in ("OPENBLAS_NUM_THREADS","MKL_NUM_THREADS","OMP_NUM_THREADS"):
    os.environ[_name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import time
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
import numpy as np
from llmbo_para.audit import audit_run, read_json
from llmbo_para.bo_repair import CompletionModel
from llmbo_para.config import parameter_space_from_config
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.synthetic import synthetic_config, FeasibilityFixtureSimulator
from llmbo_para.workflow import run_experiment


def archive_diagnostics(directory):
    directory = Path(directory)
    config = read_json(directory/"manifest.json")["config"]
    space = parameter_space_from_config(config)
    files = sorted((directory/"attempts").glob("*.json")); records = [read_json(p) for p in files]
    count = {rate:sum(next(q["valid"] for q in r["rates"] if q["rate"]==rate) for r in records) for rate in RATE_ORDER}
    complete = sum(r["valid"] for r in records)
    feedback, unknown_termination = [], 0
    series = read_json(directory/"input-series.json")
    for i, record in enumerate(records):
        for row in record["rates"]:
            t = row.get("simulation_time_s")
            end = t[-1] if t and t[-1] is not None else None
            required = series[row["rate"]]["time_s"][-1]
            termination = row.get("termination")
            if not row["valid"] and termination is None: unknown_termination += 1
            feedback.append({"record_id":i,"rate":row["rate"],"valid":row["valid"],"t_end_s":end,
                "t_required_s":required,"coverage_margin":end/required-1 if end is not None and required>0 else None,
                "termination":termination,"voltage_cutoff":row.get("voltage_cutoff"),
                "inference_limit":"archived endpoint only; missing events cannot be reconstructed"})
    predictions = []; fallbacks = 0
    # Each prediction uses only the prefix preceding that evaluation (no leakage).
    for i in range(8,len(records)):
        prefix = records[:i]
        classifier = CompletionModel().fit([space.normalize(r["parameters"]) for r in prefix],[r["valid"] for r in prefix])
        predicted = classifier.predict([space.normalize(records[i]["parameters"])])
        if predicted is None:
            fallbacks += 1; continue
        predictions.append({"record_id":i,"p_complete":float(predicted[0]),"label":int(records[i]["valid"]),
            "prefix_success_fraction":sum(r["valid"] for r in prefix)/i})
    return {"run_directory":str(directory.resolve()),"source_record_sha256":{p.name:sha256_file(p) for p in files},
        "complete_gp_counts":{rate:complete for rate in RATE_ORDER},"per_rate_gp_counts":count,
        "additional_real_labels":sum(count.values())-4*complete,"feedback":feedback,
        "failed_rates_without_event_metadata":unknown_termination,
        "prequential": {"predictions":predictions,"fallback_count":fallbacks,
            "model_brier":float(np.mean([(p["p_complete"]-p["label"])**2 for p in predictions])) if predictions else None,
            "prefix_frequency_brier_same_cases":float(np.mean([(p["prefix_success_fraction"]-p["label"])**2 for p in predictions])) if predictions else None,
            "interpretation":"adaptive historical policy, small biased sample; no held-out calibration claim"}}


def artificial_comparison(output, seeds, iterations):
    rows = []
    for seed in seeds:
        config = synthetic_config(8+iterations)
        space = parameter_space_from_config(config)
        config["optimization"].update(seed=seed,sobol_points=8,llm_warm_start_enabled=False,llm_gp_groups_enabled=False)
        rng = np.random.default_rng(np.random.SeedSequence([seed,271]))
        points = [list(space.denormalize(p)) for p in rng.uniform(.45,.55,size=(8,6))]
        plan_path = output/f"artificial-initial-{seed}.json"
        RunStore._create_json(plan_path,{"source":"random","parameters":points,"kind":"artificial_coverage_fixture_only"})
        config["optimization"].update(initial_candidates=points,initial_candidates_source="random",
            initial_candidates_evidence={"path":str(plan_path),"sha256":sha256_file(plan_path)})
        variants = {"A_original":None,"B_local":{"candidate_policy":"local","training_data":"complete"},
            "C_joint":{"feasibility_weighting":True,"training_data":"complete"},
            "D_partial":{"candidate_policy":"local","training_data":"per_rate"}}
        for name, settings in variants.items():
            variant = json.loads(json.dumps(config))
            if settings is not None: variant["optimization"]["bo_repair"] = settings
            result = run_experiment(variant,output/"artificial-arms",simulator=FeasibilityFixtureSimulator(space),command=" ".join(sys.argv)+f" arm={name} seed={seed}")
            row = {"arm":name,"seed":seed,"iterations":iterations,**result}
            rows.append(row)
            print(json.dumps({"finished":len(rows),"total":4*len(seeds),"running":0,"errors":0,"pending":4*len(seeds)-len(rows),
                "arm":name,"seed":seed,"bo_valid":result["bo_candidate_valid"],"initial_J":result["initial_best_objective_v"],"final_J":result["best_objective_v"]}),flush=True)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default=str(ROOT/"bo-repair-work/offline"))
    parser.add_argument("--archive",action="append",default=[])
    parser.add_argument("--seeds",type=int,nargs="+",default=[11,23,37])
    parser.add_argument("--iterations",type=int,default=5)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 5: parser.error("offline small-case validation is limited to 1..5 iterations")
    store = RunStore(args.output,{"kind":"P0_offline_validation","seeds":args.seeds,"iterations":args.iterations,"archives":args.archive},command=" ".join(sys.argv))
    started = time.perf_counter()
    try:
        archives = [archive_diagnostics(p) for p in args.archive]
        store.write_json("archive-diagnostics.json",archives)
        rows = artificial_comparison(store.path,args.seeds,args.iterations)
        result = {"kind":"artificial_and_archived_offline_only","battery_simulations_made":0,"api_requests":0,
            "artificial_runs":rows,"archived_additional_labels":sum(r["additional_real_labels"] for r in archives),
            "elapsed_s":time.perf_counter()-started}
        store.write_json("offline-results.json",result); store.finish("completed",result)
        print(json.dumps({"report_directory":str(store.path),"elapsed_s":result["elapsed_s"]}),flush=True)
    except BaseException as exc:
        import traceback
        diagnostic = {"error":str(exc),"traceback":traceback.format_exc()}
        store.write_json("failure.json",diagnostic); store.finish("failed",diagnostic); raise


if __name__ == "__main__": main()
