"""Run an explicit small measured-data pilot with a transient API credential."""
from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import sys

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "src"))

from llmbo_para.audit import audit_run
from llmbo_para.config import load_json
from llmbo_para.runstore import RunStore
from llmbo_para.workflow import ExperimentFailure, prepare_experiment, run_experiment, run_status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    config = load_json(args.config)
    options = config["optimization"]
    if config["run_kind"] != "research" or options["total_candidate_budget"] > 10 or not options["llm_enabled"]:
        parser.error("requires an explicit research configuration, LLM enabled and at most ten candidates")
    session = RunStore(workspace / "runs/measured-pilot-sessions", {"experiment": config,
        "maximum_llm_requests": 2, "raw_voltage_sent_to_llm": False},
        command="scripts/run_measured_pilot.py " + str(args.config.resolve()))
    session.write_json("experiment-config.json", config)
    preflight, prepared = prepare_experiment(config, base_dir=args.config.resolve().parent)
    session.write_json("preflight.json", preflight)
    print(json.dumps({"session_directory": str(session.path), "ready": prepared is not None}), flush=True)
    if prepared is None and preflight["errors"] != ["the named LLM credential environment variable is not set"]:
        session.finish("preflight_failed", preflight)
        return 2
    env_name = config["llm"]["api_key_env"]
    old_value = os.environ.get(env_name)
    key = old_value or getpass.getpass("Temporary API credential (hidden): ")
    if not key or any(char.isspace() for char in key):
        session.finish("preflight_failed", {"reason": "missing or malformed transient credential"})
        return 2
    os.environ[env_name] = key
    try:
        credential_preflight, prepared = prepare_experiment(config, base_dir=args.config.resolve().parent)
        session.write_json("credential-preflight.json", credential_preflight)
        if prepared is None:
            session.finish("preflight_failed", credential_preflight)
            return 2
        result = run_experiment(config, workspace / "runs/measured-pilots", base_dir=args.config.resolve().parent,
                                command="scripts/run_measured_pilot.py " + str(args.config.resolve()))
        path = Path(result["run_directory"])
        audit = audit_run(path, deep=True)
        report = {"result": result, "status": run_status(path), "deep_audit": audit,
            "http_responses": [str(file.relative_to(path)) for file in (path / "http").glob("*.response.json")],
            "http_errors": [str(file.relative_to(path)) for file in (path / "http").glob("*.error.json")]}
        session.write_json("pilot-validation.json", report)
        session.finish("completed" if audit["passed"] else "failed", report)
        print(json.dumps({"session_directory": str(session.path), **report}, indent=2), flush=True)
        return 0 if audit["passed"] else 1
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
