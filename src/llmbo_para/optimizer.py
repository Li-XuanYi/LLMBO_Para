"""Single-worker initialization, four GPs and Composite EI with audited failures."""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Mapping

import numpy as np

from .acquisition import composite_ei
from .evaluation import DischargeSeries, EvaluationResult, FourRateEvaluator
from .llm import LLMClient
from .metrics import RATE_ORDER, LogRMSETransform
from .parameters import ParameterSpace
from .progress import summarize_progress
from .runstore import RunStore, digest_value
from .sobol import Sobol6
from .surrogate import Matern52GP


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
    ):
        if any(not isinstance(v, int) or isinstance(v, bool) for v in (initial_llm_count, initial_sobol_count, candidate_pool_size, mc_draws, gp_sweeps, seed)):
            raise ValueError("optimizer sizes and seed must be integers")
        if initial_llm_count < 0 or initial_sobol_count < 0 or (initial_candidates is None and initial_sobol_count < 2) or candidate_pool_size < 1 or mc_draws < 1 or gp_sweeps < 0:
            raise ValueError("invalid initial-set or candidate-pool size")
        if any(not isinstance(flag, bool) for flag in (llm_warm_start_enabled, llm_gp_groups_enabled, strict_llm_tasks)):
            raise ValueError("LLM component switches and strict task policy must be booleans")
        self.space, self.evaluator, self.series_by_rate = space, evaluator, dict(series_by_rate)
        if set(self.series_by_rate) != set(RATE_ORDER):
            raise ValueError(f"optimizer needs all rates: {RATE_ORDER}")
        self.llm, self.store, self.seed = llm, run_store, seed
        self.initial_llm_count, self.initial_sobol_count = initial_llm_count, initial_sobol_count
        self.pool_size, self.mc_draws, self.gp_sweeps = candidate_pool_size, mc_draws, gp_sweeps
        self.records: list[EvaluationResult] = []
        self.frozen_transforms = None
        self.sobol = Sobol6()
        self.seen: set[tuple[float, ...]] = set()
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
            if initial_candidates_source not in {"random", "llm"}:
                raise ValueError("shared initial set requires explicit random or llm provenance")
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
        good = [r for r in self.records if r.valid]
        if len(good) < 2:
            raise RuntimeError("at least two complete valid four-rate evaluations are required to fit GPs")
        x = np.asarray([self.space.normalize(r.parameters) for r in good], dtype=float)
        models = {}
        by_rate = {rate: np.asarray([next(q.rmse_v for q in record.rates if q.rate == rate) for record in good]) for rate in RATE_ORDER}
        if self.frozen_transforms is None:
            self.frozen_transforms = {
                rate: LogRMSETransform.fit(by_rate[rate])
                for rate in RATE_ORDER
            }
        transforms = self.frozen_transforms
        groups = getattr(self, "groups", {})
        for rate in RATE_ORDER:
            transform = transforms[rate]
            y = np.asarray([transform.transform(v) for v in by_rate[rate]])
            names = groups.get(rate, ())
            indexes = [self.space.specs.index(s) for s in self.space.specs if s.name in names]
            models[rate] = Matern52GP(max_sweeps=self.gp_sweeps).fit(x, y, indexes)
        best = min(r.objective_v for r in good)
        if self.store:
            self.store.write_json(f"models/after-{len(self.records):06d}.json", {
                "transforms": {rate: asdict(transform) for rate, transform in transforms.items()},
                "models": {rate: model.state_dict() for rate, model in models.items()},
                "sobol_next_index": self.sobol.index,
                "evaluated_normalized": sorted(self.seen),
            })
        self.gp_fit_s += time.perf_counter() - fit_started
        return models, transforms, float(best)

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
            candidates = []
            pool_seen = set()
            attempts = 0
            while len(candidates) < self.pool_size and attempts < self.pool_size * 100:
                batch = self.sobol.draw(1)
                attempts += len(batch)
                for normalized in batch:
                    key = tuple(round(float(v), 12) for v in normalized)
                    if key in self.seen or key in pool_seen:
                        continue
                    try:
                        physical = self.space.denormalize(normalized)
                    except ValueError:
                        continue
                    if self.candidate_filter is not None:
                        check = self.candidate_filter(physical)
                        if not check["feasible"]:
                            self.analytical_rejections += 1
                            if self.store:
                                self.store.append_event({"type": "bo_analytical_rejection", "candidate_id": next_index,
                                    "normalized": normalized.tolist(), "parameters": physical, **check})
                            continue
                    pool_seen.add(key)
                    candidates.append((normalized, physical))
                    if len(candidates) == self.pool_size:
                        break
            if not candidates:
                raise RuntimeError("candidate pool contained no legal unique points")
            norm = np.asarray([row[0] for row in candidates])
            acquisition_started = time.perf_counter()
            scores = composite_ei(norm, models, transforms, best, draws=self.mc_draws, seed=self.seed + next_index)
            self.acquisition_s += time.perf_counter() - acquisition_started
            selected_index = int(np.argmax(scores))
            selected = candidates[selected_index][1]
            self.seen.add(tuple(round(float(v), 12) for v in candidates[selected_index][0]))
            if self.store:
                self.store.write_json(f"acquisition/candidate-{next_index:06d}.json", {
                    "normalized_pool": norm.tolist(), "composite_ei": scores.tolist(),
                    "mc_seed": self.seed + next_index, "mc_draws": self.mc_draws,
                    "best_observed_objective_v": best, "selected_index": selected_index,
                    "sobol_next_index": self.sobol.index,
                })
                self.store.write_json(f"plans/candidate-{next_index:06d}.json", {"candidate_id": next_index, "parameters": selected})
                self.store.append_event({"type": "candidate_started", "candidate_id": next_index})
            self._record(next_index, self.evaluator.evaluate(selected, self.series_by_rate))
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
                rate: (models[rate].lambda_ if 'models' in locals() else None)
                for rate in RATE_ORDER
            },
        }
        if self.store is not None:
            self.store.write_json("summary.json", summary)
            self.store.append_event({"type": "optimization_completed", "summary": summary})
        return summary
