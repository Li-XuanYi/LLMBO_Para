"""Common voltage metrics and frozen log-RMSE transformations."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Mapping, Sequence

import numpy as np

RATE_ORDER = ("0.5C", "1C", "2C", "3C")


def rmse(reference: Sequence[float], predicted: Sequence[float]) -> float:
    y = np.asarray(reference, dtype=float)
    yhat = np.asarray(predicted, dtype=float)
    if y.ndim != 1 or y.shape != yhat.shape or y.size == 0:
        raise ValueError("voltage arrays must be non-empty one-dimensional arrays of equal length")
    if not np.all(np.isfinite(y)) or not np.all(np.isfinite(yhat)):
        raise ValueError("voltage arrays must contain only finite values")
    with np.errstate(over="ignore", invalid="ignore"):
        difference = yhat - y
    if np.any(~np.isfinite(difference)):
        raise ValueError("voltage residuals overflowed; inspect simulator outputs")
    scale = float(np.max(np.abs(difference)))
    return scale * float(np.sqrt(np.mean(np.square(difference / scale)))) if scale else 0.0


def mean_rate_rmse(errors: Mapping[str, float]) -> float:
    if set(errors) != set(RATE_ORDER):
        raise ValueError(f"all four rates are required: {RATE_ORDER}")
    values = [float(errors[r]) for r in RATE_ORDER]
    if any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("RMSE values must be finite and non-negative")
    return math.fsum(values) / len(RATE_ORDER)


@dataclass(frozen=True)
class LogRMSETransform:
    mean: float
    std: float
    epsilon_v: float = 1e-8
    reference_v: float = 1.0

    def __post_init__(self):
        if not all(math.isfinite(v) for v in (self.mean, self.std, self.epsilon_v, self.reference_v)) or min(self.std, self.epsilon_v, self.reference_v) <= 0:
            raise ValueError("log-RMSE transform requires finite values and positive scale, epsilon and reference")

    @classmethod
    def fit(cls, initial_rmse: Sequence[float], epsilon_v: float = 1e-8) -> "LogRMSETransform":
        values = np.asarray(initial_rmse, dtype=float)
        if values.ndim != 1 or values.size == 0 or np.any(~np.isfinite(values)) or np.any(values < 0):
            raise ValueError("initial RMSE values must be a non-empty finite non-negative vector")
        if epsilon_v <= 0:
            raise ValueError("epsilon_v must be positive")
        log_values = np.log((values + epsilon_v) / 1.0)
        scale = float(np.std(log_values, ddof=0))
        if scale < 1e-12:
            scale = 1.0
        return cls(float(np.mean(log_values)), scale, float(epsilon_v))

    def transform(self, value: float) -> float:
        if not math.isfinite(value) or value < 0:
            raise ValueError("RMSE must be finite and non-negative")
        return (math.log((value + self.epsilon_v) / self.reference_v) - self.mean) / self.std

    def inverse_sample(self, standardized_log_rmse: float) -> float:
        exponent = self.mean + self.std * float(standardized_log_rmse)
        exponent = min(700.0, max(-700.0, exponent))
        return max(self.reference_v * math.exp(exponent) - self.epsilon_v, 0.0)
