"""Opt-in regional challengers compete against the original plain Gaussian EI."""
import numpy as np

from .acquisition import gaussian_ei
from .electrothermal_region_advice import EI_LOG_FLOOR,qualify_region_pool


def eligible_region_competition(context, region, *, mean, std, raw_shift, space, settings):
    """Mask the unchanged raw Lift; require a strict advantage over plain.

    The shortlist is information compression only. Competition uses all qualified
    regional alternatives in the frozen pool. Neither the GP nor observations
    are modified. Exact ties favor plain, then the context-bound candidate ID.
    """
    q=qualify_region_pool(context,space=space,settings=settings,mean=mean,std=std)
    raw=np.asarray(raw_shift,dtype=float)
    if raw.shape!=q.mean.shape or np.any(~np.isfinite(raw)) or np.any(raw<0) or np.any(raw>settings.max_shift_std):
        raise ValueError('raw shift must be aligned, finite and bounded')
    lb=np.asarray(region['lb'],dtype=float);ub=np.asarray(region['ub'],dtype=float)
    if lb.shape!=(6,) or ub.shape!=(6,) or np.any(~np.isfinite([lb,ub])) or np.any(lb<0) or np.any(ub>1) or np.any(lb>=ub):
        raise ValueError('valid normalized region required')
    inside=np.all((q.pool>=lb)&(q.pool<=ub),axis=1)
    challengers=[i for i in q.eligible if inside[i]]
    shift=np.zeros_like(raw);shift[challengers]=raw[challengers]
    adjusted=q.mean-shift
    lifted=gaussian_ei(adjusted,q.std,context.scalarization.best)
    unrestricted=gaussian_ei(q.mean-raw,q.std,context.scalarization.best)
    best=min(challengers,key=lambda i:(-float(lifted[i]),q.identities[i])) if challengers else None
    wins=best is not None and lifted[best]>q.ei[q.plain]
    return {'shift':shift.tolist(),'adjusted_mean':adjusted.tolist(),'lifted_ei':lifted.tolist(),
        'plain_index':q.plain,'selected_index':best if wins else q.plain,
        'eligible_indices':list(q.eligible),'challenger_indices':challengers,'best_challenger_index':best,
        'unrestricted_lifted_index':int(np.argmax(unrestricted)),
        'reason':'strict_improvement' if wins else 'not_above_plain_ei' if challengers else 'no_challenger',
        'plain_original_ei':float(q.ei[q.plain]),
        'max_shift_over_sigma':float(np.max(shift/np.maximum(q.std,EI_LOG_FLOOR)))}
