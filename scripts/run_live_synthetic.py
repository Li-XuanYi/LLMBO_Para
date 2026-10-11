"""Two real LLM tasks plus a tiny synthetic optimization; never real battery data."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import time

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(name, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))

from llmbo_para.audit import audit_run
from llmbo_para.config import load_json
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.runstore import RunStore
from llmbo_para.workflow import ExperimentFailure, run_experiment, run_status


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("config", type=Path)
    parser.add_argument("--output", type=Path, default=Path("runs/live-api-sessions"))
    args = parser.parse_args()
    config = load_json(args.config)
    if config.get("run_kind") != "synthetic_software_smoke_only":
        parser.error("this small live-API acceptance runner permits synthetic data only")
    options = config["optimization"]
    if (options["total_candidate_budget"] > 10 or not options["llm_enabled"] or
        options["warm_start_llm_points"] < 1 or options["parallel_workers"] != 1):
        parser.error("live smoke requires 1-10 candidates, LLM warm start and one worker")
    session = RunStore(args.output, {"run_kind": "live_llm_synthetic_acceptance", "experiment": config,
                                     "maximum_llm_requests": 2, "real_battery_data": False},
                       command="python " + str(Path(__file__).resolve()) + " " + " ".join(sys.argv[1:]))
    session.write_json("experiment-config.json", config)
    print(json.dumps({"session_directory": str(session.path), "state": "awaiting_transient_credential"}), flush=True)
    env_name = config["llm"]["api_key_env"]
    old_value = os.environ.get(env_name)
    key = old_value or getpass.getpass("Temporary API credential (hidden): ")
    if not key or any(char.isspace() for char in key):
        session.finish("preflight_failed", {"reason": "missing or malformed transient credential"})
        return 2
    os.environ[env_name] = key
    started = time.perf_counter()
    try:
        result = run_experiment(config, session.path/"optimization", base_dir=args.config.resolve().parent,
                                command="scripts/run_live_synthetic.py " + str(args.config.resolve()))
        path = Path(result["run_directory"])
        http_responses = sorted((path/"http").glob("*.response.json"))
        errors = list((path/"http").glob("*.error.json")) + list((path/"llm").glob("*.error.json"))
        tasks = ("warm_start", "rate_parameter_groups")
        envelopes = {task: json.loads((path/f"http/{task}.response.json").read_text(encoding="utf-8"))
                     for task in tasks if (path/f"http/{task}.response.json").exists()}
        actual_content_matches = all(
            json.loads(envelopes[task]["choices"][0]["message"]["content"]) ==
            json.loads((path/f"llm/{task}.response.json").read_text(encoding="utf-8")) for task in envelopes)
        sources = json.loads((path/"initial-set.json").read_text(encoding="utf-8"))["sources"]
        accepted = json.loads((path/"llm/warm_start.accepted.json").read_text(encoding="utf-8")) if (path/"llm/warm_start.accepted.json").exists() else {"parameters":[]}
        grouping_file = path/"llm/rate_parameter_groups.accepted.json"
        groups = json.loads(grouping_file.read_text(encoding="utf-8")) if grouping_file.exists() else {}
        validation_file = path/"llm/rate_parameter_groups.validation.json"
        group_validation = json.loads(validation_file.read_text(encoding="utf-8")) if validation_file.exists() else {}
        audit = audit_run(path, deep=True)
        passed = (result["candidate_failed"] == 0 and len(envelopes) == len(http_responses) == 2 and not errors and
                  actual_content_matches and len(accepted["parameters"]) == options["warm_start_llm_points"] and
                  sources.count("llm") == options["warm_start_llm_points"] and set(groups) == set(RATE_ORDER) and
                  group_validation.get("valid_response") is True and audit["passed"])
        report = {"passed": passed, "run_directory": str(path), "status": run_status(path),
                  "http_requests_expected": 2, "http_generation_responses": len(http_responses),
                  "llm_errors": [str(file.relative_to(path)) for file in errors],
                  "accepted_llm_warm_points": len(accepted["parameters"]), "initial_sources": sources,
                  "parameter_groups": groups, "real_response_matches_client_record": actual_content_matches,
                  "parameter_group_validation": group_validation,
                  "requested_model": config["llm"]["model"], "reported_models": {task: value.get("model") for task,value in envelopes.items()},
                  "usage_by_task": {task: value.get("usage") for task,value in envelopes.items()},
                  "elapsed_s_including_archival_and_audit": time.perf_counter()-started,
                  "result_audit": audit, "real_battery_solves": 0, "raw_experimental_data_sent": False,
                  "model_identity_note": "Reported model IDs are the service's self-reported labels; preserve alias differences for later scientific runs."}
        session.write_json("live-validation.json", report)
        session.finish("completed" if passed else "failed", report)
        print(json.dumps({"session_directory": str(session.path), **report}, indent=2), flush=True)
        return 0 if passed else 1
    except Exception as exc:
        failure = {"error_type": type(exc).__name__, "message": str(exc).replace(key, "[REDACTED]")}
        if isinstance(exc, ExperimentFailure):
            failure.update(run_directory=exc.run_directory, execution_status=exc.status)
        session.write_json("failure.json", failure)
        session.finish("failed", failure)
        print(json.dumps({"session_directory": str(session.path), **failure}, indent=2), flush=True)
        return 2
    finally:
        if old_value is None:
            os.environ.pop(env_name, None)
        else:
            os.environ[env_name] = old_value


if __name__ == "__main__":
    raise SystemExit(main())
