"""Offline contract checks for the preregistered 50-round comparison."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_et_three_arm_validation.py"
PROPOSAL = Path(
    "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/"
    "20261017_et_implementation/three-arm-50round-proposal-20261026/"
    "protocol-proposal.json"
)


def load():
    assert SCRIPT.is_file(), "three-arm runner is missing"
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_et_three_arm_validation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_five_new_seeds_three_arms_and_exact_cost_ceiling():
    runner = load()
    protocol = runner.load_protocol(PROPOSAL)
    assert protocol["seed_selection"]["seeds"] == [376330, 633262, 789058, 609653, 362724]
    assert len(set(protocol["seed_selection"]["seeds"])) == 5
    assert len(runner.cases(protocol)) == 15
    assert protocol["initial_count"] == 8
    assert protocol["BO_rounds_per_arm"] == 50
    assert protocol["total_candidate_budget_per_arm"] == 58
    assert protocol["limits"] == {"DFN": 1740, "API": 271, "wall_clock_s": 28800}
    assert protocol["cost_breakdown"] == {
        "main_DFN": 1500, "BO_initial_DFN": 80, "warmstart_pool_DFN": 160,
        "Region_API": 250, "WarmStart_API": 15, "diagnostic_API": 6,
    }
    assert all(tuple(case["rates"]) == ("0.5C", "1C") for case in runner.cases(protocol))


@pytest.mark.parametrize("field,value", [
    ("BO_rounds_per_arm", 20), ("total_candidate_budget_per_arm", 50),
    ("fit_rates", ["0.5C", "1C", "3C"]), ("limits", {"DFN": 2000, "API": 271, "wall_clock_s": 28800}),
])
def test_protocol_mutation_rejected(field, value):
    runner = load()
    changed = deepcopy(runner.read(PROPOSAL))
    changed[field] = value
    with pytest.raises(ValueError):
        runner.validate_protocol(changed)


def test_numeric_seed_coordinates_are_reconstructed_before_freeze():
    runner = load()
    changed = deepcopy(runner.read(PROPOSAL))
    changed["seed_plans"][0]["BO_initialization"]["parameters"][0][0] += 0.001
    with pytest.raises(ValueError):
        runner.validate_protocol(changed)


def test_dry_run_creates_no_live_output_or_credential_read(tmp_path, monkeypatch):
    runner = load()
    monkeypatch.setattr(runner, "read_credential", lambda: pytest.fail("dry run read credential"))
    report = runner.dry_run(PROPOSAL, output=tmp_path / "not-created")
    assert report["API"] == report["DFN"] == 0
    assert report["planned_cases"] == 15
    assert report["new_rounds"] == 750
    assert not (tmp_path / "not-created").exists()


def test_live_entry_without_software_release_stops_before_credential_or_budget(tmp_path, monkeypatch):
    runner = load()
    monkeypatch.setattr(runner, "EVIDENCE", tmp_path)
    monkeypatch.setattr(runner, "OUTPUT", tmp_path / "unused-run")
    monkeypatch.setattr(runner, "read_credential", lambda: pytest.fail("release gate read key"))
    with pytest.raises(ValueError):
        runner.execute()
    assert not (tmp_path / "budget-journal.jsonl").exists()
    assert not (tmp_path / "unused-run").exists()


def test_budget_phase_caps_reject_duplicate_and_overcap(tmp_path):
    runner = load()
    budget = runner.new_budget(tmp_path / "ledger.jsonl", protocol_sha="a" * 64)
    budget.begin("diagnostic")
    budget.charge("API", "gate-1")
    with pytest.raises(RuntimeError):
        budget.charge("API", "gate-1")
    with pytest.raises(RuntimeError):
        budget.charge("DFN", "gate-solve")
    budget.finish(True)
    budget.begin("initialization")
    with pytest.raises(RuntimeError):
        budget.require(241)
    assert budget.counts() == {"DFN": 0, "API": 1}
    text = (tmp_path / "ledger.jsonl").read_text(encoding="utf-8")
    (tmp_path / "ledger.jsonl").write_text(text.replace('"gate-1"', '"tampered"'), encoding="utf-8")
    with pytest.raises(ValueError):
        runner.ThreeArmBudget.load(tmp_path / "ledger.jsonl")


def test_spawned_mock_three_arm_closure_shares_only_warmstart_plan():
    """Real stores/BO/audits, algebraic simulator and mock LLM; zero external calls."""
    runner = load()
    import et_three_arm_validation_worker as worker

    protocol = runner.load_protocol(PROPOSAL)
    plan = protocol["seed_plans"][0]
    root = Path(tempfile.mkdtemp(prefix="g50-mock-", dir=runner.MAIN / "runs"))
    budget = runner.new_budget(root / "budget.jsonl", protocol_sha="a" * 64)
    budget.begin("diagnostic")
    budget.finish(True)
    budget.begin("initialization")
    source = runner.SOURCE
    base = runner.read(runner.PROPOSAL / f"seed-{plan['seed']}.disabled-config.json")

    def spawn(kind, arm, label, *, initial=None):
        spec = {"kind": kind, "arm": arm, "label": label,
                "source_root": str(source), "source": runner.CORE_FINGERPRINT,
                "output": str(root / label), "deadline": budget.deadline,
                "base_config": base, "seed": plan["seed"],
                "software_fixture": True, "solve_cap": 0}
        if kind == "numeric_initialization":
            spec["coordinates"] = plan["BO_initialization"]["parameters"]
        if initial is not None:
            spec["initial"] = initial
        result = runner.helper.supervise(worker.run_worker, spec, budget,
            deadline=min(budget.deadline, time.monotonic() + 180),
            metadata=root / (label + "-owned.json"))
        assert runner.read(root / (label + "-owned.json"))["owned_tree_stopped"]
        return result

    bo_init = spawn("numeric_initialization", "bo", "numeric-init")
    warm_init = spawn("warmstart_initialization", "warmstart_only", "warm-init")
    assert bo_init["audit_passed"] and warm_init["audit_passed"]
    assert bo_init["selected_count"] == warm_init["selected_count"] == 8
    assert warm_init["complete_pool_count"] == 16
    assert bo_init["plan_file_sha256"] != warm_init["plan_file_sha256"]
    budget.finish(True)
    budget.begin("main")
    results = {}
    for arm in runner.ARMS:
        init = bo_init if arm == "bo" else warm_init
        initial = {"path": init["plan_path"], "sha256": init["plan_file_sha256"],
                   "origin_run_id": init["run_directory"], "costs": init["costs"]}
        results[arm] = spawn("arm", arm, arm, initial=initial)
    budget.finish(True)
    assert all(row["BO_rounds"] == 50 and row["audit_passed"] for row in results.values())
    assert results["warmstart_only"]["initial_file_sha"] == results["full_llmbo_mo"]["initial_file_sha"]
    assert results["warmstart_only"]["first_numerical_context_sha"] == results["full_llmbo_mo"]["first_numerical_context_sha"]
    assert results["bo"]["initial_file_sha"] != results["warmstart_only"]["initial_file_sha"]
    assert results["bo"]["summary"]["API_calls"] == results["warmstart_only"]["summary"]["API_calls"] == 0
    assert budget.counts() == {"DFN": 0, "API": 0}
    assert all(len(row["rounds"]) == 50 for row in results.values())
    from analyze_et_three_arm_validation import analyze_case
    for arm, case in results.items():
        init = bo_init if arm == "bo" else warm_init
        summary, curve, front = analyze_case(case, init)
        assert summary["arm"] == arm and len(curve) == 50 and front


def test_mock_transport_gate_preserves_frozen_gp_and_charges_before_request(monkeypatch):
    runner = load()
    import et_three_arm_validation_worker as worker

    monkeypatch.setenv("LLMBO_OPENCODE_API_KEY", "offline-fixture-only")
    root = Path(tempfile.mkdtemp(prefix="g50-gate-", dir=runner.MAIN / "runs"))
    budget = runner.new_budget(root / "budget.jsonl", protocol_sha="a" * 64)
    budget.begin("diagnostic")
    historical = runner._historical_contexts()[0]
    rows = []
    for kind, extra in (("gate_minimal", {}), ("gate_historical", historical)):
        spec = {"kind": kind, "label": kind, "source_root": str(runner.SOURCE),
                "source": runner.CORE_FINGERPRINT, "output": str(root / kind),
                "deadline": budget.deadline, "timeout_s": 30., "solve_cap": 0,
                "protocol_sha": "a" * 64, "software_fixture": True, **extra}
        row = runner.helper.supervise(worker.run_worker, spec, budget,
            deadline=time.monotonic() + 50,
            metadata=root / (kind + "-owned.json"))
        assert runner.read(root / (kind + "-owned.json"))["owned_tree_stopped"]
        rows.append(row)
    assert all(row["passed"] and row["complete"] and row["wire_verified"] for row in rows)
    assert rows[1]["effect"]["state_preserved"]
    assert rows[1]["effect"]["tilt_applied"]
    assert budget.counts() == {"DFN": 0, "API": 2}  # Logical fixture charges; real API 0.


def test_candidate_only_gate_checks_fresh_reply_before_any_dfn(monkeypatch):
    runner = load()
    import et_three_arm_validation_worker as worker

    monkeypatch.setenv("LLMBO_OPENCODE_API_KEY", "offline-fixture-only")
    root = Path(tempfile.mkdtemp(prefix="g50-candidate-gate-", dir=runner.MAIN / "runs"))
    budget = runner.new_budget(root / "budget.jsonl", protocol_sha="b" * 64)
    budget.begin("diagnostic")
    base = runner.read(runner.PROPOSAL / "seed-376330.disabled-config.json")
    base["llm"]["warmstart_wire_format"] = "candidate_only_v1"
    source_sha = runner.helper.fingerprint(runner.WT)
    spec = {"kind": "gate_candidate", "label": "gate-candidate",
            "base_config": base, "source_root": str(runner.WT),
            "source": source_sha, "output": str(root / "gate-candidate"),
            "deadline": budget.deadline, "timeout_s": 30., "solve_cap": 0,
            "protocol_sha": "b" * 64, "software_fixture": True}
    row = runner.helper.supervise(worker.run_worker, spec, budget,
        deadline=time.monotonic() + 50,
        metadata=root / "gate-candidate-owned.json")
    assert row["passed"] and row["wire_verified"] and row["candidate_count"] >= 8
    assert budget.counts() == {"DFN": 0, "API": 1}


def test_bound_study_uses_new_paths_and_explicit_gate():
    legacy = load()
    old_paths = (legacy.PROPOSAL, legacy.EVIDENCE, legacy.OUTPUT)
    import run_et_three_arm_bound_validation as bound

    assert bound.runner.CANDIDATE_GATE is True
    assert (bound.runner.PROPOSAL, bound.runner.EVIDENCE, bound.runner.OUTPUT) != old_paths
    assert bound.runner.PLAN_COMMIT == "3c27fe4db152d1be7859d037ee9420a9a770119d"
    report = bound.runner.dry_run(bound.runner.PROPOSAL / "protocol-proposal.json")
    assert report["API"] == report["DFN"] == 0
    assert report["output_not_created"] is (not bound.runner.OUTPUT.exists())


def test_eof_recovery_study_has_isolated_entry_and_zero_call_dry_run():
    load()
    script = ROOT / "scripts/run_et_three_arm_eof_validation.py"
    assert script.is_file()
    import run_et_three_arm_eof_validation as eof

    assert eof.runner.CANDIDATE_GATE is True
    assert eof.runner.OUTPUT.name == "g27a"
    report = eof.runner.dry_run()
    assert report["planned_cases"] == 15 and report["new_rounds"] == 750
    assert report["API"] == report["DFN"] == 0
    assert report["output_not_created"] is True


def test_eof_recovery_study_rejects_missing_or_mixed_policy(tmp_path, monkeypatch):
    load()
    import run_et_three_arm_eof_validation as eof

    original = eof.runner.read(eof.runner.PROPOSAL / "protocol-proposal.json")
    changed = deepcopy(original)
    changed.pop("warmstart_preheader_tls_eof_continue")
    missing = tmp_path / "missing-policy.json"
    missing.write_text(json.dumps(changed), encoding="utf8")
    with pytest.raises(ValueError, match="recovery policy"):
        eof.load_eof_protocol(missing)

    for seed in eof.runner.SEEDS:
        config = eof.runner.read(eof.runner.PROPOSAL /
                                 f"seed-{seed}.disabled-config.json")
        (tmp_path / f"seed-{seed}.disabled-config.json").write_text(
            json.dumps(config), encoding="utf8")
    mixed = tmp_path / f"seed-{eof.runner.SEEDS[2]}.disabled-config.json"
    config = json.loads(mixed.read_text(encoding="utf8"))
    config["llm"]["warmstart_preheader_tls_eof_continue"] = False
    mixed.write_text(json.dumps(config), encoding="utf8")
    (tmp_path / "protocol-proposal.json").write_text(json.dumps(original), encoding="utf8")
    monkeypatch.setattr(eof.runner, "PROPOSAL", tmp_path)
    with pytest.raises(ValueError, match="every seed"):
        eof.load_eof_protocol(tmp_path / "protocol-proposal.json")


def test_eof_recovery_study_refuses_live_without_release(tmp_path, monkeypatch):
    load()
    import run_et_three_arm_eof_validation as eof

    monkeypatch.setattr(eof.runner, "EVIDENCE", tmp_path)
    monkeypatch.setattr(eof.runner, "OUTPUT", tmp_path / "unused")
    monkeypatch.setattr(eof.runner, "read_credential",
                        lambda: pytest.fail("credential read before release"))
    with pytest.raises(ValueError, match="software release"):
        eof.runner.execute()
    assert not (tmp_path / "budget-journal.jsonl").exists()
    assert not (tmp_path / "unused").exists()


def test_bound_study_worker_mock_warmstart_initialization(tmp_path):
    runner = load()
    import et_three_arm_validation_worker as worker

    proposal = (runner.BASE / "three-arm-50round-bound-proposal-20261026" /
                "seed-376330.disabled-config.json")
    base = runner.read(proposal)
    assert base["llm"]["warmstart_wire_format"] == "candidate_only_v1"
    source = runner.WT
    budget = runner.new_budget(tmp_path / "budget.jsonl", protocol_sha="c" * 64)
    budget.begin("diagnostic")
    budget.finish(True)
    budget.begin("initialization")
    spec = {"kind": "warmstart_initialization", "arm": "warmstart_only",
            "label": "bound-warmstart-mock", "source_root": str(source),
            "source": runner.helper.fingerprint(source),
            "output": str(tmp_path / "bound-warmstart-mock"),
            "deadline": budget.deadline, "base_config": base,
            "seed": 376330, "software_fixture": True, "solve_cap": 0}
    row = runner.helper.supervise(worker.run_worker, spec, budget,
        deadline=time.monotonic() + 180,
        metadata=tmp_path / "bound-warmstart-owned.json")
    assert row["audit_passed"] and row["selected_count"] == 8
    assert row["complete_pool_count"] == 16
    run_root = Path(row["run_directory"])
    assert (run_root / "llm/000000.warmstart-binding.json").is_file()
    assert budget.counts() == {"DFN": 0, "API": 0}


def test_paired_region_context_and_three_arm_weights_are_checked():
    runner = load()
    weights = [[0.8, 0.2], [0.2, 0.8]]
    base = {"initial_file_sha": "a" * 64,
            "first_numerical_context_sha": "c" * 64,
            "rounds": [{"weight": value} for value in weights]}
    cases = {arm: deepcopy(base) for arm in runner.ARMS}
    cases["bo"]["initial_file_sha"] = "b" * 64
    runner.check_case_consistency(cases)
    changed = deepcopy(cases)
    changed["full_llmbo_mo"]["first_numerical_context_sha"] = "d" * 64
    with pytest.raises(ValueError):
        runner.check_case_consistency(changed)
    changed = deepcopy(cases)
    changed["bo"]["rounds"][1]["weight"] = [0.5, 0.5]
    with pytest.raises(ValueError):
        runner.check_case_consistency(changed)
