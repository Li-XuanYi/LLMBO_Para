"""Source-pinned three-rule WarmStart comparison; no live work by default."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from et_selection_trial_budget import SelectionTrialBudget


WT = Path(__file__).resolve().parents[1]
if str(WT / "src") not in sys.path:
    sys.path.insert(0, str(WT / "src"))
MAIN = Path(r"D:\Users\aa133\Desktop\LLMBO_Para")
EVIDENCE = MAIN / "bo-repair-work/20261017_et_implementation/warmstart-v3-trial-20261029"
PROPOSAL = EVIDENCE / "protocol-no-retry.json"
OUTPUT = MAIN / "runs/w29"
SEEDS = (659578, 564327, 336546, 769762, 465948)
OLD_SEEDS = (376330, 633262, 789058, 609653, 362724,
             260437, 152325, 947445, 235695, 299924)
ORDERS = (("v1", "v2", "v3"), ("v2", "v3", "v1"), ("v3", "v1", "v2"),
          ("v1", "v3", "v2"), ("v2", "v1", "v3"))
RULES = {"v1": "pareto_maximin_v1", "v2": "pareto_core_spacefill_v2",
         "v3": "pareto_quality_gated_spacefill_v3"}
CAPS = {"DFN": 1660, "API": 15, "wall_clock_s": 28800}
RUNTIME_FILES = (
    "scripts/et_selection_trial_budget.py", "scripts/run_et_warmstart_quality_gate_trial.py",
    "scripts/analyze_et_warmstart_quality_gate_trial.py", "scripts/et_warmstart_selection_paired_worker.py",
    "scripts/et_three_arm_validation_worker.py", "scripts/run_lgbo_real_gain.py",
    "scripts/lgbo_real_gain_worker.py", "scripts/analyze_et_three_arm_validation.py",
    "scripts/run_region_transport_validation.py",
)
_ACTIVE_RELEASE = None


def _sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict) -> None:
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_protocol(protocol: dict) -> dict:
    fields = {"schema_version", "status", "spec", "plan", "plan_commit", "seed_run_order",
              "historical_seed_exclusions", "arm_order_by_seed", "fit_rates", "rate_window_s",
              "candidate_pool_size", "initial_count_per_arm", "new_bo_rounds_per_arm",
              "metric_space", "independent_live_caps", "phase_count", "template", "configs",
              "live_output", "real_api_requests_at_proposal", "real_dfn_solves_at_proposal",
              "transport_retries"}
    if not isinstance(protocol, dict) or set(protocol) != fields:
        raise ValueError("trial protocol fields differ")
    expected_order = {str(seed): list(order) for seed, order in zip(SEEDS, ORDERS)}
    if (protocol["schema_version"] != 1 or protocol["status"] != "proposal_disabled"
            or protocol["spec"] != "docs/superpowers/specs/2026-10-29-warmstart-quality-gate-design.md"
            or protocol["plan"] != "docs/superpowers/plans/2026-10-29-warmstart-quality-gate-trial-plan.md"
            or protocol["plan_commit"] != "a6a5f0f" or protocol["seed_run_order"] != list(SEEDS)
            or protocol["historical_seed_exclusions"] != list(OLD_SEEDS)
            or set(SEEDS) & set(OLD_SEEDS) or protocol["arm_order_by_seed"] != expected_order
            or protocol["fit_rates"] != ["0.5C", "1C"] or protocol["rate_window_s"] != 60
            or protocol["candidate_pool_size"] != 16 or protocol["initial_count_per_arm"] != 8
            or protocol["new_bo_rounds_per_arm"] != 50 or protocol["phase_count"] != 20
            or protocol["metric_space"] != {"objective_scales": [0.1, 1.0], "hv_reference": [10.0, 10.0]}
            or protocol["independent_live_caps"] != CAPS or protocol["live_output"] != str(OUTPUT)
            or protocol["real_api_requests_at_proposal"] != 0
            or protocol["real_dfn_solves_at_proposal"] != 0
            or protocol["transport_retries"] is not False):
        raise ValueError("trial method, seeds, schedule or limits differ")
    template = protocol["template"]
    expected_template = MAIN / "bo-repair-work/20261017_et_implementation/warmstart-v1-v2-paired-20261027/proposal/seed-152325.disabled-config.json"
    if (not isinstance(template, dict) or set(template) != {"path", "sha256"}
            or Path(template["path"]) != expected_template or _sha(expected_template) != template["sha256"]):
        raise ValueError("synthetic template pin differs")
    base = _read(expected_template)
    if not isinstance(protocol["configs"], dict) or set(protocol["configs"]) != {str(seed) for seed in SEEDS}:
        raise ValueError("disabled config set differs")
    for seed in SEEDS:
        item = protocol["configs"][str(seed)]
        expected_path = EVIDENCE / f"seed-{seed}.no-retry.disabled-config.json"
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or Path(item["path"]) != expected_path or _sha(expected_path) != item["sha256"]):
            raise ValueError("disabled config pin differs")
        expected = deepcopy(base)
        expected["optimization"]["seed"] = seed
        expected["llm"]["warmstart_preheader_tls_eof_continue"] = False
        config = _read(expected_path)
        if (config != expected or config["fit_rates"] != ["0.5C", "1C"]
                or config["run_kind"] != "synthetic_dfn" or config["llm"]["enabled"] is not False
                or config["budgets"] != {"max_solver_calls": 0, "max_llm_requests": 0, "wall_clock_s": 28800}
                or config["optimization"]["warmstart"]["selection_rule"] != RULES["v1"]):
            raise ValueError("disabled configuration semantics differ")
    return protocol


def load_protocol(path: Path = PROPOSAL) -> dict:
    return validate_protocol(_read(path))


def cases(protocol: dict) -> list[dict]:
    validate_protocol(protocol)
    return [{"seed": seed, "arm": arm} for seed in SEEDS
            for arm in protocol["arm_order_by_seed"][str(seed)]]


def phases_for(protocol: dict) -> dict:
    validate_protocol(protocol)
    return {phase: limits for seed in SEEDS for phase, limits in (
        (f"pool-{seed}", {"DFN": 32, "API": 3}),
        *((f"arm-{seed}-{arm}", {"DFN": 100, "API": 0})
          for arm in protocol["arm_order_by_seed"][str(seed)]))}


def dry_run(path: Path = PROPOSAL, *, output: Path = OUTPUT) -> dict:
    protocol = load_protocol(path)
    return {"status": "disabled", "planned_cases": len(cases(protocol)),
            "planned_rounds": len(cases(protocol)) * 50, "limits": CAPS,
            "API": 0, "DFN": 0, "output_not_created": not Path(output).exists()}


def _seed_config(protocol: dict, seed: int) -> dict:
    item = protocol["configs"][str(seed)]
    if _sha(Path(item["path"])) != item["sha256"]:
        raise ValueError("seed configuration changed")
    return _read(Path(item["path"]))


def _check_source_pins(release: dict) -> None:
    for name, expected in release["source_pins"].items():
        if _sha(WT / name) != expected:
            raise ValueError("released source changed: " + name)
    if release.get("release_sha256") and _sha(EVIDENCE / "software-release.json") != release["release_sha256"]:
        raise ValueError("released gate record changed")


def source_names() -> set[str]:
    files = list((WT / "src/llmbo_para").rglob("*.py"))
    files += list((WT / "src/llmbo_para/prompts").glob("*.txt"))
    files += [WT / name for name in ("requirements-py312.lock", "requirements-research.lock",
                                     "requirements-test.lock", "pyproject.toml")]
    return set(RUNTIME_FILES) | {path.relative_to(WT).as_posix() for path in files if path.is_file()}


def _phase(spec: dict, budget: SelectionTrialBudget, protocol: dict, *, root: Path,
           source_root: Path, software_fixture: bool) -> dict:
    import et_three_arm_validation_worker as worker
    import run_lgbo_real_gain as helper

    validate_protocol(protocol)
    if _ACTIVE_RELEASE is not None:
        _check_source_pins(_ACTIVE_RELEASE)
    deadline = budget.deadline - 15.
    if time.monotonic() >= deadline:
        raise TimeoutError("trial deadline exhausted")
    label = spec["label"]
    output = root / label
    output.mkdir(parents=True, exist_ok=False)
    override = spec.get("base_config_override")
    intent = {**{k: v for k, v in spec.items() if k != "base_config_override"},
              "output": str(output), "source_root": str(source_root),
              "source": helper.fingerprint(source_root), "deadline": deadline,
              "base_config": override if override is not None else _seed_config(protocol, spec["seed"]),
              "software_fixture": software_fixture}
    metadata = root / (label + "-owned.json")
    result = helper.supervise(worker.run_worker, intent, budget, deadline=deadline,
                              metadata=metadata, integrity_check=lambda: (
                                  validate_protocol(protocol),
                                  _check_source_pins(_ACTIVE_RELEASE) if _ACTIVE_RELEASE else None))
    if _read(metadata).get("owned_tree_stopped") is not True:
        raise RuntimeError("owned worker tree remains live")
    _write_json(root / (label + "-result.json"), result)
    return result


def _plan_configs(protocol: dict, seed: int, *, software_fixture: bool) -> dict:
    import et_three_arm_validation_worker as worker

    v1 = worker.config_for(_seed_config(protocol, seed), kind="warmstart_initialization",
                           arm="warmstart_only", seed=seed, remaining=3600., initial_plan=None)
    if software_fixture:
        v1["model"]["provider"] = "software"
        v1["run_kind"] = "synthetic_software"
        v1["llm"]["enabled"] = False
        v1["budgets"]["max_solver_calls"] = 0
        v1["budgets"]["max_llm_requests"] = 0
    configs = {}
    for arm, rule in RULES.items():
        configs[arm] = deepcopy(v1)
        configs[arm]["optimization"]["warmstart"]["selection_rule"] = rule
    return configs


def run_seed(protocol: dict, *, seed: int, budget: SelectionTrialBudget, root: Path,
             source_root: Path, software_fixture: bool = False) -> dict:
    import et_warmstart_selection_paired_worker as plans

    validate_protocol(protocol)
    if seed not in SEEDS or Path(source_root).resolve() != WT.resolve():
        raise ValueError("unexpected seed or source checkout")
    root = Path(root)
    pair = {"seed": seed, "status": "incomplete", "cases": {},
            "metric_space": protocol["metric_space"]}
    partial = root / f"seed-{seed}-partial.json"
    try:
        budget.begin(f"pool-{seed}")
        pool = _phase({"kind": "warmstart_initialization", "arm": "warmstart_only",
                       "seed": seed, "label": f"seed-{seed}-pool",
                       "solve_cap": 0 if software_fixture else 32}, budget, protocol,
                      root=root, source_root=Path(source_root), software_fixture=software_fixture)
        if (pool.get("audit_passed") is not True or pool.get("complete_pool_count") != 16
                or pool.get("selected_count") != 8):
            raise ValueError("shared candidate pool incomplete")
        pair["pool"] = pool
        pair["plans"] = plans.derive_selection_plans(
            pool["run_directory"], configs=_plan_configs(protocol, seed, software_fixture=software_fixture),
            rules=RULES, out=root / f"seed-{seed}-plans")
        budget.finish(True)
        _write_json(partial, pair)
        for arm in protocol["arm_order_by_seed"][str(seed)]:
            budget.begin(f"arm-{seed}-{arm}")
            plan = pair["plans"][arm]
            initial = {"path": plan["path"], "sha256": plan["sha256"],
                       "origin_run_id": pool["run_directory"], "costs": pair["plans"]["shared_costs"]}
            base = _seed_config(protocol, seed)
            base["optimization"]["warmstart"]["selection_rule"] = RULES[arm]
            row = _phase({"kind": "arm", "arm": "warmstart_only", "seed": seed,
                          "label": f"seed-{seed}-{arm}", "solve_cap": 0 if software_fixture else 100,
                          "initial": initial, "base_config_override": base}, budget, protocol,
                         root=root, source_root=Path(source_root), software_fixture=software_fixture)
            if (row.get("audit_passed") is not True or row.get("BO_rounds") != 50
                    or row.get("initial_file_sha") != plan["sha256"]
                    or row.get("summary", {}).get("API_calls") != 0):
                raise ValueError("formal arm incomplete")
            row["arm"] = arm
            pair["cases"][arm] = row
            budget.finish(True)
            _write_json(partial, pair)
        pair["status"] = "completed"
    except Exception as exc:
        state = budget.state()
        pair.update(status="failed", failed_phase=state["phase"], error_type=type(exc).__name__,
                    costs=budget.counts())
        if state["phase"] is not None:
            budget.finish(False)
        elif not state["closed"]:
            budget.abort()
    _write_json(partial, pair)
    return pair


def read_credential() -> str:
    """Read the dedicated user credential only after the release gate passes."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
        value, _ = winreg.QueryValueEx(handle, "LLMBO_OPENCODE_API_KEY")
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError("dedicated credential unavailable")
    return value


def _live_preflight(evidence_dir: Path, output: Path) -> tuple[dict, dict]:
    evidence_dir, output = Path(evidence_dir), Path(output)
    if output.exists() or (evidence_dir / "budget.jsonl").exists():
        raise ValueError("live output or budget already exists")
    release_path, approval_path = evidence_dir / "software-release.json", evidence_dir / "approval.json"
    if not release_path.is_file() or not approval_path.is_file():
        raise ValueError("software release and authorization record required")
    if evidence_dir.resolve() != EVIDENCE.resolve() or output.resolve() != OUTPUT.resolve():
        raise ValueError("live evidence or output path differs")
    protocol, release, approval = load_protocol(), _read(release_path), _read(approval_path)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=WT, text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], cwd=WT, text=True).strip()
    if (approval.get("approved") is not True or approval.get("protocol_sha256") != _sha(PROPOSAL)
            or approval.get("limits") != CAPS or release.get("status") != "passed"
            or release.get("protocol_sha256") != _sha(PROPOSAL) or release.get("limits") != CAPS
            or release.get("head") != head or status
            or set(release.get("source_pins", {})) != source_names()):
        raise ValueError("authorization, source status or release differs")
    for name, expected in release["source_pins"].items():
        snapshot = evidence_dir / "source-snapshot" / name
        if _sha(WT / name) != expected or _sha(snapshot) != expected:
            raise ValueError("released source snapshot differs")
    for gate in ("targeted", "full", "mock"):
        item = release.get("gates", {}).get(gate, {})
        path = Path(item.get("result_path", ""))
        if not path.is_file() or _sha(path) != item.get("sha256"):
            raise ValueError("released software gate missing or changed")
        result = _read(path)
        if gate == "mock":
            if result != {"status": "completed", "cases": 15, "rounds": 750, "API": 0, "DFN": 0}:
                raise ValueError("mock rehearsal gate failed")
        else:
            counts = result.get("counts", {})
            if (result.get("exit_code") != 0 or counts.get("tests", 0) < (1600 if gate == "full" else 1)
                    or any(counts.get(key) != 0 for key in ("failures", "errors", "skipped"))):
                raise ValueError("software regression gate failed")
            if gate == "full" and (result.get("head") != head or result.get("source_unchanged") is not True
                    or result.get("started_status") != "" or result.get("ended_status") != ""
                    or result.get("boundary", {}).get("network_attempts") != 0
                    or result.get("boundary", {}).get("battery_solve_attempts") != 0):
                raise ValueError("full regression boundary differs")
    release["release_sha256"] = _sha(release_path)
    return protocol, release


def run_mock_rehearsal(*, output: Path) -> dict:
    global _ACTIVE_RELEASE
    import analyze_et_warmstart_quality_gate_trial as analyzer

    protocol = load_protocol()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    budget = SelectionTrialBudget.start(output / "budget.jsonl", protocol_sha=_sha(PROPOSAL),
                                        caps=CAPS, phases=phases_for(protocol))
    _ACTIVE_RELEASE = {"source_pins": {name: _sha(WT / name) for name in source_names()}}
    try:
        pairs = []
        for seed in SEEDS:
            pair = run_seed(protocol, seed=seed, budget=budget, root=output,
                            source_root=WT, software_fixture=True)
            if pair["status"] != "completed":
                raise ValueError("mock seed incomplete")
            analyzer.analyze_seed(pair, protocol)
            pairs.append(pair)
        result = {"status": "completed", "pairs": pairs, "costs": budget.counts()}
        _write_json(output / "result.json", result)
        report = analyzer.analyze_trial(output / "result.json", protocol)
        if report["status"] != "completed" or not budget.state()["closed"] or budget.counts() != {"DFN": 0, "API": 0}:
            raise ValueError("mock closure failed")
        _check_source_pins(_ACTIVE_RELEASE)
        _write_json(output / "analysis.json", report)
        summary = {"status": "completed", "cases": 15, "rounds": 750, "API": 0, "DFN": 0}
        _write_json(output / "summary.json", summary)
        return summary
    finally:
        _ACTIVE_RELEASE = None


def execute_live(*, evidence_dir: Path = EVIDENCE, output: Path = OUTPUT) -> dict:
    """Execute one released trial; a failed or closed budget is never resumed."""
    global _ACTIVE_RELEASE
    import analyze_et_warmstart_quality_gate_trial as analyzer
    import run_lgbo_real_gain as helper

    evidence_dir, output = Path(evidence_dir), Path(output)
    protocol, release = _live_preflight(evidence_dir, output)
    credential = read_credential()
    os.environ["LLMBO_OPENCODE_API_KEY"] = credential
    del credential
    try:
        output.mkdir(parents=True, exist_ok=False)
        budget = SelectionTrialBudget.start(evidence_dir / "budget.jsonl", protocol_sha=_sha(PROPOSAL),
                                            caps=CAPS, phases=phases_for(protocol))
    except BaseException:
        os.environ.pop("LLMBO_OPENCODE_API_KEY", None)
        raise
    _ACTIVE_RELEASE = release
    result = {"status": "incomplete", "protocol_sha256": _sha(PROPOSAL),
              "release_sha256": release["release_sha256"], "limits": CAPS, "pairs": []}
    started = time.monotonic()
    try:
        _write_json(output / "result.json", result)
        with helper.keep_awake(output / "wake.json"):
            for seed in SEEDS:
                pair = run_seed(protocol, seed=seed, budget=budget, root=output, source_root=WT)
                result["pairs"].append(pair)
                result["costs"] = budget.counts()
                _write_json(output / "result.json", result)
                if pair["status"] != "completed":
                    raise RuntimeError("seed incomplete: " + pair.get("error_type", "unknown"))
                analyzer.analyze_seed(pair, protocol)
                print(json.dumps({"seed": seed, "completed_pairs": len(result["pairs"]),
                                  "costs": result["costs"]}), flush=True)
            result.update(status="completed", costs=budget.counts(), elapsed_s=time.monotonic() - started)
            _write_json(output / "result.json", result)
            report = analyzer.analyze_trial(output / "result.json", protocol)
            if report["status"] != "completed" or not budget.state()["closed"]:
                raise ValueError("final independent audit incomplete")
            _write_json(output / "analysis.json", report)
    except Exception as exc:
        state = budget.state()
        if state["phase"] is not None:
            budget.finish(False)
        elif not state["closed"]:
            budget.abort()
        result.update(status="failed", error_type=type(exc).__name__, costs=budget.counts(),
                      elapsed_s=time.monotonic() - started)
        _write_json(output / "result.json", result)
    finally:
        _ACTIVE_RELEASE = None
        os.environ.pop("LLMBO_OPENCODE_API_KEY", None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--mock-rehearsal", type=Path)
    group.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        result = dry_run()
    elif args.mock_rehearsal:
        result = run_mock_rehearsal(output=args.mock_rehearsal)
    else:
        result = execute_live()
    display = result if not args.execute else {
        "status": result.get("status"), "costs": result.get("costs"),
        "completed_seeds": sum(pair.get("status") == "completed" for pair in result.get("pairs", [])),
        "error_type": result.get("error_type"), "output": str(OUTPUT),
    }
    print(json.dumps(display, indent=2, ensure_ascii=False), flush=True)
    return 0 if result.get("status") in ("disabled", "completed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
