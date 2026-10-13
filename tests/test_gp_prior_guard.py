"""Forward-only prior checks; synthetic fixtures are never battery evidence."""
import copy
import importlib.util
import json
import math
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from llmbo_para.metrics import RATE_ORDER, LogRMSETransform
from llmbo_para.config import configuration_errors


def guard_classes():
    assert importlib.util.find_spec("llmbo_para.gp_prior_guard") is not None, "GP prior guard is not implemented"
    from llmbo_para.gp_prior_guard import GuardSettings, PredictivePriorGuard
    return GuardSettings, PredictivePriorGuard


def prediction(candidate_id, full_offset, mixed_offset):
    transform = LogRMSETransform(0., 1.)
    target = transform.transform(.02)
    return {"candidate_id": candidate_id, "record_count": candidate_id,
        "normalized_parameters": [.5]*6,
        "rates": {r: {"transform": asdict(transform),
            "ordinary": {"mean": target+full_offset, "variance": .04},
            "mixed": {"mean": target+mixed_offset, "variance": .04}} for r in RATE_ORDER}}


def labels(valid_rates=RATE_ORDER):
    return {"rates": [{"rate": r, "valid": r in valid_rates,
                       "rmse_v": .02 if r in valid_rates else None} for r in RATE_ORDER]}


def test_prior_guard_defaults_and_configuration_validation():
    Settings, Guard = guard_classes()
    assert not Settings.parse(None).enabled
    assert Settings.parse({"enabled": True}).min_new_labels == 5
    for raw in (False, {"enabled": 1}, {"min_new_labels": 0}, {"min_gain": -1}, {"se_multiplier": float("nan")}, {"bogus": True}):
        with pytest.raises(ValueError):
            Settings.parse(raw)
    from llmbo_para.synthetic import synthetic_config
    config = synthetic_config(); config["optimization"]["gp_prior_guard"] = {"enabled": True}
    assert configuration_errors(config) == []


def test_guard_does_not_accept_a_prior_without_new_predictions():
    Settings, Guard = guard_classes()
    guard = Guard(Settings.parse({"enabled": True}), initial_count=8)
    assert guard.decision("3C", has_group=True)["active"] == "ordinary"
    assert guard.decision("3C", has_group=False)["reason"] == "no_parameter_group"
    with pytest.raises(ValueError, match="initial|chronolog"):
        guard.observe(prediction(7, 1, 0), labels())
    assert guard.state_dict()["scores"]["3C"] == []


@pytest.mark.parametrize("full,mixed,expected", [(0., 1., "ordinary"), (1., 0., "mixed")])
def test_guard_uses_paired_forward_nlpd_and_minimum_sample_count(full, mixed, expected):
    Settings, Guard = guard_classes()
    guard = Guard(Settings.parse({"enabled": True}), initial_count=8)
    for candidate_id in range(8, 13):
        assert guard.decision("1C", has_group=True)["active"] == "ordinary"
        guard.observe(prediction(candidate_id, full, mixed), labels())
    decision = guard.decision("1C", has_group=True)
    assert decision["active"] == expected and decision["new_valid_labels"] == 5
    assert abs(decision["mean_nlpd_gain"]) == pytest.approx(12.5)
    with pytest.raises(ValueError, match="chronolog"):
        guard.observe(prediction(12, full, mixed), labels())


def test_failed_rates_cannot_supply_scores_or_promote_prior():
    Settings, Guard = guard_classes()
    guard = Guard(Settings.parse({"enabled": True}), initial_count=8)
    for candidate_id in range(8, 13):
        guard.observe(prediction(candidate_id, 1, 0), labels(("0.5C", "1C")))
    assert guard.decision("0.5C", has_group=True)["active"] == "mixed"
    assert guard.decision("3C", has_group=True)["active"] == "ordinary"
    assert guard.decision("3C", has_group=True)["new_valid_labels"] == 0
    bad = prediction(13, 1, 0); bad["record_count"] = 14
    with pytest.raises(ValueError, match="lookahead|count"):
        guard.observe(bad, labels())


def test_shadow_prediction_uses_observation_not_just_latent_variance():
    Settings, Guard = guard_classes()
    from llmbo_para.surrogate import Matern52GP
    x = np.asarray([[.3]*6, [.7]*6]); y = [-1., 1.]
    ordinary = Matern52GP(max_sweeps=0).fit(x, y)
    mixed = Matern52GP(max_sweeps=0).fit(x, y, [0])
    guard = Guard(Settings.parse({"enabled": True}), initial_count=2)
    pairs = {"1C": {"ordinary": ordinary, "mixed": mixed}}
    out = guard.predict_before(2, [.5]*6, pairs, {"1C": LogRMSETransform(0., 1.)})
    _, latent_std = ordinary.predict([[.5]*6])
    assert out["rates"]["1C"]["ordinary"]["variance"] == pytest.approx(latent_std[0]**2 + math.exp(2*ordinary.params[7]))
    assert guard.state_dict()["scores"]["1C"] == []


def test_guarded_workflow_archives_predictions_and_rejects_tampering(tmp_path):
    guard_classes()
    from test_bo_repair import setup_problem, artificial_simulator
    from llmbo_para.audit import audit_run
    from llmbo_para.workflow import run_experiment
    config, space, _ = setup_problem()
    config["optimization"].update(total_candidate_budget=9, llm_enabled=True,
        llm_gp_groups_enabled=True, llm_warm_start_enabled=False,
        bo_repair={"training_data": "per_rate", "candidate_policy": "local"},
        gp_prior_guard={"enabled": True, "min_new_labels": 3})
    config["llm"].update(transport="structured_json_service", endpoint="https://example.test/json",
        api_key_env="FG_TEST_KEY", model="fixture", timeout_s=30)
    class Groups:
        last_group_validation = {"valid_response": True}
        def parameter_groups(self, space, observations):
            return {r: (space.specs[0].name,) for r in RATE_ORDER}
    with patch.dict("os.environ", {"FG_TEST_KEY": "synthetic-test-only"}), patch("llmbo_para.workflow.build_llm", return_value=Groups()):
        result = run_experiment(config, tmp_path/"run", simulator=artificial_simulator(space, all_valid=True))
    directory = Path(result["run_directory"])
    checked = audit_run(directory, deep=True)
    assert checked["passed"], checked["issues"]
    predictions = sorted((directory/"gp-prior/predictions").glob("*.json"))
    assert len(predictions) == 7
    initial = json.loads((directory/"models/after-000002.json").read_text())
    assert all(v["lambda"] == 0 for v in initial["models"].values())
    assert all(v["group"] == [0] for v in initial["models"].values())
    assert all(v["active"] == "ordinary" for v in initial["prior_guard"]["decisions"].values())
    file = predictions[0]
    value = json.loads(file.read_text()); value["rates"]["1C"]["mixed"]["variance"] *= 10
    file.write_text(json.dumps(value), encoding="utf-8")
    checked = audit_run(directory, deep=True)
    assert not checked["passed"] and any("prior" in error.lower() for error in checked["issues"])
