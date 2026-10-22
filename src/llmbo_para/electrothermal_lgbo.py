"""LGBO regional exponential tilt for a frozen, minimized scalar GP."""
from copy import deepcopy
import json
import math

import numpy as np

from .acquisition import gaussian_ei
from .runstore import canonical_json, digest_value
from .sobol import Sobol6

METHOD = 'lgbo_v1'
ANCHOR_COUNT = 32
VARIANCE_EPS = 1e-12
ENVELOPE = {'schema_version', 'parameter_profile', 'fit_rates', 'signatures',
            'context_id', 'region_method', 'region'}


def _native(value):
    if type(value) is dict:
        return all(type(k) is str and _native(v) for k, v in value.items())
    if type(value) is list:
        return all(_native(v) for v in value)
    return value is None or type(value) in (str, int, float, bool)


def validate_lgbo_region(response, *, expected_context_id, expected_signatures):
    """Validate restored host identities and the exact direct-region action."""
    if not _native(response):
        raise ValueError('LGBO action must use native JSON')
    try:
        canonical_json(response)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('LGBO action must contain finite JSON') from None
    if (type(response) is not dict or set(response) != ENVELOPE
            or type(response['schema_version']) is not int or response['schema_version'] != 2
            or response['parameter_profile'] != 'electrothermal_4e2t'
            or response['region_method'] != METHOD
            or response['context_id'] != expected_context_id
            or response['fit_rates'] != list(expected_signatures['fit_rates'])
            or digest_value(response['signatures']) != digest_value(expected_signatures)):
        raise ValueError('stale or incompatible LGBO action')
    region = response['region']
    if type(region) is not dict:
        raise ValueError('LGBO region must be an object')
    if region.get('kind') == 'none' and set(region) == {'kind'}:
        return deepcopy(region)
    if set(region) != {'kind', 'lb', 'ub', 'confidence'} or region['kind'] != 'region':
        raise ValueError('direct LGBO region required')
    confidence = region['confidence']
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
        raise ValueError('finite confidence in [0,1] required')
    for key in ('lb', 'ub'):
        if (type(region[key]) is not list or len(region[key]) != 6
                or any(type(x) not in (int, float) or not 0 <= x <= 1 for x in region[key])):
            raise ValueError('six bounded finite coordinates required')
    if any(lo >= hi for lo, hi in zip(region['lb'], region['ub'])):
        raise ValueError('strictly ordered region bounds required')
    return deepcopy(region)


def lgbo_mean_tilt(*, mean, std, cov_xa, cov_aa, confidence):
    """Exact finite Gaussian tilt; covariance and observation labels are untouched."""
    if (type(confidence) not in (int, float)
            or not math.isfinite(confidence) or not 0 <= confidence <= 1):
        raise ValueError('finite confidence in [0,1] required')
    mean, std = np.asarray(mean, dtype=float), np.asarray(std, dtype=float)
    xa, aa = np.asarray(cov_xa, dtype=float), np.asarray(cov_aa, dtype=float)
    if (mean.ndim != 1 or not mean.size or std.shape != mean.shape
            or aa.ndim != 2 or not aa.shape[0] or aa.shape[0] != aa.shape[1]
            or xa.shape != (len(mean), aa.shape[0])
            or any(np.any(~np.isfinite(v)) for v in (mean, std, xa, aa))
            or np.any(std < 0)):
        raise ValueError('finite aligned Gaussian moments required')
    weights = np.full(aa.shape[0], 1/aa.shape[0])
    variance = float(weights @ aa @ weights)
    if confidence and variance < -VARIANCE_EPS:
        raise ValueError('negative_region_variance')
    if confidence and variance <= VARIANCE_EPS:
        raise ValueError('degenerate_region_variance')
    lam = float(confidence/math.sqrt(variance)) if confidence else 0.
    delta = lam*(xa @ weights) if confidence else np.zeros_like(mean)
    adjusted = mean-delta
    if not np.all(np.isfinite(adjusted)):
        raise ValueError('nonfinite_tilt')
    return {'region_variance': variance, 'lambda': lam,
            'anchor_weights': weights.tolist(), 'signed_delta': delta.tolist(),
            'adjusted_mean': adjusted.tolist()}


def apply_lgbo_region(gp, context, pool, response, *, space, request_outcome=None):
    """Apply a direct regional preference, then maximize EI over the whole pool."""
    x = np.asarray(pool, dtype=float)
    mean, std = gp.predict(x)
    mean, std = np.asarray(mean, dtype=float), np.asarray(std, dtype=float)
    ei = gaussian_ei(mean, std, context.scalarization.best)
    plain = int(np.argmax(ei))
    result = {'region_method': METHOD, 'context_id': context.context_id,
              'mean': mean.tolist(), 'std': std.tolist(), 'plain_ei': ei.tolist(),
              'signed_delta': np.zeros_like(mean).tolist(), 'adjusted_mean': mean.tolist(),
              'effective_ei': ei.tolist(), 'plain_index': plain, 'selected_index': plain,
              'action_valid': False, 'tilt_applied': False, 'selection_changed': False,
              'accepted': False, 'fallback_reason': None,
              'response': deepcopy(response), 'request_outcome': deepcopy(request_outcome)}
    def fallback(reason):
        result['fallback_reason'] = reason
        return result
    if response is None:
        return fallback('no_response')
    try:
        region = validate_lgbo_region(response, expected_context_id=context.context_id,
                                     expected_signatures=json.loads(context.signatures_json))
    except (ValueError, TypeError, KeyError, OverflowError):
        return fallback('invalid_lgbo_action')
    result['action_valid'] = True
    if region['kind'] == 'none':
        return fallback('abstained')
    if region['confidence'] == 0:
        return fallback('zero_confidence')
    lower, upper = np.asarray(region['lb']), np.asarray(region['ub'])
    samples = lower+(upper-lower)*Sobol6(1+ANCHOR_COUNT*(context.ordinal-1)).draw(ANCHOR_COUNT)
    feasible = []
    for anchor in samples:
        try:
            space.denormalize(anchor)
            feasible.append(True)
        except ValueError:
            feasible.append(False)
    result.update(sampled_anchors=samples.tolist(), anchor_feasible_mask=feasible)
    anchors = samples[np.asarray(feasible)]
    result['anchors'] = anchors.tolist()
    if not len(anchors):
        return fallback('no_feasible_anchors')
    try:
        values = lgbo_mean_tilt(mean=mean, std=std, cov_xa=gp.posterior_covariance(x, anchors),
                               cov_aa=gp.posterior_covariance(anchors),
                               confidence=region['confidence'])
    except (ValueError, TypeError, OverflowError) as exc:
        reason = str(exc) if str(exc) in ('negative_region_variance', 'degenerate_region_variance') else 'invalid_posterior'
        return fallback(reason)
    lifted = gaussian_ei(values['adjusted_mean'], std, context.scalarization.best)
    selected = int(np.argmax(lifted))
    result.update(values)
    result.update(effective_ei=lifted.tolist(), selected_index=selected,
                  tilt_applied=bool(np.any(np.asarray(values['signed_delta']) != 0)),
                  selection_changed=selected != plain, accepted=selected != plain)
    return result
