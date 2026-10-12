import json
import importlib.util
import io
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from llmbo_para.ablation import ARMS, arm_config, random_initial_points
from llmbo_para.audit import audit_run
from llmbo_para.config import configuration_errors, parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
from llmbo_para.llm import LLMClient
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.optimizer import Optimizer
from llmbo_para.parameters import PARAMETER_NAMES
from llmbo_para.synthetic import synthetic_config
from llmbo_para.workflow import prepare_experiment, run_experiment
from test_core import test_space, series_fixture


class AblationTests(unittest.TestCase):
    def test_four_switch_combinations_call_only_the_enabled_tasks(self):
        space = test_space()
        for _, warm, groups in ARMS:
            calls = []
            class Client:
                def warm_start(self, space, count):
                    calls.append("warm_start")
                    return (space.denormalize((.55,) * 6),)
                def parameter_groups(self, space, observations):
                    calls.append("groups")
                    return {rate: (PARAMETER_NAMES[0],) for rate in RATE_ORDER}
            optimizer = Optimizer(space, FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v))),
                series_fixture(), llm=Client(), initial_llm_count=1, initial_sobol_count=2, gp_sweeps=0,
                llm_warm_start_enabled=warm, llm_gp_groups_enabled=groups)
            result = optimizer.optimize(3)
            self.assertEqual(calls, (["warm_start"] if warm else []) + (["groups"] if groups else []))
            self.assertTrue(all(bool(value) == groups for value in result["groups"].values()))

    def test_selection_accepts_only_distinct_existing_indices(self):
        space = test_space()
        candidates = [space.denormalize((fraction,) * 6) for fraction in (.2, .4, .6, .8)]
        for response, valid in (({"selected_indices": [3, 1]}, True), ({"selected_indices": [1, 1]}, False),
            ({"selected_indices": [True, 2]}, False), ({"selected_indices": [0, 9]}, False),
            ({"selected_indices": [0]}, False)):
            calls = []
            class Transport:
                def post(self, payload):
                    calls.append(payload)
                    return response
            client = LLMClient(Transport())
            if valid:
                self.assertEqual(client.select_warm_start(space, candidates, 2), (candidates[3], candidates[1]))
                self.assertEqual(calls[0]["task"], "warm_start_select")
            else:
                with self.assertRaises(ValueError):
                    client.select_warm_start(space, candidates, 2)

    def test_random_initial_points_are_reproducible_and_respect_physical_constraints(self):
        space = test_space()
        self.assertEqual(random_initial_points(space, 8, 1), random_initial_points(space, 8, 1))
        self.assertNotEqual(random_initial_points(space, 8, 1), random_initial_points(space, 8, 2))
        for point in random_initial_points(space, 8, 1):
            space.validate(point)

    def test_shared_initial_plan_is_archived_and_tampering_is_detected_before_execution(self):
        config = synthetic_config(); config["optimization"].update(candidate_pool_size=8, composite_ei_draws=8, gp_sweeps=0)
        space = parameter_space_from_config(config)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            plan_file = Path(folder) / "plan.json"
            plan = {"source": "random", "parameters": [list(point) for point in random_initial_points(space, 2, 123)]}
            plan_file.write_text(json.dumps(plan), encoding="utf-8")
            case = arm_config(config, plan, plan_file, warm_start=False, gp_groups=False, bo_iterations=1)
            self.assertEqual(case["status"], "paired_four_arm_ablation_2_initial_then_1_bo")
            self.assertEqual(configuration_errors(case), [])
            result = run_experiment(case, Path(folder) / "runs")
            self.assertTrue(audit_run(result["run_directory"], deep=True)["passed"])
            plan_file.write_text("{}", encoding="utf-8")
            report, prepared = prepare_experiment(case)
            self.assertIsNone(prepared)
            self.assertTrue(any("SHA-256" in error for error in report["errors"]))

    def test_strict_group_failure_does_not_silently_disable_component(self):
        class Client:
            def parameter_groups(self, space, observations):
                raise RuntimeError("service unavailable")
        space = test_space()
        optimizer = Optimizer(space, FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v))),
            series_fixture(), llm=Client(), initial_llm_count=0, initial_sobol_count=2, gp_sweeps=0,
            llm_warm_start_enabled=False, llm_gp_groups_enabled=True, strict_llm_tasks=True)
        with self.assertRaisesRegex(RuntimeError, "service unavailable"):
            optimizer.optimize(2)

    def test_suite_keeps_independent_arms_after_warm_failure_and_rejects_failed_audit(self):
        script = Path(__file__).resolve().parents[1] / "scripts/run_ablation_suite.py"
        spec = importlib.util.spec_from_file_location("ablation_suite_test", script)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            root = Path(folder)
            config_file = root / "template.json"
            config_file.write_text(json.dumps(synthetic_config()), encoding="utf-8")
            called = []
            def execute(config, output, **kwargs):
                self.assertEqual(Path(output), root / "artifacts/arms")
                flags = config["optimization"]
                called.append((flags["llm_warm_start_enabled"], flags["llm_gp_groups_enabled"]))
                return {"run_directory": str(root / ("groups" if flags["llm_gp_groups_enabled"] else "baseline"))}
            def screen(template, source, suite, base_dir, **kwargs):
                if source == "llm":
                    raise RuntimeError("service unavailable")
                plan = {"source": "random", "parameters": [list(point) for point in random_initial_points(test_space(), 8, 123)],
                    "complete": True, "screening_cost": {"rate_solve_attempts": 32, "api_requests": 0}}
                return plan, suite.write_json("mock-initial.json", plan)
            status = {"completed_candidates": 9, "successful_candidates": 9, "failed_candidates": 0, "pending_candidates": 0}
            with patch.object(runner, "workspace", root), \
                 patch.object(runner.sys, "argv", [str(script), str(config_file), "--bo-iterations", "1", "--output", str(root / "suite"), "--artifact-root", str(root / "artifacts")]), \
                 patch.object(runner, "screen_family", side_effect=screen), \
                 patch.object(runner, "cost_curve", return_value=[]), \
                 patch.object(runner, "run_experiment", side_effect=execute), \
                 patch.object(runner, "run_status", return_value=status), \
                 patch.object(runner, "audit_run", side_effect=lambda path, **kwargs: {"passed": Path(path).name != "baseline"}), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 1)
            self.assertEqual(called, [(False, False), (False, True)])
            summary_file = next((root / "suite").glob("*/study-summary.json"))
            summary = json.loads(summary_file.read_text(encoding="utf-8"))
            self.assertEqual((summary["completed_arms"], summary["failed_arms"], summary["blocked_arms"]), (1, 1, 2))
            self.assertEqual((summary["completed_candidates"], summary["pending_candidates"]), (18, 18))
            self.assertFalse(summary["all_four_arms_completed"])


if __name__ == "__main__":
    unittest.main()
