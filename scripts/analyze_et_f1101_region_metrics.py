"""Read-only selection and HV improvement metrics from complete f1101 archive."""
import argparse
import json
from pathlib import Path

ARMS = ("A00", "A10", "A01", "A11")
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    x = parser.parse_args()
    src = json.loads(x.source.read_text(encoding="utf-8-sig"))
    seeds = src["seeds"]
    if src["status"] != "completed" or len(seeds) != 5:
        raise RuntimeError("Unexpected source coverage")
    lines = [
        "# Five-seed budget and Region preflight (read-only)",
        "",
        "Source: complete runs/f1101 analysis.json, 5 seeds x 50 BO iterations.",
        "Original HV reference and all historical seed choices are kept.",
        "This is descriptive evidence for a single synthetic 0.5C/1C task.",
        "A positive HV step means end-of-round HV increased by more than 1e-10.",
        "",
        "| Arm | BO rounds | Positive HV rounds | Positive round rate | Avg HV gain per positive round |",
        "|---|---:|---:|---:|---:|",
    ]
    for arm in ARMS:
        steps, positive, gain = 0, 0, 0.
        for s in seeds:
            tr = s["arms"][arm]["trajectory"]
            if len(tr) != 51:
                raise RuntimeError("bad trajectory length")
            seq = [float(v["HV"]) for v in tr]
            positive += sum(v-u > 1e-10 for u,v in zip(seq,seq[1:]))
            steps += len(seq)-1
            gain += seq[-1]-seq[0]
        lines.append(f"| {arm} | {steps} | {positive} | {positive/steps:.1%} | {(gain/positive if positive else 0):.6g} |")
    lines += ["", "## Region decision diagnostics", "",
              "| Arm | LLM Region requests | Replies | Changed selections | Changed / total |",
              "|---|---:|---:|---:|---:|"]
    for arm in ("A01", "A11"):
        diagnostics = [s["arms"][arm]["region_diagnostics"] for s in seeds]
        requests = sum(int(d.get("request_attempts",0)) for d in diagnostics)
        responses = sum(int(d.get("responses",0)) for d in diagnostics)
        changed = sum(int(d.get("selection_changed",0)) for d in diagnostics)
        lines.append(f"| {arm} | {requests} | {responses} | {changed} | {changed/requests:.1%} |")
    lines += ["", "## Limits to interpretation", "",
              "A01 and A11 modify different GP trajectories and use different initialization histories.",
              "A changed selection is not a measured causal gain; frozen-context counterfactual evaluation is required.",
              "HV gain frequency differs from total HV gain magnitude and from HV-AUC.",
              "The full GPIM-style near-best conversion analysis requires a predeclared shared objective-quality threshold and per-candidate accounting.",
              "The original HV reference (10,10) produces saturated values near 100 and reduces discrimination.",
              ""]
    x.output.parent.mkdir(parents=True, exist_ok=True)
    with x.output.open("x",encoding="utf-8") as o:
        o.write("\n".join(lines))
    print(x.output)

if __name__ == "__main__":
    main()
