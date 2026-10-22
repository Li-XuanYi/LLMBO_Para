"""Human/LLM interpretation of the frozen objective; never GP training labels."""
import math
import numpy as np


def weighted_objective_evidence(objectives, *, weights, objective_scales, ideal, rho_aug):
    def pair(value, name):
        if (type(value) not in (list,tuple) or len(value)!=2
                or any(type(x) not in (int,float) or not math.isfinite(x) for x in value)):
            raise ValueError(name+' requires two native finite numbers')
        return np.asarray(value,dtype=float)
    y=pair(objectives,'objectives');w=pair(weights,'weights')
    scales=pair(objective_scales,'objective_scales');z=pair(ideal,'ideal')
    if (np.any(y<0) or np.any(w<0) or abs(float(w.sum())-1)>1e-12
            or np.any(scales<=0) or np.any(z!=0)
            or type(rho_aug) not in (int,float) or not math.isfinite(rho_aug) or rho_aug<0):
        raise ValueError('invalid fixed-space objective evidence')
    with np.errstate(over='ignore',invalid='ignore',divide='ignore'):
        q=w*(y/scales-z)
        maximum=float(np.max(q));scalar=float(maximum+rho_aug*np.sum(q))
    if np.any(~np.isfinite(q)) or not math.isfinite(scalar):
        raise ValueError('nonfinite derived objective evidence')
    names=('F_U_V','F_T_K')
    return dict(version='weighted_tchebycheff_v1',weighted_components=q.tolist(),max_component=maximum,
                active_objectives=[names[j] for j in range(2) if q[j]==maximum],augmented_scalar=scalar)
