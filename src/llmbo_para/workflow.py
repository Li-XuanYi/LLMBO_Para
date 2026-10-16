"""Configuration-to-results orchestration; preflight never imports lab plugins."""

from dataclasses import dataclass, asdict
from importlib import metadata
from pathlib import Path
import json
import os
import shutil
import sys
import time
import traceback

from .audit import audit_run, read_json
from .config import configuration_errors, parameter_space_from_config
from .data import WorkbookSchema, load_four_rate_workbook
from .evaluation import DischargeSeries, FourRateEvaluator
from .llm import HttpJsonTransport, ChatCompletionsTransport, LLMClient
from .metrics import RATE_ORDER
from .optimizer import Optimizer
from .parameters import ParameterSpace
from .runstore import RunStore, sha256_file, digest_value
from .progress import summarize_progress
from .synthetic import synthetic_series, SyntheticSimulator
from .initialization import validated_cached_results
from .feasibility import InventoryGate


@dataclass
class PreparedExperiment:
    config: dict
    space: ParameterSpace
    series: dict[str, DischargeSeries]
    input_hashes: dict[str, str]
    workbook: Path | None = None
    initial_plan: Path | None = None
    initial_evaluations: list | None = None
    screening_history: object | None = None


class ExperimentFailure(RuntimeError):
    def __init__(self, message: str, run_directory: Path, status: str):
        super().__init__(message)
        self.run_directory, self.status = str(run_directory), status


def prepare_experiment(config: dict, *, base_dir: Path | None = None, archived_series=None) -> tuple[dict, PreparedExperiment | None]:
    errors = configuration_errors(config)
    warnings = []
    if sys.version_info[:2] != (3, 12):
        errors.append("the validated runtime requires Python 3.12; select the recorded interpreter")
    base_dir = (base_dir or Path.cwd()).resolve()
    model = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    optimization = config.get("optimization", {}) if isinstance(config.get("optimization"), dict) else {}
    installed_pybamm = RunStore._package_version("pybamm")
    if model.get("provider") == "pybamm" and (installed_pybamm is None or installed_pybamm != model.get("pybamm_version")):
        errors.append("the configured PyBaMM version is unavailable in the selected Python environment")
    if optimization.get("llm_enabled"):
        llm = config.get("llm", {}) if isinstance(config.get("llm"), dict) else {}
        key_env = llm.get("api_key_env") if isinstance(llm.get("api_key_env"), str) else ""
        if not os.environ.get(key_env):
            errors.append("the named LLM credential environment variable is not set")
        try:
            build_transport(llm)
        except (ValueError, TypeError):
            errors.append("LLM HTTPS transport settings are invalid")
    report = {"ready": False, "errors": errors, "warnings": warnings,
              "base_directory": str(base_dir), "parallel_workers": optimization.get("parallel_workers"),
              "gpu_backend": optimization.get("gpu_backend"), "installed_pybamm": installed_pybamm,
              "paid_api_calls_made": 0, "battery_simulations_made": 0}
    threads = {name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")}
    report["numerical_thread_environment"] = threads
    if any(value not in {None, "1"} for value in threads.values()):
        errors.append("the validated CPU path requires BLAS/OpenMP thread environment settings to be 1")
    if any(value is None for value in threads.values()):
        warnings.append("library caller must set BLAS/OpenMP threads before importing NumPy; CLI and verification scripts set them to 1")
    if errors:
        return report, None
    try:
        space = parameter_space_from_config(config)
        initial_plan = None
        if "initial_candidates" in optimization:
            evidence = optimization["initial_candidates_evidence"]
            initial_plan = Path(evidence["path"])
            if not initial_plan.is_absolute():
                initial_plan = base_dir / initial_plan
            initial_plan = initial_plan.resolve()
            if sha256_file(initial_plan) != evidence["sha256"]:
                raise ValueError("shared initial plan differs from its configured SHA-256")
            plan = read_json(initial_plan)
            if plan.get("parameters") != optimization["initial_candidates"] or plan.get("source") != optimization["initial_candidates_source"]:
                raise ValueError("shared initial candidates or provenance differ from the archived plan")
            report["shared_initial_plan_sha256"] = evidence["sha256"]
        data = config["data"]
        workbook = None
        hashes = {}
        if archived_series is not None:
            series = archived_series
            warnings.append("recovery uses the archived input snapshot; the original workbook is not reinterpreted")
        elif data["kind"] == "builtin_synthetic":
            series = synthetic_series()
            warnings.append("synthetic software fixture; its scores and throughput are not battery results")
        else:
            workbook = Path(data["path"])
            if not workbook.is_absolute():
                workbook = base_dir / workbook
            workbook = workbook.resolve()
            actual_hash = sha256_file(workbook)
            if actual_hash != data["sha256"].lower():
                raise ValueError("workbook hash differs from the explicit configuration")
            schema = WorkbookSchema(
                data["sheet_by_rate"], data.get("time_column"), data.get("current_column"),
                data["voltage_column"], data.get("temperature_column"), data["legacy_assumed_1s"],
                data.get("sample_period_s"), config["nominal_capacity_ah"], data["discharge_current_sign"],
            )
            series, digest = load_four_rate_workbook(workbook, schema)
            if digest != actual_hash:
                raise ValueError("workbook changed while it was being read")
            hashes[str(workbook)] = digest
        if set(series) != set(RATE_ORDER):
            raise ValueError("exactly four rate input series are required")
        for rate, item in series.items():
            if item.time_s[0] != 0:
                raise ValueError(f"{rate}: input time must start at zero; no implicit time shift is applied")
            if item.assumptions:
                warnings.append(f"{rate}: " + "; ".join(item.assumptions))
        cached = validated_cached_results(config, series, plan, initial_plan) if initial_plan else None
        history = None
        if optimization.get("reuse_screening_history"):
            if cached is None:
                raise ValueError("screening history reuse requires cached original evaluations")
            from .screening_history import load_screening_history
            history = load_screening_history(config, series, plan, initial_plan)
            report["screening_history"] = {k: history.catalog[k] for k in (
                "reused_failed_candidates", "partial_rate_labels", "attributed_screening_cost")}
            if history.catalog.get('schema_version') == 2:
                report['screening_history'].update({k:history.catalog[k] for k in ('reused_valid_candidates','reused_candidates')})
        report.update(ready=True, samples_by_rate={r: len(v.time_s) for r, v in series.items()}, input_sha256=hashes,
                      cached_initial_evaluations=0 if cached is None else len(cached))
        return report, PreparedExperiment(config, space, series, hashes, workbook, initial_plan, cached, history)
    except (ValueError, TypeError, OSError, KeyError) as exc:
        errors.append(f"input preflight: {type(exc).__name__}: {exc}")
        return report, None


def build_backend(prepared: PreparedExperiment):
    if prepared.config["model"]["provider"] == "synthetic":
        return SyntheticSimulator(prepared.space)
    from .pybamm_adapter import build_simulator
    return build_simulator(prepared.config)


def build_llm(config: dict, store: RunStore, *, prepared=None) -> LLMClient | None:
    if not config["optimization"]["llm_enabled"]:
        return None
    llm = config["llm"]
    context = {"cell_id": config["cell_id"], "cell_format": config["cell_format"],
               "base_parameterization": config["model"].get("parameterization_id"),
               "model": config["model"]["name"], "conditions_by_rate": config["conditions_by_rate"],
               "llm_model": llm["model"]}
    context["initial_state_mode"] = config["model"].get("initial_state_mode", "explicit_soc")
    context["nominal_capacity_ah"] = config["nominal_capacity_ah"]
    if config["model"].get("provider") == "pybamm":
        context["fixed_electrolyte_diffusivity_multiplier"] = config["model"].get("fixed_electrolyte_diffusivity_multiplier", 1.0)
    if prepared is not None:
        context["discharge_summary_by_rate"] = {}
        for rate, series in prepared.series.items():
            currents, times = series.current_a, series.time_s
            summary = {"duration_s": times[-1] - times[0], "samples": len(times), "current_source": series.current_source}
            if currents is not None:
                sign = series.discharge_current_sign
                summary["discharged_charge_ah"] = sum((a + b) * .5 * (right - left) * sign / 3600
                    for a, b, left, right in zip(currents, currents[1:], times, times[1:]))
                if all(value == currents[0] for value in currents):
                    summary["constant_discharge_current_a"] = currents[0] * sign
            context["discharge_summary_by_rate"][rate] = summary
    parameterization_file = store.path / "parameterization.json"
    if parameterization_file.exists():
        values = read_json(parameterization_file)["values"]
        context["nominal_parameter_values_from_reference"] = {spec.name: values[spec.name] for spec in prepared.space.specs} if prepared is not None else {}
    return LLMClient(build_transport(llm, store),
                     context=context, run_store=store, min_diversity_distance=llm["min_diversity_distance"])


def build_transport(settings: dict, store=None):
    common = {"endpoint": settings.get("endpoint") or "", "api_key_env": settings.get("api_key_env") or "",
              "timeout_s": settings.get("timeout_s", 0), "run_store": store}
    if settings.get("transport") == "openai_chat_completions":
        return ChatCompletionsTransport(**common, model=settings.get("model"),
                                        max_tokens=settings.get("max_tokens"), json_mode=settings.get("json_mode"),
                                        thinking=settings.get("thinking"))
    if settings.get("transport") != "structured_json_service":
        raise ValueError("unsupported configured LLM transport")
    return HttpJsonTransport(**common)


def run_experiment(config: dict, output, *, base_dir=None, command="run_experiment", simulator=None) -> dict:
    report, prepared = prepare_experiment(config, base_dir=base_dir)
    store = RunStore(output, config, data_hashes=prepared.input_hashes if prepared else {}, command=command)
    store.write_json("preflight.json", report)
    if prepared is None:
        store.finish("preflight_failed", {"errors": report["errors"]})
        raise ExperimentFailure("; ".join(report["errors"]), store.path, "preflight_failed")
    start = time.perf_counter()
    try:
        if prepared.workbook:
            target = store.path / "inputs" / "raw.xlsx"
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(prepared.workbook, target)
            if sha256_file(target) not in prepared.input_hashes.values():
                raise ValueError("archived workbook copy differs from the validated input")
        if prepared.initial_plan:
            target = store.path / "inputs" / "initial-plan.json"
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(prepared.initial_plan, target)
            if sha256_file(target) != config["optimization"]["initial_candidates_evidence"]["sha256"]:
                raise ValueError("archived shared initial plan differs from the validated evidence")
            if prepared.initial_evaluations is not None:
                source_index = Path(read_json(target)["screening_directory"]) / "source-sha256.json"
                shutil.copy2(source_index, store.path / "inputs/cache-source-sha256.json")
                if sha256_file(store.path / "inputs/cache-source-sha256.json") != prepared.initial_evaluations[0].cache_provenance["source_manifest_sha256"]:
                    raise ValueError("cached source snapshot index changed during archiving")
                for index, source in enumerate(read_json(target)["evaluation_sources"]):
                    copied = store.path / "inputs" / f"cache-record-{index:06d}.json"
                    shutil.copy2(source["path"], copied)
                    if sha256_file(copied) != source["sha256"]:
                        raise ValueError("cached source record changed during archiving")
        if simulator is not None and config["run_kind"] != "synthetic_software_smoke_only":
            raise ValueError("simulator overrides are allowed only in explicit synthetic tests")
        if prepared.screening_history is not None:
            prepared.screening_history.archive(store)
        backend = simulator or build_backend(prepared)
        if hasattr(backend, "save_parameterization"):
            backend.save_parameterization(store)
        options = config["optimization"]
        if prepared.initial_evaluations is not None and config["model"]["provider"] == "pybamm":
            expected = read_json(prepared.initial_plan).get("parameterization_fingerprint")
            if not expected or digest_value(read_json(store.path / "parameterization.json")["values"]) != expected:
                raise ValueError("cached initialization fixed parameterization differs from the execution backend")
        gate = InventoryGate.from_parameters(backend.base_parameters(), prepared.series) if options.get("inventory_feasibility_filter") else None
        if gate:
            store.write_json("inventory-gate.json", asdict(gate))
        evaluator = FourRateEvaluator(prepared.space, backend, max_rate_attempts=options["max_rate_attempts"], event_callback=store.append_event)
        optimizer = Optimizer(
            prepared.space, evaluator, prepared.series, llm=build_llm(config, store, prepared=prepared), run_store=store,
            seed=options["seed"], initial_llm_count=options["warm_start_llm_points"],
            initial_sobol_count=options["sobol_points"], candidate_pool_size=options["candidate_pool_size"],
            mc_draws=options["composite_ei_draws"], gp_sweeps=options["gp_sweeps"],
            llm_warm_start_enabled=options.get("llm_warm_start_enabled", options["llm_enabled"]),
            llm_gp_groups_enabled=options.get("llm_gp_groups_enabled", options["llm_enabled"]),
            initial_candidates=options.get("initial_candidates"),
            initial_candidates_source=options.get("initial_candidates_source"),
            strict_llm_tasks=options.get("strict_llm_tasks", False),
            initial_evaluations=prepared.initial_evaluations,
            candidate_filter=gate.check if gate else None,
            bo_repair=options.get("bo_repair"),
            surrogate_mode=options.get("surrogate_mode", "per_rate"),
            llm_informed_enabled=options.get("llm_informed_enabled", False),
            llm_informed=options.get("llm_informed"),
            screening_history=prepared.screening_history,
        )
        summary = optimizer.optimize(options["total_candidate_budget"])
        audit_started = time.perf_counter()
        audit = audit_run(store.path, deep=config["run_kind"] == "synthetic_software_smoke_only", require_terminal=False)
        store.write_json("audit-timing.json", {"elapsed_s": time.perf_counter()-audit_started, "deep": audit["deep"]})
        store.write_json("result-audit.json", audit)
        if not audit["passed"]:
            raise RuntimeError("post-run consistency audit failed; see result-audit.json")
        status = "completed_with_failures" if summary["candidate_failed"] or summary.get("llm_informed",{}).get("error_iterations",0) else "completed"
        store.finish(status, summary)
        return {"run_directory": str(store.path), "run_kind": config["run_kind"], "status": status, "audit_passed": audit["passed"], **summary}
    except BaseException as exc:
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        diagnostic = {"error_type": type(exc).__name__, "message": str(exc),
                      "traceback": traceback.format_exc(), "elapsed_s": time.perf_counter() - start}
        store.write_json("failure.json", diagnostic)
        store.finish(status, diagnostic)
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise ExperimentFailure(str(exc), store.path, status) from exc


def run_status(path) -> dict:
    path = Path(path).resolve()
    manifest = read_json(path / "manifest.json")
    events = [json.loads(line) for line in (path / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    attempts = [read_json(p) for p in sorted((path / "attempts").glob("*.json"))]
    terminal = read_json(path / "terminal.json") if (path / "terminal.json").exists() else None
    total = manifest.get("config", {}).get("optimization", {}).get("total_candidate_budget", 0) or 0
    active = None
    progress = {}
    for event in events:
        if event["type"] == "optimization_started":
            total = event["budget"]
        elif event["type"] == "candidate_started":
            active = event["candidate_id"]
        elif event["type"] == "candidate_attempt":
            active = None
        elif event["type"] == "progress":
            progress = event
    running = int(active is not None and terminal is None)
    return {"run_directory": str(path), "status": terminal["status"] if terminal else "running_or_interrupted",
            "total_candidates": total, "completed_candidates": len(attempts),
            "successful_candidates": sum(r["valid"] for r in attempts),
            "failed_candidates": sum(not r["valid"] for r in attempts),
            "running_candidates": running, "pending_candidates": max(0, total-len(attempts)-running),
            "rate_solve_attempts": sum(len(q.get("attempts", [])) for r in attempts if not r.get("cache_provenance") for q in r["rates"]),
            "failed_rate_attempts": sum(not a["valid"] for r in attempts if not r.get("cache_provenance") for q in r["rates"] for a in q.get("attempts", [])),
            "cache_hits": sum(bool(r.get("cache_provenance")) for r in attempts),
            "completed_by_rate": {rate: sum(q["rate"] == rate for r in attempts for q in r["rates"]) for rate in RATE_ORDER},
            "candidate_rate_per_min": terminal["summary"].get("candidate_evaluations_per_min", progress.get("candidate_rate_per_min")) if terminal else progress.get("candidate_rate_per_min"),
            "eta_minutes": 0 if terminal and terminal["status"] in {"completed", "completed_with_failures"} else progress.get("eta_minutes"),
            "activity_is_confirmed": terminal is not None,
            "note": "without a terminal record, running status is the last recorded state and may reflect an interrupted process" if terminal is None else None}


def run_fixed_candidates(config: dict, output, candidates, *, mode: str, base_dir=None,
                         archived_series=None, source_info=None, source_hashes=None, simulator=None) -> dict:
    """Shared small-case/recovery path: explicit candidates, four rates, no GP or LLM."""
    if mode not in {"smoke", "recovery"} or not candidates:
        raise ValueError("fixed evaluation needs smoke/recovery mode and at least one explicit candidate")
    config = json.loads(json.dumps(config))
    original_config = json.loads(json.dumps(config))
    original_hash = digest_value(config)
    config["optimization"]["llm_enabled"] = False
    for name in ("llm_warm_start_enabled", "llm_gp_groups_enabled", "llm_informed_enabled"):
        if name in config["optimization"]:
            config["optimization"][name] = False
    # Fixed candidate replay does not initialize or optimize. Keep the original
    # provenance separately; no cached initialization plan is executed here.
    for name in ("initial_candidates", "initial_candidates_source", "initial_candidates_evidence"):
        config["optimization"].pop(name, None)
    config["optimization"].update(warm_start_llm_points=0, sobol_points=2)
    config["optimization"].pop("reuse_screening_history", None)
    report, prepared = prepare_experiment(config, base_dir=base_dir, archived_series=archived_series)
    store = RunStore(output, config, data_hashes=source_hashes or (prepared.input_hashes if prepared else {}), command=f"llmbo-para {mode} explicit-candidates")
    store.write_json("preflight.json", report)
    store.write_json("original-config.json", original_config)
    store.write_json("execution-mode.json", {"mode": mode, "original_config_sha256": original_hash,
                                             "llm_calls": 0, "candidate_count": len(candidates)})
    if source_info:
        store.write_json("replay-source.json", source_info)
    if prepared is None:
        store.finish("preflight_failed", report)
        raise ExperimentFailure("fixed-candidate preflight failed", store.path, "preflight_failed")
    started = time.perf_counter()
    try:
        if simulator is not None and config["run_kind"] != "synthetic_software_smoke_only":
            raise ValueError("simulator overrides are restricted to synthetic tests")
        backend = simulator or build_backend(prepared)
        if hasattr(backend, "save_parameterization"):
            backend.save_parameterization(store)
        if prepared.workbook:
            target = store.path / "inputs" / "raw.xlsx"
            target.parent.mkdir(exist_ok=True)
            shutil.copy2(prepared.workbook, target)
            if sha256_file(target) not in prepared.input_hashes.values():
                raise ValueError("fixed-run raw workbook copy failed its integrity check")
        if config["optimization"].get("inventory_feasibility_filter"):
            gate = InventoryGate.from_parameters(backend.base_parameters(), prepared.series)
            store.write_json("inventory-gate.json", asdict(gate))
        evaluator = FourRateEvaluator(prepared.space, backend, max_rate_attempts=config["optimization"]["max_rate_attempts"], event_callback=store.append_event)
        inputs = {rate: asdict(series) for rate, series in prepared.series.items()}
        store.write_json("input-series.json", inputs)
        store.write_json("input-series-sha256.json", {"sha256": digest_value(inputs)})
        store.append_event({"type": "optimization_started", "budget": len(candidates), "mode": mode})
        records = []
        for index, (source_id, parameters) in enumerate(candidates):
            prepared.space.validate(parameters)
            store.write_json(f"plans/candidate-{index:06d}.json", {"candidate_id": index, "source_candidate_id": source_id, "parameters": parameters})
            store.append_event({"type": "candidate_started", "candidate_id": index, "source_candidate_id": source_id})
            result = evaluator.evaluate(parameters, prepared.series)
            store.save_attempt(index, 1, result.to_dict())
            records.append(result)
            progress = summarize_progress(len(candidates), [r.to_dict() for r in records], time.perf_counter()-started)
            store.append_event({"type": "progress", **asdict(progress)})
        good = [r for r in records if r.valid]
        best = min(good, key=lambda r: r.objective_v) if good else None
        elapsed = time.perf_counter()-started
        summary = {"candidate_budget": len(candidates), "candidate_completed": len(records), "candidate_valid": len(good),
                   "candidate_failed": len(records)-len(good), "candidate_pending": 0,
                   "best_parameters": list(best.parameters) if best else None, "best_objective_v": best.objective_v if best else None,
                   "best_rmse_v": {q.rate: q.rmse_v for q in best.rates} if best else None,
                   "elapsed_s": elapsed, "candidate_evaluations_per_min": len(records)*60/elapsed if elapsed else None,
                   "rate_solve_attempts": sum(len(q.attempts) for r in records for q in r.rates)}
        store.write_json("summary.json", summary)
        audit = audit_run(store.path, require_terminal=False)
        store.write_json("result-audit.json", audit)
        if not audit["passed"]:
            raise RuntimeError("fixed-candidate consistency audit failed")
        status = "completed_with_failures" if len(good) != len(records) else "completed"
        store.finish(status, summary)
        return {"run_directory": str(store.path), "status": status, "mode": mode, **summary}
    except BaseException as exc:
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
        failure = {"error_type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()}
        store.write_json("failure.json", failure)
        store.finish(status, failure)
        if isinstance(exc, KeyboardInterrupt):
            raise
        raise ExperimentFailure(str(exc), store.path, status) from exc
