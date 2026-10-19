"""Frozen-posterior candidate information for the optional Region advice policy.

This module does not fit hyperparameters, change acquisitions or evaluate a cell.
Qualification reproduces the existing EI/sigma guards, including their floors.
"""
import json
import math
from dataclasses import dataclass

import numpy as np

from .acquisition import gaussian_ei
from .runstore import digest_value
from .surrogate import Matern52GP


ADVICE_VERSION = 'candidate_aware_v1'
SHORTLIST_LIMIT = 12
EI_LOG_FLOOR = 1e-12


def candidate_region_requirements(settings, *, selection_mode='global_lift_v1'):
    requirements={'min_confidence': settings.min_confidence,
            'min_width': settings.min_width, 'max_width': settings.max_width,
            'max_plain_log_ei_gap': settings.max_plain_log_ei_gap,
            'min_sigma_ratio': settings.min_sigma_ratio, 'ei_log_floor': EI_LOG_FLOOR,
            'must_cover_eligible_alternative': True}
    if selection_mode=='eligible_region_v1':
        requirements.update(selection_policy=selection_mode,competition_scope='all_qualified_inside_region',
                            plain_baseline='original_EI',tie_rule='plain_first_then_stable_ID')
    elif selection_mode!='global_lift_v1':raise ValueError('invalid Region selection policy')
    return requirements


@dataclass(frozen=True)
class QualifiedRegionPool:
    pool:np.ndarray
    mean:np.ndarray
    std:np.ndarray
    ei:np.ndarray
    plain:int
    gap:np.ndarray
    sigma_ratio:np.ndarray
    physical:dict
    eligible:tuple
    identities:tuple


def qualify_region_pool(context, *, space, settings, mean, std):
    """One original-guard definition shared by advice and regional competition."""
    pool = np.asarray(context.pool, dtype=float)
    if pool.ndim != 2 or pool.shape[1] != 6 or not len(pool):
        raise ValueError('nonempty six-dimensional frozen pool required')
    if np.any(~np.isfinite(pool)) or np.any((pool < 0) | (pool > 1)):
        raise ValueError('frozen pool must contain finite normalized coordinates')
    mean=np.asarray(mean,dtype=float);std=np.asarray(std,dtype=float)
    if mean.shape!=(len(pool),) or std.shape!=mean.shape:raise ValueError('posterior and frozen pool must align')
    ei = gaussian_ei(mean, std, context.scalarization.best)
    plain = int(np.argmax(ei))
    gap = np.log(max(ei[plain], EI_LOG_FLOOR)) - np.log(np.maximum(ei, EI_LOG_FLOOR))
    sigma_ratio = std / max(std[plain], EI_LOG_FLOOR)
    observed = np.asarray(context.scalarization.x, dtype=float)
    seen = set()
    physical = {}
    eligible = []
    identities = [digest_value({'context_id': context.context_id, 'point': x.tolist()}) for x in pool]
    for i, point in enumerate(pool):
        try:
            physical[i] = list(space.denormalize(point))
        except ValueError:
            continue
        key = tuple(point)
        duplicate = key in seen
        seen.add(key)
        already_observed = bool(len(observed) and np.any(np.max(np.abs(observed-point), axis=1) <= 1e-12))
        if (i != plain and not duplicate and not already_observed
                and gap[i] <= settings.max_plain_log_ei_gap
                and sigma_ratio[i] >= settings.min_sigma_ratio):
            eligible.append(i)
    if plain not in physical:
        raise ValueError('plain candidate violates the physical parameter space')
    return QualifiedRegionPool(pool,mean,std,ei,plain,gap,sigma_ratio,physical,tuple(eligible),tuple(identities))


def build_region_candidate_advice(context, *, space, settings):
    """Restore the frozen posterior and select plain, then Max–Min alternatives.

    Distances use normalized coordinates, including configured log10 transforms.
    Exact ties use higher original EI, then a context-bound stable ID.
    """
    state=json.loads(context.gp_state_json);gp=Matern52GP.from_state(state)
    mean,std=gp.predict(context.pool)
    q=qualify_region_pool(context,space=space,settings=settings,mean=mean,std=std)
    pool,ei,plain,gap,sigma_ratio=q.pool,q.ei,q.plain,q.gap,q.sigma_ratio
    physical,eligible,identities=q.physical,q.eligible,q.identities
    selected = [plain]
    remaining = list(eligible)
    while remaining and len(selected) < SHORTLIST_LIMIT:
        distances = {i: min(float(np.linalg.norm(pool[i]-pool[j])/math.sqrt(6)) for j in selected)
                     for i in remaining}
        chosen = min(remaining, key=lambda i: (-distances[i], -float(ei[i]), identities[i]))
        selected.append(chosen)
        remaining.remove(chosen)
    candidates = [{
        'candidate_id': identities[i], 'pool_index': i,
        'normalized_parameters': pool[i].tolist(), 'parameters': physical[i],
        'mean_standardized': float(mean[i]), 'std_standardized': float(std[i]),
        'plain_ei': float(ei[i]), 'relative_plain_ei': float(ei[i]/ei[plain]) if ei[plain]>0 else None,
        'plain_log_ei_gap': float(gap[i]), 'sigma_ratio': float(sigma_ratio[i]),
        'is_plain': i == plain, 'eligible_alternative': i != plain,
    } for i in selected]
    return {'version': ADVICE_VERSION, 'context_id': context.context_id,
            'pool_digest': digest_value(context.pool), 'gp_state_digest': digest_value(state),
            'pool_count': len(pool), 'plain_index': plain,
            'eligible_alternative_count': len(eligible), 'shortlist_limit': SHORTLIST_LIMIT,
            'selection_rule': 'plain_then_maximin_EI_ID_v1',
            'guards': {'max_plain_log_ei_gap': settings.max_plain_log_ei_gap,
                       'min_sigma_ratio': settings.min_sigma_ratio, 'ei_log_floor': EI_LOG_FLOOR},
            'candidates': candidates}


def region_covers_advised_alternative(advice, region):
    """Inclusive exact-coordinate coverage; covering only plain is insufficient."""
    return any(row['eligible_alternative'] and all(
        lo <= x <= hi for lo, x, hi in zip(region['lb'], row['normalized_parameters'], region['ub']))
        for row in advice['candidates'])
