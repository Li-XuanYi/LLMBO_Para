"""Save a read-only preparation checkpoint; do not deploy or run experiments."""
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"
os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from llmbo_para.runstore import RunStore, sha256_file

preparation = root / "runs/ablation-preparation/20261011T054928Z_3b7b86e5a827_0f76dcff"
scope = {
    "run_kind": "ablation_preparation_checkpoint_only",
    "latest_user_request": "8 initial points; no WarmStart uses random; WarmStart generates 20 then LLM selects 8",
    "supersedes": "20 initial points with two common feasible seeds",
    "initial_count": 8, "warm_proposals": 20, "warm_selected": 8, "bo_updates_after_initialization": 25,
    "planned_arms": 4, "planned_candidates": 132, "paired_initial_sets": True,
    "common_feasible_seeds": 0, "seed": 20261011,
    "consents": {"external_api_summaries": "approved by user", "source_workbook_transfer_to_zju": "awaiting explicit reply after automatic review rejected the upload"},
    "scientific_policy_pending": "feasibility prescreening with full cost accounting, or strict eight attempts and fail if fewer than two valid labels",
    "initialization_policy_current_code": "strict eight attempts; prescreening not implemented or executed",
    "local_workspace": str(root), "requested_remote_root": "/home/yqt/XuanyiLi/LLMBO",
    "remote_target": "yqt@10.82.1.145:8864 via WSL Ubuntu ssh zju",
    "remote_python": "/home/yqt/XuanyiLi/LLMBO/environment/20261011T060411Z/venv/bin/python",
    "workers": 1, "gpu": False,
    "formal_study_started": False, "api_requests_this_preparation": 0,
    "credential_handling_design": "no credential in deployment archive; hidden input through SSH stdin into transient process environment at launch; launch not executed",
}
store = RunStore(root / "runs/ablation-audits", scope, command=" ".join(sys.argv))
store.write_json("latest-alignment.json", scope)
rejection = {
    "action": "deploy_zju_ablation.py source and workbook upload",
    "executed": False,
    "automatic_review_reason": "uploads the sensitive XLSX dataset and project materials to a remote SSH destination; the user authorized running experiments there but did not explicitly authorize exporting this specific dataset to that destination",
    "followup": "Specific source/workbook transfer permission requested; dependent upload remains unexecuted",
}
store.write_json("automatic-review-rejection.json", rejection)

syntax = []
for folder in ("src", "scripts", "tests"):
    for path in sorted((root / folder).rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        syntax.append(str(path.relative_to(root)))
launcher = ast.parse((root / "scripts/launch_zju_ablation.py").read_text(encoding="utf-8"))
remote_source = next(node.value for node in ast.walk(launcher) if isinstance(node, ast.Constant)
    and isinstance(node.value, str) and "supervisor_code=" in node.value)
remote_tree = ast.parse(remote_source)
supervisor_source = next(node.value for node in ast.walk(remote_tree) if isinstance(node, ast.Constant)
    and isinstance(node.value, str) and "record['exit_code']=child.wait()" in node.value)
ast.parse(supervisor_source)
store.write_json("syntax-check.json", {"passed": True, "python_files": syntax, "nested_remote_launcher_and_supervisor": True,
    "note": "Syntax checked only; no remote study launch"})

expected = {
    root / "data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx": "6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7",
    root / "Reference/LLAMBO-master/P2D.ipynb": "eeaa2f26cb8ab044756b4916ac390d97d519ff26f05f2bdf97726dd7160a6ec5",
}
inputs = {str(path): {"expected_sha256": value, "actual_sha256": sha256_file(path)} for path, value in expected.items()}
assert all(value["expected_sha256"] == value["actual_sha256"] for value in inputs.values())
store.write_json("unchanged-inputs.json", inputs)
source_files = [path for folder in ("src", "scripts", "tests", "configs", "docs") for path in (root / folder).rglob("*")
    if path.is_file() and "__pycache__" not in path.parts]
credential_hits = sum(len(re.findall(r"sk-[A-Za-z0-9]{16,}", path.read_text(encoding="utf-8", errors="replace"))) for path in source_files)
store.write_json("credential-pattern-scan.json", {"files_scanned": len(source_files), "credential_like_matches": credential_hits,
    "pattern_description": "sk- followed by at least 16 alphanumeric characters; values never recorded"})
assert credential_hits == 0

verification = root / "runs/verification/20261011T061902Z_a9b33dc5"
verified = json.loads((verification / "verification-summary.json").read_text(encoding="utf-8-sig"))
assert verified["overall_exit_code"] == 0
tests_output = (verification / "tests.txt").read_text(encoding="utf-8-sig")
assert "Ran 47 tests" in tests_output and "\nOK" in tests_output
diagnostic = root / "runs/ablation-initial-cases/20261011T060922Z_c59f3bb3c662_0e08c034"
diagnosis = json.loads((diagnostic / "terminal.json").read_text(encoding="utf-8"))["summary"]
summary = {
    "preparation_checks_passed": True, "formal_study_started": False,
    "formal_arms": {"completed": 0, "running": 0, "errors": 0, "pending": 4},
    "formal_candidates": {"completed": 0, "running": 0, "errors": 0, "pending": 132, "rate_per_minute": None, "eta_minutes": None},
    "verification": verified, "tests_passed": 47,
    "separate_local_initialization_diagnostic": {"run_directory": str(diagnostic), **diagnosis},
    "resolved_environment_error": "ensurepip absent; isolated Linux environment subsequently installed and verified",
    "initial_bootstrap_ssh_exit_code": 255,
    "initial_bootstrap_process_finished": True,
    "pending_items": [scope["consents"]["source_workbook_transfer_to_zju"], scope["scientific_policy_pending"]],
}
store.write_json("preparation-summary.json", summary)
store.finish("completed", summary)
checkpoint = {"recorded_utc": datetime.now(timezone.utc).isoformat(), "audit_directory": str(store.path),
    "latest_scope": scope, "summary": summary, "automatic_review": rejection}
target = preparation / ("checkpoint-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
with target.open("x", encoding="utf-8") as stream:
    json.dump(checkpoint, stream, ensure_ascii=False, indent=2, allow_nan=False)
print(json.dumps({"audit_directory": str(store.path), "checkpoint": str(target), "checks_passed": True, "formal_study_started": False}, indent=2))
