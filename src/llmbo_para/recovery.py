"""Re-evaluate failed or unfinished planned candidates without changing old runs."""

from pathlib import Path
import copy

from .audit import read_json
from .evaluation import DischargeSeries
from .runstore import digest_value
from .workflow import run_fixed_candidates


def retry_failed(source_run, output, *, replacement_config=None, simulator=None) -> dict:
    source = Path(source_run).resolve()
    manifest = read_json(source / "manifest.json")
    original_config = manifest["config"]
    config = copy.deepcopy(replacement_config or original_config)

    def fixed_settings(value):
        value = copy.deepcopy(value)
        value.get("model", {}).pop("solver", None)
        value.get("optimization", {}).pop("max_rate_attempts", None)
        value.get("optimization", {}).pop("llm_enabled", None)
        return value

    if fixed_settings(config) != fixed_settings(original_config):
        raise ValueError("recovery may change only solver settings or max_rate_attempts; changed scientific settings require a new experiment")
    config["optimization"]["llm_enabled"] = False
    plans = {}
    if (source / "initial-set.json").exists():
        plans.update(enumerate(read_json(source / "initial-set.json")["parameters"]))
    for file in (source / "plans").glob("*.json"):
        row = read_json(file)
        plans[row["candidate_id"]] = row["parameters"]
    completed = {}
    for file in sorted((source / "attempts").glob("*.json")):
        candidate_id = int(file.name.split("-")[1])
        completed[candidate_id] = read_json(file)
    pending = [(key, value) for key, value in sorted(plans.items()) if key not in completed or not completed[key]["valid"]]
    if not pending:
        return {"source_run": str(source), "recovery_candidates": 0, "message": "no failed or unfinished planned candidates"}
    raw_series = read_json(source / "input-series.json")
    if digest_value(raw_series) != read_json(source / "input-series-sha256.json")["sha256"]:
        raise ValueError("recovery refused: archived input integrity check failed")
    series = {}
    for rate, values in raw_series.items():
        values = dict(values)
        for name in ("time_s", "voltage_v", "current_a", "temperature", "assumptions"):
            if values.get(name) is not None:
                values[name] = tuple(values[name])
        series[rate] = DischargeSeries(**values)
    info = {"source_run": str(source), "source_run_id": manifest["run_id"],
            "source_config_sha256": manifest["config_sha256"],
            "recovered_candidate_ids": [row[0] for row in pending],
            "unplanned_original_budget": max(0, original_config["optimization"]["total_candidate_budget"] - len(plans))}
    result = run_fixed_candidates(config, output, pending, mode="recovery", archived_series=series,
                                  source_info=info, source_hashes=manifest.get("data_sha256", {}), simulator=simulator)
    return {"source_run": str(source), **result}
