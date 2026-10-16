"""Six-dimensional adaptation of New_LLMBO's bounded posterior-correlation lift.

The GP remains fitted only to simulated observations. This module supplies an
acquisition-time heuristic, not an extra kernel or a Bayesian observation.
Source mapping and intentional adaptations: docs/llm-informed.md.
"""
from dataclasses import asdict, dataclass
import math
from collections.abc import Mapping

import numpy as np

from .acquisition import scalar_log_ei
from .bo_repair import decision_scores, select_candidate
from .metrics import RATE_ORDER
from .sobol import Sobol6


@dataclass(frozen=True)
class InformedSettings:
    n_anchors: int = 32
    active_until: int = 12
    min_confidence: float = .60
    lambda_max: float = .25
    max_shift_std: float = .25
    min_width: float = .03
    max_width: float = .80
    anchor_temperature: float = .35
    min_feasible_anchor_ratio: float = .60
    close_distance: float = .05
    max_close_fraction: float = .50
    max_plain_log_ei_gap: float = .25
    min_sigma_ratio: float = .85
    trust_init: float = .50
    trust_beta: float = .20

    @classmethod
    def parse(cls, value=None):
        if value is not None and not isinstance(value, dict):
            raise ValueError("llm_informed must be an object")
        try:
            settings = cls(**(value or {}))
        except TypeError as exc:
            raise ValueError("unknown llm_informed setting") from exc
        for name, val in asdict(settings).items():
            if type(val) not in (int, float) or not math.isfinite(val) or val < 0:
                raise ValueError(f"llm_informed.{name} must be a finite nonnegative number")
        if type(settings.n_anchors) is not int or not 2 <= settings.n_anchors <= 256:
            raise ValueError("llm_informed.n_anchors must be an integer in [2, 256]")
        if type(settings.active_until) is not int or settings.active_until < 1:
            raise ValueError("llm_informed.active_until must be a positive integer")
        if not 0 < settings.min_width <= settings.max_width <= 1 or settings.anchor_temperature <= 0:
            raise ValueError("invalid informed region widths or anchor temperature")
        for name in ("min_confidence", "min_feasible_anchor_ratio", "max_close_fraction", "min_sigma_ratio", "trust_init", "trust_beta"):
            if getattr(settings, name) > 1:
                raise ValueError(f"llm_informed.{name} must be in [0, 1]")
        if settings.lambda_max > 1 or settings.max_shift_std > 1:
            raise ValueError("informed shifts are limited to one standardized target unit")
        return settings


def validate_region_response(payload):
    """No default parameter values, coordinate guessing, clipping or rounding."""
    if not isinstance(payload, Mapping) or set(payload) - {"kind", "coordinate_space", "lb", "ub", "confidence", "reason"}:
        raise ValueError("region response must match the documented JSON fields")
    kind = payload.get("kind")
    if kind not in ("none", "region") or payload.get("coordinate_space") != "normalized":
        raise ValueError("kind must be region/none and coordinate_space must be normalized")
    confidence = payload.get("confidence")
    if type(confidence) not in (int, float) or not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("region confidence must be a finite number in [0, 1]")
    if not isinstance(payload.get("reason"), str) or len(payload["reason"]) > 2000:
        raise ValueError("region reason must be a short string")
    result = dict(kind=kind, coordinate_space="normalized", confidence=float(confidence), reason=payload["reason"])
    if kind == "none":
        if "lb" in payload or "ub" in payload:
            raise ValueError("abstention must not contain region coordinates")
        return result
    for key in ("lb", "ub"):
        v = payload.get(key)
        if not isinstance(v, list) or len(v) != 6 or any(type(x) not in (int, float) or not math.isfinite(x) or not 0 <= x <= 1 for x in v):
            raise ValueError("region bounds require exactly six finite normalized numbers")
        result[key] = [float(x) for x in v]
    if any(lo >= hi for lo, hi in zip(result["lb"], result["ub"])):
        raise ValueError("each region lower bound must be strictly below its upper bound")
    return result


def observation_summary(space, records):
    """Allowlisted top/recent evaluation summaries; never send pointwise curves."""
    top = sorted((i for i, r in enumerate(records) if r.valid), key=lambda i: records[i].objective_v)[:8]
    ids = sorted(set(top + list(range(max(0, len(records)-8), len(records)))))
    rows = []
    for i in ids:
        r = records[i]
        rates = {q.rate: {"valid": q.valid, "rmse_v": q.rmse_v,
            "covered_until_s": q.t_end_s, "required_until_s": q.t_required_s,
            "coverage_right_censored": q.coverage_right_censored,
            "failure_kind": q.failure_kind, "residual_summary": q.residual_summary} for q in r.rates}
        rows.append({"record_id": i, "parameters_normalized": list(space.normalize(r.parameters)),
            "valid": r.valid, "objective_v": r.objective_v, "rates": rates})
    return rows


def region_decision(gp, transform, best, pool, eligible, preference, *, space, settings,
                    trust, iteration, seed, candidate_id, probabilities=None, feasibility_weighting=False,
                    candidate_filter=None):
    """Pure/replayable adaptation of evaluate_region_lift_on_pool.

    Reuses its EI/uncertainty/novelty anchor weights, posterior correlation,
    bounded mean shift, and plain-EI/inside-region/uncertainty safeguards.
    All comparisons respect the existing global exploration eligibility mask.
    """
    x = np.asarray(pool, dtype=float)
    eligible = np.asarray(eligible, dtype=bool)
    mean, std = gp.predict(x)
    plain_ei = scalar_log_ei(mean, std, transform, best)
    plain_scores, _, _ = decision_scores(plain_ei, probabilities, enabled=feasibility_weighting)
    plain = select_candidate(plain_scores, eligible, seed=seed, candidate_id=candidate_id)
    result = dict(accepted=False, selected_index=plain, plain_index=plain, lifted_index=None,
        fallback_reason=None, mean_z=mean.tolist(), std_z=std.tolist(),
        shift_z=np.zeros(len(x)).tolist(), lifted_mean_z=mean.tolist(),
        plain_ei_v=plain_ei.tolist(), lifted_ei_v=plain_ei.tolist(),
        effective_ei_v=plain_ei.tolist(), effective_scores=plain_scores.tolist(),
        sigma_unchanged=True, preference=preference, trust_before=float(trust), iteration=iteration)

    def fallback(reason):
        result["fallback_reason"] = reason
        return result

    if iteration >= settings.active_until:
        return fallback("inactive")
    preference = validate_region_response(preference)
    if preference["kind"] == "none":
        return fallback("llm_abstained")
    if preference["confidence"] < settings.min_confidence:
        return fallback("low_confidence")
    lb, ub = np.array(preference["lb"]), np.array(preference["ub"])
    width = ub-lb
    if np.any(width < settings.min_width-1e-12) or np.any(width > settings.max_width+1e-12):
        return fallback("region_width")
    # Separate sequence: adding the LLM module must not advance the BO pool RNG.
    anchors = lb + Sobol6(start_index=1).draw(settings.n_anchors)*width
    keep = []
    for a in anchors:
        try:
            physical = space.denormalize(a)
            keep.append(candidate_filter is None or candidate_filter(physical)["feasible"])
        except ValueError:
            keep.append(False)
    ratio = float(np.mean(keep))
    result["feasible_anchor_ratio"] = ratio
    if ratio < settings.min_feasible_anchor_ratio or not any(keep):
        return fallback("insufficient_legal_anchors")
    anchors = anchors[np.asarray(keep)]
    novelty = np.linalg.norm(anchors[:, None, :] - gp.x[None, :, :], axis=2).min(axis=1)
    result["close_fraction"] = float(np.mean(novelty < settings.close_distance))
    if result["close_fraction"] > settings.max_close_fraction:
        return fallback("too_close_to_observed")
    ma, sa = gp.predict(anchors)
    anchor_ei = scalar_log_ei(ma, sa, transform, best)

    def zscore(v):
        return (v-v.mean()) / max(float(v.std()), 1e-12)

    signal = .60*zscore(np.log(np.maximum(anchor_ei, 1e-12))) + .25*zscore(sa) + .15*zscore(novelty)
    logits = signal/settings.anchor_temperature
    weights = np.exp(logits-logits.max()); weights /= weights.sum()
    entropy = -float(np.sum(weights*np.log(weights+1e-12)))
    consistency = float(np.clip(.55*(1-entropy/math.log(len(weights)))+.45*np.tanh(signal.std()), 0, 1)) if len(weights)>1 else 0.
    kgg = gp.posterior_covariance(anchors) + np.eye(len(anchors))*1e-6
    kxg = gp.posterior_covariance(x, anchors)
    norm_sq = float(weights @ kgg @ weights)
    if not math.isfinite(norm_sq) or norm_sq <= 1e-12 or np.any(~np.isfinite(kxg)):
        return fallback("degenerate_posterior_covariance")
    corr = np.clip((kxg@weights) / np.sqrt(np.maximum(std**2 * norm_sq, 1e-12)), -1, 1)
    anneal = max(0., 1.-iteration/settings.active_until)
    reliability = preference["confidence"]*trust*consistency
    shift = np.clip(settings.lambda_max*anneal*reliability*np.maximum(corr, 0.), 0., settings.max_shift_std)
    shifted_ei = scalar_log_ei(mean-shift, std, transform, best)
    shifted_scores, _, _ = decision_scores(shifted_ei, probabilities, enabled=feasibility_weighting)
    lifted = select_candidate(shifted_scores, eligible, seed=seed, candidate_id=candidate_id)
    gap = float(np.log(max(plain_ei[plain],1e-12))-np.log(max(plain_ei[lifted],1e-12)))
    sigma_ratio = float(std[lifted]/max(std[plain],1e-12))
    result.update(anchors=anchors.tolist(), anchor_weights=weights.tolist(), anchor_consistency=consistency,
        anneal=anneal, correlation=corr.tolist(), kernel_norm_sq=norm_sq, reliability=reliability,
        shift_z=shift.tolist(), lifted_mean_z=(mean-shift).tolist(), lifted_ei_v=shifted_ei.tolist(),
        lifted_index=lifted, plain_log_ei_gap=gap, sigma_ratio=sigma_ratio)
    if not np.any(shift > 1e-12):
        return fallback("zero_shift")
    if lifted == plain:
        return fallback("same_as_plain")
    if gap > settings.max_plain_log_ei_gap:
        return fallback("plain_ei_gap")
    if np.any(x[lifted] < lb) or np.any(x[lifted] > ub):
        return fallback("outside_region")
    if sigma_ratio < settings.min_sigma_ratio:
        return fallback("low_sigma_ratio")
    result.update(accepted=True, selected_index=lifted, effective_ei_v=shifted_ei.tolist(), effective_scores=shifted_scores.tolist())
    return result


def trust_feedback(trust, accepted, valid, objective, previous_best, settings):
    improved = bool(valid and objective is not None and previous_best is not None and objective < previous_best)
    updated = (1-settings.trust_beta)*trust + settings.trust_beta*float(improved) if accepted else trust
    return {"trust_before": float(trust), "trust_after": float(updated), "accepted": bool(accepted),
        "improved": improved, "rule": "ema_of_joint_objective_improvement_when_adopted"}
