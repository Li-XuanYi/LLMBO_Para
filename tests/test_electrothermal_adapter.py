from types import SimpleNamespace
import numpy as np
import pytest
from electrothermal_fixtures import et_config,R3,NAMES


def test_single_solution_contains_cell_temperature_and_heat(monkeypatch):
    import pybamm
    from llmbo_para.pybamm_adapter import build_electrothermal_simulator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    calls=[]
    class Simulation:
        def __init__(self,model,**kwargs):self.model=model;self.settings=kwargs
        def solve(self,**kwargs):
            calls.append(kwargs)
            class Solution:
                termination='final time'
                def __getitem__(self,key):
                    values={'Time [s]':[0,1,2,4],'Terminal voltage [V]':[4.2,4.15,4.1,4.],
                        'Volume-averaged cell temperature [K]':[300,301,302,303],
                        'Total heating [W]':[1,1,1,1]}
                    assert key!='Surface temperature [K]'
                    return SimpleNamespace(entries=np.asarray(values[key]))
            return Solution()
    monkeypatch.setattr(pybamm,'Simulation',Simulation)
    cfg=et_config();cfg['model']['provider']='pybamm';cfg['run_kind']='synthetic_dfn'
    sim=build_electrothermal_simulator(cfg)
    trace=sim.simulate(dict(zip(NAMES,[.5,.5,1e-13,2e-13,40,.1])),make_synthetic_dataset(R3).cases['1C'])
    assert len(calls)==1 and trace.temperature_k[-1]==303
    assert trace.heat_generation_w[-1]==1 and trace.solution_id
    assert set([0,1,2,4])<=set(calls[0]['t_interp'])


def test_native_model_is_constructible_without_solving():
    import pybamm
    model=pybamm.lithium_ion.DFN(options=et_config()['model']['options'])
    assert 'Volume-averaged cell temperature [K]' in model.variables
    assert 'Total heating [W]' in model.variables
    from pybamm.models.submodels.thermal.surface.ambient import Ambient
    assert isinstance(model.submodels['surface temperature'],Ambient)
