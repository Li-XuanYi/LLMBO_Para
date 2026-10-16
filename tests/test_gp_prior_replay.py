import copy
import importlib.util
import math
from pathlib import Path
import numpy as np
import pytest
from llmbo_para.metrics import LogRMSETransform, RATE_ORDER

spec = importlib.util.spec_from_file_location("prior_replay", Path(__file__).parents[1] / "scripts/compare_full_ard_priors.py")
replay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(replay)


def test_prediction_keeps_nonunit_reference_scale():
    class Model:
        params = np.array([0.] * 7 + [math.log(.1)])
        def predict(self, x): return np.array([.2]), np.array([.3])
    transform = LogRMSETransform(-3., .5, epsilon_v=.001, reference_v=2.)
    actual = transform.inverse_sample(.2)
    row = replay.prediction_row(Model(), transform, [.5] * 6, actual)
    assert row["predicted_median_v"] == pytest.approx(actual)
    assert row["absolute_error_mV"] == pytest.approx(0.)
    assert row["covered_95"]


def test_chronological_alignment_rejects_future_label_or_changed_transform(monkeypatch):
    class Space:
        def normalize(self, x): return x
    tr = {r: dict(mean=-3., std=.5) for r in RATE_ORDER}
    old = {"parameters": [.4]*6, "rates": [{"rate": r, "valid": True, "rmse_v": .05} for r in RATE_ORDER]}
    z = LogRMSETransform(**tr["1C"]).transform(.05)
    saved = {"transforms": tr, "models": {r: {"x": [[.4]*6], "y": [z]} for r in RATE_ORDER}}
    monkeypatch.setattr(replay, "initial_records", lambda source: [("initial-0", old)])
    monkeypatch.setattr(replay, "read_json", lambda path: {"transforms": tr})
    args = (Path("archive"), Space(), 8, saved, {"normalized_pool": [[.6]*6], "selected_index": 0}, {"parameters": [.6]*6})
    replay.check_replay_alignment(*args)
    altered = copy.deepcopy(saved); altered["models"]["1C"]["y"][0] += 1.
    with pytest.raises(AssertionError):
        replay.check_replay_alignment(*args[:3], altered, *args[4:])
    altered = copy.deepcopy(saved); altered["transforms"]["1C"]["mean"] += .1
    with pytest.raises(AssertionError):
        replay.check_replay_alignment(*args[:3], altered, *args[4:])
