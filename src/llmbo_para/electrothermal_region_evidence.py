"""Read-only arithmetic and coordinate examples for one frozen Region request.

Examples express no preference, confidence, physical feasibility or true outcome.
They neither evaluate candidates nor change the posterior or Region guards.
"""
import math

import numpy as np


VERSION = 'decision_geometry_v2'
OBJECTIVES = ('F_U_V', 'F_T_K')


def build_region_decision_evidence(context, *, advice, settings, observation_ids):
    """Explain already available scalars; construct equal-width geometry examples."""
    c = context.scalarization
    ids = tuple(observation_ids)
    if len(set(ids)) != len(ids) or any(i not in c.observation_ids for i in ids):
        raise ValueError('decision evidence requires unique past frozen observation IDs')
    if advice.get('context_id') != context.context_id:
        raise ValueError('decision advice must match the frozen context')
    width, maximum = float(settings.min_width), float(settings.max_width)
    if not math.isfinite(width) or not math.isfinite(maximum) or not 0 < width <= maximum <= 1:
        raise ValueError('valid configured Region widths required')
    y = np.asarray(c.y, dtype=float)
    scales = np.asarray(c.objective_scales, dtype=float)
    scaled = y/scales
    components = np.asarray(c.weights)*(scaled-np.asarray(c.ideal))
    observations = []
    for ident in ids:
        i = c.observation_ids.index(ident)
        values = components[i]
        largest = float(values.max())
        augmentation = float(c.rho_aug*values.sum())
        observations.append({'evaluation_id': ident,
            'scaled_objectives': scaled[i].tolist(), 'weighted_components': values.tolist(),
            'dominant_objectives': [name for name, value in zip(OBJECTIVES, values) if value == largest],
            'maximum_component': largest, 'augmentation': augmentation, 'g': largest+augmentation})
    candidates = advice['candidates']
    plain = [row for row in candidates if row['is_plain']]
    if len(plain) != 1:
        raise ValueError('one plain candidate required for decision evidence')
    plain_mean = float(plain[0]['mean_standardized'])
    if not math.isfinite(plain_mean):
        raise ValueError('finite frozen posterior means required')
    comparisons = []
    for row in candidates:
        mean = float(row['mean_standardized'])
        if not math.isfinite(mean):
            raise ValueError('finite frozen posterior means required')
        example = None
        if row['eligible_alternative']:
            point = np.asarray(row['normalized_parameters'], dtype=float)
            if point.shape != (6,) or np.any(~np.isfinite(point)) or np.any((point < 0) | (point > 1)):
                raise ValueError('six normalized coordinates required for geometry examples')
            # Shift the whole interval at cube boundaries, preserving its width.
            # No display rounding, physical transform, or LLM-response repair.
            lower = np.clip(point-width/2, 0., 1.-width)
            example = {'lb': lower.tolist(), 'ub': (lower+width).tolist()}
        comparisons.append({'candidate_id': row['candidate_id'],
            'mean_delta_to_plain': mean-plain_mean, 'region_example': example})
    return {'version': VERSION, 'context_id': context.context_id,
        'rules': {
            'components': 'w_j*(F_j/scale_j-ideal_j); exact maximum ties retain both objective names',
            'scalar': 'max(weighted_components)+rho_aug*sum(weighted_components)',
            'mean_delta': 'candidate_mean_minus_plain_mean; negative is lower, positive is higher predicted standardized scalar',
            'region_example': 'configured_min_width_centered_then_shifted_into_unit_cube; coordinates_and_width_only',
            'limits': 'examples are not preferences, confidence, physical feasibility, adoption or unobserved U/T predictions'},
        'observations': observations, 'candidates': comparisons}
