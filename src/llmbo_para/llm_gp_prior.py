"""Bounded LLM hypotheses for full-dimensional ARD lengthscale priors.

This opt-in interface does not change live BO. It reuses LLMClient's archived
transport. Neutral suggestions remain valid and never trigger a forced repair.
"""
from __future__ import annotations
import math
from collections.abc import Mapping
import numpy as np
from .metrics import RATE_ORDER

MAX_SHIFT = math.log(2.0)
BASE_MU = math.sqrt(2.0) + 0.5 * math.log(6.0)
BASE_SIGMA = math.sqrt(3.0)


def make_prior(shifts=None):
    shifts = [0.0] * 6 if shifts is None else shifts
    if len(shifts) != 6 or any(type(v) not in (int, float) or not math.isfinite(v)
                              or abs(v) > MAX_SHIFT for v in shifts):
        raise ValueError("six finite log-lengthscale shifts in [-ln(2),ln(2)] required")
    return {"mu": [BASE_MU + float(v) for v in shifts], "sigma": [BASE_SIGMA] * 6,
            "density_domain": "lengthscale", "bounds": [0.03, 8.0]}


def summarize_observations(space, records):
    """Whitelist summaries only: never transmit time series or arbitrary fields."""
    rows = []
    seen = set()
    scalar_fields = ("rate", "valid", "rmse_v", "failure_kind", "termination",
                     "t_end_s", "t_required_s", "coverage_margin", "coverage_right_censored")
    residual_fields = ("n_points", "mean_v", "rmse_v", "max_abs_v", "early_mean_v", "late_mean_v")
    for record_id, record in records:
        if not isinstance(record_id, str) or record_id in seen:
            raise ValueError("observation IDs must be unique strings")
        seen.add(record_id)
        rates = []
        for q in record["rates"]:
            row = {k: q[k] for k in scalar_fields if k in q}
            row["residual_summary"] = {k: q["residual_summary"][k] for k in residual_fields
                                        if k in (q.get("residual_summary") or {})}
            rates.append(row)
        rows.append({"id": record_id, "parameters": list(record["parameters"]),
                     "normalized_parameters": list(space.normalize(record["parameters"])),
                     "complete_four_rates": bool(record["valid"]), "rates": rates})
    return rows


def build_payload(space, records):
    observations = summarize_observations(space, records)
    if not observations:
        raise ValueError("training observations required")
    x = np.asarray([o["normalized_parameters"] for o in observations])
    return {"task": "lengthscale_prior", "rates": list(RATE_ORDER),
            "parameter_order": [s.name for s in space.specs],
            "units": [s.unit for s in space.specs],
            "bounds": [[s.lower, s.upper] for s in space.specs],
            "transforms": [s.transform for s in space.specs],
            "observations": observations,
            "training_summary": {"count": len(observations),
                "normalized_spans": np.ptp(x, axis=0).tolist(),
                "valid_count_by_rate": {r: sum(q["valid"] for o in observations for q in o["rates"] if q["rate"] == r) for r in RATE_ORDER}},
            "gp_target": "Per-rate standardized log of full-horizon voltage RMSE; one full-six-dimensional Matern-5/2 ARD GP per rate.",
            "prior_policy": {"base_mu": BASE_MU, "sigma": BASE_SIGMA,
                "lengthscale_bounds": [0.03, 8.0], "max_abs_log_shift": MAX_SHIFT,
                "density_domain": "lengthscale", "variance_is_not_adjustable": True},
            "response_schema": {"priors": {r: {"log_lengthscale_shifts": "six finite numbers, [-ln(2),ln(2)]",
                 "rationale": "short physical and statistical hypothesis with limitations",
                 "evidence_ids": "list of supplied training observation IDs, may be empty",
                 "uncertainty": "high, medium, or low"} for r in RATE_ORDER}}}


def validate_response(response, evidence_ids):
    if not isinstance(response, Mapping) or set(response) != {"priors"}:
        raise ValueError("response must contain only priors")
    priors = response["priors"]
    if not isinstance(priors, Mapping) or set(priors) != set(RATE_ORDER):
        raise ValueError("exactly the four configured rates are required")
    result = {}
    for rate in RATE_ORDER:
        row = priors[rate]
        required = {"log_lengthscale_shifts", "rationale", "evidence_ids", "uncertainty"}
        if not isinstance(row, Mapping) or set(row) != required:
            raise ValueError(f"{rate}: exact prior fields required")
        shifts = row["log_lengthscale_shifts"]
        if not isinstance(shifts, list):
            raise ValueError(f"{rate}: shifts must be a list")
        prior = make_prior(shifts)
        if not isinstance(row["rationale"], str) or not 1 <= len(row["rationale"].strip()) <= 4000:
            raise ValueError(f"{rate}: short nonempty rationale required")
        ids = row["evidence_ids"]
        if not isinstance(ids, list) or any(not isinstance(v, str) or v not in evidence_ids for v in ids):
            raise ValueError(f"{rate}: unknown training evidence ID")
        if row["uncertainty"] not in ("high", "medium", "low"):
            raise ValueError(f"{rate}: uncertainty must be high/medium/low")
        result[rate] = {**row, "lengthscale_prior": prior,
                        "informative": any(abs(v) > 1e-12 for v in shifts)}
    return result


def request_priors(client, space, records):
    """One request; at most one explicit schema repair. No benefit chasing."""
    payload = build_payload(space, records)
    ids = {o["id"] for o in payload["observations"]}
    for attempt in (1, 2):
        prefix = f"prior-requests/attempt-{attempt:03d}/"
        response = client._request(payload, archive_prefix=prefix)
        try:
            result = validate_response(response, ids)
        except ValueError as exc:
            if client.store:
                client.store.write_json(prefix + "validation.json", {"accepted": False, "reason": str(exc)})
            if attempt == 2:
                raise
            payload = {**payload, "contract_repair": {"previous_response": response, "error": str(exc),
                "instruction": "Repair the schema only. Neutral shifts are valid; do not manufacture a nonzero adjustment."}}
            continue
        if client.store:
            client.store.write_json(prefix + "validation.json", {"accepted": True, "attempts": attempt,
                "informative_by_rate": {r: result[r]["informative"] for r in RATE_ORDER}})
        return result
    raise AssertionError("unreachable")
