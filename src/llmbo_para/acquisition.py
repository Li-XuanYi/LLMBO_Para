"""Numerical Monte Carlo Composite EI for the equal-weight four-rate objective."""

from __future__ import annotations

import math
import json
from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np

from .metrics import RATE_ORDER, LogRMSETransform
from .runstore import digest_value


@dataclass(frozen=True)
class FrozenAcquisitionView:
    """Owned immutable moments in one frozen standardized scalar target space."""

    context_id: str
    pool_digest: str
    gp_state_digest: str
    scalarization_digest: str
    pool: tuple[tuple[float, ...], ...]
    best: float
    mean: tuple[float, ...]
    std: tuple[float, ...]
    plain_ei: tuple[float, ...]
    plain_index: int


def _acquisition_binding(gp, context, pool) -> tuple:
    """Reject mismatched history/posterior/pool before predicting or evaluating."""
    x = np.asarray(pool, dtype=float)
    frozen_pool = np.asarray(context.pool, dtype=float)
    if (x.ndim != 2 or not len(x) or x.shape[1] != 6
            or np.any(~np.isfinite(x)) or np.any((x < 0) | (x > 1))
            or frozen_pool.shape != x.shape or not np.array_equal(x, frozen_pool)):
        raise ValueError('finite ordered pool must match the frozen six-dimensional context')
    if type(context.context_id) is not str or not context.context_id:
        raise ValueError('frozen context identity required')
    state_digest = digest_value(gp.state_dict())
    if state_digest != digest_value(json.loads(context.gp_state_json)):
        raise ValueError('GP state differs from the frozen context')
    best = context.scalarization.best
    if not math.isfinite(best):
        raise ValueError('finite frozen incumbent required')
    owned_pool = tuple(tuple(float(value) for value in row) for row in x)
    return (owned_pool, digest_value(owned_pool), state_digest,
            digest_value(context.scalarization.to_dict()), float(best))


def build_acquisition_view(gp, context, pool) -> FrozenAcquisitionView:
    """Compute exactly one base prediction and Gaussian EI; own all output values."""
    owned_pool, pool_digest, gp_digest, scalar_digest, best = _acquisition_binding(gp, context, pool)
    mean, std = gp.predict(owned_pool)
    ei = gaussian_ei(mean, std, best)
    view = FrozenAcquisitionView(context.context_id, pool_digest, gp_digest, scalar_digest,
        owned_pool, best, tuple(float(value) for value in mean),
        tuple(float(value) for value in std), tuple(float(value) for value in ei), int(np.argmax(ei)))
    validate_acquisition_view(view, gp, context, owned_pool)
    return view


def validate_acquisition_view(view: FrozenAcquisitionView, gp, context, pool) -> None:
    """Validate binding and finite immutable moments, without prediction/EI replay.

    This is a host-owned computation view, never an LLM credential. Independent
    archive auditing still verifies posterior moments and acquisition arithmetic.
    """
    if type(view) is not FrozenAcquisitionView:
        raise ValueError('a frozen acquisition view is required')
    owned_pool, pool_digest, gp_digest, scalar_digest, best = _acquisition_binding(gp, context, pool)
    if (view.context_id != context.context_id or view.pool_digest != pool_digest
            or view.gp_state_digest != gp_digest or view.scalarization_digest != scalar_digest
            or view.best != best or type(view.pool) is not tuple
            or any(type(row) is not tuple for row in view.pool) or view.pool != owned_pool):
        raise ValueError('stale acquisition view: context, pool, GP, scalarization or incumbent differs')
    for name in ('mean', 'std', 'plain_ei'):
        values = getattr(view, name)
        if (type(values) is not tuple or len(values) != len(owned_pool)
                or any(type(value) not in (int, float) or not math.isfinite(value) for value in values)):
            raise ValueError('finite aligned immutable acquisition moments required')
    if any(value < 0 for value in (*view.std, *view.plain_ei)):
        raise ValueError('nonnegative acquisition standard deviations and EI required')
    if type(view.plain_index) is not int or view.plain_index != int(np.argmax(view.plain_ei)):
        raise ValueError('plain acquisition index must retain the original first-maximum rule')


def gaussian_ei(mean, std, best: float) -> np.ndarray:
    """Minimization EI in the current linearly standardized scalar space."""
    mean=np.asarray(mean,dtype=float);std=np.asarray(std,dtype=float)
    if mean.ndim!=1 or mean.shape!=std.shape or np.any(~np.isfinite(mean)) or np.any(~np.isfinite(std)) or np.any(std<0) or not math.isfinite(best):
        raise ValueError('finite aligned Gaussian posterior and threshold required')
    improvement=best-mean;positive=std>0;ei=np.maximum(improvement,0.)
    z=improvement[positive]/std[positive]
    cdf=np.array([.5*math.erfc(-float(v)/math.sqrt(2)) for v in z])
    ei[positive]=improvement[positive]*cdf+std[positive]*np.exp(-.5*z*z)/math.sqrt(2*math.pi)
    return np.maximum(ei,0.)


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
