"""Cache archive replay preserves one true GP point without accepting forgeries."""
from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def cached_fixture(tmp_path):
    from test_mo_optimizer import make_optimizer

    optimizer = make_optimizer(tmp_path)
    optimizer.initialize()
    initial = list(optimizer.history)
    repeated, cached = optimizer.evaluate(initial[0].parameters)
    assert cached and len(optimizer.history) == 2
    files = sorted((optimizer.store.path / "electrothermal-evaluations").glob("*.json"))
    records = [json.loads(path.read_text(encoding="utf-8")) for path in files]
    assert records[-1]["source_kind"] == "validated_cache"
    return records, [r.evaluation_id for r in initial], [{"evaluation_id": repeated.evaluation_id, "cached": True}]


def test_real_cache_hit_is_archived_but_not_duplicated_in_history(tmp_path):
    from analyze_et_warmstart_quality_gate_trial import verify_archive_records

    records, initial, rounds = cached_fixture(tmp_path)
    by_id = verify_archive_records(records, initial, rounds)
    assert len(records) == 3 and len(by_id) == 2
    assert by_id[initial[0]]["source_kind"] == "fresh_simulation"


def test_distinct_parameters_with_equal_objectives_remain_distinct():
    from analyze_et_warmstart_quality_gate_trial import verify_archive_records

    first = {"evaluation_id": "a", "source_kind": "fresh_simulation",
             "parameters": [.2] * 6, "objectives": [.01, .02]}
    second = {"evaluation_id": "b", "source_kind": "fresh_simulation",
              "parameters": [.8] * 6, "objectives": [.01, .02]}
    by_id = verify_archive_records([first, second], ["a"],
                                   [{"evaluation_id": "b", "cached": False}])
    assert set(by_id) == {"a", "b"}


@pytest.mark.parametrize("mutation", ["changed_parameters", "unclaimed_cache", "unseen_id"])
def test_forged_or_unclaimed_cache_record_is_rejected(tmp_path, mutation):
    from analyze_et_warmstart_quality_gate_trial import verify_archive_records

    records, initial, rounds = cached_fixture(tmp_path)
    records, rounds = deepcopy(records), deepcopy(rounds)
    if mutation == "changed_parameters":
        records[-1]["parameters"][0] += .01
    elif mutation == "unclaimed_cache":
        rounds[-1]["cached"] = False
    else:
        records[-1]["evaluation_id"] = "unseen"
    with pytest.raises(ValueError):
        verify_archive_records(records, initial, rounds)
