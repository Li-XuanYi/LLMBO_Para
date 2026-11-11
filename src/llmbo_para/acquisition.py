"""Numerical Monte Carlo Composite EI for the equal-weight four-rate objective."""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np

from .metrics import RATE_ORDER, LogRMSETransform


def scalar_log_ei(mean, std, transform: LogRMSETransform, best_objective_v: float) -> np.ndarray:
    """Exact EI in volts for J=max(exp(log(J+epsilon))-epsilon, 0).

    A single GP models standardized log *mean four-rate RMSE*. This is not
    the mean of four logarithms. No Monte Carlo draws or rate independence
    assumption are needed for this scalar posterior.
    """
    mean, std = np.asarray(mean, dtype=float), np.asarray(std, dtype=float)
    if mean.ndim != 1 or mean.shape != std.shape or np.any(~np.isfinite(mean)) or np.any(~np.isfinite(std)) or np.any(std < 0):
        raise ValueError("scalar EI needs finite, equally shaped posterior vectors and nonnegative std")
    if not math.isfinite(best_objective_v) or best_objective_v < 0:
        raise ValueError("scalar EI threshold must be finite and nonnegative")
    mu = transform.mean + transform.std * mean + math.log(transform.reference_v)
    sigma = transform.std * std
    deterministic = sigma < 1e-12
    safe_sigma = np.maximum(sigma, 1e-12)

    def put(strike):
        d = (math.log(strike) - mu) / safe_sigma
        cdf = lambda values: np.array([0.5 * math.erfc(-float(v) / math.sqrt(2)) for v in values])
        # The second term cannot exceed the strike mathematically. Compute in
        # log space to avoid overflow of the untruncated lognormal mean.
        z = d - safe_sigma
        log_cdf = np.empty_like(z)
        tail = z < -10
        v = z[tail]
        log_cdf[tail] = -.5*v*v - np.log(-v) - .5*math.log(2*math.pi) + np.log(1 - 1/v**2 + 3/v**4 - 15/v**6 + 105/v**8)
        log_cdf[~tail] = np.log(np.maximum(cdf(z[~tail]), np.finfo(float).tiny))
        term = np.exp(np.minimum(mu + .5*safe_sigma**2 + log_cdf, math.log(strike)))
        return np.maximum(strike*cdf(d) - term, 0.)

    ei = np.maximum(put(best_objective_v + transform.epsilon_v) - put(transform.epsilon_v), 0.)
    prediction = np.maximum(np.exp(np.clip(mu, -700, 700)) - transform.epsilon_v, 0.)
    ei[deterministic] = np.maximum(best_objective_v - prediction[deterministic], 0.)
    return np.minimum(ei, best_objective_v)


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
