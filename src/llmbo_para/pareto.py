"""Two-objective minimization and exact HV in a fixed, scaled space."""
import numpy as np


def _objectives(y):
    a=np.asarray(y,dtype=float)
    if a.size==0:a=np.empty((0,2))
    if a.ndim!=2 or a.shape[1]!=2 or np.any(~np.isfinite(a)) or np.any(a<0):raise ValueError('complete finite nonnegative objective pairs required')
    return a


def pareto_indices(y):
    a=_objectives(y)
    return tuple(i for i,p in enumerate(a) if not np.any(np.all(a<=p,axis=1)&np.any(a<p,axis=1)))


def hypervolume_2d(y,*,objective_scales,reference_point):
    a=_objectives(y);s=np.asarray(objective_scales,dtype=float)
    if s.shape!=(2,) or np.any(~np.isfinite(s)) or np.any(s<=0):raise ValueError('two positive scales required')
    if reference_point is None:return None
    r=np.asarray(reference_point,dtype=float)
    if r.shape!=(2,) or np.any(~np.isfinite(r)) or np.any(r<=0):raise ValueError('fixed finite positive reference required')
    a=a/s;a=a[np.all(a<r,axis=1)];height=float(r[1]);hv=0.
    for x,y in sorted(set(map(tuple,a))):
        if y<height:hv+=(r[0]-x)*(height-y);height=y
    return float(hv)


def validate_hv_comparison(protocol_signatures):
    values=tuple(protocol_signatures)
    if not values or not all(isinstance(s,str) and s for s in values) or len(set(values))!=1:raise ValueError('HV comparison requires identical nonempty protocol signatures')
    return values[0]
