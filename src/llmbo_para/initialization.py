"""Bounded feasible initialization with recorded proposals and reusable results."""
from dataclasses import asdict, dataclass, replace
import json
import math
from pathlib import Path
import time
import traceback
import shutil
import numpy as np

from .evaluation import CallableSimulator, EvaluationResult, FourRateEvaluator, RateResult
from .feasibility import simulation_signature
from .metrics import RATE_ORDER
from .runstore import digest_value, sha256_file

SIMULATION_FILES = ("data.py", "evaluation.py", "metrics.py", "parameters.py", "pybamm_adapter.py", "providers.py", "reference_cell.py")


def validated_simulation_sources(screening_directory):
    directory = Path(screening_directory)
    index_path = directory / "source-sha256.json"
    hashes = {key.replace("\\", "/"): value for key, value in json.loads(index_path.read_text(encoding="utf-8")).items()}
    selected = {}
    for name in SIMULATION_FILES:
        key = "src/llmbo_para/" + name
        expected = hashes.get(key)
        archived = directory / "source" / Path(key)
        if not expected or not archived.is_file() or sha256_file(archived) != expected or sha256_file(Path(__file__).parent / name) != expected:
            raise ValueError("cached simulation implementation source mismatch: " + name)
        selected[key] = expected
    return selected, sha256_file(index_path)


@dataclass(frozen=True)
class ScreeningBudget:
    target: int = 8
    max_evaluations: int = 200
    max_random_draws: int = 20000
    warm_batch_size: int = 20
    max_warm_batches: int = 10
    max_selection_requests: int = 30

    def __post_init__(self):
        if any(type(value) is not int or value < 1 for value in asdict(self).values()):
            raise ValueError("screening budgets must be positive integers")
        if self.target < 2 or self.max_evaluations < self.target or self.warm_batch_size < self.target:
            raise ValueError("screening target must be at least two and fit the evaluation/proposal budget")


def validated_cached_results(config, series, plan, plan_path):
    """Recompute every cached label from its curves before training any GP."""
    if "evaluations" not in plan:
        return None
    if plan.get("simulation_signature") != simulation_signature(config, series):
        raise ValueError("cached initialization simulation/data signature mismatch")
    sources_fingerprint, source_manifest = validated_simulation_sources(plan["screening_directory"])
    records, sources = plan["evaluations"], plan.get("evaluation_sources", [])
    if len(records) != len(plan["parameters"]) or len(sources) != len(records):
        raise ValueError("cached evaluation count differs from the initial set")
    results = []
    for point, record, source in zip(plan["parameters"], records, sources):
        source_path = Path(source["path"])
        if not source_path.is_file() or sha256_file(source_path) != source["sha256"]:
            raise ValueError("cached source record is missing or its SHA-256 changed")
        if json.loads(source_path.read_text(encoding="utf-8")) != record or record.get("parameters") != list(point):
            raise ValueError("cached evaluation differs from its source record or candidate")
        if not record.get("valid") or record.get("cache_provenance"):
            raise ValueError("initial cache must contain valid original evaluations")
        rates = {row["rate"]: row for row in record["rates"]}
        if list(rates) != list(RATE_ORDER):
            raise ValueError("cached initial evaluation lacks the four ordered rates")
        simulator = CallableSimulator(lambda parameters, row: (rates[row.rate]["simulation_time_s"], rates[row.rate]["simulation_voltage_v"]))
        from .config import parameter_space_from_config
        checked = FourRateEvaluator(parameter_space_from_config(config), simulator).evaluate(point, series)
        if not checked.valid or not math.isclose(checked.objective_v, record["objective_v"], rel_tol=1e-10, abs_tol=1e-12):
            raise ValueError("cached initial objective does not reproduce from the complete curves")
        for actual in checked.rates:
            saved = rates[actual.rate]
            if (not saved["valid"] or not math.isclose(saved["rmse_v"], actual.rmse_v, rel_tol=1e-10, abs_tol=1e-12)
                or not np.allclose(saved["aligned_voltage_v"], actual.aligned_voltage_v, rtol=0, atol=1e-12)
                or set(saved["residual_summary"]) != set(actual.residual_summary)
                or any(not math.isclose(saved["residual_summary"][key], value, rel_tol=1e-10, abs_tol=1e-12) for key, value in actual.residual_summary.items())):
                raise ValueError("cached initial labels or residual summaries do not reproduce")
        result = EvaluationResult(tuple(point), tuple(RateResult(**row) for row in record["rates"]), True, record["objective_v"])
        provenance = {"plan_sha256": sha256_file(plan_path), "source_record_sha256": source["sha256"],
            "source_record_path": str(source_path.resolve()), "simulation_signature": plan["simulation_signature"],
            "simulation_source_sha256": sources_fingerprint, "source_manifest_sha256": source_manifest}
        results.append(replace(result, cache_provenance=provenance))
    return results


class FeasibleInitializer:
    def __init__(self, config, space, series, evaluator, store, *, gate, source, budget=None, llm_factory=None, parameterization_fingerprint=None, checkpoint_callback=None):
        if source not in {"random", "llm"} or source == "llm" and llm_factory is None:
            raise ValueError("initialization requires explicit source and an LLM factory for LLM points")
        self.config, self.space, self.series, self.evaluator, self.store = config, space, series, evaluator, store
        self.gate, self.source = gate, source
        self.budget, self.llm_factory = budget or ScreeningBudget(), llm_factory
        self.parameterization_fingerprint = parameterization_fingerprint
        self.checkpoint_callback = checkpoint_callback
        self.accepted, self.accepted_sources, self.seen = [], [], set()
        self.draws = self.evaluations = self.batches = self.selection_requests = self.analytical_rejections = self.physical_rejections = 0
        self.api_requests = self.rate_solves = 0
        self.simulation_elapsed_s = 0.
        self.started = time.perf_counter()
        self.elapsed_offset_s = 0.
        self.failures = []

    def restore_llm(self, plan, plan_path):
        """Continue a bounded LLM family without replacing its validated points or costs."""
        if self.source != "llm" or plan.get("source") != "llm":
            raise ValueError("LLM continuation requires an LLM source plan")
        validated_cached_results(self.config, self.series, plan, plan_path)
        directory = Path(plan["screening_directory"])
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        previous_config = manifest["config"].get("experiment", manifest["config"])
        if previous_config["llm"] != self.config["llm"] or previous_config["optimization"]["seed"] != self.config["optimization"]["seed"]:
            raise ValueError("LLM continuation model/configuration or seed differs")
        if plan.get("parameterization_fingerprint") != self.parameterization_fingerprint:
            raise ValueError("LLM continuation fixed parameterization differs")
        cost = plan["screening_cost"]
        if (cost["candidate_evaluations"] > self.budget.max_evaluations or len(plan["parameters"]) > self.budget.target
            or cost["batches"] > self.budget.max_warm_batches or cost["selection_requests"] > self.budget.max_selection_requests):
            raise ValueError("continuation budget is smaller than its previously consumed cost")
        for attr,key in (("draws","generated_draws"),("evaluations","candidate_evaluations"),("batches","batches"),
            ("selection_requests","selection_requests"),("analytical_rejections","analytical_rejections"),
            ("physical_rejections","physical_rejections"),("rate_solves","rate_solve_attempts"),("api_requests","api_requests")):
            setattr(self,attr,cost[key])
        self.accepted,self.accepted_sources = list(plan["evaluations"]),list(plan["evaluation_sources"])
        records = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((directory/"attempts").glob("*.json"))]
        if len(records)+plan.get("prior_candidate_evaluations",0) != self.evaluations:
            raise ValueError("continuation candidate cost differs from archived attempts")
        self.seen = {tuple(p) for p in plan.get("seen_parameters", [])}
        if not self.seen:
            # Legacy plans retain the exact generation archives in their event stream.
            for line in (directory/"events.jsonl").read_text(encoding="utf-8").splitlines():
                event=json.loads(line)
                if event["type"] == "llm_request_archive" and event["stage"] == "generate":
                    accepted=Path(event["path"])/"llm/warm_start.accepted.json"
                    for point in json.loads(accepted.read_text(encoding="utf-8"))["parameters"]:
                        point=self.space.validate(point)
                        if self.gate is None or self.gate.check(point)["feasible"]:
                            self.seen.add(point)
        if any(tuple(r["parameters"]) not in self.seen for r in records+self.accepted):
            raise ValueError("LLM cached/evaluated points lack original generation provenance")
        self.failures = list(plan.get("failed_candidate_feedback", []))
        if not self.failures:
            self.failures=[{"parameters":r["parameters"],"reason":"four_rate_incomplete",
                "covered_duration_s":{v["rate"]:v["simulation_time_s"][-1] if v["simulation_time_s"] else None for v in r["rates"]}}
                for r in records if not r["valid"]][-20:]
        self.elapsed_offset_s=cost["elapsed_s"]
        self.simulation_elapsed_s=cost["simulation_elapsed_s"]
        self.prior_candidate_evaluations,self.prior_rate_solves,self.prior_draws=self.evaluations,self.rate_solves,self.draws
        target=self.store.path/"inputs/resume-plan.json"
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(plan_path,target)
        self.store.write_json("resume-lineage.json",{"plan_path":str(Path(plan_path).resolve()),"plan_sha256":sha256_file(target),
            "screening_directory":str(directory),"original_cost":cost,"old_budget":manifest["config"].get("budget"),
            "new_budget":asdict(self.budget),"next_generation_batch":self.batches+1})
        self.store.append_event({"type":"llm_screening_resumed",**self.progress()})

    def restore_random(self, plan, plan_path):
        """Continue the exact RNG sequence and cumulative budget, retaining originals."""
        if self.source != "random" or plan.get("source") != "random":
            raise ValueError("this continuation path supports the random family only")
        validated_cached_results(self.config, self.series, plan, plan_path)
        directory = Path(plan["screening_directory"])
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        previous_config = manifest["config"].get("experiment", manifest["config"])
        if previous_config["optimization"]["seed"] != self.config["optimization"]["seed"]:
            raise ValueError("random continuation seed differs from the original run")
        if plan.get("parameterization_fingerprint") != self.parameterization_fingerprint:
            raise ValueError("random continuation fixed parameterization differs")
        cost = plan["screening_cost"]
        self.draws, self.evaluations = cost["generated_draws"], cost["candidate_evaluations"]
        if self.draws > self.budget.max_random_draws or self.evaluations > self.budget.max_evaluations or len(plan["parameters"]) > self.budget.target:
            raise ValueError("continuation budget is smaller than its previously consumed cost")
        self.accepted, self.accepted_sources = list(plan["evaluations"]), list(plan["evaluation_sources"])
        self.analytical_rejections, self.physical_rejections = cost["analytical_rejections"], cost["physical_rejections"]
        self.rate_solves = cost["rate_solve_attempts"]
        self.elapsed_offset_s = cost["elapsed_s"]
        rng = np.random.default_rng(self.config["optimization"]["seed"])
        for normalized in rng.random((self.draws, self.space.dimension)):
            try:
                self.seen.add(self.space.denormalize(normalized))
            except ValueError:
                continue
        if any(tuple(row["parameters"]) not in self.seen for row in self.accepted):
            raise ValueError("cached random points do not belong to the original seeded draw sequence")
        records = [json.loads(file.read_text(encoding="utf-8")) for file in sorted((directory / "attempts").glob("*.json"))]
        prior = plan.get("prior_candidate_evaluations", 0)
        if len(records)+prior != self.evaluations:
            raise ValueError("continuation candidate cost differs from archived attempts")
        self.simulation_elapsed_s = cost.get("simulation_elapsed_s", sum(row["elapsed_s"] for record in records for row in record["rates"]))
        self.prior_candidate_evaluations = self.evaluations
        self.prior_rate_solves, self.prior_draws = self.rate_solves, self.draws
        target = self.store.path / "inputs/resume-plan.json"
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(plan_path, target)
        self.store.write_json("resume-lineage.json", {"plan_path": str(Path(plan_path).resolve()), "plan_sha256": sha256_file(target),
            "screening_directory": str(directory), "original_cost": cost, "rng_next_raw_draw": self.draws+1})
        self.store.append_event({"type": "random_screening_resumed", **self.progress()})

    def progress(self):
        elapsed = time.perf_counter() - self.started + self.elapsed_offset_s
        speed = len(self.accepted) * 60. / elapsed if self.accepted else None
        return {"source": self.source, "target": self.budget.target, "accepted": len(self.accepted),
            "pending": max(0, self.budget.target - len(self.accepted)), "candidate_evaluations": self.evaluations,
            "physical_rejections": self.physical_rejections, "analytical_rejections": self.analytical_rejections,
            "generated_draws": self.draws, "batches": self.batches, "selection_requests": self.selection_requests,
            "api_requests": self.api_requests, "rate_solve_attempts": self.rate_solves, "elapsed_s": elapsed,
            "simulation_elapsed_s": self.simulation_elapsed_s,
            "new_candidate_evaluations": self.evaluations-getattr(self, "prior_candidate_evaluations", 0),
            "new_rate_solve_attempts": self.rate_solves-getattr(self, "prior_rate_solves", 0),
            "new_generated_draws": self.draws-getattr(self, "prior_draws", 0),
            "accepted_points_per_min": speed, "eta_minutes": (self.budget.target-len(self.accepted))/speed if speed else None}

    def _evaluate(self, point):
        if self.evaluations >= self.budget.max_evaluations:
            return False
        check = self.gate.check(point) if self.gate else {"feasible": True}
        if not check["feasible"]:
            self.analytical_rejections += 1
            self.store.append_event({"type": "screening_rejected", "parameters": point, **check})
            return False
        self.store.append_event({"type": "screening_candidate_started", "candidate_id": self.evaluations, "parameters": point})
        result = self.evaluator.evaluate(point, self.series)
        self.last_result = result
        path = self.store.save_attempt(self.evaluations, 1, result.to_dict())
        self.evaluations += 1
        self.rate_solves += sum(len(row.attempts) for row in result.rates)
        self.simulation_elapsed_s += sum(row.elapsed_s for row in result.rates)
        if result.valid:
            self.accepted.append(json.loads(path.read_text(encoding="utf-8")))
            self.accepted_sources.append({"path": str(path), "sha256": sha256_file(path)})
            if len(self.accepted) == 2 and self.checkpoint_callback:
                checkpoint_plan = self.plan()
                checkpoint = self.store.write_json("two-point-checkpoint.json", checkpoint_plan)
                self.checkpoint_callback(checkpoint_plan, checkpoint)
        else:
            self.physical_rejections += 1
        self.store.append_event({"type": "screening_progress", **self.progress()})
        return result.valid

    def _random(self):
        rng = np.random.default_rng(self.config["optimization"]["seed"])
        if self.draws:
            rng.random((self.draws, self.space.dimension))
        while len(self.accepted) < self.budget.target and self.evaluations < self.budget.max_evaluations and self.draws < self.budget.max_random_draws:
            normalized = rng.random(self.space.dimension)
            self.draws += 1
            try:
                point = self.space.denormalize(normalized)
                if point in self.seen:
                    raise ValueError("duplicate proposal")
            except ValueError as exc:
                self.analytical_rejections += 1
                self.store.append_event({"type": "screening_draw_rejected", "draw": self.draws, "normalized": normalized.tolist(), "reason": str(exc)})
                continue
            self.seen.add(point)
            self.store.append_event({"type": "screening_proposal", "draw": self.draws, "parameters": point})
            self._evaluate(point)

    def _warm(self):
        failures = self.failures
        while len(self.accepted) < self.budget.target and self.evaluations < self.budget.max_evaluations and self.batches < self.budget.max_warm_batches and self.selection_requests < self.budget.max_selection_requests:
            self.batches += 1
            context = {"initialization_recovery": {"accepted_count": len(self.accepted), "target": self.budget.target,
                "generation_batch": self.batches, "accepted_parameters": [row["parameters"] for row in self.accepted],
                "previous_generated_parameters": [list(point) for point in sorted(self.seen)][-200:],
                "failed_candidates": failures[-20:], "inventory_check": asdict(self.gate) if self.gate else None}}
            client = self.llm_factory("generate", self.batches, context)
            self.api_requests += 1
            proposals = client.warm_start(self.space, self.budget.warm_batch_size)
            statistics = getattr(client, "last_warm_statistics", {"received": len(proposals)})
            self.draws += statistics["received"]
            self.analytical_rejections += statistics["received"] - len(proposals)
            self.store.append_event({"type": "screening_generation", "batch": self.batches, "statistics": statistics})
            pool = []
            for proposed in proposals:
                point = self.space.validate(proposed)
                check = self.gate.check(point) if self.gate else {"feasible": True}
                if point in self.seen or not check["feasible"]:
                    self.analytical_rejections += 1
                    self.store.append_event({"type": "screening_proposal_rejected", "batch": self.batches, "parameters": point,
                        "reason": "duplicate" if point in self.seen else "necessary_inventory_bound", "inventory": check})
                    continue
                self.seen.add(point)
                pool.append(point)
            while pool and len(self.accepted) < self.budget.target and self.evaluations < self.budget.max_evaluations and self.selection_requests < self.budget.max_selection_requests:
                self.selection_requests += 1
                client = self.llm_factory("select", self.selection_requests, context)
                count = min(self.budget.target-len(self.accepted), len(pool), self.budget.max_evaluations-self.evaluations)
                self.api_requests += 1
                selected = client.select_warm_start(self.space, pool, count)
                if len(selected) != count or len(set(selected)) != count or any(point not in pool for point in selected):
                    raise ValueError("LLM selection did not return distinct existing candidate vectors")
                for point in selected:
                    pool.remove(point)
                    if not self._evaluate(point):
                        failures.append({"parameters": list(point), "reason": "four_rate_incomplete",
                            "covered_duration_s": {row.rate: row.simulation_time_s[-1] if row.simulation_time_s else None for row in self.last_result.rates}})
                context["initialization_recovery"].update(accepted_count=len(self.accepted),
                    accepted_parameters=[row["parameters"] for row in self.accepted], failed_candidates=failures[-20:])

    def run(self):
        self.store.write_json("screening-policy.json", {"source": self.source, "budget": asdict(self.budget),
            "gate": asdict(self.gate) if self.gate else None, "simulation_signature": simulation_signature(self.config, self.series)})
        try:
            self._random() if self.source == "random" else self._warm()
            complete = len(self.accepted) == self.budget.target
            plan = self.plan()
            self.store.write_json("initial-plan.json", plan)
            self.store.finish("completed" if complete else "completed_with_failures", {"complete": complete, **self.progress()})
            return plan
        except Exception as exc:
            if not (self.store.path / "initial-plan.json").exists():
                self.store.write_json("initial-plan.json", self.plan())
            self.store.write_json("screening-failure.json", {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc(), **self.progress()})
            self.store.finish("failed", {"error_type": type(exc).__name__, "message": str(exc), **self.progress()})
            raise

    def plan(self):
        return {"source": self.source, "parameters": [row["parameters"] for row in self.accepted],
            "evaluations": list(self.accepted), "evaluation_sources": list(self.accepted_sources),
            "simulation_signature": simulation_signature(self.config, self.series),
            "parameterization_fingerprint": self.parameterization_fingerprint,
            "screening_directory": str(self.store.path), "screening_cost": self.progress(),
            "prior_candidate_evaluations": getattr(self, "prior_candidate_evaluations", 0),
            "seen_parameters": [list(point) for point in sorted(self.seen)] if self.source == "llm" else [],
            "failed_candidate_feedback": self.failures[-20:] if self.source == "llm" else [],
            "complete": len(self.accepted) == self.budget.target}
