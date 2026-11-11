"""Regressions for the observed wrong-schema response and truthful feedback."""
import copy
import json
from pathlib import Path

import pytest

from llmbo_para.config import configuration_errors, parameter_space_from_config
from llmbo_para.llm import LLMClient
from llmbo_para.runstore import RunStore
from llmbo_para.synthetic import synthetic_config


class ReplySequence:
    def __init__(self, replies):
        self.replies = replies
        self.calls = []

    def post(self, payload):
        self.calls.append(copy.deepcopy(payload))
        reply = self.replies[len(self.calls) - 1]
        if isinstance(reply, Exception):
            raise reply
        return copy.deepcopy(reply)


def pool():
    space = parameter_space_from_config(synthetic_config())
    return space, [space.denormalize([x] * 6) for x in (.2, .4, .6)]


def test_selection_repairs_observed_json_object_without_changing_pool(tmp_path):
    space, points = pool()
    transport = ReplySequence([{"type": "json_object"}, {"selected_indices": [2, 0]}])
    store = RunStore(tmp_path / "r", {"test": "format_only"}, command="selection repair regression")
    client = LLMClient(transport, run_store=store, selection_max_attempts=3)
    assert client.select_warm_start(space, points, 2) == (points[2], points[0])
    assert client.last_select_request_attempts == 2
    assert transport.calls[0]["candidates"] == transport.calls[1]["candidates"]
    assert transport.calls[1]["contract_repair"]["validation"]["reason"] == "missing_selected_indices"
    assert transport.calls[1]["requested_count"] == 2
    first = store.path / "llm-attempts/warm_start_select/attempt-001/llm/warm_start_select.response.json"
    assert json.loads(first.read_text()) == {"type": "json_object"}
    assert json.loads((store.path / "llm/warm_start_select.response.json").read_text()) == {"selected_indices": [2, 0]}
    assert json.loads((store.path / "llm/warm_start_select.validation.json").read_text())["request_attempts"] == 2
    with pytest.raises(ValueError, match="once"):
        client.select_warm_start(space, points, 2)
    assert len(transport.calls) == 2


@pytest.mark.parametrize("bad", [{"selected_indices": [0, 0]}, {"selected_indices": [True, 1]},
    {"selected_indices": [0]}, {"selected_indices": [0, 8]}, {"selected_indices": [0.0, 1]}])
def test_selection_invalid_indices_exhaust_bounded_budget(bad):
    space, points = pool()
    transport = ReplySequence([bad] * 3)
    client = LLMClient(transport, selection_max_attempts=3)
    with pytest.raises(ValueError, match="candidate indices"):
        client.select_warm_start(space, points, 2)
    assert len(transport.calls) == 3
    assert client.last_select_request_attempts == 3
    assert not client.last_select_validation["valid_response"]


def test_selection_transport_error_is_not_retried_as_format_repair():
    space, points = pool()
    transport = ReplySequence([RuntimeError("simulated network outage")])
    client = LLMClient(transport, selection_max_attempts=3)
    with pytest.raises(RuntimeError, match="LLM warm_start_select failed"):
        client.select_warm_start(space, points, 2)
    assert len(transport.calls) == 1
    assert client.last_select_request_attempts == 1


def test_selection_legacy_default_still_makes_one_call():
    space, points = pool()
    transport = ReplySequence([{"type": "json_object"}])
    with pytest.raises(ValueError, match="candidate indices"):
        LLMClient(transport).select_warm_start(space, points, 2)
    assert len(transport.calls) == 1


def test_selection_repair_configuration_and_limits():
    config = synthetic_config()
    config["llm"]["selection_max_attempts"] = 3
    assert configuration_errors(config) == []
    for value in (0, 4, True, 1.5):
        config["llm"]["selection_max_attempts"] = value
        assert any("selection_max_attempts" in error for error in configuration_errors(config))


def test_screening_counts_format_repairs_against_selection_budget(tmp_path):
    from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
    from llmbo_para.initialization import FeasibleInitializer, ScreeningBudget
    from llmbo_para.synthetic import synthetic_series
    config = synthetic_config()
    space, points = pool()
    generated = ReplySequence([{"candidates": [{"parameters": list(p)} for p in points]}])
    selected = ReplySequence([{"type": "json_object"}, {"selected_indices": [0, 1]}])
    def factory(stage, index, context):
        return LLMClient(generated if stage == "generate" else selected,
                         context=context, selection_max_attempts=3)
    series = synthetic_series()
    evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v)))
    store = RunStore(tmp_path / "screen", config, command="count actual selector repairs")
    init = FeasibleInitializer(config, space, series, evaluator, store, gate=None,
        source="llm", llm_factory=factory, budget=ScreeningBudget(target=2, max_selection_requests=2))
    plan = init.run()
    assert plan["complete"]
    assert init.selection_requests == 2 and init.api_requests == 3
    assert len(selected.calls) == 2


def feedback_functions():
    import importlib.util
    assert importlib.util.find_spec("llmbo_para.llm_feedback") is not None, "real-feedback module is not implemented"
    from llmbo_para.llm_feedback import summarize_evaluation, build_feedback
    return summarize_evaluation, build_feedback


def test_feedback_preserves_partial_labels_and_never_serializes_raw_arrays():
    import numpy as np
    from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
    from llmbo_para.synthetic import synthetic_series
    summarize, build = feedback_functions()
    space, points = pool()
    def simulator(p, s):
        if s.rate == "3C":
            return s.time_s[:-1], s.voltage_v[:-1]
        return s.time_s, np.asarray(s.voltage_v) + .02
    result = FourRateEvaluator(space, CallableSimulator(simulator)).evaluate(points[0], synthetic_series())
    row = summarize(space, result.to_dict(), candidate_id=4)
    assert not row["valid"] and row["objective_v"] is None
    assert row["rates"]["0.5C"]["rmse_v"] == pytest.approx(.02)
    assert row["rates"]["3C"]["rmse_v"] is None
    assert row["rates"]["3C"]["coverage_fraction"] < 1
    payload = build(space, [row])
    assert payload["total_evaluated"] == 1 and payload["records"][0]["candidate_id"] == 4
    text = json.dumps(payload, allow_nan=False)
    for raw_key in ("simulation_voltage_v", "aligned_voltage_v", "simulation_time_s", "traceback"):
        assert raw_key not in text
    bad = result.to_dict(); bad["objective_v"] = 99
    with pytest.raises(ValueError):
        summarize(space, bad, candidate_id=4)


def test_feedback_necessary_bounds_and_diversity_do_not_change_parameter_space():
    import numpy as np
    from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
    from llmbo_para.feasibility import InventoryGate
    from llmbo_para.synthetic import synthetic_series
    summarize, build = feedback_functions()
    space, points = pool()
    original_specs = space.specs
    evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, np.asarray(s.voltage_v) + .02)))
    rows = [summarize(space, evaluator.evaluate(p, synthetic_series()).to_dict(), candidate_id=i) for i, p in enumerate(points)]
    payload = build(space, rows, gate=InventoryGate(2, 3, 1), max_records=2)
    assert payload["retained_count"] == 2 and payload["omitted_count"] == 1
    assert payload["necessary_parameter_bounds"][0][0] == pytest.approx(.5)
    assert payload["accepted_diversity"]["minimum_pairwise_distance"] > 0
    assert payload["necessary_conditions_only"] is True
    assert space.specs == original_specs


def test_feedback_is_opt_in_and_success_rmse_reaches_next_generation(tmp_path):
    import numpy as np
    from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
    from llmbo_para.initialization import FeasibleInitializer, ScreeningBudget
    from llmbo_para.synthetic import synthetic_series
    for enabled in (False, True):
        config = synthetic_config(); config["llm"]["warm_start_feedback"] = enabled
        assert configuration_errors(config) == []
        space, points = pool(); contexts = []
        class Client:
            def warm_start(self, space, count):
                return [points[len(contexts) // 2]]
            def select_warm_start(self, space, candidates, count):
                return tuple(candidates[:count])
        def factory(stage, index, context):
            contexts.append(copy.deepcopy(context)); return Client()
        evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, np.asarray(s.voltage_v) + .02)))
        store = RunStore(tmp_path / str(enabled), config, command="feedback interface regression")
        init = FeasibleInitializer(config, space, synthetic_series(), evaluator, store, gate=None,
            source="llm", llm_factory=factory, budget=ScreeningBudget(target=2))
        assert init.run()["complete"]
        assert ("evaluation_feedback" in contexts[2]["initialization_recovery"]) is enabled
        if enabled:
            data = contexts[2]["initialization_recovery"]["evaluation_feedback"]
            assert data["records"][0]["objective_v"] == pytest.approx(.02)
            assert data["records"][0]["rates"]["3C"]["valid"] is True
            assert init.plan()["feedback_schema_version"] == 1


def test_feedback_rejects_non_boolean_censor_field_instead_of_forwarding_data():
    from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
    from llmbo_para.synthetic import synthetic_series
    summarize, _ = feedback_functions()
    space, points = pool()
    evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v)))
    record = evaluator.evaluate(points[0], synthetic_series()).to_dict()
    record["rates"][0]["coverage_right_censored"] = [1.0, 2.0, 3.0]
    with pytest.raises(ValueError, match="censor|boolean"):
        summarize(space, record, candidate_id=0)


def test_rich_feedback_resume_recomputes_original_labels_and_costs(tmp_path):
    import numpy as np
    from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
    from llmbo_para.initialization import FeasibleInitializer, ScreeningBudget
    from llmbo_para.synthetic import synthetic_series
    config = synthetic_config(); config["llm"]["warm_start_feedback"] = True
    space, points = pool(); contexts = []
    class Client:
        def __init__(self, batch): self.batch = batch
        def warm_start(self, space, count): return [points[self.batch - 1]]
        def select_warm_start(self, space, candidates, count): return tuple(candidates[:count])
    def factory(stage, batch, context):
        contexts.append(copy.deepcopy(context)); return Client(batch)
    series = synthetic_series()
    evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, np.asarray(s.voltage_v) + .02)))
    def make(batches):
        store = RunStore(tmp_path / "r", config, command="strict rich-feedback continuation")
        return FeasibleInitializer(config, space, series, evaluator, store, gate=None, source="llm", llm_factory=factory,
            budget=ScreeningBudget(target=2, max_warm_batches=batches))
    first = make(1); plan = first.run()
    assert not plan["complete"] and len(plan["feedback_history"]) == 1
    resumed = make(2); resumed.restore_llm(plan, first.store.path / "initial-plan.json")
    finished = resumed.run()
    assert finished["complete"] and finished["screening_cost"]["new_candidate_evaluations"] == 1
    assert [row["candidate_id"] for row in finished["feedback_history"]] == [0, 1]
    assert contexts[-2]["initialization_recovery"]["evaluation_feedback"]["records"][0]["objective_v"] == pytest.approx(.02)
    assert finished["generated_history"] == [list(points[0]), list(points[1])]
