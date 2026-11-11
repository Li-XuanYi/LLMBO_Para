from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
from openpyxl import Workbook

from llmbo_para.acquisition import composite_ei
from llmbo_para.config import load_json, validate_experiment_config
from llmbo_para.data import WorkbookSchema, inspect_workbook, load_four_rate_workbook
from llmbo_para.evaluation import CallableSimulator, DischargeSeries, FourRateEvaluator
from llmbo_para.llm import LLMClient
from llmbo_para.metrics import RATE_ORDER, LogRMSETransform, mean_rate_rmse, rmse
from llmbo_para.optimizer import Optimizer
from llmbo_para.parameters import PARAMETER_NAMES, ParameterSpace
from llmbo_para.progress import summarize_progress
from llmbo_para.runstore import RunStore
from llmbo_para.sobol import Sobol6
from llmbo_para.surrogate import Matern52GP


def test_space() -> ParameterSpace:
    bounds = {
        PARAMETER_NAMES[0]: (0.2, 0.8),
        PARAMETER_NAMES[1]: (0.2, 0.8),
        PARAMETER_NAMES[2]: (1e-16, 1e-12),
        PARAMETER_NAMES[3]: (1e-16, 1e-12),
        PARAMETER_NAMES[4]: (0.1, 300.0),
        PARAMETER_NAMES[5]: (0.1, 300.0),
    }
    transforms = {name: ("log10" if "diffusivity" in name else "linear") for name in PARAMETER_NAMES}
    units = {name: "test" for name in PARAMETER_NAMES}
    return ParameterSpace.from_bounds(bounds, transforms, units)


test_space.__test__ = False  # Helper, not an assertion-bearing pytest test.


def series_fixture():
    return {
        rate: DischargeSeries(rate, (0.0, 1.0, 2.0), (4.2, 4.0, 3.8), (-0.5, -0.5, -0.5))
        for rate in RATE_ORDER
    }


class CoreTests(unittest.TestCase):
    def test_incomplete_research_config_is_refused(self):
        template = load_json(Path.cwd() / "configs" / "research-template.json")
        with self.assertRaisesRegex(ValueError, "research-group lower and upper bounds"):
            validate_experiment_config(template)

    def test_parameter_roundtrip_and_invalid_bounds(self):
        space = test_space()
        point = tuple((spec.lower * spec.upper) ** 0.5 if spec.transform == "log10" else (spec.lower + spec.upper) / 2 for spec in space.specs)
        np.testing.assert_allclose(space.denormalize(space.normalize(point)), point, rtol=1e-12)
        with self.assertRaises(ValueError):
            space.validate((0.1, *point[1:]))

    def test_metrics_and_frozen_transform(self):
        self.assertAlmostEqual(rmse((1, 2), (1, 3)), 2**-0.5)
        self.assertAlmostEqual(mean_rate_rmse({rate: i / 10 for i, rate in enumerate(RATE_ORDER)}), 0.15)
        fit = LogRMSETransform.fit((0.1, 0.2, 0.3))
        for value in (0.1, 0.2, 0.3):
            self.assertAlmostEqual(fit.inverse_sample(fit.transform(value)), value)

    def test_sobol_reference_prefix_and_chunking(self):
        expected = np.asarray([
            [0, 0, 0, 0, 0, 0],
            [.5, .5, .5, .5, .5, .5],
            [.75, .25, .25, .25, .75, .75],
            [.25, .75, .75, .75, .25, .25],
            [.375, .375, .625, .875, .375, .125],
            [.875, .875, .125, .375, .875, .625],
            [.625, .125, .875, .625, .625, .875],
            [.125, .625, .375, .125, .125, .375],
        ])
        np.testing.assert_array_equal(Sobol6().draw(8), expected)
        engine = Sobol6()
        np.testing.assert_array_equal(engine.draw(3), expected[:3])
        np.testing.assert_array_equal(engine.draw(5), expected[3:])

    def test_evaluator_fixed_grid_failures_and_full_rate_attempts(self):
        seen = []

        def simulator(params, series):
            seen.append(series.rate)
            if series.rate == "1C":
                return (1.0, 2.0), (4.0, 3.8)  # fixed grid starts before simulated coverage
            return series.time_s, series.voltage_v

        result = FourRateEvaluator(test_space(), CallableSimulator(simulator)).evaluate(
            (0.5, 0.5, 1e-14, 1e-14, 10, 10), series_fixture()
        )
        self.assertEqual(seen, list(RATE_ORDER))
        self.assertFalse(result.valid)
        self.assertIsNone(result.objective_v)
        self.assertFalse(result.rates[1].valid)
        self.assertIn("extrapolation is forbidden", result.rates[1].reason)

    def test_excel_loader_requires_real_time_and_current(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "data.xlsx"
            workbook = Workbook()
            first = workbook.active
            first.title = RATE_ORDER[0]
            for rate in RATE_ORDER[1:]:
                workbook.create_sheet(rate)
            for sheet in workbook.worksheets:
                sheet.append(("U", "T"))
                sheet.append((4.2, 22.0))
                sheet.append((4.1, 22.1))
            workbook.save(path)
            inventory = inspect_workbook(path)
            self.assertEqual([row["name"] for row in inventory["sheets"]], list(RATE_ORDER))
            self.assertEqual(inventory["sheets"][0]["columns"][0]["header"], "U")
            schema = WorkbookSchema(dict(zip(RATE_ORDER, RATE_ORDER)), "Time", "I", "U", "T")
            with self.assertRaisesRegex(ValueError, "no configured time column"):
                load_four_rate_workbook(path, schema)
            legacy = WorkbookSchema(
                dict(zip(RATE_ORDER, RATE_ORDER)), "Time", "I", "U", "T",
                legacy_assumed_1s=True, sample_period_s=1, nominal_capacity_ah=2.5,
                discharge_current_sign=-1,
            )
            series, digest = load_four_rate_workbook(path, legacy)
            self.assertEqual(len(digest), 64)
            self.assertEqual(series["0.5C"].time_s, (0, 1))
            self.assertEqual(series["0.5C"].current_a, (-1.25, -1.25))
            self.assertEqual(series["0.5C"].current_source, "legacy_assumed_1s")
            self.assertEqual(series["0.5C"].assumptions[0], "sample_period_s=1")

    def test_gp_and_composite_ei_finite(self):
        x = Sobol6().draw(8)
        y = np.sin(x[:, 0] * 4) + x[:, 1]
        model = Matern52GP(max_sweeps=1).fit(x, y, (0, 1))
        mean, std = model.predict(x[:3])
        self.assertTrue(np.all(np.isfinite(mean)))
        self.assertTrue(np.all(std > 0))
        self.assertGreaterEqual(model.lambda_, 0)
        self.assertLessEqual(model.lambda_, 0.8)
        models = {rate: model for rate in RATE_ORDER}
        transforms = {rate: LogRMSETransform(0, 1) for rate in RATE_ORDER}
        scores = composite_ei(x[:4], models, transforms, 1.0, draws=16, seed=4)
        self.assertEqual(scores.shape, (4,))
        self.assertTrue(np.all(np.isfinite(scores)))

    def test_optimizer_freezes_log_rmse_transforms_after_initial_data(self):
        space = test_space()

        def simulator(parameters, measured):
            error = 0.001 + abs(parameters[PARAMETER_NAMES[0]] - 0.5) * 0.02
            return measured.time_s, tuple(v + error for v in measured.voltage_v)

        evaluator = FourRateEvaluator(space, CallableSimulator(simulator))
        optimizer = Optimizer(space, evaluator, series_fixture(), initial_llm_count=0,
                              initial_sobol_count=2, gp_sweeps=1)
        for normalized in Sobol6().draw(2):
            optimizer.records.append(evaluator.evaluate(space.denormalize(normalized), series_fixture()))
        _, transforms_before, _ = optimizer._fit_models()
        frozen_values = {rate: (t.mean, t.std) for rate, t in transforms_before.items()}
        optimizer.records.append(evaluator.evaluate(space.denormalize((0.9,) * 6), series_fixture()))
        _, transforms_after, _ = optimizer._fit_models()
        self.assertEqual({rate: (t.mean, t.std) for rate, t in transforms_after.items()}, frozen_values)

    def test_llm_contract_and_optimizer_small_synthetic_run(self):
        class FakeTransport:
            def __init__(self):
                self.calls = []

            def post(self, payload):
                self.calls.append(payload)
                if payload["task"] == "warm_start":
                    return {"candidates": []}
                return {"groups": {rate: [PARAMETER_NAMES[0]] for rate in RATE_ORDER}}

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            space = test_space()
            simulator = CallableSimulator(lambda _p, s: (s.time_s, s.voltage_v))
            evaluator = FourRateEvaluator(space, simulator)
            transport = FakeTransport()
            llm = LLMClient(transport)
            store = RunStore(Path(directory) / "runs", {"fixture": "synthetic"}, command="unittest synthetic")
            optimizer = Optimizer(space, evaluator, series_fixture(), llm=llm, run_store=store,
                                  initial_llm_count=2, initial_sobol_count=2,
                                  candidate_pool_size=16, mc_draws=8, gp_sweeps=1)
            summary = optimizer.optimize(5)
            self.assertEqual(summary["candidate_completed"], 5)
            self.assertEqual(summary["candidate_failed"], 0)
            self.assertEqual([call["task"] for call in transport.calls], ["warm_start", "rate_parameter_groups"])
            self.assertEqual(len(list((store.path / "attempts").glob("*.json"))), 5)
            self.assertTrue((store.path / "manifest.json").is_file())
            events = [json.loads(line) for line in store.events_path.read_text(encoding="utf-8").splitlines()]
            progress = [event for event in events if event["type"] == "progress"]
            self.assertEqual(len(progress), 5)
            self.assertEqual(progress[-1]["completed_candidates"], 5)
            self.assertEqual(summarize_progress(5, [r.to_dict() for r in optimizer.records], 1).completed_candidates, 5)


if __name__ == "__main__":
    unittest.main()
