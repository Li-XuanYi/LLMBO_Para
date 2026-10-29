"""Fail-fast trial policy; all simulators and transports here are software doubles."""
import json
from pathlib import Path
import sys

import pytest

from electrothermal_fixtures import et_config


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_trial_evaluator_stops_after_first_failed_rate_and_preserves_partial_result():
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_provenance import verify_evaluation
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset

    rates = ("0.5C", "1C")
    space = parameter_space_from_config(et_config(rates))

    class FailingSimulator:
        backend_kind = "software"

        def __init__(self):
            self.calls = []

        def simulate(self, params, case):
            self.calls.append(case.rate)
            raise RuntimeError("synthetic solver failure")

    simulator = FailingSimulator()
    dataset = make_synthetic_dataset(rates)
    evaluator = ElectrothermalEvaluator(space, simulator, fit_rates=rates,
                                       max_rate_attempts=1, stop_on_failure=True)
    result = evaluator.evaluate(space.denormalize([.5] * 6), dataset)
    assert simulator.calls == ["0.5C"]
    assert result.complete_pair_valid is False and result.objectives is None
    assert result.costs["software_calls"] == 1
    assert len(result.rates[0].attempts) == 1 and not result.rates[1].attempts
    assert "not attempted" in result.rates[1].voltage.reason
    assert "not attempted" in result.rates[1].cell_temperature.reason
    assert verify_evaluation(result, dataset)


def test_default_evaluator_keeps_legacy_all_rate_behavior():
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset

    rates = ("0.5C", "1C")
    space = parameter_space_from_config(et_config(rates))

    class FailingSimulator:
        backend_kind = "software"
        calls = []

        def simulate(self, params, case):
            self.calls.append(case.rate)
            raise RuntimeError("synthetic solver failure")

    simulator = FailingSimulator()
    evaluator = ElectrothermalEvaluator(space, simulator, fit_rates=rates, max_rate_attempts=1)
    evaluator.evaluate(space.denormalize([.5] * 6), make_synthetic_dataset(rates))
    assert simulator.calls == ["0.5C", "1C"]


def test_trial_evaluator_does_not_retry_transient_solver_failure():
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    from llmbo_para.evaluation import TransientSimulationError

    rates = ("0.5C", "1C")
    space = parameter_space_from_config(et_config(rates))

    class TransientFailure:
        backend_kind = "software"

        def __init__(self):
            self.calls = []

        def simulate(self, params, case):
            self.calls.append(case.rate)
            raise TransientSimulationError("synthetic transient failure")

    simulator = TransientFailure()
    evaluator = ElectrothermalEvaluator(space, simulator, fit_rates=rates,
                                       max_rate_attempts=3, stop_on_failure=True)
    result = evaluator.evaluate(space.denormalize([.5] * 6), make_synthetic_dataset(rates))
    assert simulator.calls == ["0.5C"]
    assert result.costs["retry_calls"] == 0 and result.objectives is None


def test_trial_evaluator_stops_on_missing_temperature_without_fabricating_zero():
    from dataclasses import replace
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_provenance import verify_evaluation
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator, make_synthetic_dataset

    rates = ("0.5C", "1C")
    space = parameter_space_from_config(et_config(rates))

    class MissingTemperature(SyntheticElectrothermalSimulator):
        def __init__(self):
            self.calls = []

        def simulate(self, params, case):
            self.calls.append(case.rate)
            return replace(super().simulate(params, case), temperature_k=None)

    simulator = MissingTemperature()
    dataset = make_synthetic_dataset(rates)
    result = ElectrothermalEvaluator(space, simulator, fit_rates=rates,
        stop_on_failure=True).evaluate(space.denormalize([.5] * 6), dataset)
    assert simulator.calls == ["0.5C"]
    assert result.rates[0].voltage.valid and not result.rates[0].cell_temperature.valid
    assert result.rates[0].cell_temperature.rmse_k is None and result.objectives is None
    assert not result.rates[1].attempts and verify_evaluation(result, dataset)


def test_trial_guard_saves_partial_result_before_aborting():
    from et_three_arm_validation_worker import install_trial_failure_guard, TrialIncompleteEvaluation

    class Store:
        def __init__(self):
            self.saved = []

        def save_evaluation(self, result, **kwargs):
            self.saved.append((result, kwargs))
            return "saved.json"

    class Result:
        complete_pair_valid = False

    store, result = Store(), Result()
    install_trial_failure_guard(store)
    with pytest.raises(TrialIncompleteEvaluation):
        store.save_evaluation(result, phase="BO", cached=False)
    assert store.saved == [(result, {"phase": "BO", "cached": False})]


def test_worker_preserves_legacy_evaluator_interface_and_fails_closed_for_strict_policy():
    from et_three_arm_validation_worker import make_worker_evaluator

    class LegacyEvaluator:
        def __init__(self, space, backend, *, fit_rates, max_rate_attempts):
            self.fit_rates = fit_rates

    evaluator = make_worker_evaluator(LegacyEvaluator, object(), object(),
                                      fit_rates=("0.5C", "1C"), spec={})
    assert evaluator.fit_rates == ("0.5C", "1C")
    with pytest.raises(ValueError, match="strict trial policy"):
        make_worker_evaluator(LegacyEvaluator, object(), object(),
                              fit_rates=("0.5C", "1C"), spec={"stop_on_failure": True})


def test_failed_bo_candidate_is_persisted_then_stops_before_next_round(tmp_path):
    from et_three_arm_validation_worker import install_trial_failure_guard, TrialIncompleteEvaluation
    from test_mo_optimizer import make_optimizer

    optimizer = make_optimizer(tmp_path)
    optimizer.initialize()

    class FailingSimulator:
        backend_kind = "software"

        def __init__(self):
            self.calls = []

        def simulate(self, params, case):
            self.calls.append(case.rate)
            raise RuntimeError("synthetic solver failure")

    simulator = FailingSimulator()
    optimizer.evaluator.simulator = simulator
    optimizer.evaluator.stop_on_failure = True
    install_trial_failure_guard(optimizer.store)
    with pytest.raises(TrialIncompleteEvaluation):
        optimizer.step()
    assert simulator.calls == [optimizer.dataset.fit_rates[0]]
    assert optimizer.rounds == [] and len(optimizer.history) == 2
    files = sorted((optimizer.store.path / "electrothermal-evaluations").glob("*.json"))
    saved = json.loads(files[-1].read_text(encoding="utf-8"))
    assert not saved["complete_pair_valid"] and saved["objectives"] is None
    assert saved["rates"][1]["attempts"] == []


def test_failed_warmstart_candidate_is_persisted_then_stops_screening(tmp_path):
    from et_three_arm_validation_worker import install_trial_failure_guard, TrialIncompleteEvaluation
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from test_electrothermal_llm import Proposed

    cfg = et_config(); cfg["optimization"]["mode"] = "warmstart_only"
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)

    class FailingSimulator:
        backend_kind = "software"

        def __init__(self):
            self.calls = []

        def simulate(self, params, case):
            self.calls.append(case.rate)
            raise RuntimeError("synthetic solver failure")

    simulator = FailingSimulator()
    evaluator = ElectrothermalEvaluator(prepared.space, simulator,
        fit_rates=prepared.dataset.fit_rates, stop_on_failure=True)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
        signatures=prepared.signatures, command="strict warmstart test")
    install_trial_failure_guard(store)
    transport = Proposed(prepared.space, [[.2] * 6, [.8] * 6, [.4] * 6])
    controller = ElectrothermalLLMController(transport=transport, is_mock=True, evaluator=evaluator)
    with pytest.raises(TrialIncompleteEvaluation):
        controller.generate_warmstart(prepared, store=store, budgets=cfg["budgets"])
    assert simulator.calls == [prepared.dataset.fit_rates[0]] and transport.calls == 1
    files = list((store.path / "electrothermal-evaluations").glob("*.json"))
    assert len(files) == 1 and not json.loads(files[0].read_text())["complete_pair_valid"]
    assert not (store.path / "initial-plan.json").exists()


def test_invalid_warmstart_reply_is_recorded_and_not_retried(tmp_path):
    from et_three_arm_validation_worker import install_trial_reply_guard, TrialInvalidReply
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    cfg = et_config(); cfg["optimization"]["mode"] = "warmstart_only"
    cfg["optimization"]["warmstart"]["max_requests"] = 2
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
        signatures=prepared.signatures, command="strict reply test")
    install_trial_reply_guard(store)

    class InvalidReply:
        calls = 0

        def post(self, payload):
            self.calls += 1
            return {"candidates": []}

    transport = InvalidReply()
    controller = ElectrothermalLLMController(transport=transport, is_mock=True)
    with pytest.raises(TrialInvalidReply):
        controller.generate_warmstart(prepared, store=store, budgets=cfg["budgets"])
    assert transport.calls == 1
    assert store.ledger.summary()["screening_rejections"] == 1
    assert store.ledger.summary()["software_calls"] == 0


def test_default_warmstart_controller_retains_legacy_invalid_reply_behavior(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    cfg = et_config(); cfg["optimization"]["mode"] = "warmstart_only"
    cfg["optimization"]["warmstart"]["max_requests"] = 2
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
        signatures=prepared.signatures, command="legacy reply test")

    class InvalidReply:
        calls = 0

        def post(self, payload):
            self.calls += 1
            return {"candidates": []}

    transport = InvalidReply()
    controller = ElectrothermalLLMController(transport=transport, is_mock=True)
    with pytest.raises(ValueError, match="insufficient_initialization"):
        controller.generate_warmstart(prepared, store=store, budgets=cfg["budgets"])
    assert transport.calls == 2 and store.ledger.summary()["screening_rejections"] == 2


def test_parent_rejects_completed_arm_with_failed_solver_or_partial_pair(tmp_path, monkeypatch):
    import et_warmstart_selection_paired_worker as plans
    import run_et_warmstart_quality_gate_trial as runner
    from et_selection_trial_budget import SelectionTrialBudget

    protocol = runner.load_protocol()
    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps=runner.CAPS, phases=runner.phases_for(protocol))
    fake_plans = {arm: {"path": str(tmp_path / arm), "sha256": arm} for arm in runner.RULES}
    fake_plans["shared_costs"] = {"solver_calls": 1}
    monkeypatch.setattr(runner, "_plan_configs", lambda *a, **k: {})
    monkeypatch.setattr(plans, "derive_selection_plans", lambda *a, **k: fake_plans)
    labels = []

    def fake_phase(spec, *args, **kwargs):
        labels.append(spec["label"])
        if spec["kind"] == "warmstart_initialization":
            return {"audit_passed": True, "complete_pool_count": 16,
                    "selected_count": 8, "run_directory": str(tmp_path)}
        arm = spec["label"].rsplit("-", 1)[-1]
        return {"audit_passed": True, "BO_rounds": 50, "initial_file_sha": arm,
                "summary": {"API_calls": 0, "costs": {"failed_solver_calls": 1}},
                "rounds": [{"complete_pair_valid": False}] * 50}

    monkeypatch.setattr(runner, "_phase", fake_phase)
    pair = runner.run_seed(protocol, seed=659578, budget=budget, root=tmp_path,
                           source_root=ROOT, software_fixture=True)
    assert pair["status"] == "failed"
    assert labels == ["seed-659578-pool", "seed-659578-v1"]
    assert budget.state()["closed"] is True
    saved = json.loads((tmp_path / "seed-659578-partial.json").read_text())
    assert saved["status"] == "failed" and saved["failed_phase"] == "arm-659578-v1"


def test_trial_phase_explicitly_enables_worker_failure_policy(tmp_path, monkeypatch):
    import run_et_warmstart_quality_gate_trial as runner
    import run_lgbo_real_gain as helper
    from et_selection_trial_budget import SelectionTrialBudget

    protocol = runner.load_protocol()
    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps=runner.CAPS, phases=runner.phases_for(protocol))
    budget.begin("pool-659578")
    captured = {}

    def supervise(worker, spec, budget, *, deadline, metadata, integrity_check):
        captured.update(spec)
        Path(metadata).write_text(json.dumps({"owned_tree_stopped": True}))
        return {"status": "fixture"}

    monkeypatch.setattr(helper, "supervise", supervise)
    runner._phase({"kind": "warmstart_initialization", "arm": "warmstart_only",
                   "seed": 659578, "label": "phase", "solve_cap": 0},
                  budget, protocol, root=tmp_path, source_root=ROOT, software_fixture=True)
    assert captured["stop_on_failure"] is True


def test_execution_pin_records_and_checks_trial_failure_policy(tmp_path):
    from et_three_arm_validation_worker import execution_pin
    from run_et_warmstart_quality_gate_trial import verify_trial_failure_policy

    strict = execution_pin(tmp_path, {"source": "fixture", "stop_on_failure": True})
    assert strict["stop_on_failure"] is True
    assert "stop_on_failure" not in execution_pin(tmp_path, {"source": "fixture"})
    path = tmp_path / "source-execution-pin.json"
    path.write_text(json.dumps(strict))
    verify_trial_failure_policy(tmp_path)
    strict["stop_on_failure"] = False
    path.write_text(json.dumps(strict))
    with pytest.raises(ValueError, match="failure policy"):
        verify_trial_failure_policy(tmp_path)
