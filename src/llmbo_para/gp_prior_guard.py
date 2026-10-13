"""Forward predictive comparison of an ordinary and a fixed LLM-subset GP.

The decision thresholds are engineering safeguards, not an IID significance test.
Only newly evaluated valid rate labels enter the ledger; initial LLM context does not.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from typing import Mapping

import numpy as np

from .metrics import RATE_ORDER, LogRMSETransform


@dataclass(frozen=True)
class GuardSettings:
    enabled: bool = False
    min_new_labels: int = 5
    min_gain: float = .05
    se_multiplier: float = 1.

    @classmethod
    def parse(cls, value=None):
        if value is not None and not isinstance(value, dict):
            raise ValueError("gp_prior_guard must be an object")
        try:
            obj = cls(**(value or {}))
        except TypeError as exc:
            raise ValueError("unknown gp_prior_guard setting") from exc
        if type(obj.enabled) is not bool or type(obj.min_new_labels) is not int or obj.min_new_labels < 2:
            raise ValueError("gp_prior_guard requires boolean enabled and min_new_labels >= 2")
        for name in ("min_gain", "se_multiplier"):
            value = getattr(obj, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError(f"gp_prior_guard.{name} must be finite and nonnegative")
        return obj


def observation_prediction(model, x) -> dict:
    """Use predictive observation variance, not an overconfident latent-only score."""
    mean, latent_std = model.predict(np.asarray(x, dtype=float).reshape(1, 6))
    variance = float(latent_std[0]**2 + math.exp(2.*model.params[7]))
    value = float(mean[0])
    if not math.isfinite(value) or not math.isfinite(variance) or variance <= 0:
        raise ValueError("invalid GP predictive observation distribution")
    return {"mean": value, "variance": variance}


def gaussian_nlpd(target: float, predictive: Mapping) -> float:
    mean, variance = float(predictive["mean"]), float(predictive["variance"])
    if not all(math.isfinite(v) for v in (target, mean, variance)) or variance <= 0:
        raise ValueError("NLPD requires finite moments and positive variance")
    value = .5*(math.log(2*math.pi) + math.log(variance) + ((target-mean)/math.sqrt(variance))**2)
    if not math.isfinite(value):
        raise ValueError("non-finite GP predictive score")
    return value


class PredictivePriorGuard:
    def __init__(self, settings: GuardSettings, *, initial_count: int):
        if type(initial_count) is not int or initial_count < 0:
            raise ValueError("initial count must be a nonnegative integer")
        self.settings = settings
        self.initial_count = initial_count
        self.last_candidate_id = initial_count - 1
        self.scores = {rate: [] for rate in RATE_ORDER}

    def predict_before(self, candidate_id, x, pairs, transforms) -> dict:
        if candidate_id < self.initial_count or candidate_id != self.last_candidate_id + 1:
            raise ValueError("prior predictions must follow chronological post-initialization evaluations")
        rates = {}
        for rate in RATE_ORDER:
            if rate not in pairs or rate not in transforms:
                continue
            rates[rate] = {"transform": asdict(transforms[rate]),
                **{name: observation_prediction(pairs[rate][name], x) for name in ("ordinary", "mixed")}}
        return {"candidate_id": candidate_id, "record_count": candidate_id,
                "normalized_parameters": list(map(float, x)), "rates": rates}

    def observe(self, prediction: Mapping, record: Mapping) -> dict:
        candidate_id = prediction["candidate_id"]
        if candidate_id < self.initial_count or candidate_id != self.last_candidate_id + 1:
            raise ValueError("prior scores must follow chronological post-initialization evaluations")
        if prediction.get("record_count") != candidate_id:
            raise ValueError("prior prediction record count permits lookahead")
        raw_rates = record["rates"]
        if [r["rate"] for r in raw_rates] != list(RATE_ORDER):
            raise ValueError("prior scoring needs four ordered rate results")
        updates = {}
        for result in raw_rates:
            rate = result["rate"]
            if not result["valid"] or rate not in prediction["rates"]:
                continue
            error = result["rmse_v"]
            if error is None:
                raise ValueError("valid rate missing actual RMSE for predictive scoring")
            data = prediction["rates"][rate]
            target = LogRMSETransform(**data["transform"]).transform(error)
            full = gaussian_nlpd(target, data["ordinary"])
            mixed = gaussian_nlpd(target, data["mixed"])
            row = {"candidate_id": candidate_id, "nlpd_ordinary": full,
                   "nlpd_mixed": mixed, "gain": full-mixed}
            updates[rate] = row
        # Commit only after every score validates, avoiding partially updated state.
        for rate, row in updates.items():
            self.scores[rate].append(row)
        self.last_candidate_id = candidate_id
        return {"candidate_id": candidate_id, "updates": updates}

    def decision(self, rate: str, *, has_group: bool) -> dict:
        values = [row["gain"] for row in self.scores[rate]]
        n = len(values)
        mean = float(np.mean(values)) if n else None
        se = float(np.std(values, ddof=1)/math.sqrt(n)) if n > 1 else None
        threshold = self.settings.min_gain + self.settings.se_multiplier*se if se is not None else None
        if not self.settings.enabled:
            active, reason = "ordinary", "guard_disabled"
        elif not has_group:
            active, reason = "ordinary", "no_parameter_group"
        elif n < self.settings.min_new_labels:
            active, reason = "ordinary", "insufficient_new_valid_labels"
        elif mean > threshold:
            active, reason = "mixed", "forward_prediction_gain"
        else:
            active, reason = "ordinary", "no_reliable_forward_gain"
        return {"active": active, "reason": reason, "new_valid_labels": n,
                "mean_nlpd_gain": mean, "gain_standard_error": se, "required_gain": threshold}

    def state_dict(self) -> dict:
        return {"settings": asdict(self.settings), "initial_count": self.initial_count,
                "last_candidate_id": self.last_candidate_id,
                "scores": {rate: [dict(row) for row in rows] for rate, rows in self.scores.items()}}
