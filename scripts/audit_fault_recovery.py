"""Durable synthetic proof of four-rate smoke, diagnosed failure and new-run repair."""

from __future__ import annotations

import argparse
from pathlib import Path
import os
import json

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(name, "1")

from llmbo_para.audit import audit_run
from llmbo_para.config import parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator
from llmbo_para.recovery import retry_failed
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.synthetic import synthetic_config, SyntheticSimulator
from llmbo_para.workflow import run_experiment, run_fixed_candidates, run_status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("runs/fault-recovery-audits"))
    args = parser.parse_args()
    config = synthetic_config(5)
    config["optimization"].update(candidate_pool_size=8, composite_ei_draws=8, gp_sweeps=1)
    space = parameter_space_from_config(config)
    good = SyntheticSimulator(space)
    proof = RunStore(args.output, {"run_kind": "synthetic_fault_recovery_proof", "experiment": config},
                     command=f"python {Path(__file__).resolve()} --output {args.output.resolve()}")
    state = {"injected": False}

    def fail_first_solve(parameters, series):
        if not state["injected"]:
            state["injected"] = True
            raise ValueError("deliberately injected first solve failure; synthetic audit fixture")
        return good.simulate(parameters, series)

    try:
        smoke = run_fixed_candidates(config, proof.path / "smoke", [(None, space.denormalize((0.5,) * 6))], mode="smoke")
        original = run_experiment(config, proof.path / "failure", simulator=CallableSimulator(fail_first_solve),
                                  command="scripts/audit_fault_recovery.py: synthetic first-solve fault injection")
        source = Path(original["run_directory"])
        before = {str(p.relative_to(source)): sha256_file(p) for p in source.rglob("*") if p.is_file()}
        proof.write_json("source-before-sha256.json", before)
        recovery = retry_failed(source, proof.path / "recovery", simulator=good)
        after = {str(p.relative_to(source)): sha256_file(p) for p in source.rglob("*") if p.is_file()}
        proof.write_json("source-after-sha256.json", after)
        statuses = {name: run_status(row["run_directory"]) for name, row in
                    (("smoke", smoke), ("injected_failure", original), ("recovery", recovery))}
        audits = {name: audit_run(row["run_directory"], deep=True) for name, row in
                  (("smoke", smoke), ("injected_failure", original), ("recovery", recovery))}
        passed = (smoke["rate_solve_attempts"] == 4 and original["candidate_failed"] == 1 and
                  recovery["candidate_valid"] == 1 and recovery["candidate_failed"] == 0 and
                  before == after and all(row["passed"] for row in audits.values()))
        result = {"passed": passed, "source_files_unchanged": before == after,
                  "original_source_files_checked": len(before), "statuses": statuses, "audits": audits,
                  "real_battery_solves": 0, "paid_api_calls": 0,
                  "note": "The original failure remains in its immutable history; recovery is a separately linked successful run."}
        proof.write_json("proof.json", result)
        proof.finish("completed" if passed else "failed", result)
        print(json.dumps({"proof_directory": str(proof.path), **result}, indent=2))
        return 0 if passed else 1
    except Exception as exc:
        import traceback
        diagnostic = {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        proof.write_json("failure.json", diagnostic)
        proof.finish("failed", diagnostic)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
