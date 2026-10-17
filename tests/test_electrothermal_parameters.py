import pytest
from llmbo_para.config import parameter_space_from_config
from llmbo_para.parameters import ParameterSpace
from electrothermal_fixtures import et_config,NAMES


def test_profiles_with_six_values_have_different_semantics():
    space=parameter_space_from_config(et_config())
    assert tuple(s.name for s in space.specs)==NAMES
    point=space.denormalize([.5]*6)
    assert space.normalize(point)==pytest.approx([.5]*6)
    with pytest.raises(ValueError):ParameterSpace(space.specs)
    with pytest.raises(ValueError):space.validate([.9,*point[1:]])


def test_native_heat_mapping_uses_actual_volume_area():
    import pybamm
    from llmbo_para.electrothermal_parameters import apply_electrothermal_parameters
    cfg=et_config();theta=dict(zip(NAMES,[.5,.5,1e-13,2e-13,40.,.1]))
    base=pybamm.ParameterValues('Chen2020');original=base['Negative electrode exchange-current density [A.m-2]']
    applied=apply_electrothermal_parameters(base,theta,{**cfg['fixed'],'property_law':cfg['property_law']})
    p=applied.parameter_values
    assert p['Cell heat capacity [J.K-1.m-3]']==pytest.approx(2e6)
    assert p['Total heat transfer coefficient [W.m-2.K-1]']==pytest.approx(20.)
    assert p['Cell volume [m3]']==2e-5 and p['Cell cooling surface area [m2]']==.005
    assert p['Negative electrode exchange-current density [A.m-2]'] is original
    assert base['Cell volume [m3]']!=2e-5


def test_reference_diffusivity_function_and_fixed_sources():
    import pybamm
    from llmbo_para.electrothermal_parameters import apply_electrothermal_parameters
    cfg=et_config();theta=dict(zip(NAMES,[.5,.5,1e-13,2e-13,40.,.1]))
    fixed={**cfg['fixed'],'property_law':cfg['property_law']}
    p=apply_electrothermal_parameters(pybamm.ParameterValues('Chen2020'),theta,fixed).parameter_values
    fn=p['Negative particle diffusivity [m2.s-1]']
    assert callable(fn) and float(fn(.5,298.15).evaluate())==pytest.approx(1e-13,rel=1e-12,abs=0)
    assert float(fn(.5,310.).evaluate())>1e-13
    fixed['property_law']={**fixed['property_law'],'sources':{}}
    with pytest.raises(ValueError):apply_electrothermal_parameters(pybamm.ParameterValues('Chen2020'),theta,fixed)
