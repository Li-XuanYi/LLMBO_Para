"""Recount the current local validation and save immutable evidence, without API."""
import json
from pathlib import Path
import re
import sys

workspace = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(workspace / "src"))
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.workflow import run_status


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    parent = workspace / "runs/measured-identification/20261011T034241Z_ae3b9f8abb98_bb29a09f"
    calibration = workspace / "runs/electrolyte-calibration/20261011T040957Z_eda2c6f1a4de_fded22c5"
    figures = workspace / "runs/calibration-figures/20261011T041642Z_205652fd9502_4e25439f"
    pilot = workspace / "runs/measured-pilots/20261011T041240Z_1e15119cefd1_9df156d4"
    stage = RunStore(workspace / "runs/local-calibration-audits", {"run_kind": "local_calibration_audit_only",
        "reference_session": str(parent), "calibration": str(calibration), "failed_pilot": str(pilot),
        "whole_real_llmbo_complete": False, "pending": "explicit external disclosure approval"},
        command="scripts/finalize_calibration_audit.py")
    summaries = [read(parent / name) for name in ("smoke-result.json", "finer-solver-result.json",
        "idaklu-smoke-result.json", "transport-smoke-result.json", "maximum-transport-result.json")]
    summaries.extend(read(calibration / "calibration-summary.json")["cases"])
    paths = [Path(item["run_directory"]) for item in summaries] + [pilot]
    rows = []
    for path in paths:
        attempts = [read(file) for file in sorted((path / "attempts").glob("*.json"))]
        rows.append({"run_directory": str(path), "candidates": len(attempts),
            "valid_candidates": sum(item["valid"] for item in attempts),
            "rate_calls": sum(len(rate["attempts"]) for item in attempts for rate in item["rates"]),
            "valid_rate_results": sum(rate["valid"] for item in attempts for rate in item["rates"]),
            "status": run_status(path)})
    failed_pilot = []
    for file in sorted((pilot / "attempts").glob("*.json")):
        record = read(file)
        failed_pilot.append({"parameters": record["parameters"], "valid": record["valid"],
            "rates": [{"rate": rate["rate"], "valid": rate["valid"], "reason": rate["reason"],
                "time_end_s": (rate["simulation_time_s"] or [None])[-1],
                "measured_time_end_s": read(pilot / "input-series.json")[rate["rate"]]["time_s"][-1]}
                for rate in record["rates"]]})
    stage.write_json("failed-pilot-diagnosis.json", {"candidate_records": failed_pilot,
        "http_error": read(pilot / "http/warm_start.error.json"), "initial_set": read(pilot / "initial-set.json")})
    verified = {"workbook": {"path": str(workspace / "data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx"),
        "expected": "6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7"},
        "reference_notebook": {"path": str(workspace / "Reference/LLAMBO-master/P2D.ipynb"),
        "expected": "eeaa2f26cb8ab044756b4916ac390d97d519ff26f05f2bdf97726dd7160a6ec5"}}
    for value in verified.values():
        value["actual"] = sha256_file(value["path"])
        value["unchanged"] = value["actual"] == value["expected"]
    privacy_roots = [workspace / name for name in ("src", "configs", "scripts", "tests", "docs")]
    privacy_roots += [parent, calibration, figures, pilot]
    examined, matches = 0, []
    pattern = re.compile(r"sk-[A-Za-z0-9_-]{35,}")
    for root in privacy_roots:
        for file in root.rglob("*"):
            if not file.is_file() or file.suffix.lower() not in {".py", ".json", ".jsonl", ".txt", ".md", ".ps1"}:
                continue
            examined += 1
            if pattern.search(file.read_text(encoding="utf-8-sig", errors="replace")):
                matches.append(str(file.relative_to(workspace)))
    stage.write_json("credential-pattern-scan.json", {"files_examined": examined, "matching_paths_only": matches,
        "values_never_printed": True, "scope_excludes_original_reference_notebook": True})
    summary = {"four_rate_evaluation_runs": rows,
        "four_rate_candidates_completed": sum(row["candidates"] for row in rows),
        "complete_four_rate_candidates": sum(row["valid_candidates"] for row in rows),
        "four_rate_solver_calls": sum(row["rate_calls"] for row in rows),
        "diagnostic_solver_calls": 8, "all_real_solver_calls": sum(row["rate_calls"] for row in rows) + 8,
        "running_now": 0, "provider_answers_this_measured_session": 0,
        "blocked_local_http_attempts": 1, "network_retry_process_started": False,
        "integrity": verified, "calibration_audits_passed": read(figures / "comparison-and-audits.json")["all_calibration_audits_passed"],
        "frozen_pilot_config_equal_to_project_copy": sha256_file(calibration / "frozen-pilot-config.json") == sha256_file(workspace / "configs/21700-reference-calibrated-pilot.json"),
        "whole_real_llmbo_complete": False, "pending": "explicit approval to send data-derived summaries to the specified API"}
    stage.write_json("local-validation-summary.json", summary)
    passed = (summary["all_real_solver_calls"] == 56 and summary["four_rate_candidates_completed"] == 12
              and summary["complete_four_rate_candidates"] == 3 and summary["calibration_audits_passed"]
              and all(value["unchanged"] for value in verified.values()) and not matches
              and summary["frozen_pilot_config_equal_to_project_copy"])
    stage.finish("completed" if passed else "failed", {"local_checks_passed": passed, **summary})
    with (parent / ("local-audit-link-" + stage.run_id + ".json")).open("x", encoding="utf-8") as stream:
        json.dump({"audit_directory": str(stage.path), "local_checks_passed": passed}, stream, indent=2)
    print(json.dumps({"audit_directory": str(stage.path), "local_checks_passed": passed,
        "solver_calls": summary["all_real_solver_calls"], "credential_scan_matches": len(matches)}), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
