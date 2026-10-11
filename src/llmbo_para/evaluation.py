"""Fixed-grid evaluation; failed rates never receive fabricated GP targets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import time
import traceback
from typing import Callable, Mapping, Protocol, Sequence

import numpy as np

from .metrics import RATE_ORDER, mean_rate_rmse, rmse
from .parameters import ParameterSpace


@dataclass(frozen=True)
class DischargeSeries:
    rate: str
    time_s: tuple[float, ...]
    voltage_v: tuple[float, ...]
    current_a: tuple[float, ...] | None = None
    temperature: tuple[float, ...] | None = None
    current_source: str = "measured"
    assumptions: tuple[str, ...] = ()
    time_source: str = "measured"
    discharge_current_sign: int | None = None

    def __post_init__(self) -> None:
        if self.rate not in RATE_ORDER:
            raise ValueError(f"unknown rate: {self.rate}")
        n = len(self.time_s)
        if n < 2 or len(self.voltage_v) != n:
            raise ValueError("time and voltage must have at least two aligned samples")
        if self.current_a is not None and len(self.current_a) != n:
            raise ValueError("current must align with time and voltage")
        if self.temperature is not None and len(self.temperature) != n:
            raise ValueError("temperature must align with time")
        arrays = [self.time_s, self.voltage_v]
        if self.current_a is not None:
            arrays.append(self.current_a)
        if self.temperature is not None:
            arrays.append(self.temperature)
        if any(not math.isfinite(float(x)) for arr in arrays for x in arr):
            raise ValueError("series values must be finite")
        if any(b <= a for a, b in zip(self.time_s, self.time_s[1:])):
            raise ValueError("time values must be strictly increasing")
        if self.current_source not in {"measured", "legacy_assumed_1s"}:
            raise ValueError("current_source must be measured or legacy_assumed_1s")
        if self.current_source == "measured" and self.current_a is None:
            raise ValueError("measured-current series require current values")
        if self.time_source not in {"measured", "legacy_assumed_1s"}:
            raise ValueError("unknown time provenance")
        if self.discharge_current_sign not in {None, -1, 1}:
            raise ValueError("discharge current sign must be -1 or +1")


class TransientSimulationError(RuntimeError):
    """Explicit retry signal; physical/coverage failures are not retried blindly."""


@dataclass(frozen=True)
class RateResult:
    rate: str
    valid: bool
    rmse_v: float | None
    elapsed_s: float
    reason: str | None = None
    simulation_time_s: tuple[float | None, ...] | None = None
    simulation_voltage_v: tuple[float | None, ...] | None = None
    aligned_voltage_v: tuple[float, ...] | None = None
    residual_summary: dict | None = None
    attempts: tuple[dict, ...] = ()


@dataclass(frozen=True)
class EvaluationResult:
    parameters: tuple[float, ...]
    rates: tuple[RateResult, ...]
    valid: bool
    objective_v: float | None
    cache_provenance: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class RateSimulator(Protocol):
    def simulate(self, parameters: Mapping[str, float], series: DischargeSeries) -> tuple[Sequence[float], Sequence[float]]: ...


class CallableSimulator:
    """Injectable adapter for tests and a lab-specific PyBaMM integration."""

    def __init__(self, function: Callable[[Mapping[str, float], DischargeSeries], tuple[Sequence[float], Sequence[float]]]):
        self.function = function

    def simulate(self, parameters: Mapping[str, float], series: DischargeSeries):
        return self.function(parameters, series)


class FourRateEvaluator:
    def __init__(self, space: ParameterSpace, simulator: RateSimulator, *, max_rate_attempts: int = 1, event_callback=None):
        if not isinstance(max_rate_attempts, int) or isinstance(max_rate_attempts, bool) or max_rate_attempts < 1:
            raise ValueError("max_rate_attempts must be a positive integer")
        self.space = space
        self.simulator = simulator
        self.max_rate_attempts = max_rate_attempts
        self.event_callback = event_callback

    def evaluate(self, candidate: Sequence[float], series_by_rate: Mapping[str, DischargeSeries]) -> EvaluationResult:
        point = self.space.validate(candidate)
        if set(series_by_rate) != set(RATE_ORDER):
            raise ValueError(f"exactly the four rates are required: {RATE_ORDER}")
        params = dict(zip((s.name for s in self.space.specs), point))
        results = []
        for rate in RATE_ORDER:
            series = series_by_rate[rate]
            if series.rate != rate:
                raise ValueError(f"series key {rate} contains {series.rate}")
            attempts = []
            started = time.perf_counter()
            final = None
            for attempt in range(1, self.max_rate_attempts + 1):
                start = time.perf_counter()
                if self.event_callback:
                    self.event_callback({"type": "rate_started", "rate": rate, "attempt": attempt, "parameters": point})
                raw_t = raw_v = None
                try:
                    sim_t, sim_v = self.simulator.simulate(params, series)
                    t = np.asarray(sim_t, dtype=float)
                    v = np.asarray(sim_v, dtype=float)
                    raw_t = tuple(float(z) if np.isfinite(z) else None for z in t.ravel())
                    raw_v = tuple(float(z) if np.isfinite(z) else None for z in v.ravel())
                    observed_t = np.asarray(series.time_s, dtype=float)
                    if t.ndim != 1 or v.shape != t.shape or t.size < 2:
                        raise ValueError("simulator returned misaligned time and voltage arrays")
                    if np.any(~np.isfinite(t)) or np.any(~np.isfinite(v)) or np.any(np.diff(t) <= 0):
                        raise ValueError("simulator returned non-finite or non-increasing results")
                    if observed_t[0] < t[0] or observed_t[-1] > t[-1]:
                        raise ValueError("simulation does not cover the fixed measured time grid; extrapolation is forbidden")
                    aligned = np.interp(observed_t, t, v)
                    residual = aligned - np.asarray(series.voltage_v)
                    err = rmse(series.voltage_v, aligned)
                    n = len(residual)
                    summary = {"n_points": n, "mean_v": float(residual.mean()), "rmse_v": err,
                               "max_abs_v": float(np.abs(residual).max()),
                               "early_mean_v": float(residual[:max(1, n // 3)].mean()),
                               "late_mean_v": float(residual[-max(1, n // 3):].mean())}
                    attempts.append({"attempt": attempt, "valid": True, "elapsed_s": time.perf_counter() - start})
                    final = RateResult(rate, True, err, time.perf_counter() - started, None,
                                       raw_t, raw_v, tuple(float(z) for z in aligned), summary, tuple(attempts))
                except Exception as exc:
                    reason = f"{type(exc).__name__}: {exc}"
                    attempts.append({"attempt": attempt, "valid": False, "elapsed_s": time.perf_counter() - start,
                                     "reason": reason, "traceback": traceback.format_exc(),
                                     "simulation_time_s": raw_t, "simulation_voltage_v": raw_v,
                                     "retryable": isinstance(exc, TransientSimulationError)})
                    final = RateResult(rate, False, None, time.perf_counter() - started, reason,
                                       raw_t, raw_v, attempts=tuple(attempts))
                if self.event_callback:
                    self.event_callback({"type": "rate_finished", "rate": rate, "attempt": attempt,
                                         "valid": final.valid, "parameters": point})
                if final.valid or not attempts[-1].get("retryable"):
                    break
            results.append(final)
        valid = all(r.valid for r in results)
        objective = mean_rate_rmse({r.rate: r.rmse_v for r in results if r.rmse_v is not None}) if valid else None
        return EvaluationResult(point, tuple(results), valid, objective)
