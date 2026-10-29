"""Independent curve, Pareto and fixed-space HV replay for the three-rule study."""
from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics

import analyze_et_three_arm_validation as core
from run_et_warmstart_quality_gate_trial import RULES, SEEDS, validate_protocol, verify_trial_failure_policy


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def front(records: list[dict]) -> list[dict]:
    valid = [row for row in records if row.get("objectives") is not None]
    return [row for row in valid if not any(
        other is not row and all(a <= b for a, b in zip(other["objectives"], row["objectives"]))
        and any(a < b for a, b in zip(other["objectives"], row["objectives"]))
        for other in valid)]


def exact_hv(points, reference=(10., 10.)) -> float:
    return core.exact_hv(points, reference=reference)


def representative(rows: list[dict], *, normalize, scales=(.1, 1.)) -> dict:
    def key(row):
        values = tuple(.5 * objective / scale for objective, scale in zip(row["objectives"], scales))
        return (max(values) + .05 * math.fsum(values),
                tuple(normalize(row["parameters"])), row["evaluation_id"])
    return min(rows, key=key)


def _row(record: dict) -> dict:
    return {name: record[name] for name in ("evaluation_id", "parameters", "objectives")}


def verify_archive_ids(records: list[dict], initial_ids: list[str], round_ids: list[str]) -> dict:
    by_id = {record["evaluation_id"]: record for record in records}
    if len(by_id) != len(records) or set(by_id) != set(initial_ids) | set(round_ids):
        raise ValueError("archive contains duplicate, missing or unseen evaluations")
    return by_id


def verify_archive_records(records: list[dict], initial_ids: list[str], rounds: list[dict]) -> dict:
    """Validate ordered saves and collapse only substantiated, identical cache hits."""
    if len(set(initial_ids)) != len(initial_ids) or len(records) != len(initial_ids) + len(rounds):
        raise ValueError("archive record count or initial IDs differ")
    by_id = {}
    for record, expected in zip(records[:len(initial_ids)], initial_ids):
        if record.get("evaluation_id") != expected:
            raise ValueError("initial archive order differs")
        by_id[expected] = record
    for record, event in zip(records[len(initial_ids):], rounds):
        ident, cached = event.get("evaluation_id"), event.get("cached")
        if type(cached) is not bool or record.get("evaluation_id") != ident:
            raise ValueError("round archive identity or cache flag differs")
        if cached:
            if ident not in by_id or record.get("source_kind") != "validated_cache":
                raise ValueError("cache hit lacks a prior true evaluation")
            original = by_id[ident]
            if _digest({k: v for k, v in record.items() if k != "source_kind"}) != _digest(
                    {k: v for k, v in original.items() if k != "source_kind"}):
                raise ValueError("cached evaluation differs from its source")
        else:
            if ident in by_id or record.get("source_kind") != "fresh_simulation":
                raise ValueError("unclaimed duplicate or nonfresh evaluation")
            by_id[ident] = record
    return by_id


def _hv(records: list[dict]) -> float:
    for record in records:
        core.verify_objectives(record)
    return exact_hv([(row["objectives"][0] / .1, row["objectives"][1])
                     for row in front(records)])


def _plan(pair: dict, arm: str, manifest: dict) -> dict:
    info = pair["plans"][arm]
    if info != manifest[arm] or _sha(info["path"]) != info["sha256"]:
        raise ValueError("plan file hash differs")
    payload = json.loads(Path(info["path"]).read_text(encoding="utf-8"))
    claimed = payload.pop("plan_sha256")
    if claimed != _digest(payload) or claimed != info["plan_sha256"]:
        raise ValueError("plan digest differs")
    ids = [row["evaluation_id"] for row in payload["records"]]
    if (len(ids) != 8 or len(set(ids)) != 8 or ids != info["selected_ids"]
            or payload["history_evidence"]["selection"]["rule"] != RULES[arm]
            or payload["history_evidence"]["costs"] != pair["plans"]["shared_costs"]):
        raise ValueError("plan selection, rule or shared cost differs")
    return payload


def analyze_seed(pair: dict, protocol: dict) -> dict:
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_audit import audit_electrothermal_run

    validate_protocol(protocol)
    seed = pair["seed"]
    if (pair.get("status") != "completed" or seed not in SEEDS
            or set(pair.get("cases", {})) != set(RULES)
            or pair.get("metric_space") != protocol["metric_space"]):
        raise ValueError("incomplete seed or changed metric space")
    manifest_path = Path(pair["plans"]["manifest_path"])
    if _sha(manifest_path) != pair["plans"]["manifest_sha256"]:
        raise ValueError("plan manifest hash differs")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for path, expected in manifest["source_files"].items():
        if _sha(path) != expected:
            raise ValueError("screening pool source artifact changed")
    if (manifest["pool_run"] != pair["pool"]["run_directory"]
            or manifest["shared_costs"] != pair["plans"]["shared_costs"]
            or pair["plans"]["shared_costs"] != pair["pool"]["costs"]
            or pair["pool"].get("complete_pool_count") != 16
            or audit_electrothermal_run(Path(pair["pool"]["run_directory"]), deep=True).get("passed") is not True):
        raise ValueError("screening pool, audit or cost differs")
    verify_trial_failure_policy(pair["pool"]["run_directory"])
    pool = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(
        (Path(pair["pool"]["run_directory"]) / "electrothermal-evaluations").glob("*.json"))]
    if len(pool) != 16:
        raise ValueError("screening pool count differs")
    config_path = Path(protocol["configs"][str(seed)]["path"])
    space = parameter_space_from_config(json.loads(config_path.read_text(encoding="utf-8")))
    arms = {}
    for arm in RULES:
        plan = _plan(pair, arm, manifest)
        case = pair["cases"][arm]
        if (case.get("arm") != arm or case.get("seed") != seed
                or case.get("initial_file_sha") != pair["plans"][arm]["sha256"]
                or case["summary"].get("API_calls") != 0
                or case.get("parent_initialization_cost") != pair["plans"]["shared_costs"]
                or case.get("parent_initialization_origin") != pair["pool"]["run_directory"]
                or audit_electrothermal_run(Path(case["run_directory"]), deep=True).get("passed") is not True):
            raise ValueError("formal arm binding, audit or cost differs")
        verify_trial_failure_policy(case["run_directory"])
        initial = {"audit_passed": True, "ordered_records": plan["records"],
                   "costs": pair["plans"]["shared_costs"]}
        summary, curve, _ = core.analyze_case(case, initial)
        records = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(
            (Path(case["run_directory"]) / "electrothermal-evaluations").glob("*.json"))]
        by_id = verify_archive_records(records, [r["evaluation_id"] for r in plan["records"]],
                                      case["rounds"])
        for record in records:
            core.verify_objectives(record)
        for initial_record in plan["records"]:
            saved = by_id.get(initial_record["evaluation_id"])
            if saved is None or _digest({k: saved[k] for k in ("parameters", "rates", "objectives")}) != _digest(
                    {k: initial_record[k] for k in ("parameters", "rates", "objectives")}):
                raise ValueError("initial archived curves differ from signed plan")
        independent_front = front(list(by_id.values()))
        rows = [_row(record) for record in independent_front]
        if _digest({row["evaluation_id"]: row for row in rows}) != _digest({
                row["evaluation_id"]: row for row in case["summary"]["pareto"]}):
            raise ValueError("full Pareto parameter rows differ")
        chosen = representative(independent_front, normalize=space.normalize)
        if (_digest(_row(chosen)) != _digest(_row(case["representative"]))
                or _digest(chosen["objectives"]) != _digest([case["F_U"], case["F_T"]])):
            raise ValueError("symmetric representative differs")
        initial_hv = _hv(plan["records"])
        trajectory = [initial_hv, *(row["HV"] for row in curve)]
        auc = math.fsum((a + b) / 2 for a, b in zip(trajectory, trajectory[1:])) / 50
        normalized = [space.normalize(row["parameters"]) for row in plan["records"]]
        distance = math.fsum(math.dist(a, b) / math.sqrt(6)
                             for a, b in itertools.combinations(normalized, 2)) / 28
        qualities = []
        for record in plan["records"]:
            values = (.5 * record["objectives"][0] / .1, .5 * record["objectives"][1])
            qualities.append(max(values) + .05 * math.fsum(values))
        arms[arm] = {"final_F_U_V": summary["F_U_V"], "final_F_T_K": summary["F_T_K"],
                     "final_HV": summary["HV"], "initial_HV": initial_hv, "HV_AUC": auc,
                     "initial_mean_pairwise_distance": distance,
                     "initial_mean_quality": statistics.fmean(qualities), "rounds": curve,
                     "pareto_parameter_set": rows, "representative": _row(chosen),
                     "screening_DFN_attributed": summary["initial_screening_or_numeric_DFN"],
                     "formal_DFN": summary["main_DFN"], "run_directory": case["run_directory"]}
    if len({arms[arm]["run_directory"] for arm in RULES}) != 3:
        raise ValueError("formal run stores are shared")
    weights = [[(row["weight_U"], row["weight_T"]) for row in arms[arm]["rounds"]] for arm in RULES]
    if weights[0] != weights[1] or weights[1] != weights[2]:
        raise ValueError("paired weight schedules differ")
    return {"seed": seed, "status": "completed", "arms": arms,
            "pool_HV": _hv(pool), "shared_pool_costs": pair["plans"]["shared_costs"],
            "delta_final_HV_v3_v2": arms["v3"]["final_HV"] - arms["v2"]["final_HV"],
            "delta_final_HV_v3_v1": arms["v3"]["final_HV"] - arms["v1"]["final_HV"],
            "delta_HV_AUC_v3_v2": arms["v3"]["HV_AUC"] - arms["v2"]["HV_AUC"],
            "delta_HV_AUC_v3_v1": arms["v3"]["HV_AUC"] - arms["v1"]["HV_AUC"],
            "delta_F_U_V_v3_v2": arms["v3"]["final_F_U_V"] - arms["v2"]["final_F_U_V"],
            "delta_F_T_K_v3_v2": arms["v3"]["final_F_T_K"] - arms["v2"]["final_F_T_K"]}


def _summary(values: list[float]) -> dict:
    mean, sd = statistics.fmean(values), statistics.stdev(values)
    half = 2.7764451052 * sd / math.sqrt(5)
    return {"mean": mean, "median": statistics.median(values), "sample_sd": sd,
            "positive": sum(value > 0 for value in values),
            "negative": sum(value < 0 for value in values),
            "ties": sum(value == 0 for value in values),
            "descriptive_t_interval": [mean - half, mean + half]}


def analyze_trial(archive: Path, protocol: dict) -> dict:
    validate_protocol(protocol)
    result = json.loads(Path(archive).read_text(encoding="utf-8"))
    rows = [analyze_seed(pair, protocol) for pair in result.get("pairs", [])
            if pair.get("status") == "completed"]
    if result.get("status") != "completed" or [row["seed"] for row in rows] != list(SEEDS):
        return {"status": "incomplete", "completed_pairs": len(rows), "expected_pairs": 5,
                "seed_results": rows, "failure": result.get("error_type"), "costs": result.get("costs")}
    expected_costs = {
        "DFN": sum(row["shared_pool_costs"]["solver_calls"] +
                   sum(row["arms"][arm]["formal_DFN"] for arm in RULES) for row in rows),
        "API": sum(row["shared_pool_costs"]["llm_requests"] for row in rows),
    }
    if result.get("costs") != expected_costs:
        raise ValueError("parent budget differs from pool and formal charges")
    return {"status": "completed", "seed_results": rows,
            "primary_v3_minus_v2_final_HV": _summary([row["delta_final_HV_v3_v2"] for row in rows]),
            "benchmark_v3_minus_v1_final_HV": _summary([row["delta_final_HV_v3_v1"] for row in rows]),
            "actual_costs": result.get("costs"),
            "claim_limit": "Real DFN synthetic comparison only; no measured fit or universal gain claim"}
