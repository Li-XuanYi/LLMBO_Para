"""Read-only post-analysis of runs/f1101. Never invokes DFN or an LLM API."""
import argparse
import csv
import json
import math
import statistics as st
from pathlib import Path

ARMS = ("A00", "A10", "A01", "A11")
NAMES = ("eps_s_n", "eps_s_p", "D_s_n_ref", "D_s_p_ref", "C_th", "G_th")
CONTRASTS = (("A10", "A00"), ("A01", "A00"), ("A11", "A10"), ("A11", "A01"), ("A11", "A00"))

def avg(rows, key):
    return st.mean(r[key] for r in rows)

def write_csv(path, rows):
    with path.open("x", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    opts = parser.parse_args()
    study = opts.study.resolve()
    source = json.loads((study / "analysis.json").read_text(encoding="utf-8-sig"))
    cfg = json.loads((study / "template.json").read_text(encoding="utf-8-sig"))
    if source.get("status") != "completed":
        raise RuntimeError("archived source run incomplete")
    known = [tuple(v["voltage"]["provenance"]["known_parameters"]) for v in cfg["data"]["by_rate"].values()]
    if len(set(known)) != 1 or len(known[0]) != 6:
        raise RuntimeError("synthetic truth inconsistent")
    truth = known[0]
    rows, paired = [], []
    for run in source["seeds"]:
        by_arm = {}
        for arm in ARMS:
            trajectory = run["arms"][arm]["trajectory"]
            if [x["round"] for x in trajectory] != list(range(51)):
                raise RuntimeError(f"incomplete trace: {run['seed']}, {arm}")
            last = trajectory[-1]
            hv = [float(x["HV"]) for x in trajectory]
            estimate = last["representative_parameters"]
            if len(estimate) != 6:
                raise RuntimeError("parameter shape error")
            record = {"seed": run["seed"], "arm": arm,
                      "HV": float(last["HV"]),
                      "HV_AUC": (sum(hv[1:-1]) + (hv[0] + hv[-1]) / 2) / 50,
                      "F_U_mV": float(last["F_U_V"]) * 1000,
                      "F_T_K": float(last["F_T_K"]),
                      "HV_improvement_rounds": sum(y - x > 1e-10 for x, y in zip(hv, hv[1:]))}
            for i, name in enumerate(NAMES):
                record[name + "_estimate"] = estimate[i]
                if i in (2, 3):
                    record[name + "_absolute_log10_error"] = abs(math.log10(estimate[i] / truth[i]))
                else:
                    record[name + "_absolute_pct_error"] = abs(estimate[i] / truth[i] - 1) * 100
            rows.append(record)
            by_arm[arm] = record
        for a, b in CONTRASTS:
            paired.append({"seed": run["seed"], "comparison": a + "-" + b,
                           **{"delta_" + key: by_arm[a][key] - by_arm[b][key]
                              for key in ("HV", "HV_AUC", "F_U_mV", "F_T_K")}})
    out = opts.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    write_csv(out / "parameter_recovery.csv", rows)
    write_csv(out / "paired_effects.csv", paired)
    fields = ("HV", "HV_AUC", "F_U_mV", "F_T_K",
              "D_s_n_ref_absolute_log10_error", "D_s_p_ref_absolute_log10_error",
              "C_th_absolute_pct_error", "G_th_absolute_pct_error")
    report = {"source": str(study), "seed_count": len(source["seeds"]),
              "truth": dict(zip(NAMES, truth)), "costs": source.get("counts"),
              "arm_means": {}, "paired_means": {}}
    for arm in ARMS:
        subset = [x for x in rows if x["arm"] == arm]
        report["arm_means"][arm] = {k: avg(subset, k) for k in fields}
    for a, b in CONTRASTS:
        name = a + "-" + b
        subset = [x for x in paired if x["comparison"] == name]
        report["paired_means"][name] = {
            "delta_HV": avg(subset, "delta_HV"),
            "delta_HV_AUC": avg(subset, "delta_HV_AUC"),
            "HV_positive_seeds": sum(x["delta_HV"] > 0 for x in subset)}
    (out / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    md = [
        "# Original five-seed factorial study: reproducible evidence audit",
        "",
        "Source: runs/f1101, 5 algorithmic seeds, four arms, 50 BO rounds.",
        "Synthetic truth parsed from archived data provenance; no solver/API calls.",
        "Each rate (0.5C, 1C) includes short 60 s synthetic DFN response.",
        "Errors are based on the final symmetric Pareto representative.",
        "The original HV reference (10, 10) is retained for comparisons.",
        "The five runs share the same synthetic task; they quantify optimizer randomness.",
        "This is historical exploratory evidence, not an independent prospective test.",
        "",
        "| Arm | Final HV | HV-AUC | Voltage mV | Temperature K | D_n log10 err | D_p log10 err | C_th % err | G_th % err |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|"
    ]
    for arm in ARMS:
        val = report["arm_means"][arm]
        md.append("| " + arm + " | " + " | ".join(f"{val[k]:.6g}" for k in fields) + " |")
    md += ["", "## Paired effects", "",
           "Positive HV differences indicate improvement; negative error differences indicate reduced fit error.",
           "", "| Contrast | Delta HV | Delta HV-AUC | Seeds with positive delta HV |",
           "|---|---:|---:|---:|"]
    for key, v in report["paired_means"].items():
        md.append(f"| {key} | {v['delta_HV']:.6g} | {v['delta_HV_AUC']:.6g} | {v['HV_positive_seeds']}/5 |")
    md += ["", "## Limitations", "",
           "A small parameter-fit error cannot establish parameter identifiability.",
           "The synthetic truth could produce multiple parameter solutions with similar output responses.",
           "The historic large HV reference affects discriminative power; freeze a physically grounded metric for new studies.",
           "Do not pool post hoc filtered studies as independent trials.", ""]
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")
    print("written", out)
    print("seeds", len(source["seeds"]), "arms", len(rows), "paired", len(paired))

if __name__ == "__main__":
    main()
