"""Portable runner guards and shared-cache wiring without calling PyBaMM."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from llmbo_para.synthetic import synthetic_config, SyntheticSimulator
from llmbo_para.config import parameter_space_from_config
from llmbo_para.workflow import prepare_experiment

_spec = importlib.util.spec_from_file_location("repair_runner",Path(__file__).resolve().parents[1]/"scripts/run_bo_repair.py")
runner = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(runner)


def test_portable_template_and_all_variants_validate_without_any_simulation():
    config = runner.load_config()
    points, evidence = runner.initial_points(config)
    assert len(points) == 8 and not Path(config["data"]["path"]).is_absolute()
    assert not config["optimization"]["llm_enabled"] and config["llm"]["endpoint"] is None
    variants = runner.arm_settings("local")
    assert variants["A_original"] is None
    assert variants["B_local"]["training_data"] == "complete"
    assert variants["C_joint"]["candidate_policy"] == "global"
    assert variants["D_partial"]["training_data"] == "per_rate"


def test_formal_and_oversized_smoke_are_blocked_before_run_creation(tmp_path):
    config = synthetic_config()
    plan = tmp_path/"plan.json"; plan.write_text("{}",encoding="utf8")
    with pytest.raises(ValueError,match="smoke budget"):
        runner.run_suite(config,plan,tmp_path/"outputs",iterations=25)
    with pytest.raises(ValueError,match="requires exactly 25"):
        runner.run_suite(config,plan,tmp_path/"outputs",iterations=25,formal=True)
    bad = tmp_path/"bad-smoke.json"; bad.write_text(json.dumps({"kind":"unverified"}),encoding="utf8")
    with pytest.raises(ValueError,match="smoke report"):
        runner.run_suite(config,plan,tmp_path/"outputs",iterations=25,formal=True,smoke_report=bad)
    assert not (tmp_path/"outputs").exists()


def test_runner_preserves_configured_numeric_tuning_without_contaminating_arms(tmp_path):
    config = runner.load_config()
    config["optimization"]["bo_repair"].update(local_radius=.03,global_every=3)
    points, _ = runner.initial_points(config)
    plan = tmp_path/"points.json"; plan.write_text(json.dumps({"source":"random","parameters":points}),encoding="utf8")
    for name, settings in runner.arm_settings("local").items():
        variant = runner.configure_arm(config,plan,5,settings)
        if name == "A_original":
            assert "bo_repair" not in variant["optimization"]
        else:
            repair = variant["optimization"]["bo_repair"]
            assert repair["local_radius"] == .03 and repair["global_every"] == 3
            assert repair.get("candidate_policy", "global") == ("global" if name == "C_joint" else "local")
            assert repair.get("feasibility_weighting",False) == (name == "C_joint")


def test_current_code_initial_cache_is_solved_once_and_reused_by_all_variants(tmp_path_factory):
    tmp_path = tmp_path_factory.mktemp("r")
    config = synthetic_config(9)
    config["optimization"].update(sobol_points=8,candidate_pool_size=8,composite_ei_draws=8,gp_sweeps=0,
        llm_warm_start_enabled=False,llm_gp_groups_enabled=False)
    space = parameter_space_from_config(config)
    points = [list(space.denormalize([.4+.02*i]*6)) for i in range(8)]
    calls = []
    class CountingSimulator(SyntheticSimulator):
        def simulate(self, parameters, series):
            calls.append(series.rate)
            return super().simulate(parameters,series)
        def save_parameterization(self, store): store.write_json("parameterization.json",{"values":{"fixture":1}})
    with patch.object(runner,"initial_points",return_value=(points,{"source":"artificial_test"})), patch("llmbo_para.workflow.build_backend",return_value=CountingSimulator(space)):
        plan_path, prepared = runner.prepare_initial(config,tmp_path/"outputs")
        assert prepared["candidate_valid"] == 8 and len(calls) == 32
        for name, settings in runner.arm_settings("local").items():
            variant = runner.configure_arm(config,plan_path,1,settings)
            report, experiment = prepare_experiment(variant)
            assert report["ready"] and len(experiment.initial_evaluations) == 8
        result = runner.run_suite(config,plan_path,tmp_path/"outputs",iterations=1)
    assert result["passed"]
    assert len(calls) == 32+4*4  # 32 shared initial rate solves, then one four-rate BO point per arm.
    assert all(row["cache_hits"] == 8 for row in result["arms"].values())
    assert result["new_bo_rate_solve_attempts"] == 16
