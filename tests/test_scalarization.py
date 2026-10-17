import numpy as np
import pytest


def test_weights_relabel_history_incumbent_and_local_center():
    from llmbo_para.scalarization import augmented_tchebycheff,build_scalarization_context
    y=[[.1,2],[.2,1]];x=[[.2]*6,[.8]*6]
    assert augmented_tchebycheff(y,[.8,.2],[.1,1])==pytest.approx([.86,1.69])
    assert augmented_tchebycheff(y,[.2,.8],[.1,1])==pytest.approx([1.69,.86])
    a=build_scalarization_context(x,y,['a','b'],weights=[.8,.2],objective_scales=[.1,1],rho_aug=.05,protocol_signature='p')
    b=build_scalarization_context(x,y,['a','b'],weights=[.2,.8],objective_scales=[.1,1],rho_aug=.05,protocol_signature='p')
    assert a.incumbent_id=='a' and b.incumbent_id=='b'
    assert a.local_center!=b.local_center and a.context_id!=b.context_id
    assert a.std==pytest.approx(.415) and a.std<1
    y[0][0]=100;assert a.y[0][0]==.1


def test_constant_labels_use_one_std_and_equal_y_different_x_remain():
    from llmbo_para.scalarization import build_scalarization_context
    c=build_scalarization_context([[.2]*6,[.8]*6],[[.1,1],[.1,1]],['z','a'],weights=[.5,.5],objective_scales=[.1,1],rho_aug=.05,protocol_signature='p')
    assert c.std==1 and len(c.labels)==2 and c.incumbent_id=='a'


@pytest.mark.parametrize('y,w,s', [([[float('nan'),1]],[.5,.5],[1,1]),([[1,2,3]],[.5,.5],[1,1]),
    ([[1,2]],[.2,.2],[1,1]),([[1,2]],[.5,.5],[0,1]),([[-1,2]],[.5,.5],[1,1])])
def test_scalar_inputs_reject_nonfinite_wrong_shape_or_nonpositive_scales(y,w,s):
    from llmbo_para.scalarization import augmented_tchebycheff
    with pytest.raises(ValueError):augmented_tchebycheff(y,w,s)


def test_weight_scheduler_is_seeded_without_replacement():
    from llmbo_para.scalarization import WeightScheduler
    weights=[[.8,.2],[.2,.8],[.5,.5]];a=WeightScheduler(weights,17);b=WeightScheduler(weights,17)
    first=[a.next() for _ in range(3)]
    assert len(set(first))==3 and first==[b.next() for _ in range(3)]
