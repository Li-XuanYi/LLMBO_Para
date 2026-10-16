"""Validated, separately costed supplementary screening for four-GP training.

The accepted initial points stay in the normal run ledger. Only the remaining
screening records are imported here, so neither labels nor costs are duplicated.
"""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import shutil

import numpy as np

from .config import parameter_space_from_config
from .evaluation import CallableSimulator, EvaluationResult, FourRateEvaluator, RateResult
from .feasibility import simulation_signature
from .initialization import validated_simulation_sources
from .metrics import RATE_ORDER
from .runstore import digest_value, sha256_file


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def validate_record(record, config, series):
    """Recompute all available complete-rate labels; never extrapolate a failure."""
    space = parameter_space_from_config(config)
    point = space.validate(record["parameters"])
    if record.get("cache_provenance") or [q["rate"] for q in record["rates"]] != list(RATE_ORDER):
        raise ValueError("screening history must contain original ordered four-rate records")
    rates = {q["rate"]: q for q in record["rates"]}
    simulator = CallableSimulator(lambda p, s: (rates[s.rate]["simulation_time_s"], rates[s.rate]["simulation_voltage_v"]))
    checked = FourRateEvaluator(space, simulator).evaluate(point, series)
    if checked.valid != record["valid"]:
        raise ValueError("screening history validity does not reproduce from its curves")
    if not record["valid"] and record["objective_v"] is not None:
        raise ValueError("incomplete screening candidate has a fabricated joint objective")
    if record["valid"] and not math.isclose(checked.objective_v, record["objective_v"], rel_tol=1e-10, abs_tol=1e-12):
        raise ValueError("screening history joint objective does not reproduce")
    for actual in checked.rates:
        saved = rates[actual.rate]
        if actual.valid != saved["valid"]:
            raise ValueError("screening history rate validity differs")
        if actual.valid:
            if (not math.isclose(actual.rmse_v, saved["rmse_v"], rel_tol=1e-10, abs_tol=1e-12)
                or not np.allclose(actual.aligned_voltage_v, saved["aligned_voltage_v"], rtol=0, atol=1e-12)
                or set(saved["residual_summary"]) != set(actual.residual_summary)
                or any(not math.isclose(saved["residual_summary"][k], v, rel_tol=1e-10, abs_tol=1e-12) for k, v in actual.residual_summary.items())):
                raise ValueError("screening history rate labels or residuals do not reproduce")
        elif saved["rmse_v"] is not None:
            raise ValueError("incomplete screening rate has a fabricated RMSE")
        if saved.get("feedback_source") == "structured_trace":
            required = series[actual.rate].time_s[-1]
            end = saved["simulation_time_s"][-1] if saved["simulation_time_s"] else None
            if saved["t_required_s"] != required or saved["t_end_s"] != end:
                raise ValueError("screening coverage summary differs from the original trace")
            if saved.get("failure_kind") == "voltage_cutoff":
                cutoff = config["conditions_by_rate"][actual.rate]["voltage_cutoff_v"]
                if (end is None or end >= required or not saved.get("voltage_cutoff")
                    or "Minimum voltage" not in str(saved.get("termination"))
                    or not math.isclose(saved["simulation_voltage_v"][-1], cutoff, abs_tol=1e-5)):
                    raise ValueError("screening voltage cutoff lacks matching event/trace evidence")
    return EvaluationResult(point, tuple(RateResult(**q) for q in record["rates"]), record["valid"], record["objective_v"])


@dataclass
class ScreeningHistory:
    results: list
    sources: list
    catalog: dict

    def archive(self, store):
        for source in self.sources:
            target = store.path / source["artifact"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                raise ValueError("screening history artifact already exists")
            shutil.copy2(source["source_path"], target)
            if sha256_file(target) != source["sha256"]:
                raise ValueError("screening history source changed while archiving")
        store.write_json("screening-history/catalog.json", self.catalog)


def load_screening_history(config, series, plan, plan_path):
    expected_signature = simulation_signature(config, series)
    initial = {tuple(p): (r, s) for p, r, s in zip(plan["parameters"], plan["evaluations"], plan["evaluation_sources"])}
    segments, all_records, visited = [], [], set()

    def visit(current, current_path):
        directory = Path(current["screening_directory"]).resolve()
        if directory in visited:
            raise ValueError("cyclic screening history lineage")
        visited.add(directory)
        if current["simulation_signature"] != expected_signature or current.get("parameterization_fingerprint") != plan.get("parameterization_fingerprint"):
            raise ValueError("screening history simulation/parameterization differs")
        fingerprints, index_hash = validated_simulation_sources(directory)
        prior = current.get("prior_candidate_evaluations", 0)
        if prior:
            previous_path = directory / "inputs/resume-plan.json"
            lineage = read(directory / "resume-lineage.json")
            if sha256_file(previous_path) != lineage["plan_sha256"]:
                raise ValueError("screening resume plan hash differs")
            previous = read(previous_path)
            if previous["screening_cost"]["candidate_evaluations"] != prior:
                raise ValueError("screening prior candidate cost differs")
            visit(previous, previous_path)
        files = sorted((directory / "attempts").glob("*.json"))
        expected_count = current["screening_cost"]["candidate_evaluations"] - prior
        if len(files) != expected_count or [p.name for p in files] != [f"candidate-{i:06d}-attempt-001.json" for i in range(prior, prior + expected_count)]:
            raise ValueError("screening attempt sequence/cost is incomplete")
        for file in files:
            all_records.append((file, read(file)))
        segments.append({"plan_sha256": sha256_file(current_path), "directory": str(directory),
            "record_count": len(files), "simulation_source_sha256": fingerprints,
            "source_manifest_sha256": index_hash})

    visit(plan, plan_path)
    quality = 'quality_selection' in plan
    if quality:
        from .quality_initialization import validate_quality_selection
        validate_quality_selection(plan, [record for _, record in all_records], parameter_space_from_config(config))
    results, sources, seen, found_initial = [], [], set(), set()
    rate_solves = 0
    for candidate_id, (file, record) in enumerate(all_records):
        point = tuple(record["parameters"])
        if point in seen:
            raise ValueError("duplicate evaluated screening parameters")
        seen.add(point)
        checked = validate_record(record, config, series)
        rate_solves += sum(len(q["attempts"]) for q in record["rates"])
        if point in initial:
            expected, source = initial[point]
            if expected != record or sha256_file(file) != source["sha256"]:
                raise ValueError("screening initial record differs from the initial plan")
            found_initial.add(point)
            continue
        if checked.valid and not quality:
            raise ValueError("screening has a valid point outside the declared initial set")
        source = {"source_path": str(file.resolve()), "sha256": sha256_file(file),
            "artifact": f"screening-history/record-{len(results):06d}.json"}
        if quality:
            source['screening_candidate_id'] = candidate_id
        results.append(checked)
        sources.append(source)
    cost = plan["screening_cost"]
    if (found_initial != set(initial) or len(all_records) != cost["candidate_evaluations"]
        or rate_solves != cost["rate_solve_attempts"]):
        raise ValueError("screening history does not account for the full initial set/cost")
    catalog = {"schema_version": 2 if quality else 1, "plan_sha256": sha256_file(plan_path),
        "simulation_signature": expected_signature, "parameterization_fingerprint": plan.get("parameterization_fingerprint"),
        "attributed_screening_cost": cost, "initial_points_excluded": len(initial),
        "reused_failed_candidates": sum(not r.valid for r in results), "new_dfn_solves": 0,
        "partial_rate_labels": {r: sum(q.valid for record in results for q in record.rates if q.rate == r) for r in RATE_ORDER},
        "sources": sources, "segments": segments}
    if quality:
        catalog.update(reused_valid_candidates=sum(r.valid for r in results), reused_candidates=len(results))
    return ScreeningHistory(results, sources, catalog)


def audited_history(path, config, series, source_hashes):
    """Offline self-contained audit, without reading the old screening directory."""
    path = Path(path)
    catalog = read(path / "screening-history/catalog.json")
    plan_file = path / "inputs/initial-plan.json"
    plan = read(plan_file)
    if (catalog["plan_sha256"] != sha256_file(plan_file)
        or catalog["simulation_signature"] != simulation_signature(config, series)
        or catalog["parameterization_fingerprint"] != plan.get("parameterization_fingerprint")
        or catalog["attributed_screening_cost"] != plan["screening_cost"]):
        raise ValueError("archived screening history provenance/cost differs")
    source_hashes = {k.replace("\\", "/"): v for k, v in source_hashes.items()}
    for segment in catalog["segments"]:
        if any(source_hashes.get(k) != v for k, v in segment["simulation_source_sha256"].items()):
            raise ValueError("archived screening simulation implementation differs")
    initial = {tuple(p) for p in plan["parameters"]}
    seen, results = set(initial), []
    for i, source in enumerate(catalog["sources"]):
        expected = f"screening-history/record-{i:06d}.json"
        if source["artifact"] != expected or sha256_file(path / expected) != source["sha256"]:
            raise ValueError("archived screening source hash/path differs")
        record = read(path / expected)
        result = validate_record(record, config, series)
        if (result.valid and catalog.get('schema_version',1) != 2) or result.parameters in seen:
            raise ValueError("archived supplementary history repeats an initial/valid point")
        seen.add(result.parameters)
        results.append(record)
    count = len(results)
    rate_solves = sum(len(q["attempts"]) for record in results + plan["evaluations"] for q in record["rates"])
    partial = {r: sum(q["valid"] for record in results for q in record["rates"] if q["rate"] == r) for r in RATE_ORDER}
    if (sum(not r['valid'] for r in results) != catalog["reused_failed_candidates"] or catalog["initial_points_excluded"] != len(initial)
        or count + len(initial) != plan["screening_cost"]["candidate_evaluations"]
        or rate_solves != plan["screening_cost"]["rate_solve_attempts"]
        or partial != catalog["partial_rate_labels"] or catalog["new_dfn_solves"] != 0):
        raise ValueError("archived screening labels/cost totals differ")
    if catalog.get('schema_version',1) == 2:
        cost = catalog['attributed_screening_cost']
        if catalog.get('reused_valid_candidates') != sum(r['valid'] for r in results) or catalog.get('reused_candidates') != count:
            raise ValueError('archived quality screening success/failure counts differ')
        from .quality_initialization import validate_quality_selection
        ordered = dict(zip(plan['quality_selection']['selected_candidate_ids'], plan['evaluations']))
        for source,record in zip(catalog['sources'],results):
            candidate_id = source.get('screening_candidate_id')
            if type(candidate_id) is not int or candidate_id in ordered:
                raise ValueError('archived quality selection record IDs duplicate or are missing')
            ordered[candidate_id] = record
        if set(ordered) != set(range(cost['candidate_evaluations'])):
            raise ValueError('archived quality selection candidate IDs/cost differ')
        validate_quality_selection(plan,[ordered[i] for i in range(len(ordered))],parameter_space_from_config(config))
    return results, catalog
