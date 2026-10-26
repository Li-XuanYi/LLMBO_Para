"""The three arms must retain distinct initialization and API semantics."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/et_three_arm_validation_worker.py"
PROPOSAL = Path(
    "D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/"
    "20261017_et_implementation/three-arm-50round-proposal-20261026"
)


def load():
    assert SCRIPT.is_file(), "three-arm worker is missing"
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("et_three_arm_validation_worker", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("arm,mode,api", [
    ("bo", "parego", 0), ("warmstart_only", "warmstart_only", 0),
    ("full_llmbo_mo", "full_llmbo_mo", 50),
])
def test_formal_mode_has_fifty_new_rounds_and_only_full_has_region_api(arm, mode, api):
    worker = load()
    base = json.loads((PROPOSAL / "seed-376330.disabled-config.json").read_text())
    original = deepcopy(base)
    config = worker.config_for(base, kind="arm", arm=arm, seed=376330,
                               remaining=1000, initial_plan={"path": "signed.json", "sha256": "a" * 64})
    assert base == original
    assert config["optimization"]["mode"] == mode
    assert config["optimization"]["total_candidate_budget"] == 58
    assert config["budgets"]["max_solver_calls"] == 100
    assert config["budgets"]["max_llm_requests"] == api
    assert config["llm"]["enabled"] is (api > 0)
    assert config["data"] == base["data"] and config["model"] == base["model"]


@pytest.mark.parametrize("kind,arm,dfn,api", [
    ("numeric_initialization", "bo", 16, 0),
    ("warmstart_initialization", "warmstart_only", 32, 3),
])
def test_initialization_has_explicit_independent_cost(kind, arm, dfn, api):
    worker = load()
    base = json.loads((PROPOSAL / "seed-376330.disabled-config.json").read_text())
    config = worker.config_for(base, kind=kind, arm=arm, seed=376330,
                               remaining=1000, initial_plan=None)
    assert config["optimization"]["total_candidate_budget"] == 8
    assert config["budgets"]["max_solver_calls"] == dfn
    assert config["budgets"]["max_llm_requests"] == api
    assert config["llm"]["enabled"] is (api > 0)


def test_wrong_arm_and_kind_do_not_become_full_region():
    worker = load()
    base = json.loads((PROPOSAL / "seed-376330.disabled-config.json").read_text())
    for bad in ("plain", "old_full", "volt_only"):
        with pytest.raises(ValueError):
            worker.config_for(base, kind="arm", arm=bad, seed=376330,
                              remaining=1000, initial_plan={"path": "x", "sha256": "a" * 64})
