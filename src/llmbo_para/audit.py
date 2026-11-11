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
        from .bo_repair import RepairSettings, CompletionModel, decision_scores, LocalNeighborhood, select_candidate
        repair = RepairSettings.parse(options.get("bo_repair"))
        repaired = "bo_repair" in options
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
                if result.get("feedback_source"):
                    if result.get("t_required_s") != series[rate]["time_s"][-1]:
                        issues.append(f"{file.name}/{rate}: required time differs from measured grid")
                    if result.get("t_end_s") is not None:
                        required = result["t_required_s"]
                        margin = result["t_end_s"] / required - 1 if required > 0 else None
                        if margin != result.get("coverage_margin"):
                            issues.append(f"{file.name}/{rate}: coverage margin differs from endpoint ratio")
                    if result["valid"] and result.get("full_grid_coverage") is not True:
                        issues.append(f"{file.name}/{rate}: valid rate lacks complete coverage")
                    if result.get("failure_kind") == "voltage_cutoff" and result.get("voltage_cutoff") is not True:
                        issues.append(f"{file.name}/{rate}: voltage cutoff claimed without event evidence")
                    if result.get("failure_kind") == "solver_error" and not result.get("solver_error_type"):
                        issues.append(f"{file.name}/{rate}: solver failure lacks its error type")
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
        if initial_count and not repaired:
            initial_valid = [row for row in attempts[:initial_count] if row["valid"]]
            if len(initial_valid) >= 2:
                from dataclasses import asdict
                expected_frozen = {
                    rate: asdict(LogRMSETransform.fit([next(q["rmse_v"] for q in row["rates"] if q["rate"] == rate) for row in initial_valid]))
                    for rate in RATE_ORDER
                }
        frozen = None
        fixed_groups = None
        repair_frozen, previous_models, previous_ids = {}, {}, {}
        expected_fit_counts = {rate:0 for rate in RATE_ORDER}
        for file in models:
            state = read_json(file)
            history_count = int(file.stem.split("-")[-1])
            training = [row for row in attempts[:history_count] if row["valid"]]
            if not repaired and (set(state["transforms"]) != set(RATE_ORDER) or set(state["models"]) != set(RATE_ORDER)):
                issues.append(f"{file.name}: GP archive does not contain all four rates")
            if repaired:
                from dataclasses import asdict
                if state.get("schema_version") != 2 or state.get("training_data") != repair.training_data:
                    issues.append(f"{file.name}: repaired GP schema/policy differs from configuration")
                for rate in RATE_ORDER:
                    rows = [(i, row, next(q for q in row["rates"] if q["rate"] == rate)) for i, row in enumerate(attempts[:history_count])]
                    rows = [(i, row, q) for i, row, q in rows if q["valid"] and (repair.training_data == "per_rate" or row["valid"])]
                    metadata = state["training"][rate]
                    if metadata["record_ids"] != [i for i, _, _ in rows] or metadata["count"] != len(rows):
                        issues.append(f"{file.name}/{rate}: training record IDs or count differ")
                    if len(rows) >= 2:
                        repair_frozen.setdefault(rate, asdict(LogRMSETransform.fit([q["rmse_v"] for _, _, q in rows])))
                        if rate not in state["models"]:
                            issues.append(f"{file.name}/{rate}: sufficient valid labels but GP missing")
                        expected_reuse = rate in previous_models and previous_ids.get(rate) == metadata["record_ids"]
                        expected_fit_counts[rate] += int(not expected_reuse)
                        if metadata["fit_reused"] != expected_reuse or metadata.get("cumulative_fits") != expected_fit_counts[rate]:
                            issues.append(f"{file.name}/{rate}: GP reuse or cumulative fit count differs")
                    elif rate in state["models"]:
                        issues.append(f"{file.name}/{rate}: fitted GP has insufficient labels")
                    if metadata.get("fit_reused") and state["models"].get(rate) != previous_models.get(rate):
                        issues.append(f"{file.name}/{rate}: reused GP changed its state")
                if state["transforms"] != repair_frozen:
                    issues.append(f"{file.name}: per-rate frozen transforms do not reproduce")
                if repair.feasibility_weighting:
                    classifier = CompletionModel().fit([space.normalize(r["parameters"]) for r in attempts[:history_count]], [r["valid"] for r in attempts[:history_count]])
                    if classifier.state != state["completion_model"]:
                        issues.append(f"{file.name}: joint completion classifier does not reproduce")
                previous_models = state["models"]
                previous_ids = {r:v["record_ids"] for r,v in state["training"].items()}
                neighborhood = state["neighborhood"]
                if neighborhood["settings"] != asdict(repair):
                    issues.append(f"{file.name}: local search settings differ from configuration")
                if history_count == initial_count:
                    expected_local = {"radius_after":repair.local_radius,"success_streak":0,"failure_streak":0}
                else:
                    expected_local = read_json(path/"feedback"/f"candidate-{history_count-1:06d}.json")
                if neighborhood["radius"] != expected_local["radius_after"] or any(neighborhood[key] != expected_local[key] for key in ("success_streak","failure_streak")):
                    issues.append(f"{file.name}: radius/streak state differs from previous feedback")
            if expected_frozen is not None and state["transforms"] != expected_frozen:
                issues.append(f"{file.name}: output transform does not reproduce from initial valid observations")
            if frozen is None:
                frozen = state["transforms"]
            elif not repaired and frozen != state["transforms"]:
                issues.append(f"{file.name}: initial output standardization was not frozen")
            groups = {rate: model["group"] for rate, model in state["models"].items()}
            if fixed_groups is None:
                fixed_groups = groups
            elif any(rate in fixed_groups and group != fixed_groups[rate] for rate, group in groups.items()):
                issues.append(f"{file.name}: parameter groups changed during optimization")
            fixed_groups.update(groups)
            for rate, model in state["models"].items():
                if repaired:
                    training = [row for row in attempts[:history_count] if
                        (repair.training_data == "per_rate" or row["valid"]) and next(q["valid"] for q in row["rates"] if q["rate"] == rate)]
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
            if (previous and not math.isclose(row["best_observed_objective_v"], min(value["objective_v"] for value in previous), rel_tol=1e-12, abs_tol=1e-14)) or (not previous and (not repaired or row["best_observed_objective_v"] is not None)):
                issues.append(f"{file.name}: EI threshold differs from the best actually completed objective")
            if not repaired and (not np.all(np.isfinite(scores)) or selected != int(np.argmax(scores))):
                issues.append(f"{file.name}: selected candidate does not maximize finite Composite EI")
            if repaired:
                from .evaluation import EvaluationResult, RateResult
                state = read_json(path / "models" / f"after-{candidate_id:06d}.json")
                ready = set(state["models"]) == set(RATE_ORDER) and bool(previous)
                if row.get("schema_version") != 2 or row["gp_ready"] != ready:
                    issues.append(f"{file.name}: acquisition schema or GP readiness differs")
                classifier = CompletionModel(); classifier.state = state["completion_model"]
                predicted = classifier.predict(row["normalized_pool"]) if repair.feasibility_weighting else None
                if (predicted is None) != (row["p_complete"] is None) or (predicted is not None and not np.allclose(predicted, row["p_complete"], rtol=1e-12, atol=1e-14)):
                    issues.append(f"{file.name}: joint completion probabilities differ from archived classifier")
                expected_scores, policy, fallback = decision_scores(scores, predicted, enabled=repair.feasibility_weighting)
                if not ready:
                    expected_scores = np.zeros(len(scores)); policy, fallback = "seeded_eligible_space_filling", "gp_or_complete_objective_unavailable"
                    if np.any(scores):
                        issues.append(f"{file.name}: unavailable GP generated a fabricated EI")
                proposal = row["proposal"]
                n_pool = len(row["normalized_pool"])
                if not 1 <= n_pool <= options["candidate_pool_size"] or any(len(proposal[key]) != n_pool for key in ("origins","center_record_ids","eligible")):
                    issues.append(f"{file.name}: candidate pool metadata has inconsistent lengths")
                if proposal["radius"] != state["neighborhood"]["radius"] or proposal["local_actual"] != proposal["origins"].count("local"):
                    issues.append(f"{file.name}: candidate radius or local pool count differs")
                past_keys = {tuple(round(v,12) for v in space.normalize(value["parameters"])) for value in attempts[:candidate_id]}
                keys = [tuple(round(v,12) for v in point) for point in row["normalized_pool"]]
                if len(set(keys)) != len(keys) or any(key in past_keys for key in keys):
                    issues.append(f"{file.name}: candidate pool duplicates a current or evaluated point")
                ordinal = candidate_id - initial_count + 1
                quota = repair.candidate_policy == "local" and ordinal % repair.global_every == 0
                eligible = np.asarray([o == "global" or not quota for o in proposal["origins"]])
                if proposal["global_quota"] != quota or proposal["eligible"] != eligible.tolist() or not np.any(eligible):
                    issues.append(f"{file.name}: global exploration quota/mask differs")
                if not np.allclose(row["decision_scores"], expected_scores, rtol=1e-12, atol=1e-14) or row["policy"] != policy or row["fallback"] != fallback:
                    issues.append(f"{file.name}: constrained scores or declared fallback differ")
                expected_selected = select_candidate(expected_scores,eligible,seed=options["seed"],candidate_id=candidate_id,cold_start=not ready)
                if selected != expected_selected:
                    issues.append(f"{file.name}: selected candidate differs from eligible score/fallback policy")
                for point, origin, center_id in zip(row["normalized_pool"], proposal["origins"], proposal["center_record_ids"]):
                    if origin not in {"local", "global"} or (repair.candidate_policy == "global" and origin != "global"):
                        issues.append(f"{file.name}: unexpected candidate origin")
                    if origin == "local":
                        if center_id is None or not 0 <= center_id < candidate_id or not attempts[center_id]["valid"]:
                            issues.append(f"{file.name}: local center is not a past valid point")
                        elif np.max(np.abs(np.asarray(point)-space.normalize(attempts[center_id]["parameters"]))) > proposal["radius"]+1e-12:
                            issues.append(f"{file.name}: local candidate exceeds declared radius")
                local = LocalNeighborhood(repair, options["seed"])
                for key in ("radius", "success_streak", "failure_streak"):
                    setattr(local, key, state["neighborhood"][key])
                current = attempts[candidate_id]
                result = EvaluationResult(tuple(current["parameters"]), tuple(RateResult(**q) for q in current["rates"]), current["valid"], current["objective_v"])
                feedback = local.update(result, proposal["origins"][selected])
                if feedback != read_json(path / "feedback" / f"candidate-{candidate_id:06d}.json"):
                    issues.append(f"{file.name}: local radius feedback does not reproduce")
            plan = read_json(path / "plans" / f"candidate-{candidate_id:06d}.json")
            selected_parameters = parameter_space_from_config(manifest["config"]).denormalize(row["normalized_pool"][selected])
            if gate:
                if any(not gate.check(space.denormalize(point))["feasible"] for point in row["normalized_pool"]):
                    issues.append(f"{file.name}: acquisition pool contains an analytically infeasible point")
            if not np.allclose(selected_parameters, plan["parameters"], rtol=1e-12, atol=0):
                issues.append(f"{file.name}: selected normalized input differs from evaluated parameters")
            if deep and (not repaired or row["gp_ready"]):
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
