"""Independent curve RMSE/HV and paired-seed analysis; no API or DFN calls."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import statistics


RATES = ("0.5C", "1C")
ARMS = ("bo", "warmstart_only", "full_llmbo_mo")
SCALES = (0.1, 1.0)
REFERENCE = (10.0, 10.0)


def _close(left, right):
    return math.isclose(left, right, rel_tol=1e-10, abs_tol=1e-12)


def _rmse(component, *, error_key, unit):
    if component.get("unit") != unit:
        raise ValueError("archived observation unit differs")
    if component.get("valid") is not True:
        if component.get(error_key) is not None or not component.get("reason"):
            raise ValueError("invalid output has fabricated zero/missing diagnostic")
        return None
    observed, predicted = component.get("observed"), component.get("predicted")
    if (not isinstance(observed, (list, tuple)) or not isinstance(predicted, (list, tuple))
            or len(observed) != len(predicted) or len(observed) < 2):
        raise ValueError("valid output curve shape differs")
    if any(not isinstance(x, (int, float)) or not math.isfinite(x)
           for x in tuple(observed) + tuple(predicted)):
        raise ValueError("nonfinite archived curve")
    value = math.sqrt(math.fsum((a - b) ** 2 for a, b in zip(predicted, observed))
                      / len(observed))
    saved = component.get(error_key)
    if not isinstance(saved, (int, float)) or not _close(value, saved):
        raise ValueError("archived rate RMSE differs from curve")
    return value


def verify_objectives(record, rates=RATES):
    """Recompute two separate equal-rate RMSEs; never create a partial pair."""
    rows = record.get("rates")
    if not isinstance(rows, (list, tuple)) or tuple(row.get("rate") for row in rows) != tuple(rates):
        raise ValueError("archived fitting-rate membership/order differs")
    u, t = [], []
    for row in rows:
        u.append(_rmse(row["voltage"], error_key="rmse_v", unit="V"))
        t.append(_rmse(row["cell_temperature"], error_key="rmse_k", unit="K"))
        if (row["voltage"].get("valid") and row["cell_temperature"].get("valid")
                and not row.get("solution_id")):
            # Synthetic unit fixtures can omit an identity; archived real cases may not.
            if record.get("source_kind") == "fresh_simulation":
                raise ValueError("coupled U/T solution identity missing")
    complete = all(x is not None for x in u + t)
    saved = record.get("objectives")
    if record.get("complete_pair_valid") is not complete or (saved is not None) is not complete:
        raise ValueError("partial objective pair was promoted or complete pair dropped")
    if not complete:
        return None
    mean = (math.fsum(u) / len(u), math.fsum(t) / len(t))
    if (not isinstance(saved, (list, tuple)) or len(saved) != 2
            or any(not isinstance(v, (int, float)) or not _close(v, m)
                   for v, m in zip(saved, mean))):
        raise ValueError("archived aggregate two-objective RMSE differs")
    return mean


def exact_hv(points, reference=REFERENCE):
    """Independent two-dimensional rectangle sweep in fixed metric space."""
    rx, ry = reference
    if not all(math.isfinite(v) and v > 0 for v in (rx, ry)):
        raise ValueError("invalid fixed HV reference")
    accepted = []
    for pair in points:
        if len(pair) != 2 or any(not math.isfinite(v) or v < 0 for v in pair):
            raise ValueError("nonfinite/negative metric objective")
        x, y = pair
        if x < rx and y < ry:
            accepted.append((x, y))
    area, best_y = 0.0, ry
    for x, y in sorted(set(accepted)):
        if y < best_y:
            area += (rx - x) * (best_y - y)
            best_y = y
    return area


def _front(records):
    valid = [row for row in records if row.get("objectives") is not None]
    return [row for row in valid if not any(
        other is not row and all(a <= b for a, b in zip(other["objectives"], row["objectives"]))
        and any(a < b for a, b in zip(other["objectives"], row["objectives"]))
        for other in valid)]


def analyze_case(case, initial):
    if case.get("BO_rounds") != 50 or len(case.get("rounds", [])) != 50:
        raise ValueError("case ended before 50 new BO attempts")
    if case.get("audit_passed") is not True or initial.get("audit_passed") is not True:
        raise ValueError("case or initialization deep audit absent")
    selected = initial["ordered_records"]
    if len(selected) != 8:
        raise ValueError("signed initialization is not eight")
    seen = {}
    for raw in selected:
        verify_objectives(raw)
        seen[raw["evaluation_id"]] = raw
    if len(seen) != 8:
        raise ValueError("initial evaluation IDs duplicate")
    init_cost = initial["costs"]["solver_calls"]
    cumulative_cost = init_cost
    main_cost = 0
    curve = []
    run = Path(case["run_directory"])
    archived = {row["evaluation_id"]: row for row in
                [json.loads(path.read_text(encoding="utf-8"))
                 for path in (run / "electrothermal-evaluations").glob("*.json")]}
    for row in case["rounds"]:
        pair = verify_objectives(row)
        ident = row["evaluation_id"]
        if ident not in archived:
            raise ValueError("round evaluation missing from run archive")
        saved = archived[ident]
        verify_objectives(saved)
        if saved["objectives"] != row["objectives"]:
            raise ValueError("round summary and full curve objectives differ")
        if not row["cached"]:
            spent = saved["costs"]["solver_calls"]
            main_cost += spent
            cumulative_cost += spent
        if pair is not None:
            seen[ident] = saved
        front = _front(list(seen.values()))
        hv = exact_hv([(item["objectives"][0] / SCALES[0],
                        item["objectives"][1] / SCALES[1]) for item in front])
        curve.append({"seed": case["seed"], "arm": case["arm"],
                      "round": row["ordinal"], "candidate_F_U_V": pair[0] if pair else None,
                      "candidate_F_T_K": pair[1] if pair else None,
                      "complete": pair is not None, "HV": hv,
                      "cumulative_DFN_attributed": cumulative_cost,
                      "weight_U": row["weight"][0], "weight_T": row["weight"][1]})
    if main_cost != case["summary"]["costs"]["solver_calls"]:
        raise ValueError("formal solver cost differs from round records")
    if not _close(curve[-1]["HV"], case["HV"]):
        raise ValueError("final fixed-space HV differs")
    front = _front(list(seen.values()))
    by_id = {item["evaluation_id"]: item for item in front}
    claimed = {item["evaluation_id"] for item in case["summary"]["pareto"]}
    if set(by_id) != claimed:
        raise ValueError("final Pareto membership differs")
    representative = case["representative"]
    verify_objectives(representative)
    if (representative["evaluation_id"] not in by_id
            or not _close(case["F_U"], representative["objectives"][0])
            or not _close(case["F_T"], representative["objectives"][1])):
        raise ValueError("reported representative differs from archived Pareto")
    summary = {"seed": case["seed"], "arm": case["arm"],
               "F_U_V": case["F_U"], "F_U_mV": 1000 * case["F_U"],
               "F_T_K": case["F_T"], "HV": case["HV"],
               "min_U_V": min(item["objectives"][0] for item in front),
               "min_T_K": min(item["objectives"][1] for item in front),
               "initial_screening_or_numeric_DFN": init_cost,
               "main_DFN": main_cost,
               "total_attributed_DFN": init_cost + main_cost,
               "initial_API": initial["costs"]["llm_requests"],
               "region_API": case["summary"]["API_calls"],
               "region_diagnostics": case["summary"]["region_diagnostics"],
               "initial_plan_sha256": case["initial_file_sha"],
               "pareto_count": len(front),
               "run_directory": case["run_directory"]}
    return summary, curve, case["summary"]["pareto"]


def analyze(result):
    if result.get("status") != "completed" or len(result.get("cases", [])) != 15:
        return {"status": "incomplete", "completed_cases": len(result.get("cases", [])),
                "costs": result.get("costs"), "reason": result.get("error_type")}
    initial = {row["seed"]: row for row in result["initialization"]}
    if len(initial) != 5:
        raise ValueError("five per-seed initialization pairs required")
    rows, curves, fronts = [], [], {}
    for case in result["cases"]:
        seed, arm = case["seed"], case["arm"]
        source = initial[seed]["bo" if arm == "bo" else "warmstart"]
        summary, curve, pareto = analyze_case(case, source)
        rows.append(summary)
        curves.extend(curve)
        fronts[f"{seed}:{arm}"] = pareto
    lookup = {(row["seed"], row["arm"]): row for row in rows}
    if len(lookup) != 15:
        raise ValueError("duplicate/missing case in five-seed comparison")
    paired = []
    for seed in sorted(initial):
        for treatment, control in (("warmstart_only", "bo"),
                                   ("full_llmbo_mo", "warmstart_only"),
                                   ("full_llmbo_mo", "bo")):
            a, b = lookup[seed, treatment], lookup[seed, control]
            paired.append({"seed": seed, "treatment": treatment, "control": control,
                           "delta_HV": a["HV"] - b["HV"],
                           "delta_F_U_mV": a["F_U_mV"] - b["F_U_mV"],
                           "delta_F_T_K": a["F_T_K"] - b["F_T_K"],
                           "extra_attributed_DFN": a["total_attributed_DFN"] - b["total_attributed_DFN"]})
    aggregate = {}
    for arm in ARMS:
        group = [row for row in rows if row["arm"] == arm]
        aggregate[arm] = {key: {"mean": statistics.fmean(row[key] for row in group),
                                "sample_sd": statistics.stdev(row[key] for row in group)}
                          for key in ("F_U_mV", "F_T_K", "HV", "total_attributed_DFN")}
    return {"status": "completed", "cases": rows, "rounds": curves,
            "paired": paired, "aggregate": aggregate,
            "pareto_parameter_sets": fronts, "actual_costs": result["costs"],
            "claim_limit": "Real DFN synthetic comparison only; no measured fit or parameter identifiability claim"}


def _csv(path, rows):
    if not rows:
        return
    with Path(path).open("x", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_analysis(analysis, out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False,
        allow_nan=False, indent=2), encoding="utf-8")
    if analysis["status"] == "completed":
        _csv(out / "cases.csv", [{k: v for k, v in row.items()
            if k not in ("region_diagnostics",)} for row in analysis["cases"]])
        _csv(out / "rounds.csv", analysis["rounds"])
        _csv(out / "paired.csv", analysis["paired"])
        (out / "pareto-parameter-sets.json").write_text(json.dumps(
            analysis["pareto_parameter_sets"], ensure_ascii=False, indent=2,
            allow_nan=False), encoding="utf-8")
    return out / "analysis.json"


def seal(paths, target):
    """Hash current evidence without modifying a previous archive."""
    files = {}
    target = Path(target)
    for root in paths:
        for path in sorted(Path(root).rglob("*")):
            if path.is_file() and path.resolve() != target.resolve():
                files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    with target.open("x", encoding="utf-8") as stream:
        json.dump({"closed": True, "files": files}, stream, indent=2)
    return len(files)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    analysis = analyze(json.loads(Path(args.result).read_text(encoding="utf-8")))
    path = write_analysis(analysis, args.output)
    print(json.dumps({"status": analysis["status"], "analysis": str(path),
                      "cases": len(analysis.get("cases", [])),
                      "actual_costs": analysis.get("actual_costs", analysis.get("costs"))}))
    return 0 if analysis["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
