"""Independent chronological replay of saved predictive-prior decisions."""
from __future__ import annotations

import json
import math
from pathlib import Path

from .gp_prior_guard import GuardSettings, PredictivePriorGuard
from .metrics import RATE_ORDER, LogRMSETransform
from .surrogate import Matern52GP


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _same(a, b):
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    if type(a) is bool or type(b) is bool:
        return type(a) is type(b) and a == b
    if isinstance(a, (float, int)) and isinstance(b, (float, int)):
        return math.isfinite(a) and math.isfinite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-12)
    return a == b


def audit_prior_guard(path, options, attempts, initial_count):
    path = Path(path)
    issues = []
    guard = PredictivePriorGuard(GuardSettings.parse(options.get("gp_prior_guard")), initial_count=initial_count)
    expected_ids = {f"candidate-{i:06d}.json" for i in range(initial_count, len(attempts))}
    for kind in ("predictions", "scores"):
        if {p.name for p in (path/"gp-prior"/kind).glob("*.json")} != expected_ids:
            issues.append(f"prior {kind} ledger is incomplete")
    shadow_counts = {r: 0 for r in RATE_ORDER}
    previous_training = {}
    for count in range(initial_count, len(attempts) + 1):
        state = _read(path/"models"/f"after-{count:06d}.json")
        prior = state["prior_guard"]
        expected_prior = guard.state_dict()
        if not _same({k: prior[k] for k in expected_prior}, expected_prior):
            issues.append(f"prior after-{count}: score ledger uses incorrect or future labels")
        pairs = {}
        for rate, model in state["models"].items():
            group = model["group"]
            expected_decision = guard.decision(rate, has_group=bool(group))
            if not _same(prior["decisions"][rate], expected_decision):
                issues.append(f"prior after-{count}/{rate}: selected branch is not supported by past scores")
            if not group:
                if rate in state.get("shadow_models", {}):
                    issues.append(f"prior after-{count}/{rate}: empty group unexpectedly has shadow models")
                continue
            saved = state["shadow_models"][rate]
            if set(saved) != {"ordinary", "mixed"}:
                issues.append(f"prior after-{count}/{rate}: missing comparison model")
                continue
            if saved["ordinary"]["group"] or saved["ordinary"]["lambda"] != 0 or saved["mixed"]["group"] != group:
                issues.append(f"prior after-{count}/{rate}: model roles or fixed parameter group changed")
            for branch in ("ordinary", "mixed"):
                if not _same(saved[branch]["x"], model["x"]) or not _same(saved[branch]["y"], model["y"]):
                    issues.append(f"prior after-{count}/{rate}: shadow model trained on different or future labels")
                if saved[branch]["max_sweeps"] != options["gp_sweeps"]:
                    issues.append(f"prior after-{count}/{rate}: unequal fitting budgets")
            training = [model["x"], model["y"], group]
            if not _same(previous_training.get(rate), training):
                shadow_counts[rate] += 2
                previous_training[rate] = training
            pairs[rate] = {name: Matern52GP.from_state(value) for name, value in saved.items()}
            active = expected_decision["active"]
            expected_model = dict(saved[active])
            if active == "ordinary":
                expected_model["group"] = list(group)
                expected_model["hyperparameters"] = list(expected_model["hyperparameters"])
                expected_model["hyperparameters"][8] = 0.0
                expected_model["lambda"] = 0.0
            if not _same(model, expected_model):
                issues.append(f"prior after-{count}/{rate}: active GP differs from selected fitted kernel")
        if prior["shadow_fit_counts"] != shadow_counts:
            issues.append(f"prior after-{count}: shadow fitting count differs")
        if count == len(attempts):
            break
        prediction = _read(path/"gp-prior/predictions"/f"candidate-{count:06d}.json")
        acquisition = _read(path/"acquisition"/f"candidate-{count:06d}.json")
        x = acquisition["normalized_pool"][acquisition["selected_index"]]
        transforms = {r: LogRMSETransform(**v) for r, v in state["transforms"].items()}
        reconstructed = guard.predict_before(count, x, pairs, transforms)
        if not _same(prediction, reconstructed):
            issues.append(f"prior candidate-{count}: pre-evaluation prediction does not reproduce")
        updates = guard.observe(reconstructed, attempts[count])
        if not _same(updates, _read(path/"gp-prior/scores"/f"candidate-{count:06d}.json")):
            issues.append(f"prior candidate-{count}: actual-label NLPD update does not reproduce")
    return issues
