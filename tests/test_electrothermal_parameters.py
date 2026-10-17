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
