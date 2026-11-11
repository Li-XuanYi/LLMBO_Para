"""Single-worker initialization, four GPs and Composite EI with audited failures."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Mapping

import numpy as np

from .acquisition import composite_ei, scalar_log_ei
from .evaluation import DischargeSeries, EvaluationResult, FourRateEvaluator
from .llm import LLMClient
from .metrics import RATE_ORDER, LogRMSETransform
from .parameters import ParameterSpace
from .progress import summarize_progress
from .runstore import RunStore, digest_value
from .sobol import Sobol6
from .surrogate import Matern52GP
from .bo_repair import RepairSettings, CompletionModel, LocalNeighborhood, decision_scores, select_candidate
from .informed import InformedSettings, region_decision, trust_feedback


class Optimizer:
    def __init__(
        self,
        space: ParameterSpace,
        evaluator: FourRateEvaluator,
        series_by_rate: Mapping[str, DischargeSeries],
        *,
        llm: LLMClient | None = None,
        run_store: RunStore | None = None,
        seed: int = 0,
        initial_llm_count: int = 10,
        initial_sobol_count: int = 10,
        candidate_pool_size: int = 1024,
        mc_draws: int = 512,
        gp_sweeps: int = 4,
        llm_warm_start_enabled: bool = True,
        llm_gp_groups_enabled: bool = True,
        initial_candidates=None,
        initial_candidates_source: str | None = None,
        strict_llm_tasks: bool = False,
        initial_evaluations=None,
        candidate_filter=None,
        bo_repair=None,
        surrogate_mode: str = "per_rate",
        llm_informed_enabled: bool = False,
        llm_informed=None,
        screening_history=None,
    ):
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (initial_llm_count, initial_sobol_count, candidate_pool_size, mc_draws, gp_sweeps, seed)):
            raise ValueError("optimizer sizes and seed must be integers")
        if initial_llm_count < 0 or initial_sobol_count < 0 or (initial_candidates is None and initial_sobol_count < 2) or candidate_pool_size < 1 or mc_draws < 1 or gp_sweeps < 0:
            raise ValueError("invalid initial-set or candidate-pool size")
        if any(not isinstance(flag, bool) for flag in (llm_warm_start_enabled, llm_gp_groups_enabled, strict_llm_tasks)):
            raise ValueError("LLM component switches and strict task policy must be booleans")
        self.space, self.evaluator, self.series_by_rate = space, evaluator, dict(series_by_rate)
        if not isinstance(surrogate_mode, str) or surrogate_mode not in {"per_rate", "single_objective"}:
            raise ValueError("surrogate_mode must be per_rate or single_objective")
        if surrogate_mode == "single_objective" and llm_gp_groups_enabled:
            raise ValueError("single_objective uses one full Matérn kernel; disable parameter-group mixtures")
        self.surrogate_mode = surrogate_mode
        if type(llm_informed_enabled) is not bool:
            raise ValueError("llm_informed_enabled must be boolean")
        if llm_informed_enabled and (surrogate_mode != "single_objective" or llm is None):
            raise ValueError("LLM-Informed needs a single objective GP and an explicit LLM client")
        self.informed_enabled = llm_informed_enabled
        self.informed_settings = InformedSettings.parse(llm_informed)
        self.informed_trust = self.informed_settings.trust_init
        self.informed_stats = dict(enabled=llm_informed_enabled, requested_iterations=0, request_attempts=0,
            valid_responses=0, adopted=0, error_iterations=0, fallback_counts={})
        if set(self.series_by_rate) != set(RATE_ORDER):
            raise ValueError(f"optimizer needs all rates: {RATE_ORDER}")
        self.llm, self.store, self.seed = llm, run_store, seed
        self.initial_llm_count, self.initial_sobol_count = initial_llm_count, initial_sobol_count
        self.pool_size, self.mc_draws, self.gp_sweeps = candidate_pool_size, mc_draws, gp_sweeps
        self.records: list[EvaluationResult] = []
        self.screening_history = screening_history
        self.historical_records = list(screening_history.results) if screening_history is not None else []
        if self.historical_records and (surrogate_mode != "per_rate" or initial_evaluations is None):
            raise ValueError("supplementary screening requires verified initial cache and per-rate models")
        historical_valid = [r for r in self.historical_records if r.valid]
        if historical_valid and (screening_history.catalog.get('schema_version') != 2
            or screening_history.catalog.get('reused_valid_candidates') != len(historical_valid)
            or min(r.objective_v for r in initial_evaluations) > min(r.objective_v for r in historical_valid) + 1e-12):
            raise ValueError('quality screening must preserve its best complete point in the verified initial set')
        self.frozen_transforms = None
        self.repair_enabled = bo_repair is not None or surrogate_mode == "single_objective"
        self.repair = RepairSettings.parse(bo_repair)
        if screening_history is not None and (surrogate_mode != "per_rate" or self.repair.training_data != "per_rate" or bo_repair is None):
            raise ValueError("screening history requires explicit per-rate repaired training")
        if surrogate_mode == "single_objective" and self.repair.training_data != "complete":
            raise ValueError("single_objective requires complete four-rate objective labels")
        self.neighborhood = LocalNeighborhood(self.repair, seed)
        self.completion = CompletionModel(self.repair.completion_model)
        self._model_cache, self._training_keys = {}, {}
        self.model_training_counts = {}
        self.model_keys = ("objective",) if surrogate_mode == "single_objective" else RATE_ORDER
        self.model_fit_counts = {rate: 0 for rate in self.model_keys}
        self.sobol = Sobol6()
        self.seen: set[tuple[float, ...]] = set()
        self.seen.update(tuple(round(v, 12) for v in self.space.normalize(r.parameters)) for r in self.historical_records)
        if len(self.seen) != len(self.historical_records) or any(
                self.space.validate(p) == r.parameters for p in (initial_candidates or []) for r in self.historical_records):
            raise ValueError("supplementary screening history contains duplicate initial/evaluated points")
        self.used = False
        self.llm_warm_start_enabled, self.llm_gp_groups_enabled = llm_warm_start_enabled, llm_gp_groups_enabled
        self.strict_llm_tasks = strict_llm_tasks
        self.initial_candidates = None if initial_candidates is None else [self.space.validate(point) for point in initial_candidates]
        self.initial_candidates_source = initial_candidates_source
        self.initial_evaluations = initial_evaluations
        self.candidate_filter = candidate_filter
        self.analytical_rejections = 0
        self.gp_fit_s = self.acquisition_s = 0.
        if initial_evaluations is not None:
            if self.initial_candidates is None or len(initial_evaluations) != len(self.initial_candidates):
                raise ValueError("cached evaluations must match the complete initial set")
            for point, result in zip(self.initial_candidates, initial_evaluations):
                if not result.valid or result.parameters != point or not result.cache_provenance:
                    raise ValueError("initial cache lacks valid matching results and verified provenance")
        if self.initial_candidates is not None:
            if len(self.initial_candidates) != initial_llm_count + initial_sobol_count or len(self.initial_candidates) < 2:
                raise ValueError("shared initial set size must match the complete initial allocation")
            if initial_candidates_source not in {"random", "llm", "history"}:
                raise ValueError("shared initial set requires explicit random, llm or history provenance")
            if initial_candidates_source == "history" and initial_evaluations is None:
                raise ValueError("historical continuation requires verified cached evaluations")
            if (initial_candidates_source == "llm") != llm_warm_start_enabled:
                raise ValueError("shared initial source must match the WarmStart ablation switch")

    def _record(self, index: int, result: EvaluationResult) -> None:
        self.records.append(result)
        if self.store is not None:
            self.store.save_attempt(index, 1, result.to_dict())
            progress = summarize_progress(
                self.total_candidate_budget, [row.to_dict() for row in self.records],
                time.perf_counter() - self.start_time,
            )
            self.store.append_event({
                "type": "progress",
                "total_candidates": progress.total_candidates,
                "completed_candidates": progress.completed_candidates,
                "failed_candidates": progress.failed_candidates,
                "pending_candidates": progress.pending_candidates,
                "running_candidates": progress.running_candidates,
                "candidate_rate_per_min": progress.candidate_rate_per_min,
                "eta_minutes": progress.eta_minutes,
                "completed_by_rate": progress.completed_by_rate,
                "failed_by_rate": progress.failed_by_rate,
            })

    def _legal_sobol(self, count: int) -> list[tuple[float, ...]]:
        points, examined = [], 0
        while len(points) < count and examined < max(10000, count * 1000):
            batch = self.sobol.draw(1)
            examined += len(batch)
            for normalized in batch:
                try:
                    physical = self.space.denormalize(normalized)
                except ValueError:
                    continue
                key = tuple(round(v, 12) for v in normalized)
                if key in self.seen:
                    continue
                self.seen.add(key)
                points.append(physical)
                if len(points) == count:
                    break
        if len(points) != count:
            raise RuntimeError(f"found only {len(points)} legal unique Sobol points; requested {count}")
        return points

    def _initial_candidates(self) -> list[tuple[float, ...]]:
        if self.initial_candidates is not None:
            points = list(self.initial_candidates)
            keys = [tuple(round(value, 12) for value in self.space.normalize(point)) for point in points]
            if len(set(keys)) != len(points):
                raise ValueError("shared initial set contains duplicate candidates")
            self.seen.update(keys)
            if self.store:
                self.store.write_json("initial-set.json", {"parameters": points,
                    "sources": [self.initial_candidates_source] * len(points), "shared_initial_set": True,
                    "llm_warm_start_enabled": self.llm_warm_start_enabled,
                    "llm_gp_groups_enabled": self.llm_gp_groups_enabled, "sobol_next_index": self.sobol.index})
            return points
        suggested = ()
        if self.llm is not None and self.llm_warm_start_enabled and self.initial_llm_count:
            try:
                suggested = self.llm.warm_start(self.space, self.initial_llm_count)
            except Exception as exc:
                if self.store is not None:
                    self.store.append_event({"type": "llm_warm_start_error", "error": f"{type(exc).__name__}: {exc}"})
                if self.strict_llm_tasks:
                    raise
        llm_points = []
        for point in suggested:
            try:
                physical = self.space.validate(point)
                key = tuple(round(v, 12) for v in self.space.normalize(physical))
            except (TypeError, ValueError):
                continue
            if key not in self.seen:
                self.seen.add(key)
                llm_points.append(physical)
            if len(llm_points) == self.initial_llm_count:
                break
        # Sobol replaces invalid, repeated or missing LLM suggestions to keep the
        # planned warm-start allocation fixed, then supplies its own space-filling set.
        replacement = self._legal_sobol(self.initial_llm_count - len(llm_points))
        space_filling = self._legal_sobol(self.initial_sobol_count)
        if self.store:
            self.store.write_json("initial-set.json", {
                "parameters": llm_points + replacement + space_filling,
                "sources": ["llm"] * len(llm_points) + ["sobol_llm_replacement"] * len(replacement) + ["sobol"] * len(space_filling),
                "sobol_next_index": self.sobol.index,
            })
        return llm_points + replacement + space_filling

    def _fit_models(self):
        fit_started = time.perf_counter()
        # Negative IDs refer to the separate immutable screening ledger. Normal
        # candidate IDs and the BO evaluation budget retain their old meaning.
        training_records = list(zip(range(-len(self.historical_records), 0), self.historical_records)) + list(enumerate(self.records))
        good = [r for r in self.records if r.valid]
        if len(good) < 2 and not self.repair_enabled:
            raise RuntimeError("at least two complete valid four-rate evaluations are required to fit GPs")
        if self.frozen_transforms is None:
            self.frozen_transforms = {}
        transforms = self.frozen_transforms
        groups = getattr(self, "groups", {})
        models, training_metadata = {}, {}
        for rate in self.model_keys:
            if rate == "objective":
                training = [(i, record, record.objective_v) for i, record in enumerate(self.records) if record.valid]
            else:
                training = [(i, record, q.rmse_v) for i, record in training_records
                    for q in record.rates if q.rate == rate and q.valid
                    and (self.repair.training_data == "per_rate" or record.valid)]
            ids = [i for i, _, _ in training]
            self.model_training_counts[rate] = len(training)
            training_metadata[rate] = {"record_ids": ids, "count": len(ids), "fit_reused": False}
            if len(training) < 2:
                training_metadata[rate]["fallback"] = "fewer_than_two_valid_rate_labels"
                continue
            x = np.asarray([self.space.normalize(record.parameters) for _, record, _ in training])
            values = [value for _, _, value in training]
            if rate not in transforms:
                transforms[rate] = LogRMSETransform.fit(values)
                training_metadata[rate]["transform_frozen_at_record_count"] = len(self.records)
            transform = transforms[rate]
            y = np.asarray([transform.transform(v) for v in values])
            names = groups.get(rate, ())
            indexes = [self.space.specs.index(s) for s in self.space.specs if s.name in names]
            key = digest_value({"x": x.tolist(), "y": y.tolist(), "group": indexes})
            if self._training_keys.get(rate) == key:
                models[rate] = self._model_cache[rate]
                training_metadata[rate]["fit_reused"] = True
            else:
                models[rate] = Matern52GP(max_sweeps=self.gp_sweeps).fit(x, y, indexes)
                self._model_cache[rate], self._training_keys[rate] = models[rate], key
                self.model_fit_counts[rate] += 1
            training_metadata[rate]["cumulative_fits"] = self.model_fit_counts[rate]
        best = float(min(r.objective_v for r in good)) if good else None
        if self.repair.feasibility_weighting:
            self.completion.fit([self.space.normalize(r.parameters) for _, r in training_records], [r.valid for _, r in training_records])
        if self.store:
            snapshot = {
                "transforms": {rate: asdict(transform) for rate, transform in transforms.items()},
                "models": {rate: model.state_dict() for rate, model in models.items()},
                "sobol_next_index": self.sobol.index,
                "evaluated_normalized": sorted(self.seen),
            }
            if self.repair_enabled:
                snapshot.update(schema_version=2, training_data=self.repair.training_data,
                    training=training_metadata, completion_model=self.completion.state,
                    neighborhood=self.neighborhood.state_dict())
            if self.surrogate_mode == "single_objective":
                snapshot.update(surrogate_mode=self.surrogate_mode, target="log_of_mean_four_rate_rmse",
                    kernel="full_6d_ard_matern52")
            self.store.write_json(f"models/after-{len(self.records):06d}.json", snapshot)
        self.gp_fit_s += time.perf_counter() - fit_started
        return models, transforms, best

    def _candidate_pool(self, next_index):
        candidates, pool_seen, origins, centers = [], set(), [], []
        valid = sorted([i for i, r in enumerate(self.records) if r.valid], key=lambda i: self.records[i].objective_v)
        local_target = int(self.pool_size*self.repair.local_fraction) if self.repair.candidate_policy == "local" and valid else 0

        def add(normalized, origin, center_id=None):
            key = tuple(round(float(v), 12) for v in normalized)
            if key in self.seen or key in pool_seen:
                return False
            try:
                physical = self.space.denormalize(normalized)
            except ValueError:
                return False
            if self.candidate_filter is not None:
                check = self.candidate_filter(physical)
                if not check["feasible"]:
                    self.analytical_rejections += 1
                    if self.store:
                        self.store.append_event({"type": "bo_analytical_rejection", "candidate_id": next_index,
                            "normalized": normalized.tolist(), "parameters": physical, **check})
                    return False
            pool_seen.add(key); candidates.append((normalized, physical)); origins.append(origin); centers.append(center_id)
            return True

        # Rejection rather than clipping avoids introducing atoms on the bounds.
        for _ in range(max(0, local_target*100)):
            if len(candidates) >= local_target:
                break
            center_id = valid[int(self.neighborhood.rng.integers(min(4, len(valid))))]
            center = np.asarray(self.space.normalize(self.records[center_id].parameters))
            point = center + self.neighborhood.rng.uniform(-self.neighborhood.radius, self.neighborhood.radius, 6)
            if np.all((point >= 0) & (point <= 1)):
                add(point, "local", center_id)
        local_actual = len(candidates)
        for _ in range(self.pool_size*100):
            if len(candidates) >= self.pool_size:
                break
            add(self.sobol.draw(1)[0], "global")
        if not candidates:
            raise RuntimeError("candidate pool contained no legal unique points")
        # Every kth *evaluation* is global; a global pool fraction alone is insufficient.
        ordinal = next_index - self.initial_llm_count - self.initial_sobol_count + 1
        quota = self.repair.candidate_policy == "local" and ordinal % self.repair.global_every == 0
        eligible = np.asarray([origin == "global" or not quota for origin in origins])
        if not np.any(eligible):
            raise RuntimeError("global exploration quota has no legal candidate; no silent local replacement")
        return candidates, dict(origins=origins, center_record_ids=centers, eligible=eligible.tolist(),
            global_quota=quota, radius=self.neighborhood.radius, local_target=local_target,
            local_actual=local_actual, local_fallback="local_pool_underfilled" if local_actual < local_target else None)

    def _apply_informed(self, model, transform, best, norm, eligible, probabilities, ready, next_index):
        ordinal = next_index-self.initial_llm_count-self.initial_sobol_count
        envelope = dict(iteration=ordinal, candidate_id=next_index, settings=asdict(self.informed_settings),
            trust_before=self.informed_trust, request=None, preference=None, decision=None, status=None)
        if not ready:
            envelope["status"] = "gp_unavailable"
        elif ordinal >= self.informed_settings.active_until:
            envelope["status"] = "inactive"
        else:
            self.informed_stats["requested_iterations"] += 1
            try:
                preference = self.llm.region_preference(self.space, self.records,
                    iteration=ordinal, settings=self.informed_settings)
                envelope["preference"] = preference
                self.informed_stats["valid_responses"] += 1
                envelope["status"] = "evaluated"
            except (RuntimeError, ValueError) as exc:
                envelope.update(status="llm_error", error_type=type(exc).__name__)
                self.informed_stats["error_iterations"] += 1
            envelope["request"] = dict(self.llm.last_region_request)
            self.informed_stats["request_attempts"] += envelope["request"]["attempts"]
            if envelope["status"] == "evaluated":
                try:
                    envelope["decision"] = region_decision(model, transform, best, norm, eligible, preference,
                        space=self.space, settings=self.informed_settings, trust=self.informed_trust,
                        iteration=ordinal, seed=self.seed, candidate_id=next_index, probabilities=probabilities,
                        feasibility_weighting=self.repair.feasibility_weighting, candidate_filter=self.candidate_filter)
                except (ValueError, np.linalg.LinAlgError, FloatingPointError) as exc:
                    envelope.update(status="lift_error", error_type=type(exc).__name__)
                    self.informed_stats["error_iterations"] += 1
        decision = envelope["decision"]
        if decision and decision["accepted"]:
            self.informed_stats["adopted"] += 1
        else:
            reason = decision["fallback_reason"] if decision else envelope["status"]
            counts = self.informed_stats["fallback_counts"]
            counts[reason] = counts.get(reason, 0)+1
        if self.store:
            self.store.write_json(f"informed/candidate-{next_index:06d}.json", envelope)
        return envelope

    def optimize(self, total_candidate_budget: int) -> dict:
        if self.used:
            raise ValueError("an Optimizer instance is single-use; create a new run for another configuration")
        if not isinstance(total_candidate_budget, int) or isinstance(total_candidate_budget, bool):
            raise ValueError("candidate budget must be an integer")
        initial_count = self.initial_llm_count + self.initial_sobol_count
        if total_candidate_budget < initial_count:
            raise ValueError(f"budget {total_candidate_budget} is below the {initial_count} initial evaluations")
        start = time.perf_counter()
        self.start_time = start
        self.total_candidate_budget = total_candidate_budget
        self.used = True
        if self.store is not None:
            self.store.append_event({"type": "optimization_started", "budget": total_candidate_budget, "seed": self.seed})
            self.store.write_json("input-series.json", {rate: asdict(series) for rate, series in self.series_by_rate.items()})
            self.store.write_json("input-series-sha256.json", {"sha256": digest_value({rate: asdict(series) for rate, series in self.series_by_rate.items()})})
        for index, point in enumerate(self._initial_candidates()):
            if self.store:
                self.store.write_json(f"plans/candidate-{index:06d}.json", {"candidate_id": index, "parameters": point})
                self.store.append_event({"type": "candidate_started", "candidate_id": index})
            self._record(index, self.initial_evaluations[index] if self.initial_evaluations is not None
                         else self.evaluator.evaluate(point, self.series_by_rate))
        valid = [r for r in self.records if r.valid]
        self.groups = {rate: () for rate in RATE_ORDER}
        if self.llm is not None and self.llm_gp_groups_enabled and valid:
            observations = [
                {"parameters": list(r.parameters), "rmse_v": {q.rate: q.rmse_v for q in r.rates},
                 "residual_summary": {q.rate: q.residual_summary for q in r.rates}}
                for r in valid
            ]
            try:
                self.groups = self.llm.parameter_groups(self.space, observations)
                if self.strict_llm_tasks and not getattr(self.llm, "last_group_validation", {}).get("valid_response", True):
                    raise ValueError("invalid LLM parameter groups cannot count as an enabled ablation component")
            except Exception as exc:
                if self.store is not None:
                    self.store.append_event({"type": "llm_parameter_groups_error", "error": f"{type(exc).__name__}: {exc}"})
                if self.strict_llm_tasks:
                    raise
        next_index = initial_count
        models, transforms, best = self._fit_models()
        while next_index < total_candidate_budget:
            candidates, proposal = self._candidate_pool(next_index)
            norm = np.asarray([row[0] for row in candidates])
            acquisition_started = time.perf_counter()
            ready = set(models) == set(self.model_keys) and best is not None
            if ready and self.surrogate_mode == "single_objective":
                mean, std = models["objective"].predict(norm)
                raw_ei = scalar_log_ei(mean, std, transforms["objective"], best)
            else:
                raw_ei = composite_ei(norm, models, transforms, best, draws=self.mc_draws, seed=self.seed + next_index) if ready else np.zeros(len(norm))
            probabilities = self.completion.predict(norm) if self.repair.feasibility_weighting else None
            scores, policy, fallback = decision_scores(raw_ei, probabilities, enabled=self.repair.feasibility_weighting)
            if not ready:
                scores = np.zeros(len(norm))
                policy, fallback = "seeded_eligible_space_filling", "gp_or_complete_objective_unavailable"
            self.acquisition_s += time.perf_counter() - acquisition_started
            eligible = np.asarray(proposal["eligible"])
            selected_index = select_candidate(scores, eligible, seed=self.seed, candidate_id=next_index, cold_start=not ready)
            informed = None
            if self.informed_enabled:
                informed = self._apply_informed(models.get("objective"), transforms.get("objective"), best,
                    norm, eligible, probabilities, ready, next_index)
                if informed["decision"] is not None:
                    selected_index = informed["decision"]["selected_index"]
                    scores = np.asarray(informed["decision"]["effective_scores"])
            selected = candidates[selected_index][1]
            self.seen.add(tuple(round(float(v), 12) for v in candidates[selected_index][0]))
            if self.store:
                acquisition = {
                    "normalized_pool": norm.tolist(), "composite_ei": raw_ei.tolist(),
                    "mc_seed": self.seed + next_index, "mc_draws": self.mc_draws,
                    "best_observed_objective_v": best, "selected_index": selected_index,
                    "sobol_next_index": self.sobol.index,
                }
                if self.repair_enabled:
                    acquisition.update(schema_version=2, proposal=proposal, decision_scores=scores.tolist(),
                        p_complete=probabilities.tolist() if probabilities is not None else None,
                        policy=policy, fallback=fallback, gp_ready=ready)
                if self.surrogate_mode == "single_objective":
                    acquisition.update(surrogate_mode=self.surrogate_mode, acquisition_kind="analytic_lognormal_ei_v",
                        mc_seed=None, mc_draws=0)
                if self.informed_enabled:
                    acquisition.update(informed_artifact=f"informed/candidate-{next_index:06d}.json",
                        informed_applied=bool(informed["decision"] and informed["decision"]["accepted"]))
                self.store.write_json(f"acquisition/candidate-{next_index:06d}.json", acquisition)
                self.store.write_json(f"plans/candidate-{next_index:06d}.json", {"candidate_id": next_index, "parameters": selected})
                self.store.append_event({"type": "candidate_started", "candidate_id": next_index})
            result = self.evaluator.evaluate(selected, self.series_by_rate)
            self._record(next_index, result)
            if self.informed_enabled:
                accepted = bool(informed["decision"] and informed["decision"]["accepted"])
                feedback = trust_feedback(self.informed_trust, accepted, result.valid, result.objective_v,
                    best, self.informed_settings)
                self.informed_trust = feedback["trust_after"]
                if self.store:
                    self.store.write_json(f"informed-feedback/candidate-{next_index:06d}.json", feedback)
            update = self.neighborhood.update(result, proposal["origins"][selected_index])
            if self.store and self.repair_enabled:
                self.store.write_json(f"feedback/candidate-{next_index:06d}.json", update)
            next_index += 1
            models, transforms, best = self._fit_models()
        elapsed = time.perf_counter() - start
        complete = [r for r in self.records if r.valid]
        if not complete:
            raise RuntimeError("no candidate completed all four rate evaluations")
        best_result = min(complete, key=lambda r: r.objective_v)
        summary = {
            "candidate_budget": total_candidate_budget,
            "candidate_completed": len(self.records),
            "candidate_valid": len(complete),
            "candidate_failed": len(self.records) - len(complete),
            "candidate_pending": 0,
            "rate_solve_attempts": sum(len(q.attempts) for r in self.records if not r.cache_provenance for q in r.rates),
            "rate_failed_attempts": sum(not a["valid"] for r in self.records if not r.cache_provenance for q in r.rates for a in q.attempts),
            "cache_hits": sum(bool(r.cache_provenance) for r in self.records),
            "bo_analytical_rejections": self.analytical_rejections,
            "new_candidate_evaluations": sum(not r.cache_provenance for r in self.records),
            "best_parameters": list(best_result.parameters),
            "best_rmse_v": {r.rate: r.rmse_v for r in best_result.rates},
            "best_objective_v": best_result.objective_v,
            "elapsed_s": elapsed,
            "timing_s": {"gp_fit": self.gp_fit_s, "acquisition": self.acquisition_s,
                "new_simulations": sum(q.elapsed_s for r in self.records if not r.cache_provenance for q in r.rates)},
            "candidate_evaluations_per_min": sum(not r.cache_provenance for r in self.records) * 60.0 / elapsed if elapsed else None,
            "groups": self.groups,
            "groups_learned_lambda": {
                rate: (models[rate].lambda_ if rate in models else None)
                for rate in self.model_keys
            },
            "surrogate_mode": self.surrogate_mode,
            "llm_informed": {**self.informed_stats, "final_trust": self.informed_trust},
            "gp_training_counts": self.model_training_counts,
            "gp_fit_counts": self.model_fit_counts,
            "initial_best_objective_v": min((r.objective_v for r in self.records[:initial_count] if r.valid), default=None),
            "bo_candidate_valid": sum(r.valid for r in self.records[initial_count:]),
            "rate_valid_counts": {rate: sum(q.valid for r in self.records for q in r.rates if q.rate == rate) for rate in RATE_ORDER},
        }
        if self.screening_history is not None:
            cost = self.screening_history.catalog["attributed_screening_cost"]
            summary["screening_history"] = {
                "reused_failed_candidates": sum(not r.valid for r in self.historical_records),
                "partial_rate_labels": self.screening_history.catalog["partial_rate_labels"],
                "attributed_screening_cost": cost,
                "attributed_total_candidate_evaluations": cost["candidate_evaluations"] + summary["new_candidate_evaluations"],
                "attributed_total_rate_solves": cost["rate_solve_attempts"] + summary["rate_solve_attempts"],
            }
            if self.screening_history.catalog.get('schema_version') == 2:
                summary['screening_history'].update(reused_valid_candidates=sum(r.valid for r in self.historical_records),
                    reused_candidates=len(self.historical_records))
        if self.store is not None:
            self.store.write_json("summary.json", summary)
            self.store.append_event({"type": "optimization_completed", "summary": summary})
        return summary
