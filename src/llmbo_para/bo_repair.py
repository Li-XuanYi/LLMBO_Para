"""Optional P0 policies. Physical bounds, the four-rate objective and EI stay unchanged."""
from dataclasses import asdict, dataclass
import math
import numpy as np


@dataclass(frozen=True)
class RepairSettings:
    training_data: str = "complete"
    candidate_policy: str = "global"
    feasibility_weighting: bool = False
    completion_model: str = "legacy_diagonal"
    local_fraction: float = .75
    local_radius: float = .02
    min_radius: float = .002
    max_radius: float = .2
    global_every: int = 5

    @classmethod
    def parse(cls, value=None):
        if value is not None and not isinstance(value, dict):
            raise ValueError("bo_repair must be an object")
        try:
            obj = cls(**(value or {}))
        except TypeError as exc:
            raise ValueError("unknown bo_repair setting") from exc
        if not isinstance(obj.training_data, str) or not isinstance(obj.candidate_policy, str) or obj.training_data not in {"complete", "per_rate"} or obj.candidate_policy not in {"global", "local"}:
            raise ValueError("bo_repair needs training_data=complete/per_rate and candidate_policy=global/local")
        if type(obj.feasibility_weighting) is not bool or type(obj.global_every) is not int or obj.global_every < 1:
            raise ValueError("invalid bo_repair weighting switch or global exploration period")
        if not isinstance(obj.completion_model, str) or obj.completion_model not in {"legacy_diagonal", "standardized_linear_cv"}:
            raise ValueError("bo_repair.completion_model must be legacy_diagonal or standardized_linear_cv")
        for name in ("local_fraction", "local_radius", "min_radius", "max_radius"):
            val = getattr(obj, name)
            if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val):
                raise ValueError(f"bo_repair.{name} must be finite")
        if not 0 < obj.local_fraction < 1 or not 0 < obj.min_radius <= obj.local_radius <= obj.max_radius <= 1:
            raise ValueError("invalid local fraction or radius bounds")
        return obj


class CompletionModel:
    """L2 logistic model for *operational joint completion*, not physical feasibility.

    Diagonal quadratic features permit an interior completion region. No product
    of marginal probabilities and no class balancing are used. Training Brier is
    diagnostic only; it is not a claim of out-of-sample calibration.
    """
    def __init__(self, method="legacy_diagonal"):
        if method not in {"legacy_diagonal", "standardized_linear_cv"}:
            raise ValueError("unknown completion model")
        self.method = method
        self.state = {"ready": False, "fallback": "not_fitted"}

    @staticmethod
    def features(x):
        x = np.asarray(x, dtype=float) - .5
        return np.column_stack((np.ones(len(x)), x, x*x))

    @staticmethod
    def sigmoid(z):
        return 1. / (1. + np.exp(-np.clip(z, -40, 40)))

    def fit(self, x, labels):
        x, y = np.asarray(x, dtype=float), np.asarray(labels, dtype=float)
        if self.method == "standardized_linear_cv":
            return self._fit_standardized_linear(x, y)
        positive = int(np.sum(y))
        self.state = dict(ready=False, fallback=None, sample_count=len(y), positive_count=positive,
            negative_count=len(y)-positive, label="all_four_rates_valid_including_operational_solver_failures",
            regularization=1., features="centered_linear_and_diagonal_quadratic")
        if len(y) < 8 or min(positive, len(y)-positive) < 2:
            self.state["fallback"] = "insufficient_samples_or_classes"
            return self
        f = self.features(x)
        beta = np.zeros(f.shape[1]); beta[0] = np.log(positive/(len(y)-positive))
        penalty = np.ones(len(beta)); penalty[0] = 1e-6
        converged = False
        try:
            for iteration in range(80):
                p = self.sigmoid(f @ beta)
                gradient = f.T @ (p-y) + penalty*beta
                hessian = f.T @ ((p*(1-p))[:, None]*f) + np.diag(penalty)
                step = np.linalg.solve(hessian, gradient)
                # Backtracking keeps Newton updates stable on small, separable sets.
                loss = np.sum(np.logaddexp(0, f@beta) - y*(f@beta)) + .5*np.sum(penalty*beta*beta)
                scale = 1.
                while scale > 1e-8:
                    trial = beta - scale*step
                    new_loss = np.sum(np.logaddexp(0, f@trial)-y*(f@trial)) + .5*np.sum(penalty*trial*trial)
                    if np.isfinite(new_loss) and new_loss <= loss + 1e-12:
                        break
                    scale *= .5
                if scale <= 1e-8:
                    break
                beta = trial
                if np.max(np.abs(scale*step)) < 1e-8:
                    converged = True
                    break
            p = self.sigmoid(f@beta)
            if not converged or np.any(~np.isfinite(beta)) or np.std(p) < 1e-6:
                self.state["fallback"] = "nonconverged_or_degenerate_fit"
                return self
            self.state.update(ready=True, coefficients=beta.tolist(), iterations=iteration+1,
                train_brier=float(np.mean((p-y)**2)), train_probability_range=[float(p.min()), float(p.max())],
                observed_success_fraction=positive/len(y))
        except (np.linalg.LinAlgError, FloatingPointError):
            self.state["fallback"] = "numerical_fit_failure"
        return self

    def predict(self, x):
        if not self.state["ready"]:
            return None
        if self.state.get("features") == "training_standardized_linear":
            return self._linear_predict(self.state, np.asarray(x, dtype=float))
        return self.sigmoid(self.features(x) @ np.asarray(self.state["coefficients"]))

    @classmethod
    def _linear_fit(cls, x, y, strength):
        """The scaler is fit on this training set only, including during CV."""
        mean, scale = x.mean(axis=0), x.std(axis=0)
        scale = np.where(scale < 1e-8, 1., scale)
        f = np.column_stack((np.ones(len(x)), (x-mean)/scale))
        beta = np.zeros(f.shape[1]); beta[0] = np.log(sum(y)/(len(y)-sum(y)))
        penalty = np.full(len(beta), strength); penalty[0] = 1e-6
        for iteration in range(80):
            z = f@beta; p = cls.sigmoid(z)
            gradient = f.T@(p-y) + penalty*beta
            hessian = f.T@((p*(1-p))[:,None]*f) + np.diag(penalty)
            step = np.linalg.solve(hessian, gradient)
            loss = np.sum(np.logaddexp(0,z)-y*z) + .5*np.sum(penalty*beta*beta)
            backtrack = 1.
            while backtrack > 1e-8:
                trial = beta-backtrack*step; z = f@trial
                new_loss = np.sum(np.logaddexp(0,z)-y*z) + .5*np.sum(penalty*trial*trial)
                if np.isfinite(new_loss) and new_loss <= loss+1e-12:
                    break
                backtrack *= .5
            if backtrack <= 1e-8:
                raise FloatingPointError("linear completion Newton line search failed")
            beta = trial
            if np.max(np.abs(backtrack*step)) < 1e-8:
                break
        gradient = f.T@(cls.sigmoid(f@beta)-y)+penalty*beta
        if np.any(~np.isfinite(beta)) or np.max(np.abs(gradient)) >= 1e-6:
            raise FloatingPointError("linear completion fit did not converge")
        return dict(feature_mean=mean.tolist(), feature_scale=scale.tolist(), coefficients=beta.tolist(),
            iterations=iteration+1, max_abs_gradient=float(np.max(np.abs(gradient))))

    @classmethod
    def _linear_predict(cls, state, x):
        f = np.column_stack((np.ones(len(x)), (x-np.asarray(state["feature_mean"]))/np.asarray(state["feature_scale"])))
        return cls.sigmoid(f@np.asarray(state["coefficients"]))

    def _fit_standardized_linear(self, x, y):
        if not len(y) and x.size == 0:
            x = x.reshape(0,6)
        if (x.shape != (len(y),6) or y.ndim != 1 or np.any(~np.isfinite(x))
            or np.any((x<0)|(x>1)) or np.any(~np.isfinite(y)) or np.any((y!=0)&(y!=1))):
            raise ValueError("completion training needs normalized n by 6 inputs and binary labels")
        positive = int(sum(y))
        self.state = dict(ready=False, fallback=None, sample_count=len(y), positive_count=positive,
            negative_count=len(y)-positive, label="all_four_rates_valid_including_operational_solver_failures",
            method="standardized_linear_cv", features="training_standardized_linear",
            regularization_grid=[.001,.01,.1,1.,10.,100.], cv_seed=20261014,
            cv_metric="unweighted_log_loss", intercept_regularization=1e-6)
        if len(y)<8 or min(positive,len(y)-positive)<2:
            self.state["fallback"] = "insufficient_samples_or_classes"
            return self
        rng = np.random.default_rng(self.state["cv_seed"])
        folds = [[] for _ in range(min(4,positive,len(y)-positive))]
        for label in (0,1):
            indexes = np.flatnonzero(y==label); rng.shuffle(indexes)
            for i, row in enumerate(indexes):
                folds[i % len(folds)].append(int(row))
        folds = [sorted(rows) for rows in folds]
        self.state["cv_folds"] = folds
        diagnostics = []
        try:
            for strength in self.state["regularization_grid"]:
                probabilities = np.empty(len(y)); fits = []
                for val in folds:
                    tr = np.setdiff1d(np.arange(len(y)),val)
                    model = self._linear_fit(x[tr],y[tr],strength)
                    probabilities[val] = self._linear_predict(model,x[val])
                    fits.append(dict(training_indexes=tr.tolist(),validation_indexes=val,**model))
                clipped = np.clip(probabilities,1e-12,1-1e-12)
                loss = float(np.mean(-y*np.log(clipped)-(1-y)*np.log1p(-clipped)))
                diagnostics.append(dict(regularization=strength,log_loss=loss,probabilities=probabilities.tolist(),fits=fits))
            chosen = min(diagnostics,key=lambda row:(row["log_loss"],-row["regularization"]))
            model = self._linear_fit(x,y,chosen["regularization"])
            p = self._linear_predict(model,x)
            self.state.update(cv_results=diagnostics,regularization=chosen["regularization"],**model)
            if np.std(p)<1e-6:
                self.state["fallback"] = "nonconverged_or_degenerate_fit"
                return self
            self.state.update(ready=True,train_brier=float(np.mean((p-y)**2)),
                train_probability_range=[float(p.min()),float(p.max())],observed_success_fraction=positive/len(y))
        except (np.linalg.LinAlgError,FloatingPointError):
            self.state.update(fallback="numerical_fit_failure",cv_results=diagnostics)
        return self


def decision_scores(raw_ei, probabilities, *, enabled=False):
    """EI times joint probability is an approximation; explicitly fall back to EI."""
    ei = np.asarray(raw_ei, dtype=float)
    if ei.ndim != 1 or np.any(~np.isfinite(ei)) or np.any(ei < 0):
        raise ValueError("EI must be finite and nonnegative")
    if not enabled:
        return ei.copy(), "raw_ei", None
    if probabilities is None:
        return ei.copy(), "raw_ei", "completion_model_unavailable"
    p = np.asarray(probabilities, dtype=float)
    if p.shape != ei.shape or np.any(~np.isfinite(p)) or np.any((p < 0) | (p > 1)):
        return ei.copy(), "raw_ei", "invalid_completion_probabilities"
    if np.ptp(p) < 1e-6 or np.max(p) < 1e-8:
        return ei.copy(), "raw_ei", "degenerate_pool_probabilities"
    return ei*p, "ei_times_joint_completion_approximation", None


def select_candidate(scores, eligible, *, seed, candidate_id, cold_start=False):
    """Uniform seeded fallback avoids always selecting a power-of-two Sobol prefix."""
    eligible = np.asarray(eligible, dtype=bool)
    indexes = np.flatnonzero(eligible)
    if not len(indexes):
        raise ValueError("no eligible candidate")
    if cold_start:
        rng = np.random.default_rng(np.random.SeedSequence([seed,candidate_id,911]))
        return int(rng.choice(indexes))
    return int(np.argmax(np.where(eligible, scores, -np.inf)))


class LocalNeighborhood:
    """A small adaptive box around valid points, with an actual global quota."""
    def __init__(self, settings, seed):
        self.settings = settings
        self.radius = settings.local_radius
        self.rng = np.random.default_rng(np.random.SeedSequence([seed, 7319]))
        self.success_streak = self.failure_streak = 0

    def update(self, result, origin):
        before = self.radius
        outcome = "global_or_numerical_neutral"
        if origin == "local":
            if result.valid:
                self.success_streak += 1; self.failure_streak = 0
                outcome = "local_success"
                if self.success_streak >= 3:
                    self.radius = min(self.settings.max_radius, self.radius*1.5)
                    self.success_streak = 0
            elif any(r.failure_kind in {"coverage_shortfall", "voltage_cutoff"} for r in result.rates if not r.valid):
                # An accompanying numerical error makes this update ambiguous.
                if all(r.valid or r.failure_kind in {"coverage_shortfall", "voltage_cutoff"} for r in result.rates):
                    self.failure_streak += 1; self.success_streak = 0
                    outcome = "local_coverage_failure"
                    if self.failure_streak >= 2:
                        self.radius = max(self.settings.min_radius, self.radius/1.5)
                        self.failure_streak = 0
        return dict(origin=origin, outcome=outcome, radius_before=before, radius_after=self.radius,
            success_streak=self.success_streak, failure_streak=self.failure_streak)

    def state_dict(self):
        return dict(radius=self.radius, success_streak=self.success_streak, failure_streak=self.failure_streak,
            rng_state=self.rng.bit_generator.state, settings=asdict(self.settings))
