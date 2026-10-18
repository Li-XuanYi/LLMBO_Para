"""Task-specific request budgets and observable, non-mutating failure fallback."""
import json

import pytest

from electrothermal_fixtures import et_config


WARM = "warm_start_electrothermal"
REGION = "region_preference_electrothermal"


def request_config():
    cfg = et_config()
    cfg["llm"].update(timeout_s=120., max_tokens=4096)
    return cfg


def test_explicit_task_limits_and_partial_overrides_inherit_global(tmp_path):
    from llmbo_para.electrothermal_requests import request_controls
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    cfg = request_config()
    cfg["llm"]["task_options"] = {
        WARM: {"timeout_s": 120., "max_tokens": 4096},
        REGION: {"timeout_s": 30., "max_tokens": 1536},
    }
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is not None, report["errors"]
    assert request_controls(cfg, WARM) == {"timeout_s": 120., "max_tokens": 4096}
    assert request_controls(cfg, REGION) == {"timeout_s": 30., "max_tokens": 1536}

    cfg["llm"]["task_options"] = {REGION: {"max_tokens": 1536}}
    assert request_controls(cfg, REGION) == {"timeout_s": 120., "max_tokens": 1536}
    assert request_controls(cfg, WARM) == {"timeout_s": 120., "max_tokens": 4096}


def test_existing_v2_configuration_without_task_options_inherits_global(tmp_path):
    from llmbo_para.electrothermal_requests import request_controls
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    cfg = request_config()
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is not None, report["errors"]
    for task in (WARM, REGION):
        assert request_controls(cfg, task) == {"timeout_s": 120., "max_tokens": 4096}


@pytest.mark.parametrize("task_options", [
    {REGION: {"timeout_s": float("nan")}},
    {REGION: {"timeout_s": float("inf")}},
    {REGION: {"timeout_s": True}},
    {REGION: {"timeout_s": 0}},
    {REGION: {"timeout_s": -1}},
    {REGION: {"timeout_s": 121.}},
    {REGION: {"max_tokens": True}},
    {REGION: {"max_tokens": 0}},
    {REGION: {"max_tokens": 1536.}},
    {REGION: {"max_tokens": 4097}},
    {REGION: {"max_tokens": 8193}},
    {REGION: {"automatic_retries": 1}},
    {"region_preference": {"timeout_s": 30.}},
    {REGION: []},
    [],
])
def test_invalid_task_limits_are_rejected_during_preparation(tmp_path, task_options):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    cfg = request_config()
    cfg["llm"]["task_options"] = task_options
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is None and not report["ready"]
    assert report["errors"]
    assert report["paid_api_calls_made"] == report["battery_simulations_made"] == 0


def test_unknown_request_task_is_rejected_before_any_request():
    from llmbo_para.electrothermal_requests import request_controls

    with pytest.raises(ValueError):
        request_controls(request_config(), "region_preference")


def test_timeout_is_classified_once_and_falls_back_without_rewriting_gp(tmp_path_factory):
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.mo_optimizer import MOOptimizer

    root = tmp_path_factory.mktemp("rq")
    cfg = request_config()
    cfg["optimization"]["mode"] = "full_llmbo_mo"
    cfg["llm"].update(enabled=True,
        endpoint="https://provider.example.test/v1/chat/completions",
        model="test-model", api_key_env="UNUSED_REQUEST_POLICY_TEST_CREDENTIAL")
    cfg["budgets"]["max_llm_requests"] = 2
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=root)
    assert prepared is not None, report["errors"]
    store = ElectrothermalRunStore(root, cfg, dataset=prepared.dataset,
        signatures=prepared.signatures, command="request policy regression")
    evaluator = ElectrothermalEvaluator(prepared.space, SyntheticElectrothermalSimulator(),
        fit_rates=prepared.dataset.fit_rates)
    sensitive_message = "Authorization: Bearer do-not-archive-this-test-sentinel"

    class TimeoutBoundary:
        def __init__(self):
            self.calls = 0

        def post(self, payload):
            self.calls += 1
            raise TimeoutError(sensitive_message)

    transport = TimeoutBoundary()
    controller = ElectrothermalLLMController(transport=transport)
    controller.prepared = prepared
    optimizer = MOOptimizer(prepared.space, evaluator, prepared.dataset, store,
        cfg["optimization"], llm_controller=controller)
    optimizer.initialize()
    previous_observations = [row.to_dict() for row in optimizer.history]

    event = optimizer.step()

    assert transport.calls == controller.requests == 1
    assert controller.task_requests[REGION] == 1
    assert controller.last_request_outcome["status"] == "failed"
    assert controller.last_request_outcome["reason"] == "timeout"
    assert store.ledger.summary()["llm_requests"] == 1
    assert not event["region"]["accepted"]
    assert event["selected_index"] == event["region"]["plain_index"]
    context = optimizer.last_context
    assert optimizer.gp.state_dict() == json.loads(context.gp_state_json)
    assert list(optimizer.gp.state_dict()["y"]) == list(context.scalarization.labels)
    assert [row.to_dict() for row in optimizer.history[:len(previous_observations)]] == previous_observations
    diagnostics = [json.loads(path.read_text(encoding="utf8"))
        for path in (store.path / "llm").glob("*.json")]
    assert any(row.get("status") == "failed" and row.get("reason") == "timeout"
               for row in diagnostics)
    for path in (store.path / "llm").glob("*.json"):
        assert sensitive_message not in path.read_text(encoding="utf8")
