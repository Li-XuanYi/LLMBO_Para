import numpy as np
import pytest


def test_gaussian_ei_zero_std_and_scale_equivalence():
    from llmbo_para.acquisition import gaussian_ei
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.surrogate import Matern52GP
    assert gaussian_ei([-1,1],[0,0],0)==pytest.approx([1,0])
    assert gaussian_ei([0],[1],0)[0]==pytest.approx(1/np.sqrt(2*np.pi))
    for mean,std in [([0],[-1]),([float('nan')],[1])]:
        with pytest.raises(ValueError):gaussian_ei(mean,std,0)
    contexts=[build_scalarization_context([[.2]*6,[.8]*6],y,['a','b'],weights=[.8,.2],objective_scales=s,rho_aug=.05,protocol_signature='p')
              for y,s in [([[.1,2],[.2,1]],[.1,1]),([[100,2],[200,1]],[100,1])]]
    decisions=[]
    for c in contexts:
        gp=Matern52GP(max_sweeps=1).fit(c.x,c.labels,group=())
        m,s=gp.predict([[.1]*6,[.5]*6,[.9]*6]);decisions.append(gaussian_ei(m,s,c.best))
    assert decisions[0]==pytest.approx(decisions[1])
