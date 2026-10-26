"""Independent metric checks for final synthetic comparison archives."""
from copy import deepcopy
import importlib.util
import math
from pathlib import Path
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/analyze_et_three_arm_validation.py"


def load():
    assert SCRIPT.is_file(), "independent three-arm analyzer is missing"
    if str(SCRIPT.parent) not in sys.path:
        sys.path.insert(0, str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("analyze_et_three_arm_validation", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def observed_pair():
    return {"complete_pair_valid": True, "objectives": [math.sqrt(2.5), 2.0],
            "rates": [{"rate": rate,
                       "voltage": {"valid": True, "rmse_v": math.sqrt(2.5),
                                   "observed": [0., 1.], "predicted": [1., 3.], "unit": "V"},
                       "cell_temperature": {"valid": True, "rmse_k": 2.,
                                            "observed": [300., 301., 302.],
                                            "predicted": [302., 303., 304.], "unit": "K"}}
                      for rate in ("0.5C", "1C")]}


def test_independent_rmse_and_fixed_space_hv():
    analyzer = load()
    assert analyzer.verify_objectives(observed_pair(), ("0.5C", "1C")) == pytest.approx(
        (math.sqrt(2.5), 2.0))
    assert analyzer.exact_hv([(1., 3.), (2., 1.), (3., 4.)], (4., 5.)) == 10.


def test_temperature_curve_tampering_and_incomplete_pair_cannot_be_training_target():
    analyzer = load()
    damaged = deepcopy(observed_pair())
    damaged["rates"][1]["cell_temperature"]["predicted"][1] += 0.5
    with pytest.raises(ValueError):
        analyzer.verify_objectives(damaged, ("0.5C", "1C"))
    partial = deepcopy(observed_pair())
    partial["complete_pair_valid"] = False
    partial["objectives"] = None
    partial["rates"][1]["cell_temperature"].update(valid=False, rmse_k=None,
                                                       predicted=[], reason="failed")
    assert analyzer.verify_objectives(partial, ("0.5C", "1C")) is None
    partial["objectives"] = [1., 0.]
    with pytest.raises(ValueError):
        analyzer.verify_objectives(partial, ("0.5C", "1C"))
