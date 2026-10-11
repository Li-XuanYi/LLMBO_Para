"""Numerical Monte Carlo Composite EI for the equal-weight four-rate objective."""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from .metrics import RATE_ORDER, LogRMSETransform


def composite_ei(
    candidates: Sequence[Sequence[float]],
    models: Mapping[str, object],
    transforms: Mapping[str, LogRMSETransform],
    best_objective_v: float,
    *,
    draws: int = 512,
    seed: int = 0,
) -> np.ndarray:
    x = np.asarray(candidates, dtype=float)
    if x.ndim != 2 or x.shape[1] != 6 or np.any(~np.isfinite(x)):
        raise ValueError("candidates must be a finite n by 6 matrix")
    if set(models) != set(RATE_ORDER) or set(transforms) != set(RATE_ORDER):
        raise ValueError("four GP models and four frozen output transforms are required")
    if not math.isfinite(best_objective_v) or best_objective_v < 0 or draws < 1:
        raise ValueError("best objective and Monte Carlo draw count are invalid")
    rng = np.random.default_rng(seed)
    total = np.zeros((draws, len(x)), dtype=float)
    for rate in RATE_ORDER:
        mean, std = models[rate].predict(x)
        if np.any(~np.isfinite(mean)) or np.any(~np.isfinite(std)) or np.any(std < 0):
            raise ValueError(f"{rate} GP returned invalid posterior moments")
        z = mean[None, :] + std[None, :] * rng.standard_normal((draws, len(x)))
        error = np.exp(np.clip(transforms[rate].mean + transforms[rate].std * z, -700, 700))
        error = np.maximum(error * transforms[rate].reference_v - transforms[rate].epsilon_v, 0.0)
        total += error / 4.0
    return np.maximum(best_objective_v - total, 0.0).mean(axis=0)
