"""CPU exact GP with a learned full/subset Matérn-5/2 kernel mixture."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Sequence

import numpy as np


def _matern52(x1: np.ndarray, x2: np.ndarray, lengthscales: np.ndarray) -> np.ndarray:
    scaled = (x1[:, None, :] - x2[None, :, :]) / lengthscales
    distance = np.sqrt(np.sum(scaled * scaled, axis=-1) + 1e-30)
    q = math.sqrt(5.0) * distance
    return (1.0 + q + q * q / 3.0) * np.exp(-q)


@dataclass
class Matern52GP:
    """Exact GP; bounded coordinate search maximizes marginal log likelihood."""

    max_sweeps: int = 4
    max_lambda: float = 0.8
    jitter: float = 1e-9

    def fit(self, x: Sequence[Sequence[float]], y: Sequence[float], group: Sequence[int] | None = None) -> "Matern52GP":
        self.x = np.asarray(x, dtype=float)
        self.y = np.asarray(y, dtype=float)
        if self.x.ndim != 2 or self.x.shape[1] != 6 or self.y.shape != (self.x.shape[0],):
            raise ValueError("GP training requires n by 6 inputs and n scalar targets")
        if self.x.shape[0] < 2 or np.any(~np.isfinite(self.x)) or np.any(~np.isfinite(self.y)):
            raise ValueError("GP training needs at least two finite observations")
        if np.any(self.x < 0) or np.any(self.x > 1):
            raise ValueError("GP inputs must be normalized to [0, 1]")
        if not 0 < self.max_lambda <= 0.8:
            raise ValueError("maximum kernel mixture must be in (0, 0.8]")
        self.group = tuple(sorted(set(int(i) for i in (() if group is None else group))))
        if any(i < 0 or i >= 6 for i in self.group):
            raise ValueError("group indexes must be in [0, 5]")
        self.has_group = 0 < len(self.group) < 6
        self.params = np.concatenate((np.full(6, math.log(0.35)), [0.0, math.log(0.03), self.max_lambda / 2 if self.has_group else 0.0]))
        active = list(range(8)) + ([8] if self.has_group else [])
        steps = {i: (0.45 if i < 6 else 0.30 if i in {6, 7} else 0.2) for i in active}
        best = self._mll(self.params)
        for _ in range(max(0, self.max_sweeps)):
            improved = False
            for index in active:
                alternatives = []
                for direction in (-1.0, 1.0):
                    candidate = self.params.copy()
                    candidate[index] += direction * steps[index]
                    if index < 6:
                        candidate[index] = np.clip(candidate[index], math.log(0.03), math.log(8.0))
                    elif index == 6:
                        candidate[index] = np.clip(candidate[index], math.log(0.02), math.log(10.0))
                    elif index == 7:
                        candidate[index] = np.clip(candidate[index], math.log(1e-6), math.log(0.8))
                    else:
                        candidate[index] = np.clip(candidate[index], 0.0, self.max_lambda)
                    alternatives.append((self._mll(candidate), candidate))
                score, candidate = max(alternatives, key=lambda item: item[0])
                if score > best + 1e-10:
                    self.params, best, improved = candidate, score, True
            if not improved:
                for index in active:
                    steps[index] *= 0.5
                if max(steps.values()) < 0.01:
                    break
        self.marginal_log_likelihood = float(best)
        self.lambda_ = self._lambda(self.params) if self.has_group else 0.0
        self._factor()
        return self

    def _lambda(self, params: np.ndarray) -> float:
        return float(np.clip(params[8], 0.0, self.max_lambda))

    def state_dict(self) -> dict:
        return {"x": self.x.tolist(), "y": self.y.tolist(), "hyperparameters": self.params.tolist(),
                "group": list(self.group), "lambda": self.lambda_, "jitter": self.jitter,
                "max_sweeps": self.max_sweeps, "max_lambda": self.max_lambda, "marginal_log_likelihood": self.marginal_log_likelihood}

    @classmethod
    def from_state(cls, state: dict) -> "Matern52GP":
        model = cls(max_sweeps=0, jitter=state["jitter"], max_lambda=state.get("max_lambda", 0.8)).fit(state["x"], state["y"], state["group"])
        model.params = np.asarray(state["hyperparameters"], dtype=float)
        model.lambda_ = model._lambda(model.params) if model.has_group else 0.0
        model.marginal_log_likelihood = state["marginal_log_likelihood"]
        model._factor()
        return model

    def _kernel(self, x1: np.ndarray, x2: np.ndarray, params: np.ndarray) -> np.ndarray:
        lengthscales = np.exp(params[:6])
        amplitude = math.exp(2.0 * params[6])
        full = _matern52(x1, x2, lengthscales)
        if not self.has_group:
            return amplitude * full
        idx = list(self.group)
        subset = _matern52(x1[:, idx], x2[:, idx], lengthscales[idx])
        mixture = self._lambda(params)
        return amplitude * ((1.0 - mixture) * full + mixture * subset)

    def _mll(self, params: np.ndarray) -> float:
        covariance = self._kernel(self.x, self.x, params)
        covariance.flat[:: covariance.shape[0] + 1] += math.exp(2 * params[7]) + self.jitter
        try:
            factor = np.linalg.cholesky(covariance)
            alpha = np.linalg.solve(factor.T, np.linalg.solve(factor, self.y))
            return float(-0.5 * self.y @ alpha - np.log(np.diag(factor)).sum() - 0.5 * len(self.y) * math.log(2 * math.pi))
        except np.linalg.LinAlgError:
            return -math.inf

    def _factor(self) -> None:
        covariance = self._kernel(self.x, self.x, self.params)
        covariance.flat[:: covariance.shape[0] + 1] += math.exp(2 * self.params[7]) + self.jitter
        self.cholesky = np.linalg.cholesky(covariance)
        self.alpha = np.linalg.solve(self.cholesky.T, np.linalg.solve(self.cholesky, self.y))

    def predict(self, candidates: Sequence[Sequence[float]]) -> tuple[np.ndarray, np.ndarray]:
        x = np.asarray(candidates, dtype=float)
        if x.ndim != 2 or x.shape[1] != 6 or np.any(~np.isfinite(x)) or np.any(x < 0) or np.any(x > 1):
            raise ValueError("prediction inputs must be finite normalized six-vectors")
        cross = self._kernel(self.x, x, self.params)
        mean = cross.T @ self.alpha
        solved = np.linalg.solve(self.cholesky, cross)
        variance = np.maximum(1e-14, math.exp(2 * self.params[6]) - np.sum(solved * solved, axis=0))
        return mean, np.sqrt(variance)
