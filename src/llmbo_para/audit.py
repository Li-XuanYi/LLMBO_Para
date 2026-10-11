"""Read-only consistency audit of an archived run; never rewrites old results."""

from pathlib import Path
import json
import math

import numpy as np

from .metrics import RATE_ORDER, rmse, mean_rate_rmse, LogRMSETransform
from .parameters import ParameterSpace
from .config import parameter_space_from_config
from .runstore import digest_value, sha256_file


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit_run(path, *, deep: bool = False, require_terminal: bool = True) -> dict:
    path = Path(path).resolve()
    issues, checks = [], []
    attempts = []
    models, acquisitions = [], []
    try:
        manifest = read_json(path / "manifest.json")
        if digest_value(manifest["config"]) != manifest["config_sha256"]:
            issues.append("manifest configuration hash mismatch")
        hashes = read_json(path / "source-sha256.json")
        if not hashes:
            issues.append("source snapshot is empty")
        for relative, expected in hashes.items():
            snapshot = (path / "source" / relative).resolve()
            if not snapshot.is_relative_to(path / "source") or not snapshot.is_file() or sha256_file(snapshot) != expected:
                issues.append(f"source snapshot hash mismatch: {relative}")
        checks.append("config_and_source_fingerprints")
        series = read_json(path / "input-series.json")
        saved_digest = read_json(path / "input-series-sha256.json")["sha256"]
        if digest_value(series) != saved_digest:
            issues.append("input series hash mismatch")
        if set(series) != set(RATE_ORDER):
            issues.append("input archive does not contain exactly the four fitting rates")
        raw = path / "inputs" / "raw.xlsx"
        if raw.exists() and sha256_file(raw) not in manifest["data_sha256"].values():
            issues.append("raw workbook copy does not match recorded input hash")
        checks.append("local_input_archive")
        options = manifest["config"]["optimization"]
        if "initial_candidates" in options and (path / "initial-set.json").exists():
            plan_file = path / "inputs/initial-plan.json"
            if not plan_file.exists() or sha256_file(plan_file) != options["initial_candidates_evidence"]["sha256"]:
                issues.append("shared initial plan copy or SHA-256 is invalid")
            else:
                plan = read_json(plan_file)
                initial = read_json(path / "initial-set.json")
                if plan.get("parameters") != options["initial_candidates"] or initial["parameters"] != options["initial_candidates"]:
                    issues.append("evaluated initial set differs from its shared plan")
                if plan.get("source") != options["initial_candidates_source"] or initial["sources"] != [plan.get("source")] * len(initial["parameters"]):
                    issues.append("initial source labels differ from shared plan provenance")
            checks.append("shared_initial_set_provenance")
        space = parameter_space_from_config(manifest["config"])
        cached_count = 0
        for index, file in enumerate(sorted((path / "attempts").glob("*.json"))):
            record = read_json(file)
            attempts.append(record)
            if record.get("cache_provenance"):
                cached_count += 1
                from .feasibility import simulation_signature
                from .evaluation import DischargeSeries
                provenance = record["cache_provenance"]
                plan_file = path / "inputs/initial-plan.json"
                cached_plan = read_json(plan_file)
                source_file = path / "inputs" / f"cache-record-{index:06d}.json"
                original = read_json(source_file)
                source = cached_plan["evaluation_sources"][index]
                source_index = path / "inputs/cache-source-sha256.json"
                cached_hashes = {key.replace("\\", "/"): value for key, value in read_json(source_index).items()}
                current_hashes = {key.replace("\\", "/"): value for key, value in hashes.items()}
                from .initialization import SIMULATION_FILES
                expected_sources = {"src/llmbo_para/"+name: current_hashes.get("src/llmbo_para/"+name) for name in SIMULATION_FILES}
                if (sha256_file(source_index) != provenance.get("source_manifest_sha256")
                    or provenance.get("simulation_source_sha256") != expected_sources
                    or any(cached_hashes.get(key) != value for key, value in expected_sources.items())):
                    issues.append(f"{file.name}: cached simulation implementation source hashes differ")
                if (index >= len(options.get("initial_candidates", [])) or not original["valid"]
                    or original.get("cache_provenance") or original != cached_plan["evaluations"][index]
                    or sha256_file(source_file) != source["sha256"]
                    or provenance["source_record_sha256"] != source["sha256"]
                    or provenance["source_record_path"] != source["path"]
                    or provenance["plan_sha256"] != sha256_file(plan_file)
                    or {key: value for key, value in record.items() if key != "cache_provenance"}
                       != {key: value for key, value in original.items() if key != "cache_provenance"}):
                    issues.append(f"{file.name}: cached record provenance or contents differ from the archived source")
                expected_signature = simulation_signature(manifest["config"], {r: DischargeSeries(**s) for r, s in series.items()})
                if cached_plan["simulation_signature"] != expected_signature or provenance["simulation_signature"] != expected_signature:
                    issues.append(f"{file.name}: cached simulation/data signature differs")
                if manifest["config"]["model"]["provider"] == "pybamm":
                    if digest_value(read_json(path / "parameterization.json")["values"]) != cached_plan.get("parameterization_fingerprint"):
                        issues.append(f"{file.name}: fixed parameterization cache fingerprint differs")
            space.validate(record["parameters"])
            rates = record["rates"]
            if [r["rate"] for r in rates] != list(RATE_ORDER):
                issues.append(f"{file.name}: rate sequence is incomplete")
                continue
            errors = {}
            for result in rates:
                rate = result["rate"]
                if result["valid"]:
                    t = np.asarray(result["simulation_time_s"], dtype=float)
                    v = np.asarray(result["simulation_voltage_v"], dtype=float)
                    measured_t = np.asarray(series[rate]["time_s"])
                    if t.ndim != 1 or v.shape != t.shape or np.any(~np.isfinite(t)) or np.any(~np.isfinite(v)) or np.any(np.diff(t) <= 0):
                        issues.append(f"{file.name}/{rate}: invalid archived simulation arrays")
                        continue
                    if measured_t[0] < t[0] or measured_t[-1] > t[-1]:
                        issues.append(f"{file.name}/{rate}: fixed time grid would require extrapolation")
                        continue
                    aligned = np.interp(measured_t, t, v)
                    if not np.allclose(aligned, result["aligned_voltage_v"], rtol=0, atol=1e-12):
                        issues.append(f"{file.name}/{rate}: stored alignment differs from original simulation")
                    error = rmse(series[rate]["voltage_v"], aligned)
                    errors[rate] = error
                    if not math.isclose(error, result["rmse_v"], rel_tol=1e-10, abs_tol=1e-12):
                        issues.append(f"{file.name}/{rate}: RMSE does not reproduce")
                elif result["rmse_v"] is not None or not result.get("reason"):
                    issues.append(f"{file.name}/{rate}: failure has a fabricated score or lacks a diagnosis")
            expected_valid = all(r["valid"] for r in rates)
            if record["valid"] != expected_valid:
                issues.append(f"{file.name}: candidate validity differs from rate validity")
            if not expected_valid and record["objective_v"] is not None:
                issues.append(f"{file.name}: invalid candidate received an objective")
            if len(errors) == 4 and not math.isclose(mean_rate_rmse(errors), record["objective_v"], rel_tol=1e-10, abs_tol=1e-12):
                issues.append(f"{file.name}: J is not the equal mean of four RMSEs")
        checks.append("four_rate_alignment_rmse_and_objective_recalculation")
        summary = read_json(path / "summary.json")
        expected_budget = manifest["config"]["optimization"]["total_candidate_budget"]
        mode_file = path / "execution-mode.json"
        if mode_file.exists():
            expected_budget = read_json(mode_file)["candidate_count"]
        if summary["candidate_budget"] != expected_budget or len(attempts) != expected_budget:
            issues.append("completed result does not contain the entire configured candidate budget")
        if summary["candidate_completed"] != len(attempts):
            issues.append("summary candidate count differs from immutable attempt files")
        valid = [r for r in attempts if r["valid"]]
        if summary["candidate_valid"] != len(valid) or summary["candidate_failed"] != len(attempts) - len(valid):
            issues.append("summary success/failure counts differ from attempts")
        if valid:
            best = min(valid, key=lambda r: r["objective_v"])
            if summary["best_parameters"] != best["parameters"] or not math.isclose(summary["best_objective_v"], best["objective_v"], abs_tol=1e-12):
                issues.append("reported best candidate is not the minimum actually evaluated J")
        elif summary.get("best_parameters") is not None or summary.get("best_objective_v") is not None:
            issues.append("a run without valid candidates reports a best result")
        if summary["rate_solve_attempts"] != sum(len(q["attempts"]) for row in attempts if not row.get("cache_provenance") for q in row["rates"]):
            issues.append("summary solver attempt count does not reproduce")
        if summary.get("cache_hits", 0) != cached_count:
            issues.append("summary cache hit count does not reproduce")
        if "rate_failed_attempts" in summary and summary["rate_failed_attempts"] != sum(not a["valid"] for row in attempts if not row.get("cache_provenance") for q in row["rates"] for a in q["attempts"]):
            issues.append("summary failed solver attempt count does not reproduce")
        if "new_candidate_evaluations" in summary and summary["new_candidate_evaluations"] != len(attempts)-cached_count:
            issues.append("summary new candidate count includes reused evaluations")
        if cached_count:
            checks.append("self_contained_cached_initial_curves_and_provenance")
        checks.append("best_candidate_and_budget_counts")
        models = sorted((path / "models").glob("*.json"))
        initial_file = path / "initial-set.json"
        initial_count = len(read_json(initial_file)["parameters"]) if initial_file.exists() else 0
        if initial_count and not models:
            issues.append("optimization result lacks archived GP states")
        if initial_count:
            expected_states = {f"after-{index:06d}.json" for index in range(initial_count, expected_budget + 1)}
            if {file.name for file in models} != expected_states:
                issues.append("optimization result lacks the complete sequence of GP states")
        expected_frozen = None
        if initial_count:
            initial_valid = [row for row in attempts[:initial_count] if row["valid"]]
            if len(initial_valid) >= 2:
                from dataclasses import asdict
                expected_frozen = {
                    rate: asdict(LogRMSETransform.fit([next(q["rmse_v"] for q in row["rates"] if q["rate"] == rate) for row in initial_valid]))
                    for rate in RATE_ORDER
                }
        frozen = None
        fixed_groups = None
        for file in models:
            state = read_json(file)
            history_count = int(file.stem.split("-")[-1])
            training = [row for row in attempts[:history_count] if row["valid"]]
            if set(state["transforms"]) != set(RATE_ORDER) or set(state["models"]) != set(RATE_ORDER):
                issues.append(f"{file.name}: GP archive does not contain all four rates")
            if expected_frozen is not None and state["transforms"] != expected_frozen:
                issues.append(f"{file.name}: output transform does not reproduce from initial valid observations")
            if frozen is None:
                frozen = state["transforms"]
            elif frozen != state["transforms"]:
                issues.append(f"{file.name}: initial output standardization was not frozen")
            groups = {rate: model["group"] for rate, model in state["models"].items()}
            if fixed_groups is None:
                fixed_groups = groups
            elif groups != fixed_groups:
                issues.append(f"{file.name}: parameter groups changed during optimization")
            for rate, model in state["models"].items():
                if options.get("llm_gp_groups_enabled") is False and (model["group"] or model["lambda"] != 0):
                    issues.append(f"{file.name}/{rate}: disabled GP LLM component still changed the kernel")
                if any(len(x) != 6 for x in model["x"]) or not 0 <= model["lambda"] <= 0.8:
                    issues.append(f"{file.name}/{rate}: model dimension or kernel mixture is invalid")
                if not model["group"] and model["lambda"] != 0:
                    issues.append(f"{file.name}/{rate}: empty group did not fall back to full-dimensional kernel")
                expected_x = [space.normalize(row["parameters"]) for row in training]
                transform = LogRMSETransform(**state["transforms"][rate])
                expected_y = [transform.transform(next(q["rmse_v"] for q in row["rates"] if q["rate"] == rate)) for row in training]
                if np.shape(model["x"]) != np.shape(expected_x) or not np.allclose(model["x"], expected_x, rtol=1e-12, atol=1e-14):
                    issues.append(f"{file.name}/{rate}: GP training inputs differ from actually valid observations")
                if np.shape(model["y"]) != np.shape(expected_y) or not np.allclose(model["y"], expected_y, rtol=1e-12, atol=1e-14):
                    issues.append(f"{file.name}/{rate}: GP labels differ from actually simulated log-RMSEs")
        checks.append("frozen_transforms_and_full_six_dimensional_gp_states" if models else "gp_not_applicable_to_fixed_candidate_run")
        acquisitions = sorted((path / "acquisition").glob("*.json"))
        gate = None
        if options.get("inventory_feasibility_filter"):
            from dataclasses import asdict
            from .feasibility import InventoryGate
            from .evaluation import DischargeSeries
            gate = InventoryGate.from_parameters(read_json(path / "parameterization.json")["values"],
                {rate: DischargeSeries(**row) for rate, row in series.items()})
            saved_gate = read_json(path / "inventory-gate.json")
            if any(not math.isclose(value,saved_gate.get(key,float("nan")),rel_tol=1e-12,abs_tol=1e-14) for key,value in asdict(gate).items()):
                issues.append("inventory feasibility coefficients differ from fixed parameterization and measured duration/current")
        if initial_count and len(acquisitions) != expected_budget - initial_count:
            issues.append("optimization result lacks complete acquisition decision records")
        for file in acquisitions:
            row = read_json(file)
            candidate_id = int(file.stem.split("-")[-1])
            scores = np.asarray(row["composite_ei"])
            selected = row["selected_index"]
            previous = [value for value in attempts[:candidate_id] if value["valid"]]
            if not previous or not math.isclose(row["best_observed_objective_v"], min(value["objective_v"] for value in previous), rel_tol=1e-12, abs_tol=1e-14):
                issues.append(f"{file.name}: EI threshold differs from the best actually completed objective")
            if not np.all(np.isfinite(scores)) or selected != int(np.argmax(scores)):
                issues.append(f"{file.name}: selected candidate does not maximize finite Composite EI")
            plan = read_json(path / "plans" / f"candidate-{candidate_id:06d}.json")
            selected_parameters = parameter_space_from_config(manifest["config"]).denormalize(row["normalized_pool"][selected])
            if gate:
                if any(not gate.check(space.denormalize(point))["feasible"] for point in row["normalized_pool"]):
                    issues.append(f"{file.name}: acquisition pool contains an analytically infeasible point")
            if not np.allclose(selected_parameters, plan["parameters"], rtol=1e-12, atol=0):
                issues.append(f"{file.name}: selected normalized input differs from evaluated parameters")
            if deep:
                from .surrogate import Matern52GP
                from .acquisition import composite_ei
                state = read_json(path / "models" / f"after-{candidate_id:06d}.json")
                fitted = {rate: Matern52GP.from_state(value) for rate, value in state["models"].items()}
                transforms = {rate: LogRMSETransform(**value) for rate, value in state["transforms"].items()}
                recomputed = composite_ei(row["normalized_pool"], fitted, transforms, row["best_observed_objective_v"], draws=row["mc_draws"], seed=row["mc_seed"])
                if not np.allclose(scores, recomputed, rtol=1e-10, atol=1e-12):
                    issues.append(f"{file.name}: posterior Monte Carlo EI does not reproduce from saved GP state")
        if acquisitions:
            checks.append("acquisition_choice" + ("_and_monte_carlo_recalculation" if deep else "_without_recomputing_all_gp_draws"))
        else:
            checks.append("acquisition_not_applicable_without_bo_iterations")
        if require_terminal and not (path / "terminal.json").exists():
            issues.append("run has no terminal lifecycle record")
    except (ValueError, KeyError, TypeError, OSError, IndexError) as exc:
        issues.append(f"audit could not verify an artifact: {type(exc).__name__}: {exc}")
    return {"run_directory": str(path), "passed": not issues, "deep": deep,
            "candidate_records_checked": len(attempts), "model_snapshots_checked": len(models),
            "acquisition_decisions_checked": len(acquisitions), "checks": checks, "issues": issues}
