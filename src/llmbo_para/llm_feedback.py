"""Scalar-only, provenance-bearing feedback for bounded LLM initialization."""
from __future__ import annotations

import math
from numbers import Real
from typing import Mapping, Sequence

import numpy as np

from .metrics import RATE_ORDER, mean_rate_rmse

RESIDUAL_KEYS = ("n_points", "mean_v", "rmse_v", "max_abs_v", "early_mean_v", "late_mean_v")


def _number(value, *, nullable=False, nonnegative=False):
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise ValueError("feedback values must be finite numeric scalars")
    if nonnegative and value < 0:
        raise ValueError("feedback magnitude must be nonnegative")
    return float(value)


def summarize_evaluation(space, record: Mapping, *, candidate_id: int) -> dict:
    """Validate labels, then select allowed scalars; never forward raw trajectories."""
    if type(candidate_id) is not int or candidate_id < 0:
        raise ValueError("feedback candidate ID must be a nonnegative integer")
    parameters = list(space.validate(record["parameters"]))
    raw_rates = record["rates"]
    if [r["rate"] for r in raw_rates] != list(RATE_ORDER):
        raise ValueError("feedback requires exactly the four ordered rate records")
    rates = {}
    for raw in raw_rates:
        valid = raw["valid"]
        if type(valid) is not bool:
            raise ValueError("feedback rate validity must be boolean")
        error = _number(raw.get("rmse_v"), nullable=not valid, nonnegative=True)
        if not valid and error is not None:
            raise ValueError("invalid rates cannot have fabricated RMSE feedback")
        end = _number(raw.get("t_end_s"), nullable=True, nonnegative=True)
        required = _number(raw.get("t_required_s"), nullable=True, nonnegative=True)
        # Legacy records can carry a real truncated trace without structured metadata.
        times = raw.get("simulation_time_s")
        if end is None and times:
            end = _number(times[-1], nullable=True, nonnegative=True)
        residual = {}
        if valid:
            for name in RESIDUAL_KEYS:
                value = (raw.get("residual_summary") or {}).get(name)
                if value is not None:
                    residual[name] = _number(value)
        censor = raw.get("coverage_right_censored")
        if censor is not None and type(censor) is not bool:
            raise ValueError("coverage censor flag must be boolean or null")
        failure_kind = raw.get("failure_kind")
        if failure_kind is not None and not isinstance(failure_kind, str):
            raise ValueError("failure kind must be a string or null")
        rates[raw["rate"]] = {"valid": valid, "rmse_v": error,
            "failure_kind": failure_kind if not valid else None,
            "t_end_s": end, "t_required_s": required,
            "coverage_fraction": end / required if end is not None and required is not None and required > 0 else None,
            "coverage_right_censored": raw.get("coverage_right_censored"),
            "residual_summary": residual}
    complete = all(r["valid"] for r in rates.values())
    if record["valid"] is not complete:
        raise ValueError("candidate and rate validity differ")
    objective = _number(record.get("objective_v"), nullable=not complete, nonnegative=True)
    if not complete and objective is not None:
        raise ValueError("incomplete candidate cannot have a fabricated objective")
    if complete and not math.isclose(objective, mean_rate_rmse({r: q["rmse_v"] for r, q in rates.items()}), rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError("feedback objective differs from four-rate mean RMSE")
    return {"candidate_id": candidate_id, "parameters": parameters,
            "valid": complete, "objective_v": objective, "rates": rates}


def build_feedback(space, records: Sequence[Mapping], *, gate=None, max_records: int = 16) -> dict:
    """Preserve successes, then recent other observations, with explicit omissions."""
    if type(max_records) is not int or not 1 <= max_records <= 64:
        raise ValueError("feedback max_records must be between 1 and 64")
    ids = [r["candidate_id"] for r in records]
    if len(set(ids)) != len(ids) or ids != sorted(ids):
        raise ValueError("feedback records must have distinct chronological IDs")
    successful = [r for r in records if r["valid"]]
    if len(successful) > max_records:
        chosen = sorted(successful, key=lambda r: (r["objective_v"], r["candidate_id"]))[:max_records]
    else:
        chosen = successful + [r for r in reversed(records) if not r["valid"]][:max_records-len(successful)]
    chosen = sorted(chosen, key=lambda r: r["candidate_id"])
    diversity = {"count": len(successful), "range_by_dimension": None,
                 "minimum_pairwise_distance": None, "mean_pairwise_distance": None}
    if successful:
        x = np.asarray([space.normalize(r["parameters"]) for r in successful])
        diversity["range_by_dimension"] = np.ptp(x, axis=0).tolist()
        if len(x) > 1:
            distances = np.linalg.norm(x[:, None, :] - x[None, :, :], axis=-1)[np.triu_indices(len(x), 1)]
            diversity.update(minimum_pairwise_distance=float(distances.min()), mean_pairwise_distance=float(distances.mean()))
    bounds = [[s.lower, s.upper] for s in space.specs]
    for i, porosity in enumerate((space.negative_porosity, space.positive_porosity)):
        if porosity is not None:
            bounds[i][1] = min(bounds[i][1], 1.0-porosity)
    if gate is not None:
        for i, coefficient in enumerate((gate.negative_ah_per_fraction, gate.positive_ah_per_fraction)):
            bounds[i][0] = max(bounds[i][0], gate.required_ah/coefficient)
    return {"schema_version": 1, "total_evaluated": len(records), "retained_count": len(chosen),
        "omitted_count": len(records)-len(chosen), "records": chosen,
        "record_selection": "successful_then_recent_other; excess_successes_sorted_by_observed_J",
        "accepted_diversity": diversity, "necessary_parameter_bounds": bounds,
        "necessary_conditions_only": True, "search_bounds_changed": False,
        "guidance": "These are already evaluated records, not proposed scores. Use real four-rate RMSE and signed residuals alongside completion feedback; null means unavailable. Generated candidates not listed here are not evaluated. The derived bounds express existing necessary inventory/porosity conditions, not a guarantee of DFN completion."}
