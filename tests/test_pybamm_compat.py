"""Real eSOH initialization must work on NumPy versions that removed trapz."""
import importlib
from types import SimpleNamespace
from unittest.mock import patch
import numpy as np
import pybamm
import pytest
from llmbo_para.pybamm_compat import electrode_soh_numpy_compat


def test_real_soc_initialization_matches_trapezoid_reference_and_keeps_numpy_unchanged():
    module=importlib.import_module('pybamm.models.full_battery_models.lithium_ion.electrode_soh')
    original=module.np
    had_trapz=hasattr(np,'trapz')
    parameters=pybamm.ParameterValues('Chen2020')
    with patch.object(np,'trapz',np.trapezoid,create=True):
        expected=pybamm.lithium_ion.get_initial_stoichiometries(1,parameters)
    with electrode_soh_numpy_compat():
        actual=pybamm.lithium_ion.get_initial_stoichiometries(1,parameters)
        assert hasattr(np,'trapz')==had_trapz
    assert module.np is original and hasattr(np,'trapz')==had_trapz
    np.testing.assert_allclose(actual,expected,rtol=0,atol=1e-12)
    x,y=actual
    assert 0<x<1 and 0<y<1
    ocv=parameters['Positive electrode OCP [V]'](y)-parameters['Negative electrode OCP [V]'](x)
    voltage=float(ocv.evaluate() if hasattr(ocv,'evaluate') else ocv)
    # The eSOH root solver has its own tolerance; 0.1 mV is a separate physical sanity check.
    assert abs(voltage-parameters['Upper voltage cut-off [V]'])<1e-4


def test_compatibility_restores_module_namespace_after_exception():
    module=importlib.import_module('pybamm.models.full_battery_models.lithium_ion.electrode_soh')
    original=module.np
    with pytest.raises(RuntimeError,match='probe'):
        with electrode_soh_numpy_compat():
            raise RuntimeError('probe')
    assert module.np is original


def test_older_numpy_namespace_needs_no_bridge():
    module=importlib.import_module('pybamm.models.full_battery_models.lithium_ion.electrode_soh')
    legacy=SimpleNamespace(trapz=object())
    with patch.object(module,'np',legacy):
        with electrode_soh_numpy_compat() as active:
            assert not active and module.np is legacy
