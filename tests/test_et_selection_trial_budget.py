"""Durable parent budget contracts for a selection trial."""
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def test_budget_charges_before_side_effects_and_closes_after_all_phases(tmp_path):
    from et_selection_trial_budget import SelectionTrialBudget

    path = tmp_path / "budget.jsonl"
    budget = SelectionTrialBudget.start(
        path, protocol_sha="a" * 64,
        caps={"DFN": 2, "API": 1, "wall_clock_s": 60},
        phases={"pool": {"DFN": 2, "API": 1}, "arm": {"DFN": 0, "API": 0}},
    )
    budget.begin("pool")
    budget.require(2)
    budget.charge("DFN", "solve-1")
    with pytest.raises(RuntimeError):
        budget.charge("DFN", "solve-1")
    budget.charge("DFN", "solve-2")
    budget.charge("API", "request-1")
    with pytest.raises(RuntimeError):
        budget.charge("API", "request-2")
    budget.finish(True)
    budget.begin("arm")
    budget.finish(True)
    assert budget.state()["closed"] is True
    assert budget.counts() == {"DFN": 2, "API": 1}
    with pytest.raises(FileExistsError):
        SelectionTrialBudget.start(
            path, protocol_sha="a" * 64,
            caps={"DFN": 2, "API": 1, "wall_clock_s": 60},
            phases={"pool": {"DFN": 2, "API": 1}, "arm": {"DFN": 0, "API": 0}},
        )


def test_budget_hash_chain_detects_tampering(tmp_path):
    from et_selection_trial_budget import SelectionTrialBudget

    path = tmp_path / "budget.jsonl"
    budget = SelectionTrialBudget.start(
        path, protocol_sha="a" * 64,
        caps={"DFN": 1, "API": 0, "wall_clock_s": 60},
        phases={"pool": {"DFN": 1, "API": 0}},
    )
    budget.begin("pool")
    budget.charge("DFN", "solve-1")
    value = path.read_text()
    path.write_text(value.replace("solve-1", "solve-X"))
    with pytest.raises(ValueError, match="hash"):
        budget.state()


def test_failure_between_phases_closes_the_budget(tmp_path):
    from et_selection_trial_budget import SelectionTrialBudget

    budget = SelectionTrialBudget.start(tmp_path / "budget.jsonl", protocol_sha="a" * 64,
        caps={"DFN": 2, "API": 0, "wall_clock_s": 60},
        phases={"pool": {"DFN": 1, "API": 0}, "arm": {"DFN": 1, "API": 0}})
    budget.begin("pool")
    budget.finish(True)
    budget.abort()
    assert budget.state()["closed"] is True
    with pytest.raises(RuntimeError):
        budget.begin("arm")
