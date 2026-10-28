"""Independent curve and cost replay for the paired WarmStart selector study."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import statistics

import analyze_et_three_arm_validation as core


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _metric_space(pair: dict, protocol: dict) -> None:
    if pair.get("metric_space") != {"objective_scales": [0.1, 1.0],
                                    "hv_reference": [10.0, 10.0]}:
        raise ValueError("paired metric space changed")
    for item in protocol["configs"].values():
        config = json.loads(Path(item["path"]).read_text(encoding="utf-8"))
        opt = config["optimization"]
        if opt["objective_scales"] != [0.1, 1.0] or opt["hv_reference"] != [10.0, 10.0]:
            raise ValueError("frozen config metric space changed")


def _plan_evidence(pair: dict, rule: str, manifest: dict) -> dict:
    info = pair["plans"][rule]
    if info != manifest[rule] or _sha(info["path"]) != info["sha256"]:
        raise ValueError("paired plan file hash differs")
    payload = json.loads(Path(info["path"]).read_text(encoding="utf-8"))
    claimed = payload.pop("plan_sha256")
    if claimed != _digest(payload) or claimed != info["plan_sha256"]:
        raise ValueError("paired plan digest differs")
    ids = [row["evaluation_id"] for row in payload["records"]]
    if ids != info["selected_ids"] or len(set(ids)) != 8:
        raise ValueError("paired plan selected IDs differ")
    if payload["history_evidence"]["costs"] != pair["plans"]["shared_costs"]:
        raise ValueError("paired screening cost differs")
    rule_name = "pareto_maximin_v1" if rule == "v1" else "pareto_core_spacefill_v2"
    if payload["history_evidence"]["selection"]["rule"] != rule_name:
        raise ValueError("paired plan rule differs")
    return payload


def _hv(records: list[dict]) -> float:
    for record in records:
        core.verify_objectives(record)
    return core.exact_hv([(row["objectives"][0] / 0.1, row["objectives"][1])
                          for row in core._front(records)])


def analyze_seed(pair: dict, protocol: dict) -> dict:
    """Recompute both objectives and HV from each archived curve, not summaries."""
    from llmbo_para.electrothermal_audit import audit_electrothermal_run

    if pair.get("status") != "completed" or set(pair.get("cases", {})) != {"v1", "v2"}:
        raise ValueError("incomplete paired seed")
    _metric_space(pair, protocol)
    seed = pair["seed"]
    if seed not in protocol["seeds"]:
        raise ValueError("seed outside frozen protocol")
    plans = pair["plans"]
    manifest_path = Path(plans["manifest_path"])
    if _sha(manifest_path) != plans["manifest_sha256"]:
        raise ValueError("pair manifest file hash differs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for path, expected in manifest["source_files"].items():
        if _sha(path) != expected:
            raise ValueError("screening pool source artifact changed")
    if manifest["pool_run"] != pair["pool"]["run_directory"]:
        raise ValueError("paired pool origin differs")
    if (manifest["shared_costs"] != plans["shared_costs"]
            or plans["shared_costs"] != pair["pool"]["costs"]):
        raise ValueError("pool cost attribution differs")
    if (pair["pool"].get("complete_pool_count") != 16
            or audit_electrothermal_run(Path(pair["pool"]["run_directory"]), deep=True).get("passed") is not True):
        raise ValueError("source pool no longer deep-audits")
    pool_records = [json.loads(path.read_text(encoding="utf-8")) for path in
                    sorted((Path(pair["pool"]["run_directory"]) /
                            "electrothermal-evaluations").glob("*.json"))]
    if len(pool_records) != 16:
        raise ValueError("shared screening pool count differs")
    arms = {}
    for rule in ("v1", "v2"):
        plan = _plan_evidence(pair, rule, manifest)
        case = pair["cases"][rule]
        if (case.get("arm") != rule or case.get("seed") != seed
                or case.get("initial_file_sha") != plans[rule]["sha256"]
                or case["summary"].get("API_calls") != 0
                or case.get("parent_initialization_cost") != plans["shared_costs"]
                or case.get("parent_initialization_origin") != pair["pool"]["run_directory"]):
            raise ValueError("formal arm binding or cost differs")
        if audit_electrothermal_run(Path(case["run_directory"]), deep=True).get("passed") is not True:
            raise ValueError("formal arm no longer deep-audits")
        initial = {"audit_passed": True, "ordered_records": plan["records"],
                   "costs": plans["shared_costs"]}
        summary, curve, front = core.analyze_case(case, initial)
        start_hv = _hv(plan["records"])
        hv_values = [start_hv, *(row["HV"] for row in curve)]
        auc = sum((a + b) / 2 for a, b in zip(hv_values, hv_values[1:])) / 50
        arms[rule] = {"final_F_U_V": summary["F_U_V"],
                      "final_F_T_K": summary["F_T_K"],
                      "final_HV": summary["HV"], "initial_HV": start_hv,
                      "HV_AUC": auc, "rounds": curve,
                      "pareto_parameter_set": front,
                      "representative": case["representative"],
                      "screening_DFN_attributed": summary["initial_screening_or_numeric_DFN"],
                      "formal_DFN": summary["main_DFN"],
                      "run_directory": case["run_directory"]}
    if pair["cases"]["v1"]["run_directory"] == pair["cases"]["v2"]["run_directory"]:
        raise ValueError("formal arm stores are shared")
    return {"seed": seed, "status": "completed", "arms": arms,
            "metric_space": pair["metric_space"], "pool_charged_once": True,
            "pool_HV": _hv(pool_records),
            "shared_pool_costs": plans["shared_costs"],
            "delta_final_HV": arms["v2"]["final_HV"] - arms["v1"]["final_HV"],
            "delta_HV_AUC": arms["v2"]["HV_AUC"] - arms["v1"]["HV_AUC"],
            "delta_F_U_V": arms["v2"]["final_F_U_V"] - arms["v1"]["final_F_U_V"],
            "delta_F_T_K": arms["v2"]["final_F_T_K"] - arms["v1"]["final_F_T_K"]}


def analyze_pair(archive: Path, protocol: dict) -> dict:
    """Use complete seed pairs as units; preserve partial trials explicitly."""
    result = json.loads(Path(archive).read_text(encoding="utf-8"))
    rows = [analyze_seed(pair, protocol) for pair in result.get("pairs", [])
            if pair.get("status") == "completed"]
    expected = protocol["seed_run_order"]
    if [row["seed"] for row in rows] != expected or result.get("status") != "completed":
        return {"status": "incomplete", "completed_pairs": len(rows),
                "expected_pairs": len(expected), "seed_results": rows,
                "failure": result.get("error_type"), "costs": result.get("costs")}
    deltas = [row["delta_final_HV"] for row in rows]
    sd = statistics.stdev(deltas)
    mean = statistics.fmean(deltas)
    half = 2.7764451052 * sd / math.sqrt(5)
    return {"status": "completed", "seed_results": rows,
            "primary_delta_final_HV": {"mean": mean, "median": statistics.median(deltas),
                                       "sample_sd": sd,
                                       "positive": sum(value > 0 for value in deltas),
                                       "negative": sum(value < 0 for value in deltas),
                                       "ties": sum(value == 0 for value in deltas),
                                       "descriptive_t_interval": [mean - half, mean + half]},
            "actual_costs": result.get("costs"),
            "claim_limit": "Real DFN synthetic comparison only; no measured fit or universal gain claim"}
