"""Derive two auditable WarmStart plans from one immutable evaluated pool."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path


RULES = {"v1": "pareto_maximin_v1", "v2": "pareto_core_spacefill_v2"}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _physical_record(raw: dict) -> dict:
    return {key: raw[key] for key in (
        "evaluation_id", "parameters", "parameter_profile", "fit_rates",
        "data_signature", "rates", "objectives", "objective_components",
        "complete_pair_valid", "costs",
    )}


def derive_paired_plans(pool_run: Path, *, configs: dict[str, dict], out: Path) -> dict[str, dict]:
    """Rebind only rule-specific initialization evidence; never repeat or edit a solve."""
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.electrothermal_evaluation import result_from_dict
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    from llmbo_para.electrothermal_provenance import (
        candidate_key, load_initial_plan, verify_evaluation, write_initial_plan,
    )
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    pool_run = Path(pool_run).resolve(strict=True)
    out = Path(out)
    if set(configs) != set(RULES):
        raise ValueError("exactly v1 and v2 configurations required")
    v1, v2 = deepcopy(configs["v1"]), deepcopy(configs["v2"])
    if (v1["optimization"]["warmstart"].get("selection_rule") != RULES["v1"]
            or v2["optimization"]["warmstart"].get("selection_rule") != RULES["v2"]):
        raise ValueError("paired selection rules differ from protocol")
    v1_as_v2 = deepcopy(v1)
    v1_as_v2["optimization"]["warmstart"]["selection_rule"] = RULES["v2"]
    if _digest(v1_as_v2) != _digest(v2):
        raise ValueError("paired configurations differ beyond selection rule")
    prepared = {}
    for arm, config in (("v1", v1), ("v2", v2)):
        report, current = prepare_electrothermal_experiment(config, base_dir=pool_run.parent)
        if not report["ready"] or current is None:
            raise ValueError(f"{arm} configuration preflight failed")
        prepared[arm] = current
    first, second = prepared["v1"].signatures, prepared["v2"].signatures
    if (any(getattr(first, name) != getattr(second, name)
            for name in ("data", "model_evaluation", "evaluation_protocol", "source"))
            or first.initialization_compatibility == second.initialization_compatibility):
        raise ValueError("paired physical signatures differ or selection signatures collide")
    audit = audit_electrothermal_run(pool_run, deep=True)
    if audit.get("passed") is not True:
        raise ValueError("source pool deep audit failed")
    source_plan = pool_run / "initial-plan.json"
    source_selection = pool_run / "warmstart-selection.json"
    if not source_plan.is_file() or not source_selection.is_file():
        raise ValueError("source pool initialization artifacts absent")
    loaded = load_initial_plan(source_plan, space=prepared["v1"].space,
                               dataset=prepared["v1"].dataset, signatures=first,
                               expected_selection_rule=RULES["v1"])
    selection = json.loads(source_selection.read_text(encoding="utf-8"))
    if selection.get("rule") != RULES["v1"] or selection.get("status") != "completed":
        raise ValueError("source pool is not completed v1 screening")
    evidence = loaded.history_evidence
    if evidence is None or evidence.get("origin_run_id") != pool_run.name:
        raise ValueError("source screening origin differs")
    raw_pool = evidence["screening_records"]
    if len(raw_pool) != 16 or selection.get("evaluations") != 16:
        raise ValueError("exactly 16 actual screened candidates required")
    pool = [result_from_dict(raw) for raw in raw_pool]
    keys = set()
    for record in pool:
        verify_evaluation(record, prepared["v1"].dataset, require_complete=True)
        key = candidate_key(record.parameters, record.parameter_profile, first)
        if key in keys:
            raise ValueError("duplicate physical point in common pool")
        keys.add(key)
    evaluation_paths = sorted((pool_run / "electrothermal-evaluations").glob("*.json"))
    if len(evaluation_paths) != 16:
        raise ValueError("common pool's archived evaluation count differs")
    archived = {}
    for path in evaluation_paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        ident = raw["evaluation_id"]
        if ident in archived:
            raise ValueError("duplicate archived evaluation ID")
        archived[ident] = raw
    if set(archived) != {record.evaluation_id for record in pool}:
        raise ValueError("common pool's archived IDs differ")
    for raw in raw_pool:
        if _digest(_physical_record(raw)) != _digest(_physical_record(archived[raw["evaluation_id"]])):
            raise ValueError("common pool's archived curves or costs differ")
    first_details = warmstart_selection_details(
        pool, space=prepared["v1"].space, count=8,
        objective_scales=v1["optimization"]["objective_scales"],
        rho_aug=v1["optimization"]["rho_aug"], rule=RULES["v1"],
    )
    if first_details["selected_ids"] != selection.get("selected_ids"):
        raise ValueError("v1 source selection does not reproduce")
    out.mkdir(parents=True, exist_ok=False)
    result = {"pool_size": 16, "shared_costs": evidence["costs"],
              "pool_run": str(pool_run)}
    source_files = [source_plan, source_selection, *evaluation_paths]
    source_hashes = {str(path): _sha(path) for path in source_files}
    result["pool_sha256"] = _digest(source_hashes)
    for arm, config in (("v1", v1), ("v2", v2)):
        current = prepared[arm]
        rule = RULES[arm]
        signed_pool = [replace(record, signatures=asdict(current.signatures)) for record in pool]
        replay = warmstart_selection_details(
            signed_pool, space=current.space, count=8,
            objective_scales=config["optimization"]["objective_scales"],
            rho_aug=config["optimization"]["rho_aug"], rule=rule,
        )
        if len(replay["selected_ids"]) != 8:
            raise ValueError("paired plan has fewer than eight complete inputs")
        selected_by_id = {record.evaluation_id: record for record in signed_pool}
        selected = [selected_by_id[ident] for ident in replay["selected_ids"]]
        bound_evidence = {
            "origin_run_id": evidence["origin_run_id"],
            "screening_records": [record.to_dict() for record in signed_pool],
            "selection": {**selection, **replay},
            "cost_events": deepcopy(evidence["cost_events"]),
            "costs": deepcopy(evidence["costs"]),
        }
        path = out / f"{arm}-initial-plan.json"
        write_initial_plan(path, selected, signatures=current.signatures,
                           history_evidence=bound_evidence)
        checked = load_initial_plan(path, space=current.space,
                                    dataset=current.dataset, signatures=current.signatures,
                                    expected_selection_rule=rule)
        result[arm] = {"path": str(path), "sha256": _sha(path),
                       "plan_sha256": checked.plan_sha256,
                       "selected_ids": replay["selected_ids"]}
    manifest = {"schema_version": 1, "pool_run": str(pool_run),
                "source_files": source_hashes, "pool_sha256": result["pool_sha256"],
                "shared_costs": result["shared_costs"],
                "v1": result["v1"], "v2": result["v2"]}
    manifest_path = out / "paired-plan-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, allow_nan=False),
                             encoding="utf-8")
    result["manifest_path"] = str(manifest_path)
    result["manifest_sha256"] = _sha(manifest_path)
    return result
