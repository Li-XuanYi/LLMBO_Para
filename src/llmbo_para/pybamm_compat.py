"""Scoped compatibility for PyBaMM eSOH on NumPy >= 2.4.

PyBaMM 25.10.2 calls the removed np.trapz while computing an eSOH energy
integral. NumPy's supported replacement is trapezoid, with the same arguments.
Only the eSOH module's numpy reference is bridged, then restored. The global
NumPy module and third-party installed files are never modified.
"""
from contextlib import contextmanager
import importlib
from threading import RLock

_lock=RLock()


class _TrapezoidNamespace:
    def __init__(self,numpy_module):self._numpy=numpy_module

    def __getattr__(self,name):
        if name=='trapz':return self._numpy.trapezoid
        return getattr(self._numpy,name)


@contextmanager
def electrode_soh_numpy_compat():
    """Bridge only the missing eSOH API during a serial SOC initialization."""
    pybamm=importlib.import_module('pybamm')
    if getattr(pybamm,'__version__',None)!='25.10.2':
        yield False
        return
    module=importlib.import_module('pybamm.models.full_battery_models.lithium_ion.electrode_soh')
    with _lock:
        original=module.np
        if hasattr(original,'trapz'):
            yield False
            return
        if not hasattr(original,'trapezoid'):
            raise RuntimeError('NumPy lacks the supported trapezoid integration API')
        module.np=_TrapezoidNamespace(original)
        try:
            yield True
        finally:
            module.np=original
