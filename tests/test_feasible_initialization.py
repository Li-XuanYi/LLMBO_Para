import copy
import json
from pathlib import Path
import tempfile
import unittest

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run
from llmbo_para.config import parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
from llmbo_para.feasibility import InventoryGate
from llmbo_para.initialization import FeasibleInitializer, ScreeningBudget, validated_cached_results
from llmbo_para.llm import LLMClient
from llmbo_para.optimizer import Optimizer
from llmbo_para.runstore import RunStore
from llmbo_para.synthetic import synthetic_config, synthetic_series
from llmbo_para.workflow import prepare_experiment, run_experiment


class FeasibleInitializationTests(unittest.TestCase):
    def setUp(self):
        self.config = synthetic_config()
        self.config["optimization"].update(candidate_pool_size=8, composite_ei_draws=8, gp_sweeps=0)
        self.space = parameter_space_from_config(self.config)
        self.series = synthetic_series()
        self.folder = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.root = Path(self.folder.name)
        self.addCleanup(self.folder.cleanup)

    def initializer(self, simulator, **kwargs):
        store = RunStore(self.root / "screen", self.config, command="feasibility regression")
        return FeasibleInitializer(self.config, self.space, self.series,
            FourRateEvaluator(self.space, CallableSimulator(simulator)), store, **kwargs)

    def test_necessary_inventory_rejection_consumes_draws_and_no_solves(self):
        calls = []
        init = self.initializer(lambda p, s: calls.append(1), gate=InventoryGate(1, 1, 2), source="random",
            budget=ScreeningBudget(target=2, max_random_draws=7))
        plan = init.run()
        self.assertFalse(plan["complete"])
        self.assertEqual((init.draws, init.evaluations, init.analytical_rejections, calls), (7, 0, 7, []))

    def test_failed_candidates_count_and_budget_is_bounded(self):
        init = self.initializer(lambda p, s: (s.time_s[:-1], s.voltage_v[:-1]), gate=None, source="random",
            budget=ScreeningBudget(target=2, max_evaluations=3))
        plan = init.run()
        self.assertEqual((plan["complete"], init.evaluations, init.rate_solves, init.physical_rejections), (False, 3, 12, 3))

    def test_llm_refills_one_from_same_pool_without_random_substitution(self):
        points = [self.space.denormalize((v,)*6) for v in (.2, .4, .6, .8)]
        calls = []
        class Client:
            def warm_start(client, space, count):
                calls.append(("generate", count))
                return points
            def select_warm_start(client, space, pool, count):
                calls.append(("select", count))
                return tuple(pool[:count])
        def simulate(params, row):
            return (row.time_s[:-1], row.voltage_v[:-1]) if params[self.space.specs[0].name] == points[0][0] else (row.time_s, row.voltage_v)
        init = self.initializer(simulate, gate=None, source="llm", budget=ScreeningBudget(target=2), llm_factory=lambda *args: Client())
        plan = init.run()
        self.assertEqual(calls, [("generate", 20), ("select", 2), ("select", 1)])
        self.assertEqual(plan["parameters"], [list(points[1]), list(points[2])])
        self.assertEqual((init.evaluations, init.rate_solves, init.api_requests), (3, 12, 3))
        transport = type("Transport", (), {"post": lambda self, payload: {"selected_indices": [1]}})()
        self.assertEqual(LLMClient(transport).select_warm_start(self.space, points, 1), (points[1],))

    def test_cache_is_recomputed_then_reused_and_auditable_without_original_source(self):
        checkpoints = []
        init = self.initializer(lambda p, s: (s.time_s, s.voltage_v), gate=None, source="random",
            budget=ScreeningBudget(target=2), checkpoint_callback=lambda plan, path: checkpoints.append(len(validated_cached_results(self.config, self.series, plan, path))))
        plan = init.run(); plan_file = init.store.path / "initial-plan.json"
        self.assertEqual(checkpoints, [2])
        case = arm_config(self.config, plan, plan_file, warm_start=False, gp_groups=False, bo_iterations=2)
        calls = []
        def fail_bo(params, row):
            calls.append(row.rate)
            return row.time_s[:-1], row.voltage_v[:-1]
        result = run_experiment(case, self.root / "arms", simulator=CallableSimulator(fail_bo))
        self.assertEqual((result["cache_hits"], result["candidate_failed"], result["rate_solve_attempts"], len(calls)), (2, 2, 8, 8))
        original = Path(plan["evaluation_sources"][0]["path"])
        original.rename(original.with_suffix(".hidden"))
        self.assertTrue(audit_run(result["run_directory"], deep=True)["passed"])
        report, prepared = prepare_experiment(case)
        self.assertIsNone(prepared)
        self.assertIn("cached source record", " ".join(report["errors"]))

    def test_cache_model_and_label_changes_rejected_before_simulation(self):
        init = self.initializer(lambda p, s: (s.time_s, s.voltage_v), gate=None, source="random", budget=ScreeningBudget(target=2))
        plan = init.run(); path = init.store.path / "initial-plan.json"
        changed = copy.deepcopy(self.config); changed["model"]["fixture_formula"] = "changed"
        with self.assertRaisesRegex(ValueError, "signature"):
            validated_cached_results(changed, self.series, plan, path)
        corrupted = copy.deepcopy(plan)
        corrupted["evaluations"][0]["objective_v"] = 1
        source = Path(corrupted["evaluation_sources"][0]["path"])
        source.write_text(json.dumps(corrupted["evaluations"][0]), encoding="utf-8")
        from llmbo_para.runstore import sha256_file
        corrupted["evaluation_sources"][0]["sha256"] = sha256_file(source)
        with self.assertRaisesRegex(ValueError, "objective"):
            validated_cached_results(self.config, self.series, corrupted, path)

    def test_bo_gate_rejects_before_ei_and_preserves_evaluation_budget(self):
        count = [0]
        def gate(point):
            count[0] += 1
            return {"feasible": count[0] > 2}
        opt = Optimizer(self.space, FourRateEvaluator(self.space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v))), self.series,
            initial_llm_count=0, initial_sobol_count=2, candidate_pool_size=4, mc_draws=8, gp_sweeps=0, candidate_filter=gate)
        result = opt.optimize(3)
        self.assertEqual((result["candidate_completed"], result["bo_analytical_rejections"]), (3, 2))

    def test_cached_simulator_source_change_is_rejected(self):
        init = self.initializer(lambda p, s: (s.time_s, s.voltage_v), gate=None, source="random", budget=ScreeningBudget(target=2))
        plan = init.run()
        snapshot = init.store.path / "source/src/llmbo_para/pybamm_adapter.py"
        snapshot.write_bytes(snapshot.read_bytes()+b"\n# tampered\n")
        with self.assertRaisesRegex(ValueError, "implementation source mismatch"):
            validated_cached_results(self.config, self.series, plan, init.store.path / "initial-plan.json")

    def test_random_continuation_keeps_rng_sequence_and_full_historical_cost(self):
        first = self.initializer(lambda p,s: (s.time_s,s.voltage_v), gate=None, source="random", budget=ScreeningBudget(target=2,max_evaluations=4))
        prior = first.run()
        resumed = self.initializer(lambda p,s: (s.time_s,s.voltage_v), gate=None, source="random", budget=ScreeningBudget(target=4,max_evaluations=4))
        resumed.restore_random(prior,first.store.path / "initial-plan.json")
        plan = resumed.run()
        standalone = self.initializer(lambda p,s: (s.time_s,s.voltage_v), gate=None, source="random", budget=ScreeningBudget(target=4,max_evaluations=4))
        expected = standalone.run()
        self.assertEqual(plan["parameters"],expected["parameters"])
        self.assertEqual((resumed.evaluations,resumed.rate_solves,len(list((resumed.store.path/'attempts').glob('*.json')))),(4,16,2))
        self.assertEqual(plan['evaluation_sources'][:2],prior['evaluation_sources'])


if __name__ == "__main__":
    unittest.main()
