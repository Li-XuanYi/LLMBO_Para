"""Conditioned LogNormal priors defined on GP lengthscales, not their logs.

The coordinate optimizer works in log lengthscales for numerical convenience.
That change of optimizer coordinates does not change the declared density:
MAP here maximizes a density with respect to d(ell), including -log(ell).
"""

from __future__ import annotations

import math
from typing import Mapping, Sequence

import numpy as np


LENGTHSCALE_BOUNDS = (0.03, 8.0)


def _six_values(value, name: str, *, allow_scalar: bool = False) -> list[float]:
    try:
        values = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain finite numbers") from exc
    if allow_scalar and values.ndim == 0:
        values = np.full(6, float(values))
    if values.shape != (6,) or np.any(~np.isfinite(values)):
        raise ValueError(f"{name} must contain six finite numbers")
    return values.tolist()


def _interval_probability(mu: float, sigma: float) -> float:
    lower, upper = (math.log(bound) for bound in LENGTHSCALE_BOUNDS)
    za, zb = (lower - mu) / sigma, (upper - mu) / sigma
    # Use the survival function in the positive tail to avoid subtracting
    # two values rounded to one; use the CDF in the negative tail.
    if za >= 0:
        mass = 0.5 * (math.erfc(za / math.sqrt(2)) - math.erfc(zb / math.sqrt(2)))
    else:
        mass = 0.5 * (math.erfc(-zb / math.sqrt(2)) - math.erfc(-za / math.sqrt(2)))
    if not math.isfinite(mass) or mass <= 0:
        raise ValueError("lengthscale prior has no numerically representable mass within bounds")
    return mass


def normalize_lengthscale_prior(prior: Mapping | None) -> dict | None:
    """Validate a six-dimensional independent, bounded LogNormal density.

    ``mu`` is a six-vector of log-space locations; ``sigma`` is a positive
    scalar or six-vector. ``density_domain`` must explicitly be ``lengthscale``.
    Optional bounds must match the existing GP search bounds [0.03, 8.0].
    """
    if prior is None:
        return None
    if not isinstance(prior, Mapping):
        raise ValueError("lengthscale_prior must be a mapping or None")
    unknown = set(prior) - {"mu", "sigma", "density_domain", "bounds"}
    if unknown:
        raise ValueError(f"unknown lengthscale prior fields: {sorted(unknown)}")
    if prior.get("density_domain") != "lengthscale":
        raise ValueError("lengthscale prior density_domain must be explicitly 'lengthscale'")
    if "mu" not in prior or "sigma" not in prior:
        raise ValueError("lengthscale prior requires mu and sigma")
    mu = _six_values(prior["mu"], "prior mu")
    sigma = _six_values(prior["sigma"], "prior sigma", allow_scalar=True)
    if any(value <= 0 for value in sigma):
        raise ValueError("prior sigma must be positive")
    try:
        bounds = np.asarray(prior.get("bounds", LENGTHSCALE_BOUNDS), dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("prior bounds must match [0.03, 8.0]") from exc
    if bounds.shape != (2,) or not np.array_equal(bounds, LENGTHSCALE_BOUNDS):
        raise ValueError("prior bounds must match [0.03, 8.0]")
    for location, scale in zip(mu, sigma):
        _interval_probability(location, scale)
    return {"mu": mu, "sigma": sigma, "density_domain": "lengthscale",
            "bounds": list(LENGTHSCALE_BOUNDS)}


def lengthscale_log_prior(log_lengthscales: Sequence[float], prior: Mapping | None) -> float:
    """Log density of independent conditioned LogNormals on actual ell.

    Arguments are log coordinates, but the returned density is with respect
    to actual lengthscales. A constant normalizer conditions each dimension
    on the GP's existing lengthscale search interval.
    """
    if prior is None:
        return 0.0
    values = np.asarray(log_lengthscales, dtype=float)
    if values.shape != (6,) or np.any(~np.isfinite(values)):
        raise ValueError("log lengthscales must contain six finite numbers")
    low, high = (math.log(bound) for bound in LENGTHSCALE_BOUNDS)
    if np.any(values < low) or np.any(values > high):
        return -math.inf
    normalized = normalize_lengthscale_prior(prior)
    total = 0.0
    for value, mu, sigma in zip(values, normalized["mu"], normalized["sigma"]):
        z = (value - mu) / sigma
        total += (-0.5 * z * z - value - math.log(sigma)
                  - 0.5 * math.log(2 * math.pi)
                  - math.log(_interval_probability(mu, sigma)))
    return float(total)
