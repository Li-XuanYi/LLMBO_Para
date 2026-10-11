"""Explicit software fixtures. None of these values are battery recommendations."""

from __future__ import annotations

from .evaluation import DischargeSeries
from .metrics import RATE_ORDER
from .parameters import PARAMETER_NAMES, ParameterSpace


def synthetic_config(budget: int = 5) -> dict:
    bounds = ((0.2, 0.8), (0.2, 0.8), (1e-16, 1e-12), (1e-16, 1e-12), (0.1, 300), (0.1, 300))
    units = ("1", "1", "m2.s-1", "m2.s-1", "S.m-1", "S.m-1")
    return {
        "schema_version": 1, "run_kind": "synthetic_software_smoke_only",
        "cell_id": "software-fixture-no-physical-cell", "cell_format": "synthetic",
        "nominal_capacity_ah": 1.0, "rates": list(RATE_ORDER),
        "parameters": {name: {"lower": lo, "upper": hi, "unit": unit, "transform": "log10" if i in (2, 3) else "linear"}
                       for i, (name, (lo, hi), unit) in enumerate(zip(PARAMETER_NAMES, bounds, units))},
        "physical_constraints": {"fixed_porosity": {"negative": None, "positive": None}},
        "conditions_by_rate": {rate: {"initial_soc": 1.0, "initial_temperature_k": 298.15,
                                      "ambient_temperature_k": 298.15, "voltage_cutoff_v": 2.5} for rate in RATE_ORDER},
        "data": {"kind": "builtin_synthetic", "evaluation_grid": "all_measured_samples_no_extrapolation",
                 "discharge_current_sign": 1, "time_unit": "s", "current_unit": "A", "voltage_unit": "V"},
        "model": {"provider": "synthetic", "name": "DFN", "fixture_formula": "normalized_quadratic_voltage_offset"},
        "optimization": {"seed": 20261010, "warm_start_llm_points": 0, "sobol_points": 4,
                         "total_candidate_budget": budget, "candidate_pool_size": 64, "composite_ei_draws": 64,
                         "gp_sweeps": 2, "max_rate_attempts": 1, "parallel_workers": 1,
                         "llm_enabled": False, "gpu_backend": "cpu"},
        "llm": {"transport": "structured_json_service", "endpoint": None, "api_key_env": None,
                "model": None, "timeout_s": 30.0, "min_diversity_distance": 0.001},
    }


def synthetic_series() -> dict[str, DischargeSeries]:
    return {rate: DischargeSeries(rate, (0, 1, 2, 3), (4.2, 4.05, 3.9, 3.75),
                                 (1, 1, 1, 1), discharge_current_sign=1) for rate in RATE_ORDER}


class SyntheticSimulator:
    def __init__(self, space: ParameterSpace):
        self.space = space

    def simulate(self, parameters, measured):
        x = self.space.normalize(tuple(parameters[name] for name in PARAMETER_NAMES))
        offset = 0.001 + sum((v - 0.37) ** 2 for v in x) * 0.01
        offset += RATE_ORDER.index(measured.rate) * 0.0001
        return measured.time_s, tuple(v + offset for v in measured.voltage_v)
