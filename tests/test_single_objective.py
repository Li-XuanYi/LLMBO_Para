"""Scalar surrogate semantics, independent EI quadrature, and archive replay."""
import copy
import json
import math

import numpy as np
import pytest

from llmbo_para.acquisition import scalar_log_ei
from llmbo_para.audit import audit_run
from llmbo_para.config import configuration_errors
from llmbo_para.metrics import LogRMSETransform
from llmbo_para.optimizer import Optimizer
from llmbo_para.workflow import run_experiment
from test_bo_repair import setup_problem, artificial_simulator
from llmbo_para.evaluation import FourRateEvaluator


def scalar_config():
    config, _, _ = setup_problem()
    config["optimization"].update(surrogate_mode="single_objective", gp_sweeps=4,
        bo_repair={"training_data":"complete", "candidate_policy":"local", "feasibility_weighting":True})
    return config


def test_scalar_ei_matches_independent_gaussian_quadrature():
    transform = LogRMSETransform(-3., .7, epsilon_v=.02)
    mean = np.array([-2., 0., 2.])
    std = np.array([.4, 1., 2.])
    best = .05
    actual = scalar_log_ei(mean, std, transform, best)
    z = np.linspace(-12, 12, 200001)
    density = np.exp(-z*z/2)/math.sqrt(2*math.pi)
    expected = []
    for m, s in zip(mean, std):
        j = np.maximum(np.exp(transform.mean+transform.std*(m+s*z))-transform.epsilon_v, 0.)
        expected.append(np.trapezoid(np.maximum(best-j, 0.)*density, z))
    np.testing.assert_allclose(actual, expected, rtol=2e-7, atol=1e-10)
    np.testing.assert_allclose(scalar_log_ei(mean, np.zeros(3), transform, best),
        [max(best-transform.inverse_sample(m), 0.) for m in mean])
    assert np.all(scalar_log_ei(mean, std, transform, 0.) == 0.)


def test_scalar_gp_trains_on_log_of_mean_and_reuses_fit_after_partial_failure():
    _, space, series = setup_problem()
    evaluator = FourRateEvaluator(space, artificial_simulator(space))
    opt = Optimizer(space, evaluator, series, initial_llm_count=0, initial_sobol_count=2,
        llm_warm_start_enabled=False, llm_gp_groups_enabled=False, surrogate_mode="single_objective")
    opt.records = [evaluator.evaluate(space.denormalize([v]*6), series) for v in (.47, .54)]
    models, transforms, _ = opt._fit_models()
    assert set(models) == {"objective"}
    assert models["objective"].group == () and models["objective"].lambda_ == 0.
    np.testing.assert_allclose(models["objective"].y,
        [transforms["objective"].transform(r.objective_v) for r in opt.records])
    partial = evaluator.evaluate(space.denormalize([.72]*6), series)
    assert not partial.valid and partial.objective_v is None
    opt.records.append(partial)
    after, frozen, _ = opt._fit_models()
    assert after["objective"] is models["objective"]
    assert transforms == frozen and opt.model_training_counts == {"objective":2}


def test_single_objective_config_rejects_mixture_and_partial_labels():
    config = scalar_config()
    assert not configuration_errors(config)
    for changes in ({"llm_gp_groups_enabled":True}, {"bo_repair":{"training_data":"per_rate"}}):
        invalid = copy.deepcopy(config)
        invalid["optimization"].update(changes)
        assert configuration_errors(invalid)


def test_scalar_run_and_deep_audit_detect_altered_target_and_ei(tmp_path):
    result = run_experiment(scalar_config(), tmp_path, command="test scalar archived closure")
    from pathlib import Path
    root = Path(result["run_directory"])
    assert result["surrogate_mode"] == "single_objective"
    assert audit_run(root, deep=True)["passed"]
    model_file = sorted((root/"models").glob("*.json"))[0]
    original = model_file.read_text()
    state = json.loads(original)
    assert set(state["models"]) == {"objective"}
    state["models"]["objective"]["y"][0] += .2
    model_file.write_text(json.dumps(state))
    assert not audit_run(root, deep=True)["passed"]
    model_file.write_text(original)
    acq = sorted((root/"acquisition").glob("*.json"))[0]
    row = json.loads(acq.read_text())
    row["composite_ei"][0] += .01
    acq.write_text(json.dumps(row))
    assert not audit_run(root, deep=True)["passed"]
