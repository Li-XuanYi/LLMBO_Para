"""Frozen three-arm selection study contracts."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = Path(r"D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\20261017_et_implementation\warmstart-v3-trial-20261029")
sys.path.insert(0, str(ROOT / "scripts"))


def test_five_new_seeds_have_fifteen_cases_and_no_live_side_effects(tmp_path):
    from run_et_warmstart_quality_gate_trial import load_protocol, cases, dry_run

    protocol = load_protocol(EVIDENCE / "protocol-no-retry.json")
    assert protocol["seed_run_order"] == [659578, 564327, 336546, 769762, 465948]
    assert len(cases(protocol)) == 15
    assert [item["arm"] for item in cases(protocol)] == [
        "v1", "v2", "v3", "v2", "v3", "v1", "v3", "v1", "v2",
        "v1", "v3", "v2", "v2", "v1", "v3",
    ]
    result = dry_run(EVIDENCE / "protocol-no-retry.json", output=tmp_path / "live")
    assert result["planned_rounds"] == 750
    assert result["limits"] == {"DFN": 1660, "API": 15, "wall_clock_s": 28800}
    assert result["API"] == result["DFN"] == 0
    assert not (tmp_path / "live").exists()


def test_changed_rate_or_arm_order_is_rejected(tmp_path):
    from run_et_warmstart_quality_gate_trial import load_protocol

    original = json.loads((EVIDENCE / "protocol-no-retry.json").read_text())
    for field, value in (
        ("fit_rates", ["0.5C", "1C", "3C"]),
        ("arm_order_by_seed", {**original["arm_order_by_seed"],
                               "659578": ["v1", "v2", "v2"]}),
        ("independent_live_caps", {"DFN": 1661, "API": 15, "wall_clock_s": 28800}),
        ("transport_retries", True),
    ):
        changed = deepcopy(original)
        changed[field] = value
        path = tmp_path / f"changed-{field}.json"
        path.write_text(json.dumps(changed))
        with pytest.raises(ValueError):
            load_protocol(path)


def test_failed_pool_preserves_seed_and_closes_budget(tmp_path, monkeypatch):
    import run_et_warmstart_quality_gate_trial as runner
    from et_selection_trial_budget import SelectionTrialBudget

    protocol = runner.load_protocol(EVIDENCE / "protocol-no-retry.json")
    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps=protocol["independent_live_caps"], phases=runner.phases_for(protocol))

    def fail(*args, **kwargs):
        raise RuntimeError("simulated pool failure")

    monkeypatch.setattr(runner, "_phase", fail)
    result = runner.run_seed(protocol, seed=659578, budget=budget, root=tmp_path,
                             source_root=ROOT, software_fixture=True)
    assert result["seed"] == 659578 and result["status"] == "failed"
    assert result["failed_phase"] == "pool-659578"
    assert result["error_type"] == "RuntimeError" and result["cases"] == {}
    assert budget.state()["closed"] and budget.counts() == {"DFN": 0, "API": 0}


def test_live_preflight_rejects_missing_release_before_side_effects(tmp_path, monkeypatch):
    import run_et_warmstart_quality_gate_trial as runner

    monkeypatch.setattr(runner, "read_credential", lambda: pytest.fail("credential read before release"))
    with pytest.raises(ValueError, match="release"):
        runner.execute_live(evidence_dir=tmp_path / "evidence", output=tmp_path / "live")
    assert not (tmp_path / "live").exists()
    assert not (tmp_path / "evidence" / "budget.jsonl").exists()


def test_released_source_drift_is_rejected():
    import run_et_warmstart_quality_gate_trial as runner

    with pytest.raises(ValueError, match="source changed"):
        runner._check_source_pins({"source_pins": {"src/llmbo_para/electrothermal_llm.py": "0" * 64}})


def test_failed_ledger_start_clears_temporary_credential(tmp_path, monkeypatch):
    import os
    import run_et_warmstart_quality_gate_trial as runner

    monkeypatch.delenv("LLMBO_OPENCODE_API_KEY", raising=False)
    protocol = runner.load_protocol(EVIDENCE / "protocol-no-retry.json")
    monkeypatch.setattr(runner, "_live_preflight", lambda *a: (protocol, {"release_sha256": "x"}))
    monkeypatch.setattr(runner, "read_credential", lambda: "test-only-value")
    def fail(*args, **kwargs):
        raise RuntimeError("simulated ledger failure")
    monkeypatch.setattr(runner.SelectionTrialBudget, "start", fail)
    with pytest.raises(RuntimeError, match="ledger failure"):
        runner.execute_live(evidence_dir=tmp_path, output=tmp_path / "live")
    assert "LLMBO_OPENCODE_API_KEY" not in os.environ


def test_failed_second_arm_preserves_completed_pool_arm_and_charges(tmp_path, monkeypatch):
    import et_warmstart_selection_paired_worker as plans
    import run_et_warmstart_quality_gate_trial as runner
    from et_selection_trial_budget import SelectionTrialBudget

    protocol = runner.load_protocol(EVIDENCE / "protocol-no-retry.json")
    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps=protocol["independent_live_caps"], phases=runner.phases_for(protocol))
    fake_plans = {arm: {"path": str(tmp_path / arm), "sha256": arm} for arm in runner.RULES}
    fake_plans["shared_costs"] = {"solver_calls": 1}
    monkeypatch.setattr(runner, "_plan_configs", lambda *a, **k: {})
    monkeypatch.setattr(plans, "derive_selection_plans", lambda *a, **k: fake_plans)

    def phase(spec, current_budget, *args, **kwargs):
        if spec["kind"] == "warmstart_initialization":
            current_budget.charge("API", "request-1")
            current_budget.charge("DFN", "pool-solve-1")
            return {"audit_passed": True, "complete_pool_count": 16,
                    "selected_count": 8, "run_directory": str(tmp_path)}
        current_budget.charge("DFN", spec["label"] + "-solve")
        if spec["label"].endswith("v2"):
            raise RuntimeError("simulated arm failure")
        return {"audit_passed": True, "BO_rounds": 50,
                "initial_file_sha": "v1", "summary": {"API_calls": 0}}

    monkeypatch.setattr(runner, "_phase", phase)
    pair = runner.run_seed(protocol, seed=659578, budget=budget, root=tmp_path,
                           source_root=ROOT, software_fixture=True)
    assert pair["status"] == "failed" and pair["failed_phase"] == "arm-659578-v2"
    assert set(pair["cases"]) == {"v1"} and pair["pool"]["complete_pool_count"] == 16
    assert pair["costs"] == {"DFN": 3, "API": 1} and budget.state()["closed"]
    assert json.loads((tmp_path / "seed-659578-partial.json").read_text())["cases"] == pair["cases"]


def test_failure_between_phases_closes_parent_budget(tmp_path, monkeypatch):
    import et_warmstart_selection_paired_worker as plans
    import run_et_warmstart_quality_gate_trial as runner
    from et_selection_trial_budget import SelectionTrialBudget

    protocol = runner.load_protocol(EVIDENCE / "protocol-no-retry.json")
    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps=protocol["independent_live_caps"], phases=runner.phases_for(protocol))
    monkeypatch.setattr(runner, "_phase", lambda *a, **k: {
        "audit_passed": True, "complete_pool_count": 16,
        "selected_count": 8, "run_directory": str(tmp_path)})
    monkeypatch.setattr(runner, "_plan_configs", lambda *a, **k: {})
    monkeypatch.setattr(plans, "derive_selection_plans", lambda *a, **k: {"shared_costs": {}})
    original_write = runner._write_json
    attempts = 0

    def fail_once(path, value):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("simulated partial result write failure")
        original_write(path, value)

    monkeypatch.setattr(runner, "_write_json", fail_once)
    result = runner.run_seed(protocol, seed=659578, budget=budget, root=tmp_path,
                             source_root=ROOT, software_fixture=True)
    assert result["status"] == "failed" and result["error_type"] == "OSError"
    assert budget.state()["closed"] is True
    assert json.loads((tmp_path / "seed-659578-partial.json").read_text())["status"] == "failed"


def test_one_seed_mock_has_three_independent_fifty_round_arms(tmp_path):
    import run_et_warmstart_quality_gate_trial as runner
    from et_selection_trial_budget import SelectionTrialBudget

    protocol = runner.load_protocol(EVIDENCE / "protocol-no-retry.json")
    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps=protocol["independent_live_caps"], phases=runner.phases_for(protocol))
    pair = runner.run_seed(protocol, seed=659578, budget=budget, root=tmp_path,
                           source_root=ROOT, software_fixture=True)
    assert pair["status"] == "completed", pair
    assert pair["pool"]["complete_pool_count"] == 16
    assert set(pair["cases"]) == {"v1", "v2", "v3"}
    assert len({pair["cases"][arm]["run_directory"] for arm in pair["cases"]}) == 3
    assert budget.counts() == {"DFN": 0, "API": 0}
    weights = []
    for arm, case in pair["cases"].items():
        assert case["BO_rounds"] == 50 and case["audit_passed"]
        assert case["summary"]["API_calls"] == 0
        assert case["initial_file_sha"] == pair["plans"][arm]["sha256"]
        weights.append([row["weight"] for row in case["rounds"]])
    assert weights[0] == weights[1] == weights[2]
    import analyze_et_warmstart_quality_gate_trial as analyzer
    analysis = analyzer.analyze_seed(pair, protocol)
    assert set(analysis["arms"]) == {"v1", "v2", "v3"}
    assert all(len(analysis["arms"][arm]["rounds"]) == 50 for arm in runner.RULES)
    tampered = deepcopy(pair)
    tampered["cases"]["v1"]["representative"]["objectives"][0] += .1
    with pytest.raises(ValueError):
        analyzer.analyze_seed(tampered, protocol)


def test_independent_pareto_hv_and_unit_scaled_representative():
    from analyze_et_warmstart_quality_gate_trial import front, exact_hv, representative

    rows = [
        {"evaluation_id": "a", "parameters": [.1]*6, "objectives": [1., 4.]},
        {"evaluation_id": "b", "parameters": [.2]*6, "objectives": [2., 2.]},
        {"evaluation_id": "c", "parameters": [.3]*6, "objectives": [3., 1.]},
        {"evaluation_id": "d", "parameters": [.4]*6, "objectives": [4., 4.]},
    ]
    pareto = front(rows)
    assert {row["evaluation_id"] for row in pareto} == {"a", "b", "c"}
    assert exact_hv([row["objectives"] for row in pareto], reference=(5., 5.)) == 12.
    chosen = representative(pareto, normalize=lambda x: x, scales=(1., 1.))
    scaled = [{**r, "objectives": [r["objectives"][0]*1000, r["objectives"][1]]} for r in pareto]
    assert representative(scaled, normalize=lambda x: x, scales=(1000., 1.))["evaluation_id"] == chosen["evaluation_id"]


def test_trial_analysis_rejects_underreported_parent_cost(tmp_path, monkeypatch):
    import analyze_et_warmstart_quality_gate_trial as analyzer
    import run_et_warmstart_quality_gate_trial as runner

    protocol = runner.load_protocol(EVIDENCE / "protocol-no-retry.json")
    pairs = [{"seed": seed, "status": "completed"} for seed in runner.SEEDS]
    archive = tmp_path / "result.json"
    archive.write_text(json.dumps({"status": "completed", "pairs": pairs,
                                   "costs": {"DFN": 0, "API": 0}}))
    def fake_analysis(pair, _protocol):
        return {"seed": pair["seed"], "shared_pool_costs": {"solver_calls": 32, "llm_requests": 1},
                "arms": {arm: {"formal_DFN": 100} for arm in runner.RULES},
                "delta_final_HV_v3_v2": 0., "delta_final_HV_v3_v1": 0.}
    monkeypatch.setattr(analyzer, "analyze_seed", fake_analysis)
    with pytest.raises(ValueError, match="parent budget"):
        analyzer.analyze_trial(archive, protocol)


def test_archive_accepts_cached_round_id_but_rejects_unseen_record():
    from analyze_et_warmstart_quality_gate_trial import verify_archive_ids

    records = [{"evaluation_id": "a"}, {"evaluation_id": "b"}, {"evaluation_id": "c"}]
    assert set(verify_archive_ids(records, ["a", "b"], ["c", "c"])) == {"a", "b", "c"}
    with pytest.raises(ValueError, match="archive"):
        verify_archive_ids(records + [{"evaluation_id": "extra"}], ["a", "b"], ["c", "c"])


def test_mock_supervisor_closes_all_phases_without_real_cost(tmp_path, monkeypatch):
    import analyze_et_warmstart_quality_gate_trial as analyzer
    import run_et_warmstart_quality_gate_trial as runner

    def fake_seed(protocol, *, seed, budget, root, source_root, software_fixture):
        assert software_fixture is True
        budget.begin(f"pool-{seed}")
        budget.finish(True)
        for arm in protocol["arm_order_by_seed"][str(seed)]:
            budget.begin(f"arm-{seed}-{arm}")
            budget.finish(True)
        return {"seed": seed, "status": "completed", "cases": {arm: {} for arm in runner.RULES}}

    monkeypatch.setattr(runner, "run_seed", fake_seed)
    monkeypatch.setattr(analyzer, "analyze_seed", lambda pair, protocol: {"status": "completed"})
    monkeypatch.setattr(analyzer, "analyze_trial", lambda path, protocol: {"status": "completed"})
    result = runner.run_mock_rehearsal(output=tmp_path / "mock")
    assert result == {"status": "completed", "cases": 15, "rounds": 750,
                      "API": 0, "DFN": 0}
    assert (tmp_path / "mock" / "analysis.json").is_file()


def test_live_preflight_refuses_missing_release_before_credential_or_budget(tmp_path, monkeypatch):
    import run_et_warmstart_quality_gate_trial as runner

    monkeypatch.setattr(runner, "read_credential", lambda: pytest.fail("credential accessed"))
    with pytest.raises(ValueError, match="release"):
        runner.execute_live(evidence_dir=tmp_path / "evidence", output=tmp_path / "live")
    assert not (tmp_path / "live").exists()
    assert not (tmp_path / "evidence" / "budget.jsonl").exists()
