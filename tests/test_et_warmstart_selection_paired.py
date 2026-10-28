"""Offline gates for the paired v1/v2 WarmStart selection study."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_et_warmstart_selection_paired.py"
PROPOSAL = Path(
    "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/"
    "20261017_et_implementation/warmstart-v1-v2-paired-20261027/"
    "proposal/protocol-proposal.json"
)
OLD_SEEDS = {376330, 633262, 789058, 609653, 362724}


def load():
    assert SCRIPT.is_file(), "paired runner is missing"
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_et_warmstart_selection_paired", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_worker():
    script = ROOT / "scripts/et_warmstart_selection_paired_worker.py"
    assert script.is_file(), "paired pool worker is missing"
    if str(script.parent) not in sys.path:
        sys.path.insert(0, str(script.parent))
    spec = importlib.util.spec_from_file_location("et_warmstart_selection_paired_worker", script)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def paired_pool(tmp_path_factory):
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    import et_three_arm_validation_worker as source_worker
    import run_et_three_arm_validation as legacy_runner

    base = tmp_path_factory.mktemp("paired-pool")
    seed = 152325
    source = ROOT
    base_config = json.loads(Path(json.loads(PROPOSAL.read_text(encoding="utf-8"))["configs"][str(seed)]["path"])
                             .read_text(encoding="utf-8"))
    budget = legacy_runner.new_budget(base / "budget.jsonl", protocol_sha="c" * 64)
    budget.begin("diagnostic")
    budget.finish(True)
    budget.begin("initialization")
    spec = {"kind": "warmstart_initialization", "arm": "warmstart_only",
            "label": "paired-pool-mock", "source_root": str(source),
            "source": legacy_runner.helper.fingerprint(source),
            "output": str(base / "paired-pool-mock"), "deadline": budget.deadline,
            "base_config": base_config, "seed": seed, "software_fixture": True,
            "solve_cap": 0}
    result = legacy_runner.helper.supervise(source_worker.run_worker, spec, budget,
                                            deadline=time.monotonic() + 180,
                                            metadata=base / "paired-pool-owned.json")
    assert result["audit_passed"] and result["complete_pool_count"] == 16
    assert budget.counts() == {"DFN": 0, "API": 0}
    config = source_worker.config_for(base_config, kind="warmstart_initialization",
                                      arm="warmstart_only", seed=seed,
                                      remaining=120, initial_plan=None)
    config["model"]["provider"] = "software"
    config["run_kind"] = "synthetic_software"
    config["llm"]["enabled"] = False
    config["budgets"]["max_solver_calls"] = 0
    config["budgets"]["max_llm_requests"] = 0
    v2 = deepcopy(config)
    v2["optimization"]["warmstart"]["selection_rule"] = "pareto_core_spacefill_v2"
    return Path(result["run_directory"]), {"v1": config, "v2": v2}, base


def write_protocol(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_protocol_has_five_novel_seeds_ten_cases_and_exact_upper_bounds():
    runner = load()
    protocol = runner.load_protocol(PROPOSAL)
    assert protocol["seeds"] == [260437, 152325, 947445, 235695, 299924]
    assert not set(protocol["seeds"]) & OLD_SEEDS
    assert protocol["seed_run_order"] == [152325, 235695, 947445, 260437, 299924]
    assert [row["arm"] for row in runner.cases(protocol)] == [
        "v1", "v2", "v2", "v1", "v1", "v2", "v2", "v1", "v1", "v2"
    ]
    assert len(runner.cases(protocol)) == 10
    assert protocol["candidate_pool_size"] == 16
    assert protocol["initial_count_per_arm"] == 8
    assert protocol["new_bo_rounds_per_arm"] == 50
    assert protocol["independent_live_caps_if_released"] == {
        "DFN": 1160, "API": 15, "wall_clock_s": 28800
    }


@pytest.mark.parametrize("field,value", [
    ("seeds", [260437, 152325, 947445, 235695, 376330]),
    ("seed_run_order", [260437, 152325, 947445, 235695, 299924]),
    ("fit_rates", ["0.5C", "1C", "3C"]),
    ("candidate_pool_size", 8),
    ("new_bo_rounds_per_arm", 20),
    ("independent_live_caps_if_released", {"DFN": 1161, "API": 15, "wall_clock_s": 28800}),
])
def test_protocol_mutation_is_rejected(tmp_path, field, value):
    runner = load()
    payload = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    payload[field] = value
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, payload))


def test_arm_order_or_config_pin_mutation_is_rejected(tmp_path):
    runner = load()
    original = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    changed = deepcopy(original)
    changed["arm_order_by_seed"]["152325"] = ["v2", "v1"]
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, changed))
    changed = deepcopy(original)
    changed["configs"]["152325"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, changed))
    changed = deepcopy(original)
    first = next(iter(changed["source_files"]))
    changed["source_files"][first] = "0" * 64
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, changed))


def test_dry_run_neither_reads_credential_nor_creates_output(tmp_path, monkeypatch):
    runner = load()
    monkeypatch.setattr(runner, "read_credential", lambda: pytest.fail("credential read"))
    destination = tmp_path / "live-run"
    result = runner.dry_run(PROPOSAL, output=destination)
    assert result["dry_run"] is True
    assert result["planned_cases"] == 10
    assert result["new_rounds"] == 500
    assert result["API"] == result["DFN"] == 0
    assert not destination.exists()


def test_parent_budget_charges_before_effect_and_rejects_duplicate_or_closed(tmp_path):
    runner = load()
    budget = runner.PairedBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64)
    budget.begin("pool-152325")
    budget.require(32)
    with pytest.raises(RuntimeError):
        budget.require(33)
    budget.charge("API", "pool-152325-request-1")
    with pytest.raises(RuntimeError):
        budget.charge("API", "pool-152325-request-1")
    budget.charge("DFN", "pool-152325-solve-1")
    assert budget.counts() == {"DFN": 1, "API": 1}
    assert 0 < budget.deadline - time.monotonic() <= 28800
    budget.finish(False)
    with pytest.raises(RuntimeError):
        budget.begin("arm-152325-v1")


def test_budget_rejects_tampered_hash_chain_and_phase_overcap(tmp_path):
    runner = load()
    path = tmp_path / "budget.jsonl"
    budget = runner.PairedBudget.start(path, protocol_sha="b" * 64)
    budget.begin("pool-152325")
    for i in range(3):
        budget.charge("API", f"pool-152325-request-{i}")
    with pytest.raises(RuntimeError):
        budget.charge("API", "pool-152325-request-overcap")
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace("request-0", "request-x"), encoding="utf-8")
    with pytest.raises(ValueError):
        budget.state()


def test_shared_pool_yields_two_rule_bound_plans_and_reproduces_v1_ids(paired_pool, tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_provenance import load_initial_plan

    pool, configs, base = paired_pool
    worker = load_worker()
    result = worker.derive_paired_plans(pool, configs=configs, out=tmp_path / "plans")
    original = json.loads((pool / "warmstart-selection.json").read_text(encoding="utf-8"))
    assert result["v1"]["selected_ids"] == original["selected_ids"]
    assert result["pool_size"] == 16
    assert result["shared_costs"]["solver_calls"] == 0
    assert result["shared_costs"]["software_calls"] == 32
    assert result["v1"]["sha256"] != result["v2"]["sha256"]
    assert result["v1"]["selected_ids"] != result["v2"]["selected_ids"]
    assert Path(result["manifest_path"]).is_file()
    selections = {}
    for rule in ("v1", "v2"):
        report, prepared = prepare_electrothermal_experiment(configs[rule], base_dir=base)
        assert report["ready"] and prepared is not None
        selections[rule] = prepared.signatures
        loaded = load_initial_plan(result[rule]["path"], space=prepared.space,
                                   dataset=prepared.dataset, signatures=prepared.signatures,
                                   expected_selection_rule=configs[rule]["optimization"]["warmstart"]["selection_rule"])
        assert len(loaded.records) == 8
        other = "v2" if rule == "v1" else "v1"
        with pytest.raises(ValueError):
            load_initial_plan(result[other]["path"], space=prepared.space,
                              dataset=prepared.dataset, signatures=prepared.signatures,
                              expected_selection_rule=configs[rule]["optimization"]["warmstart"]["selection_rule"])
    assert selections["v1"].model_evaluation == selections["v2"].model_evaluation
    assert selections["v1"].data == selections["v2"].data
    assert selections["v1"].evaluation_protocol == selections["v2"].evaluation_protocol
    assert selections["v1"].initialization_compatibility != selections["v2"].initialization_compatibility
    left = json.loads(Path(result["v1"]["path"]).read_text(encoding="utf-8"))
    right = json.loads(Path(result["v2"]["path"]).read_text(encoding="utf-8"))
    for a, b in zip(left["history_evidence"]["screening_records"],
                    right["history_evidence"]["screening_records"]):
        assert (a["parameters"], a["rates"], a["objectives"]) == (
            b["parameters"], b["rates"], b["objectives"])


def test_pair_derivation_rejects_rule_and_source_mutations(paired_pool, tmp_path):
    pool, configs, _ = paired_pool
    worker = load_worker()
    bad = deepcopy(configs)
    bad["v2"]["optimization"]["warmstart"]["selection_rule"] = "pareto_maximin_v1"
    with pytest.raises(ValueError):
        worker.derive_paired_plans(pool, configs=bad, out=tmp_path / "bad-rule")
    altered = tmp_path / "altered"
    shutil.copytree(pool, altered)
    selection = altered / "warmstart-selection.json"
    payload = json.loads(selection.read_text(encoding="utf-8"))
    payload["selected_ids"] = list(reversed(payload["selected_ids"]))
    selection.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        worker.derive_paired_plans(altered, configs=configs, out=tmp_path / "bad-source")


def test_pair_derivation_rejects_incomplete_or_duplicate_pool(paired_pool, tmp_path):
    pool, configs, _ = paired_pool
    worker = load_worker()
    altered = tmp_path / "partial"
    shutil.copytree(pool, altered)
    evaluations = sorted((altered / "electrothermal-evaluations").glob("*.json"))
    assert len(evaluations) == 16
    evaluations[0].unlink()
    with pytest.raises(ValueError):
        worker.derive_paired_plans(altered, configs=configs, out=tmp_path / "bad-partial")
    altered = tmp_path / "duplicate"
    shutil.copytree(pool, altered)
    evaluations = sorted((altered / "electrothermal-evaluations").glob("*.json"))
    first = json.loads(evaluations[0].read_text(encoding="utf-8"))
    second = json.loads(evaluations[1].read_text(encoding="utf-8"))
    second["parameters"] = first["parameters"]
    evaluations[1].write_text(json.dumps(second), encoding="utf-8")
    with pytest.raises(ValueError):
        worker.derive_paired_plans(altered, configs=configs, out=tmp_path / "bad-duplicate")


@pytest.mark.parametrize("mutation", ["temperature", "cost", "signature"])
def test_pair_derivation_rejects_temperature_cost_or_signature_tampering(
        paired_pool, tmp_path, mutation):
    from llmbo_para.runstore import digest_value

    pool, configs, _ = paired_pool
    worker = load_worker()
    altered = tmp_path / mutation
    shutil.copytree(pool, altered)
    if mutation == "temperature":
        path = sorted((altered / "electrothermal-evaluations").glob("*.json"))[0]
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["rates"][0]["cell_temperature"]["valid"] = False
    else:
        path = altered / "initial-plan.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "cost":
            payload["history_evidence"]["costs"]["software_calls"] = 0
        else:
            payload["history_evidence"]["screening_records"][0]["signatures"][
                "initialization_compatibility"] = "0" * 64
        payload.pop("plan_sha256")
        payload["plan_sha256"] = digest_value(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        worker.derive_paired_plans(altered, configs=configs, out=tmp_path / "bad-plan")


@pytest.fixture(scope="module")
def paired_mock_case(tmp_path_factory):
    root = tmp_path_factory.mktemp("paired-closure")
    runner = load()
    protocol = runner.load_protocol(PROPOSAL)
    budget = runner.PairedBudget.start(root / "budget.jsonl", protocol_sha="d" * 64)
    pair = runner.run_seed_pair(protocol, seed=152325, budget=budget,
                                root=root, source_root=ROOT, software_fixture=True)
    return root, protocol, budget, pair


def test_mock_pair_closure_has_two_fifty_round_arms_without_region_or_real_calls(paired_mock_case):
    root, protocol, budget, pair = paired_mock_case
    assert pair["seed"] == 152325
    assert pair["pool"]["complete_pool_count"] == 16
    assert pair["plans"]["v1"]["selected_ids"] != pair["plans"]["v2"]["selected_ids"]
    assert budget.counts() == {"DFN": 0, "API": 0}
    assert list(pair["cases"]) == ["v1", "v2"]
    assert pair["cases"]["v1"]["run_directory"] != pair["cases"]["v2"]["run_directory"]
    for rule in ("v1", "v2"):
        case = pair["cases"][rule]
        assert case["audit_passed"] and case["BO_rounds"] == 50
        assert len(case["rounds"]) == 50
        assert case["summary"]["API_calls"] == 0
        assert case["initial_file_sha"] == pair["plans"][rule]["sha256"]
    assert [row["weight"] for row in pair["cases"]["v1"]["rounds"]] == [
        row["weight"] for row in pair["cases"]["v2"]["rounds"]]
    assert pair["cases"]["v1"]["first_numerical_context_sha"] != pair["cases"]["v2"]["first_numerical_context_sha"]


def test_independent_pair_analysis_recomputes_both_rmse_hv_and_costs(paired_mock_case):
    root, protocol, _, pair = paired_mock_case
    import analyze_et_warmstart_selection_paired as analyzer

    report = analyzer.analyze_seed(pair, protocol)
    assert report["seed"] == 152325
    assert report["status"] == "completed"
    assert set(report["arms"]) == {"v1", "v2"}
    assert all(len(report["arms"][arm]["rounds"]) == 50 for arm in ("v1", "v2"))
    assert all(report["arms"][arm]["final_F_U_V"] >= 0 and
               report["arms"][arm]["final_F_T_K"] >= 0 for arm in ("v1", "v2"))
    assert report["pool_charged_once"] is True
    assert report["delta_final_HV"] == pytest.approx(
        report["arms"]["v2"]["final_HV"] - report["arms"]["v1"]["final_HV"])
    assert report["metric_space"] == {"objective_scales": [0.1, 1.0],
                                      "hv_reference": [10.0, 10.0]}


@pytest.mark.parametrize("mutation", ["temperature", "plan_hash", "cost", "scale"])
def test_pair_analysis_rejects_tampered_curve_plan_cost_or_scale(paired_mock_case, mutation):
    _, protocol, _, pair = paired_mock_case
    import analyze_et_warmstart_selection_paired as analyzer

    bad = deepcopy(pair)
    if mutation == "temperature":
        bad["cases"]["v1"]["rounds"][0]["rates"][0]["cell_temperature"]["predicted"][0] += 1.0
    elif mutation == "plan_hash":
        bad["plans"]["v2"]["sha256"] = "0" * 64
    elif mutation == "cost":
        bad["pool"]["costs"]["solver_calls"] += 1
    else:
        bad["metric_space"]["objective_scales"] = [1.0, 1.0]
    with pytest.raises(ValueError):
        analyzer.analyze_seed(bad, protocol)


def test_failed_pool_phase_closes_budget_and_cannot_launch_arms(tmp_path, monkeypatch):
    runner = load()
    protocol = runner.load_protocol(PROPOSAL)
    budget = runner.PairedBudget.start(tmp_path / "budget.jsonl", protocol_sha="e" * 64)

    def fail_pool(*args, **kwargs):
        raise RuntimeError("mock API/DFN failure before pool completion")

    monkeypatch.setattr(runner, "_phase", fail_pool)
    with pytest.raises(RuntimeError, match="mock API/DFN failure"):
        runner.run_seed_pair(protocol, seed=152325, budget=budget,
                             root=tmp_path, source_root=ROOT, software_fixture=True)
    assert budget.state()["closed"] is True
    assert budget.state()["finished"] == ["pool-152325"]


def test_live_preflight_refuses_absent_release_without_claiming_budget(tmp_path):
    runner = load()
    with pytest.raises(ValueError, match="release"):
        runner.execute_live(evidence_dir=tmp_path / "evidence",
                            output=tmp_path / "live")
    assert not (tmp_path / "live").exists()
    assert not (tmp_path / "evidence" / "budget.jsonl").exists()


def test_live_preflight_refuses_existing_output_without_claiming_budget(tmp_path):
    runner = load()
    output = tmp_path / "live"
    output.mkdir()
    with pytest.raises(ValueError):
        runner.execute_live(evidence_dir=tmp_path / "evidence", output=output)
    assert not (tmp_path / "evidence" / "budget.jsonl").exists()


def test_five_seed_mock_rehearsal_has_ten_cases_five_hundred_rounds_and_zero_real_cost(tmp_path):
    runner = load()
    result = runner.run_mock_rehearsal(output=tmp_path / "mock")
    assert result == {"status": "completed", "cases": 10, "rounds": 500,
                      "API": 0, "DFN": 0}
    assert (tmp_path / "mock" / "analysis.json").is_file()
    assert not (tmp_path / "mock" / "result.json").read_text(encoding="utf-8").count('"status": "failed"')
