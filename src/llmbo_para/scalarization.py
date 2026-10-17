"""Frozen, linear-target ParEGO contexts for two physical error objectives."""
from dataclasses import dataclass, asdict
import numpy as np
from .runstore import digest_value


def augmented_tchebycheff(y, weights, objective_scales, *, rho_aug=.05, ideal=(0., 0.)):
    y=np.asarray(y,dtype=float);w=np.asarray(weights,dtype=float);s=np.asarray(objective_scales,dtype=float);z=np.asarray(ideal,dtype=float)
    if y.ndim!=2 or y.shape[1]!=2 or np.any(~np.isfinite(y)) or np.any(y<0):raise ValueError('finite nonnegative n by 2 objectives required')
    if w.shape!=(2,) or np.any(~np.isfinite(w)) or np.any(w<0) or not np.isclose(w.sum(),1,atol=1e-12,rtol=0):raise ValueError('two simplex weights required')
    if s.shape!=(2,) or np.any(~np.isfinite(s)) or np.any(s<=0):raise ValueError('two positive finite objective scales required')
    if z.shape!=(2,) or not np.array_equal(z,[0,0]) or not np.isfinite(rho_aug) or rho_aug<0:raise ValueError('fixed zero lower bound and nonnegative augmentation required')
    a=w*(y/s-z)
    return a.max(axis=1)+rho_aug*a.sum(axis=1)


@dataclass(frozen=True)
class ScalarizationContext:
    x:tuple
    y:tuple
    observation_ids:tuple
    weights:tuple
    objective_scales:tuple
    ideal:tuple
    rho_aug:float
    raw_labels:tuple
    labels:tuple
    mean:float
    std:float
    incumbent_id:str
    incumbent_index:int
    best:float
    local_center:tuple
    protocol_signature:str
    context_id:str

    def scalarize(self,y):
        return augmented_tchebycheff(y,self.weights,self.objective_scales,rho_aug=self.rho_aug,ideal=self.ideal)

    def to_dict(self):return asdict(self)


def build_scalarization_context(x,y,observation_ids,*,weights,objective_scales,rho_aug,protocol_signature):
    x=np.asarray(x,dtype=float);ids=tuple(observation_ids)
    raw=augmented_tchebycheff(y,weights,objective_scales,rho_aug=rho_aug)
    if x.shape!=(len(raw),6) or len(raw)<2 or len(ids)!=len(raw) or len(set(ids))!=len(ids) or not all(isinstance(i,str) and i for i in ids):raise ValueError('at least two aligned unique observations required')
    if np.any(~np.isfinite(x)) or np.any((x<0)|(x>1)):raise ValueError('normalized six dimensional inputs required')
    mean=float(raw.mean());std=float(raw.std());std=1. if std<1e-12 else std
    labels=(raw-mean)/std;index=min(range(len(raw)),key=lambda i:(raw[i],ids[i]))
    values=dict(x=tuple(map(tuple,x.tolist())),y=tuple(map(tuple,np.asarray(y,dtype=float).tolist())),observation_ids=ids,
        weights=tuple(weights),objective_scales=tuple(objective_scales),ideal=(0.,0.),rho_aug=float(rho_aug),raw_labels=tuple(raw.tolist()),
        labels=tuple(labels.tolist()),mean=mean,std=std,incumbent_id=ids[index],incumbent_index=index,best=float(labels[index]),
        local_center=tuple(x[index].tolist()),protocol_signature=protocol_signature)
    return ScalarizationContext(**values,context_id=digest_value(values))


class WeightScheduler:
    def __init__(self,weights,seed):
        self.weights=tuple(tuple(float(v) for v in w) for w in weights)
        if not self.weights:raise ValueError('nonempty weight schedule required')
        for w in self.weights:augmented_tchebycheff([[0,0]],w,[1,1])
        self.rng=np.random.default_rng(seed);self.pending=[]

    def next(self):
        if not self.pending:self.pending=list(self.rng.permutation(len(self.weights)))
        return self.weights[self.pending.pop(0)]
