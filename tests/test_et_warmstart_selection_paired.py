"""Offline gates for the paired v1/v2 WarmStart selection study."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/run_et_warmstart_selection_paired.py"
PROPOSAL = Path(
    "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/"
    "20261017_et_implementation/warmstart-v1-v2-paired-20261027/"
    "proposal/protocol-proposal.json"
)
OLD_SEEDS = {376330, 633262, 789058, 609653, 362724}


def load():
    assert SCRIPT.is_file(), "paired runner is missing"
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("run_et_warmstart_selection_paired", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_protocol(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "protocol.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def test_protocol_has_five_novel_seeds_ten_cases_and_exact_upper_bounds():
    runner = load()
    protocol = runner.load_protocol(PROPOSAL)
    assert protocol["seeds"] == [260437, 152325, 947445, 235695, 299924]
    assert not set(protocol["seeds"]) & OLD_SEEDS
    assert protocol["seed_run_order"] == [152325, 235695, 947445, 260437, 299924]
    assert [row["arm"] for row in runner.cases(protocol)] == [
        "v1", "v2", "v2", "v1", "v1", "v2", "v2", "v1", "v1", "v2"
    ]
    assert len(runner.cases(protocol)) == 10
    assert protocol["candidate_pool_size"] == 16
    assert protocol["initial_count_per_arm"] == 8
    assert protocol["new_bo_rounds_per_arm"] == 50
    assert protocol["independent_live_caps_if_released"] == {
        "DFN": 1160, "API": 15, "wall_clock_s": 28800
    }


@pytest.mark.parametrize("field,value", [
    ("seeds", [260437, 152325, 947445, 235695, 376330]),
    ("seed_run_order", [260437, 152325, 947445, 235695, 299924]),
    ("fit_rates", ["0.5C", "1C", "3C"]),
    ("candidate_pool_size", 8),
    ("new_bo_rounds_per_arm", 20),
    ("independent_live_caps_if_released", {"DFN": 1161, "API": 15, "wall_clock_s": 28800}),
])
def test_protocol_mutation_is_rejected(tmp_path, field, value):
    runner = load()
    payload = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    payload[field] = value
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, payload))


def test_arm_order_or_config_pin_mutation_is_rejected(tmp_path):
    runner = load()
    original = json.loads(PROPOSAL.read_text(encoding="utf-8"))
    changed = deepcopy(original)
    changed["arm_order_by_seed"]["152325"] = ["v2", "v1"]
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, changed))
    changed = deepcopy(original)
    changed["configs"]["152325"]["sha256"] = "0" * 64
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, changed))
    changed = deepcopy(original)
    first = next(iter(changed["source_files"]))
    changed["source_files"][first] = "0" * 64
    with pytest.raises(ValueError):
        runner.load_protocol(write_protocol(tmp_path, changed))


def test_dry_run_neither_reads_credential_nor_creates_output(tmp_path, monkeypatch):
    runner = load()
    monkeypatch.setattr(runner, "read_credential", lambda: pytest.fail("credential read"))
    destination = tmp_path / "live-run"
    result = runner.dry_run(PROPOSAL, output=destination)
    assert result["dry_run"] is True
    assert result["planned_cases"] == 10
    assert result["new_rounds"] == 500
    assert result["API"] == result["DFN"] == 0
    assert not destination.exists()


def test_parent_budget_charges_before_effect_and_rejects_duplicate_or_closed(tmp_path):
    runner = load()
    budget = runner.PairedBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64)
    budget.begin("pool-152325")
    budget.require(32)
    with pytest.raises(RuntimeError):
        budget.require(33)
    budget.charge("API", "pool-152325-request-1")
    with pytest.raises(RuntimeError):
        budget.charge("API", "pool-152325-request-1")
    budget.charge("DFN", "pool-152325-solve-1")
    assert budget.counts() == {"DFN": 1, "API": 1}
    assert 0 < budget.deadline - time.monotonic() <= 28800
    budget.finish(False)
    with pytest.raises(RuntimeError):
        budget.begin("arm-152325-v1")


def test_budget_rejects_tampered_hash_chain_and_phase_overcap(tmp_path):
    runner = load()
    path = tmp_path / "budget.jsonl"
    budget = runner.PairedBudget.start(path, protocol_sha="b" * 64)
    budget.begin("pool-152325")
    for i in range(3):
        budget.charge("API", f"pool-152325-request-{i}")
    with pytest.raises(RuntimeError):
        budget.charge("API", "pool-152325-request-overcap")
    contents = path.read_text(encoding="utf-8")
    path.write_text(contents.replace("request-0", "request-x"), encoding="utf-8")
    with pytest.raises(ValueError):
        budget.state()
