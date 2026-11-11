"""P0 scientific invariants and small, deterministic artificial closures."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from llmbo_para.bo_repair import CompletionModel, RepairSettings, LocalNeighborhood, decision_scores, select_candidate
from llmbo_para.config import configuration_errors, parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator, SimulationTrace, SimulationSolverError
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.optimizer import Optimizer
from llmbo_para.runstore import sha256_file
from llmbo_para.synthetic import synthetic_config, synthetic_series
from llmbo_para.workflow import run_experiment, prepare_experiment
from llmbo_para.audit import audit_run


def setup_problem():
    config = synthetic_config()
    config["optimization"].update(warm_start_llm_points=0, sobol_points=2, total_candidate_budget=7,
        candidate_pool_size=16, composite_ei_draws=16, gp_sweeps=0,
        llm_enabled=False, llm_warm_start_enabled=False, llm_gp_groups_enabled=False)
    return config, parameter_space_from_config(config), synthetic_series()


def artificial_simulator(space, *, all_valid=False):
    def simulate(parameters, series):
        x = np.asarray(space.normalize(list(parameters.values())))
        width = {"0.5C": .5, "1C": .35, "2C": .2, "3C": .1}[series.rate]
        if not all_valid and abs(x[0]-.5) > width:
            return SimulationTrace(series.time_s[:2], series.voltage_v[:2],
                termination="event: Minimum voltage [V]", voltage_cutoff=True, simulation_completed=False)
        error = .01 + .15*float(np.sum((x-.52)**2))
        return SimulationTrace(series.time_s, np.asarray(series.voltage_v)+error,
            termination="final time", voltage_cutoff=False, simulation_completed=True)
    return CallableSimulator(simulate)


def manual_optimizer(**settings):
    _, space, series = setup_problem()
    evaluator = FourRateEvaluator(space, artificial_simulator(space))
    optimizer = Optimizer(space, evaluator, series, initial_llm_count=0, initial_sobol_count=2,
        candidate_pool_size=16, mc_draws=16, gp_sweeps=0, bo_repair=settings or {"training_data": "per_rate"})
    optimizer.records = [evaluator.evaluate(space.denormalize([v]*6), series) for v in (.47, .54)]
    return optimizer


def test_partial_labels_enter_only_their_own_gp_and_unchanged_fits_are_reused():
    opt = manual_optimizer()
    before, transforms, _ = opt._fit_models()
    frozen = copy.deepcopy(transforms)
    partial = opt.evaluator.evaluate(opt.space.denormalize([.72]*6), opt.series_by_rate)
    assert not partial.valid and partial.objective_v is None
    assert [r.valid for r in partial.rates] == [True, True, False, False]
    assert all(r.rmse_v is None for r in partial.rates if not r.valid)
    opt.records.append(partial)
    after, _, _ = opt._fit_models()
    assert [len(after[r].x) for r in RATE_ORDER] == [3, 3, 2, 2]
    assert after["2C"] is before["2C"] and after["3C"] is before["3C"]
    assert after["1C"] is not before["1C"]
    assert opt.frozen_transforms == frozen


def test_complete_training_switch_retains_the_legacy_sample_set():
    opt = manual_optimizer(training_data="complete")
    opt.records.append(opt.evaluator.evaluate(opt.space.denormalize([.72]*6), opt.series_by_rate))
    models, _, _ = opt._fit_models()
    assert [len(models[r].x) for r in RATE_ORDER] == [2]*4


def test_cutoff_solver_and_unknown_coverage_are_distinct_and_no_labels_are_fabricated():
    _, space, series = setup_problem()
    def simulate(p, s):
        if s.rate == "0.5C":
            return SimulationTrace(s.time_s[:2], s.voltage_v[:2], "event: Minimum voltage [V]", True, False)
        if s.rate == "1C":
            raise SimulationSolverError("integration failed", solver_error_type="IDAKLUError")
        if s.rate == "2C":
            return s.time_s[:2], s.voltage_v[:2]
        return SimulationTrace(s.time_s, s.voltage_v, "final time", False, True)
    result = FourRateEvaluator(space, CallableSimulator(simulate)).evaluate(space.denormalize([.5]*6), series)
    assert [r.failure_kind for r in result.rates] == ["voltage_cutoff", "solver_error", "coverage_shortfall", None]
    assert result.rates[1].solver_error_type == "IDAKLUError"
    assert result.rates[1].coverage_margin is None
    assert result.rates[2].voltage_cutoff is None
    assert result.rates[0].coverage_margin < 0
    assert result.rates[3].coverage_margin == 0 and result.rates[3].coverage_right_censored is True
    assert result.objective_v is None and all(r.rmse_v is None for r in result.rates[:3])


def test_pybamm_adapter_retains_event_metadata_and_wraps_only_solver_errors():
    from llmbo_para.pybamm_adapter import PyBaMMSimulator
    _, space, series = setup_problem()
    capture = {}
    class Values(dict):
        def update(self, values, **kw): super().update(values)
        def copy(self): return Values(self)
    class SolverError(Exception): pass
    class Solution(dict): termination = "event: Minimum voltage [V]"
    class Simulation:
        def __init__(self, *args, **kw): pass
        def solve(self, **kw):
            if "error" in capture: raise capture["error"]
            return Solution({"Time [s]": SimpleNamespace(entries=np.array([0,1])), "Terminal voltage [V]": SimpleNamespace(entries=np.array([4,2.5]))})
    fake = SimpleNamespace(__version__="test", t="t", SolverError=SolverError, Simulation=Simulation,
        lithium_ion=SimpleNamespace(DFN=lambda **kw: None), Interpolant=lambda *a, **kw: None,
        standard_spatial_vars=SimpleNamespace(x_n="x_n"))
    simulator = PyBaMMSimulator(lambda: Values(), model_options={}, pinned_version="test", mesh_points={"x_n":5},
        conditions_by_rate={r: {"initial_soc":1., "initial_temperature_k":298., "ambient_temperature_k":298., "voltage_cutoff_v":2.5} for r in RATE_ORDER},
        solver_factory=lambda p: None)
    parameters = dict(zip((s.name for s in space.specs), space.denormalize([.5]*6)))
    with patch.dict("sys.modules", {"pybamm":fake}):
        trace = simulator.simulate(parameters, series["1C"])
        assert trace.voltage_cutoff is True and trace.simulation_completed is False
        capture["error"] = SolverError("failed")
        with pytest.raises(SimulationSolverError): simulator.simulate(parameters, series["1C"])
        capture["error"] = ValueError("invalid parameterization")
        with pytest.raises(ValueError): simulator.simulate(parameters, series["1C"])


@pytest.mark.parametrize("probabilities", [None, [float("nan"),.8], [0.,0.], [.5,.5], [-1.,.8]])
def test_degenerate_completion_predictions_fall_back_to_unmodified_ei(probabilities):
    scores, policy, fallback = decision_scores([.3,.7], probabilities, enabled=True)
    np.testing.assert_array_equal(scores, [.3,.7])
    assert policy == "raw_ei" and fallback is not None


def test_joint_classifier_uses_real_labels_and_has_small_sample_fallback():
    rng = np.random.default_rng(23)
    x = rng.uniform(size=(80,6)); y = x[:,0] > .6
    model = CompletionModel().fit(x, y)
    assert model.state["ready"] and model.state["positive_count"] == int(sum(y))
    p = model.predict(np.array([[.1]*6,[.9]*6]))
    assert 0 < p[0] < p[1] < 1
    for labels in ([True]*8, [False]*8, [True,False]):
        assert not CompletionModel().fit(x[:len(labels)], labels).state["ready"]
    repeated = CompletionModel().fit(np.ones((8,6))*.5, [True]*4+[False]*4)
    assert not repeated.state["ready"]


def test_local_numeric_failures_do_not_shrink_the_physical_neighborhood():
    opt = manual_optimizer(candidate_policy="local")
    result = opt.evaluator.evaluate(opt.space.denormalize([.72]*6), opt.series_by_rate)
    local = LocalNeighborhood(RepairSettings.parse({}), 4)
    local.update(result, "local"); local.update(result, "local")
    assert local.radius < .02
    def fail(p,s): raise SimulationSolverError("failed")
    numeric = FourRateEvaluator(opt.space, CallableSimulator(fail)).evaluate(result.parameters, opt.series_by_rate)
    before = local.radius
    local.update(numeric, "local"); local.update(numeric, "local")
    assert local.radius == before


def test_insufficient_gp_data_has_explicit_cold_start_without_fake_ei():
    opt = manual_optimizer(training_data="per_rate")
    opt.records = [opt.records[0]]
    models, transforms, best = opt._fit_models()
    assert models == {} and transforms == {} and best is not None
    opt.records = [opt.evaluator.evaluate(opt.space.denormalize([.72]*6), opt.series_by_rate)]*2
    models, _, best = opt._fit_models()
    assert set(models) == {"0.5C", "1C"} and best is None


@pytest.mark.parametrize("settings", [dict(candidate_policy="local", training_data="per_rate"), dict(feasibility_weighting=True, training_data="per_rate")])
def test_full_offline_workflow_is_auditable_and_deterministic(tmp_path, settings):
    config, space, series = setup_problem()
    points = [list(space.denormalize([v]*6)) for v in (.47,.54)]
    plan_path = tmp_path/"points.json"
    plan_path.write_text(json.dumps({"source":"random","parameters":points}), encoding="utf8")
    config["optimization"].update(initial_candidates=points, initial_candidates_source="random",
        initial_candidates_evidence={"path":str(plan_path),"sha256":sha256_file(plan_path)}, bo_repair=settings)
    results = [run_experiment(config, tmp_path/"outputs", simulator=artificial_simulator(space)) for _ in range(2)]
    selections = []
    for result in results:
        directory = Path(result["run_directory"])
        assert audit_run(directory, deep=True)["passed"]
        rows = [json.loads(p.read_text(encoding="utf8")) for p in sorted((directory/"acquisition").glob("*.json"))]
        selections.append([r["normalized_pool"][r["selected_index"]] for r in rows])
        if settings.get("candidate_policy") == "local":
            assert rows[-1]["proposal"]["global_quota"]
            assert rows[-1]["proposal"]["origins"][rows[-1]["selected_index"]] == "global"
            assert result["bo_candidate_valid"] >= 1
    assert selections[0] == selections[1]
    directory = Path(results[0]["run_directory"])
    file = sorted((directory/"acquisition").glob("*.json"))[0]
    row = json.loads(file.read_text(encoding="utf8")); row["decision_scores"][0] += 1
    file.write_text(json.dumps(row),encoding="utf8")
    assert not audit_run(directory)["passed"]


@pytest.mark.parametrize("settings", [None, {"local_radius":0}, {"global_every":0}, {"training_data":[]}, {"unknown":True}])
def test_invalid_repair_settings_fail_preflight(settings):
    config, _, _ = setup_problem()
    config["optimization"]["bo_repair"] = settings
    assert configuration_errors(config)
    report, prepared = prepare_experiment(config)
    assert not report["ready"] and prepared is None and report["battery_simulations_made"] == 0


def test_cold_start_workflow_archives_fallback_until_all_rate_gps_are_ready(tmp_path):
    config, space, _ = setup_problem()
    points = [list(space.denormalize([v]*6)) for v in (.72,.75)]
    plan_path = tmp_path/"cold.json"
    plan_path.write_text(json.dumps({"source":"random","parameters":points}),encoding="utf8")
    config["optimization"].update(total_candidate_budget=5,bo_repair={"training_data":"per_rate"},
        initial_candidates=points,initial_candidates_source="random",
        initial_candidates_evidence={"path":str(plan_path),"sha256":sha256_file(plan_path)})
    partial_backend, valid_backend = artificial_simulator(space), artificial_simulator(space,all_valid=True)
    def simulate(parameters, series):
        # Precisely the initial points are incomplete; every new point is valid.
        point = tuple(parameters.values())
        backend = partial_backend if any(np.allclose(point,p,rtol=1e-12,atol=0) for p in points) else valid_backend
        return backend.simulate(parameters,series)
    result = run_experiment(config,tmp_path/"out",simulator=CallableSimulator(simulate))
    assert result["initial_best_objective_v"] is None and result["bo_candidate_valid"] >= 1
    rows = [json.loads(p.read_text(encoding="utf8")) for p in sorted((Path(result["run_directory"])/"acquisition").glob("*.json"))]
    assert not rows[0]["gp_ready"] and rows[0]["best_observed_objective_v"] is None
    assert rows[0]["policy"] == "seeded_eligible_space_filling" and set(rows[0]["composite_ei"]) == {0.}
    assert rows[-1]["gp_ready"]
    assert audit_run(result["run_directory"],deep=True)["passed"]


def test_cold_start_selection_is_seeded_and_uses_more_than_the_first_pool_index():
    choices = [select_candidate(np.zeros(64),np.ones(64,dtype=bool),seed=23,candidate_id=i,cold_start=True) for i in range(8,40)]
    assert len(set(choices)) > 10 and any(c != 0 for c in choices)
    assert choices == [select_candidate(np.zeros(64),np.ones(64,dtype=bool),seed=23,candidate_id=i,cold_start=True) for i in range(8,40)]
    assert select_candidate([1,2,3],[True,False,True],seed=1,candidate_id=1) == 2


def test_learned_completion_workflow_scores_reproduce_after_both_classes_arrive(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("c")
    config, space, _ = setup_problem()
    points = [list(space.denormalize([.45+.014*i]*6)) for i in range(8)]
    plan = tmp_path/"points.json"; plan.write_text(json.dumps({"source":"random","parameters":points}),encoding="utf8")
    config["optimization"].update(sobol_points=8,total_candidate_budget=13,bo_repair={"feasibility_weighting":True},
        initial_candidates=points,initial_candidates_source="random",
        initial_candidates_evidence={"path":str(plan),"sha256":sha256_file(plan)})
    result = run_experiment(config,tmp_path/"out",simulator=artificial_simulator(space))
    directory = Path(result["run_directory"])
    rows = [json.loads(p.read_text(encoding="utf8")) for p in sorted((directory/"acquisition").glob("*.json"))]
    assert any(r["policy"] == "ei_times_joint_completion_approximation" for r in rows)
    assert audit_run(directory,deep=True)["passed"]
