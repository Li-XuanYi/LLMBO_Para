from __future__ import annotations

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np
from openpyxl import Workbook

from llmbo_para.data import WorkbookSchema, load_four_rate_workbook
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator, DischargeSeries
from llmbo_para.llm import LLMClient
from llmbo_para.metrics import RATE_ORDER, LogRMSETransform
from llmbo_para.optimizer import Optimizer
from llmbo_para.parameters import PARAMETER_NAMES
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.sobol import Sobol6
from llmbo_para.surrogate import Matern52GP
from test_core import test_space, series_fixture


class ExistingCodeAuditRegressions(unittest.TestCase):
    def test_sobol_initial_set_consumes_only_requested_points(self):
        space = test_space()
        evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v)))
        optimizer = Optimizer(space, evaluator, series_fixture(), initial_llm_count=0, initial_sobol_count=2)
        points = optimizer._initial_candidates()
        self.assertEqual(optimizer.sobol.index, 2)
        np.testing.assert_allclose([space.normalize(p) for p in points], Sobol6().draw(2), rtol=0, atol=1e-14)

    def test_kernel_weight_can_reach_zero_and_upper_endpoint(self):
        model = Matern52GP(max_sweeps=0).fit(Sobol6().draw(4), (0.1, 0.2, 0.3, 0.4), (0,))
        model.params[8] = 0
        self.assertEqual(model._lambda(model.params), 0)
        model.params[8] = 0.8
        self.assertEqual(model._lambda(model.params), 0.8)

    def test_failed_coverage_retains_the_actual_short_curve(self):
        evaluator = FourRateEvaluator(test_space(), CallableSimulator(lambda p, s: ((0, 1), (4.2, 4.0))))
        result = evaluator.evaluate((0.5, 0.5, 1e-14, 1e-14, 10, 10), series_fixture())
        self.assertFalse(result.valid)
        self.assertEqual(result.rates[0].simulation_time_s, (0, 1))
        self.assertEqual(result.rates[0].simulation_voltage_v, (4.2, 4.0))

    def test_nested_raw_curve_cannot_be_sent_as_a_residual_summary(self):
        class Transport:
            def __init__(self):
                self.called = False
            def post(self, payload):
                self.called = True
                return {"groups": {r: [] for r in RATE_ORDER}}
        transport = Transport()
        llm = LLMClient(transport)
        observation = {"parameters": (0.5, 0.5, 1e-14, 1e-14, 10, 10), "rmse_v": {r: 0.1 for r in RATE_ORDER},
                       "residual_summary": {r: {"raw_voltage_curve": [4.2, 4.1]} for r in RATE_ORDER}}
        with self.assertRaises(ValueError):
            llm.parameter_groups(test_space(), [observation])
        self.assertFalse(transport.called)

    def test_legacy_current_fallback_requires_explicit_sign_even_if_column_is_named(self):
        with self.assertRaises(ValueError):
            WorkbookSchema(dict(zip(RATE_ORDER, RATE_ORDER)), "time_s", "I", "U", legacy_assumed_1s=True,
                           sample_period_s=1, nominal_capacity_ah=2.5)

    def test_partial_current_is_not_silently_replaced_by_nominal_current(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            workbook = Workbook()
            workbook.remove(workbook.active)
            for rate in RATE_ORDER:
                sheet = workbook.create_sheet(rate)
                sheet.append(("time_s", "I", "U"))
                sheet.append((0, 1, 4.2))
                sheet.append((1, None, 4.1))
            path = Path(folder) / "partial.xlsx"
            workbook.save(path)
            schema = WorkbookSchema(dict(zip(RATE_ORDER, RATE_ORDER)), "time_s", "I", "U", legacy_assumed_1s=True,
                                    sample_period_s=1, nominal_capacity_ah=2.5, discharge_current_sign=1)
            with self.assertRaises(ValueError):
                load_four_rate_workbook(path, schema)

    def test_optimizer_instance_cannot_silently_append_a_second_run(self):
        space = test_space()
        evaluator = FourRateEvaluator(space, CallableSimulator(lambda p, s: (s.time_s, s.voltage_v)))
        optimizer = Optimizer(space, evaluator, series_fixture(), initial_llm_count=0, initial_sobol_count=2)
        optimizer.optimize(2)
        with self.assertRaises(ValueError):
            optimizer.optimize(2)

    def test_composite_ei_uses_minimization_and_inverse_log_transform(self):
        from llmbo_para.acquisition import composite_ei
        class ConstantPosterior:
            def predict(self, x):
                return np.full(len(x), np.log(0.1 + 1e-8)), np.zeros(len(x))
        models = {r: ConstantPosterior() for r in RATE_ORDER}
        transforms = {r: LogRMSETransform(0, 1) for r in RATE_ORDER}
        ei = composite_ei(np.zeros((2, 6)), models, transforms, 0.2, draws=16)
        np.testing.assert_allclose(ei, (0.1, 0.1), atol=1e-12)


class FrameworkTests(unittest.TestCase):
    def small_config(self):
        from llmbo_para.synthetic import synthetic_config
        config = synthetic_config()
        config["optimization"].update(candidate_pool_size=8, composite_ei_draws=8, gp_sweeps=1)
        return config

    def test_configuration_catches_missing_and_unsupported_settings_together(self):
        from llmbo_para.config import configuration_errors
        config = self.small_config()
        config["optimization"].update(parallel_workers=8, gpu_backend="cuda", misspelled_setting=1)
        config["conditions_by_rate"]["1C"]["initial_soc"] = None
        config["parameters"][PARAMETER_NAMES[0]]["lower"] = None
        config["parameters"][PARAMETER_NAMES[1]]["upper"] = None
        errors = configuration_errors(config)
        self.assertTrue(any("parallel_workers" in row for row in errors))
        self.assertTrue(any("gpu_backend" in row for row in errors))
        self.assertTrue(any("initial_soc" in row for row in errors))
        self.assertTrue(any("misspelled_setting" in row for row in errors))
        self.assertTrue(any(f"{PARAMETER_NAMES[0]}.lower" in row for row in errors))
        self.assertTrue(any(f"{PARAMETER_NAMES[1]}.upper" in row for row in errors))

    def test_runstore_refuses_overwrite_escape_and_inline_credentials(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = RunStore(Path(folder) / "runs", {"kind": "test"}, command="immutable archive test")
            store.write_json("checkpoint.json", {"value": 1})
            with self.assertRaises(FileExistsError):
                store.write_json("checkpoint.json", {"value": 2})
            with self.assertRaises(ValueError):
                store.write_json("../escaped.json", {"value": 2})
            with self.assertRaises(ValueError):
                RunStore(Path(folder) / "runs", {"llm": {"api_key": "test-placeholder"}}, command="must reject")

    def test_warm_start_checks_diversity_prompt_context_and_single_request(self):
        space = test_space()
        middle = space.denormalize((0.5,) * 6)
        nearby = space.denormalize((0.500001,) * 6)
        far = space.denormalize((0.9,) * 6)
        calls = []
        class Transport:
            def post(self, payload):
                calls.append(payload)
                return {"candidates": [{"parameters": list(p)} for p in (middle, middle, nearby, far)]}
        client = LLMClient(Transport(), context={"cell_id": "test-cell"}, min_diversity_distance=0.01)
        accepted = client.warm_start(space, 3)
        self.assertEqual(len(accepted), 2)
        self.assertEqual(calls[0]["rates"], list(RATE_ORDER))
        self.assertIn("physical_constraints", calls[0])
        self.assertIn("instructions", calls[0])
        self.assertEqual(len(calls[0]["prompt_sha256"]), 64)
        with self.assertRaises(ValueError):
            client.warm_start(space, 3)
        self.assertEqual(len(calls), 1)

    def test_synthetic_workflow_deep_audit_and_status(self):
        from llmbo_para.workflow import run_experiment, run_status
        from llmbo_para.audit import audit_run
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result = run_experiment(self.small_config(), Path(folder) / "runs")
            self.assertTrue(result["audit_passed"])
            self.assertTrue(audit_run(result["run_directory"], deep=True)["passed"])
            status = run_status(result["run_directory"])
            self.assertEqual((status["completed_candidates"], status["failed_candidates"], status["pending_candidates"]), (5, 0, 0))
            self.assertEqual(status["rate_solve_attempts"], 20)
            self.assertEqual(status["status"], "completed")
            self.assertEqual(status["candidate_rate_per_min"], result["candidate_evaluations_per_min"])

    def test_one_candidate_smoke_runs_four_rates_without_gp_or_llm(self):
        from llmbo_para.workflow import run_fixed_candidates, run_status
        from llmbo_para.config import parameter_space_from_config
        config = self.small_config()
        config["optimization"]["llm_enabled"] = True
        point = parameter_space_from_config(config).denormalize((0.5,) * 6)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result = run_fixed_candidates(config, Path(folder) / "smoke", [(None, point)], mode="smoke")
            self.assertEqual(result["candidate_completed"], 1)
            self.assertEqual(result["rate_solve_attempts"], 4)
            self.assertFalse((Path(result["run_directory"]) / "llm").exists())
            self.assertFalse((Path(result["run_directory"]) / "models").exists())
            self.assertEqual(run_status(result["run_directory"])["total_candidates"], 1)
            self.assertTrue(config["optimization"]["llm_enabled"])

    def test_result_audit_detects_a_tampered_objective(self):
        from llmbo_para.workflow import run_experiment
        from llmbo_para.audit import audit_run
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result = run_experiment(self.small_config(), Path(folder) / "runs")
            run = Path(result["run_directory"])
            file = sorted((run / "attempts").glob("*.json"))[0]
            value = json.loads(file.read_text(encoding="utf-8"))
            value["objective_v"] += 0.5
            file.write_text(json.dumps(value), encoding="utf-8")  # tamper only a disposable test fixture
            audit = audit_run(run)
            self.assertFalse(audit["passed"])
            self.assertTrue(any("J is not" in row for row in audit["issues"]))

    def test_failure_recovery_creates_a_new_run_and_leaves_source_unchanged(self):
        from llmbo_para.workflow import run_experiment, run_status
        from llmbo_para.recovery import retry_failed
        from llmbo_para.synthetic import SyntheticSimulator
        from llmbo_para.config import parameter_space_from_config
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            config = self.small_config()
            good = SyntheticSimulator(parameter_space_from_config(config))
            state = {"failed": False}
            def fail_once(parameters, series):
                if not state["failed"]:
                    state["failed"] = True
                    raise ValueError("injected deterministic test failure")
                return good.simulate(parameters, series)
            result = run_experiment(config, Path(folder) / "original", simulator=CallableSimulator(fail_once))
            source = Path(result["run_directory"])
            self.assertEqual(result["candidate_failed"], 1)
            before = {str(p.relative_to(source)): sha256_file(p) for p in source.rglob("*") if p.is_file()}
            recovered = retry_failed(source, Path(folder) / "recovery", simulator=good)
            self.assertNotEqual(recovered["run_directory"], str(source))
            self.assertEqual((recovered["candidate_completed"], recovered["candidate_failed"]), (1, 0))
            after = {str(p.relative_to(source)): sha256_file(p) for p in source.rglob("*") if p.is_file()}
            self.assertEqual(before, after)
            self.assertEqual(run_status(source)["status"], "completed_with_failures")

    def test_result_audit_detects_gp_labels_unrelated_to_simulation(self):
        from llmbo_para.workflow import run_experiment
        from llmbo_para.audit import audit_run
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            result = run_experiment(self.small_config(), Path(folder) / "runs")
            source = Path(result["run_directory"])
            file = sorted((source / "models").glob("*.json"))[0]
            value = json.loads(file.read_text(encoding="utf-8"))
            value["models"]["1C"]["y"][0] += 1
            file.write_text(json.dumps(value), encoding="utf-8")
            report = audit_run(source)
            self.assertFalse(report["passed"])
            self.assertTrue(any("GP labels differ" in row for row in report["issues"]))
            next((source / "acquisition").glob("*.json")).unlink()
            report = audit_run(source)
            self.assertTrue(any("lacks complete acquisition" in row for row in report["issues"]))

    def test_lab_porosity_must_match_the_search_constraint(self):
        from llmbo_para.pybamm_adapter import PyBaMMSimulator
        simulator = PyBaMMSimulator(lambda: {"Negative electrode porosity": 0.4, "Positive electrode porosity": 0.3},
            model_options={"thermal": "isothermal"}, conditions_by_rate={r: {} for r in RATE_ORDER},
            pinned_version="contract-test", mesh_points={"x_n": 5}, solver_factory=lambda p: None,
            fixed_porosity={"negative": 0.3, "positive": 0.3})
        with self.assertRaisesRegex(ValueError, "porosity differs"):
            simulator.base_parameters()

    def test_transient_retry_counts_actual_solver_attempts(self):
        from llmbo_para.evaluation import TransientSimulationError
        calls = []
        def simulator(p, s):
            calls.append(s.rate)
            if s.rate == "1C" and calls.count("1C") == 1:
                raise TransientSimulationError("temporary test transport failure")
            return s.time_s, s.voltage_v
        evaluator = FourRateEvaluator(test_space(), CallableSimulator(simulator), max_rate_attempts=2)
        result = evaluator.evaluate((0.5, 0.5, 1e-14, 1e-14, 10, 10), series_fixture())
        self.assertTrue(result.valid)
        self.assertEqual(len(calls), 5)
        self.assertEqual(len(result.rates[1].attempts), 2)

    def test_parameterization_initial_state_requires_explicit_null_soc(self):
        from llmbo_para.config import configuration_errors
        config = self.small_config()
        config["model"].update(provider="pybamm", initial_state_mode="parameterization")
        for condition in config["conditions_by_rate"].values():
            condition["initial_soc"] = None
        errors = configuration_errors(config)
        self.assertFalse(any("initial_soc" in error for error in errors))
        config["conditions_by_rate"]["1C"]["initial_soc"] = 1.0
        self.assertTrue(any("1C.initial_soc must be null" in error for error in configuration_errors(config)))
        config["model"]["initial_state_mode"] = "unknown"
        self.assertTrue(any("model.initial_state_mode" in error for error in configuration_errors(config)))

    def test_idaklu_solver_is_explicit_single_thread_and_uses_measured_output_times(self):
        from llmbo_para.config import configuration_errors
        from llmbo_para.pybamm_adapter import build_simulator
        config = self.small_config()
        config["model"].update(provider="pybamm", parameter_values_factory="llmbo_para.reference_cell:chen2020_reference_parameters",
            mesh_points={key: 20 for key in ("x_n", "x_s", "x_p", "r_n", "r_p")}, options={"thermal": "isothermal"},
            solver={"name": "IDAKLUSolver", "rtol": 1e-6, "atol": 1e-6, "dt_max": 60., "num_threads": 1}, pybamm_version="25.10.2")
        self.assertFalse(any("solver" in row.lower() for row in configuration_errors(config)))
        simulator = build_simulator(config)
        capture = {}
        simulator.solver_factory(SimpleNamespace(IDAKLUSolver=lambda **kwargs: capture.update(kwargs)))
        self.assertEqual(capture["options"]["num_threads"], 1)
        self.assertEqual(capture["options"]["num_solvers"], 1)
        self.assertTrue(simulator.output_at_measured_times)
        config["model"]["solver"]["num_threads"] = 2
        self.assertTrue(any("num_threads=1" in row for row in configuration_errors(config)))

    def test_llm_context_has_signed_charge_and_scalars_without_raw_curves(self):
        from llmbo_para.workflow import build_llm
        config = self.small_config()
        config["optimization"]["llm_enabled"] = True
        series = {rate: DischargeSeries(rate, (0, 1, 2), (4.2, 4, 3.8), (-2, -4, -6), discharge_current_sign=-1) for rate in RATE_ORDER}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = RunStore(folder, {"run_kind": "test"}, command="LLM scalar context regression")
            store.write_json("parameterization.json", {"values": {name: 1. for name in PARAMETER_NAMES}})
            with patch("llmbo_para.workflow.build_transport", return_value=SimpleNamespace()):
                client = build_llm(config, store, prepared=SimpleNamespace(series=series, space=test_space()))
            summary = client.context["discharge_summary_by_rate"]["1C"]
            self.assertAlmostEqual(summary["discharged_charge_ah"], 8 / 3600)
            self.assertEqual(summary["duration_s"], 2)
            self.assertNotIn("constant_discharge_current_a", summary)
            self.assertNotIn("voltage_v", json.dumps(client.context))
            self.assertNotIn("time_s", json.dumps(client.context))
            self.assertEqual(set(client.context["nominal_parameter_values_from_reference"]), set(PARAMETER_NAMES))

    def test_fixed_electrolyte_scaling_preserves_factory_and_archives_reference_function(self):
        from llmbo_para.pybamm_adapter import PyBaMMSimulator
        from llmbo_para.config import configuration_errors
        from llmbo_para.reference_cell import ScaledElectrolyteDiffusivity
        def reference(concentration, temperature):
            return concentration * temperature
        class Values(dict):
            def update(self, value, **kwargs):
                dict.update(self, value)
            def copy(self):
                return Values(self)
        original = Values({"Electrolyte diffusivity [m2.s-1]": reference})
        simulator = PyBaMMSimulator(lambda: original, model_options={"thermal": "isothermal"},
            conditions_by_rate={rate: {} for rate in RATE_ORDER}, pinned_version="test",
            mesh_points={"x_n": 5}, solver_factory=lambda p: None,
            fixed_electrolyte_diffusivity_multiplier=1.5)
        scaled = simulator.base_parameters()["Electrolyte diffusivity [m2.s-1]"]
        self.assertIsInstance(scaled, ScaledElectrolyteDiffusivity)
        self.assertEqual(scaled(2., 3.), 9.)
        self.assertIs(original["Electrolyte diffusivity [m2.s-1]"], reference)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = RunStore(folder, {"run_kind": "test"}, command="fixed electrolyte archive regression")
            simulator.save_parameterization(store)
            saved = json.loads((store.path / "parameterization.json").read_text(encoding="utf-8"))
            entry = saved["values"]["Electrolyte diffusivity [m2.s-1]"]
            self.assertEqual(entry["fixed_multiplier"], 1.5)
            self.assertIn("reference", entry["scaled_reference_function"]["callable"])
            for digest, relative in saved["source_files"].items():
                self.assertEqual(sha256_file(store.path / relative), digest)
        config = self.small_config()
        config["model"].update(provider="pybamm", fixed_electrolyte_diffusivity_multiplier=-1)
        self.assertTrue(any("fixed_electrolyte_diffusivity_multiplier" in row for row in configuration_errors(config)))

    def test_reference_initial_concentrations_are_preserved_without_soc_reset(self):
        from llmbo_para.pybamm_adapter import PyBaMMSimulator
        capture = {}
        class Values(dict):
            def update(self, value, **kwargs):
                dict.update(self, value)
            def copy(self):
                return Values(self)
        base = Values({name: 1 for name in PARAMETER_NAMES})
        base.update({"Initial concentration in negative electrode [mol.m-3]": 29866.0,
                     "Initial concentration in positive electrode [mol.m-3]": 17038.0})
        class Simulation:
            def __init__(self, model, **kwargs):
                capture.update(kwargs)
            def solve(self, **kwargs):
                capture["solve"] = kwargs
                return {"Time [s]": SimpleNamespace(entries=np.array([0, 1, 2])),
                        "Terminal voltage [V]": SimpleNamespace(entries=np.array([4.2, 4.0, 3.8]))}
        fake = SimpleNamespace(__version__="contract-test", t="time", Simulation=Simulation,
                               lithium_ion=SimpleNamespace(DFN=lambda **kwargs: kwargs),
                               Interpolant=lambda *args, **kwargs: "current",
                               standard_spatial_vars=SimpleNamespace(**{name: name for name in ("x_n", "x_s", "x_p", "r_n", "r_p")}))
        conditions = {rate: {"initial_soc": None, "initial_temperature_k": 298.15,
                            "ambient_temperature_k": 298.15, "voltage_cutoff_v": 2.5} for rate in RATE_ORDER}
        simulator = PyBaMMSimulator(lambda: base, model_options={"thermal": "isothermal"},
                    conditions_by_rate=conditions, pinned_version="contract-test",
                    mesh_points={name: 5 for name in ("x_n", "x_s", "x_p", "r_n", "r_p")},
                    solver_factory=lambda p: "solver", initial_state_mode="parameterization", output_at_measured_times=True)
        series = DischargeSeries("1C", (0, 1, 2), (4.2, 4, 3.8), (5, 5, 5), discharge_current_sign=1)
        with patch.dict("sys.modules", {"pybamm": fake}):
            simulator.simulate(dict(zip(PARAMETER_NAMES, (0.5, 0.5, 1e-14, 1e-14, 150, .5))), series)
        self.assertNotIn("initial_soc", capture["solve"])
        np.testing.assert_array_equal(capture["solve"]["t_interp"], [0, 1, 2])
        np.testing.assert_array_equal(capture["solve"]["t_eval"], [0, 2])
        self.assertEqual(capture["parameter_values"]["Initial concentration in negative electrode [mol.m-3]"], 29866.0)
        self.assertEqual(capture["parameter_values"]["Initial concentration in positive electrode [mol.m-3]"], 17038.0)
        self.assertNotIn("Current function [A]", base)

    def test_pybamm_contract_passes_soc_temperatures_cutoff_mesh_and_current_sign(self):
        from llmbo_para.pybamm_adapter import PyBaMMSimulator
        capture = {}
        class Values(dict):
            def update(self, value, **kwargs):
                dict.update(self, value)
            def copy(self):
                return Values(self)
        base = Values({name: 1 for name in PARAMETER_NAMES})
        base.update({"Current function [A]": 1, "Initial temperature [K]": 1, "Ambient temperature [K]": 1, "Lower voltage cut-off [V]": 1})
        original = dict(base)
        class Simulation:
            def __init__(self, model, **kwargs):
                capture.update(kwargs)
            def solve(self, **kwargs):
                capture["solve"] = kwargs
                return {"Time [s]": SimpleNamespace(entries=np.array([0, 1, 2])), "Terminal voltage [V]": SimpleNamespace(entries=np.array([4.2, 4.0, 3.8]))}
        def interpolant(t, current, symbolic_time, **kwargs):
            capture["current"] = current.tolist()
            capture["interpolation"] = kwargs
            return "interpolant"
        fake = SimpleNamespace(__version__="contract-test", t="symbolic_time", Simulation=Simulation,
                               lithium_ion=SimpleNamespace(DFN=lambda **kw: kw), Interpolant=interpolant,
                               standard_spatial_vars=SimpleNamespace(**{name: name for name in ("x_n", "x_s", "x_p", "r_n", "r_p")}))
        conditions = {r: {"initial_soc": .6, "initial_temperature_k": 300, "ambient_temperature_k": 301, "voltage_cutoff_v": 2.7} for r in RATE_ORDER}
        factory_calls = []
        def factory():
            factory_calls.append(1)
            return base
        simulator = PyBaMMSimulator(factory, model_options={"thermal": "isothermal"}, conditions_by_rate=conditions,
                                    pinned_version="contract-test", mesh_points={name: 5 for name in ("x_n", "x_s", "x_p", "r_n", "r_p")}, solver_factory=lambda p: "explicit_solver")
        series = DischargeSeries("1C", (0, 1, 2), (4.2, 4, 3.8), (-2, -2, -2), discharge_current_sign=-1)
        with patch.dict("sys.modules", {"pybamm": fake}):
            simulator.simulate(dict(zip(PARAMETER_NAMES, (0.5, 0.5, 1e-14, 1e-14, 10, 10))), series)
            simulator.simulate(dict(zip(PARAMETER_NAMES, (0.5, 0.5, 1e-14, 1e-14, 10, 10))), series)
        self.assertEqual(capture["solve"]["initial_soc"], .6)
        self.assertEqual(capture["current"], [2, 2, 2])
        self.assertEqual(capture["parameter_values"]["Initial temperature [K]"], 300)
        self.assertEqual(capture["parameter_values"]["Ambient temperature [K]"], 301)
        self.assertEqual(capture["parameter_values"]["Lower voltage cut-off [V]"], 2.7)
        self.assertFalse(capture["interpolation"]["extrapolate"])
        self.assertEqual(base, original)
        self.assertEqual(len(factory_calls), 1)


if __name__ == "__main__":
    unittest.main()
