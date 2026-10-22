"""LGBO algebra and acquisition tests; PSD software fixtures, no battery solve."""
from copy import deepcopy
import json
from types import SimpleNamespace

import numpy as np
import pytest


def tilt(**changes):
    from llmbo_para.electrothermal_lgbo import lgbo_mean_tilt
    values = dict(mean=[-.30, -.25], std=[.4, .4],
                  cov_xa=[[.02], [.12]], cov_aa=[[.16]], confidence=.65)
    values.update(changes)
    return lgbo_mean_tilt(**values)


def test_covariance_tilt_matches_known_gaussian_and_changes_ei_pick():
    from llmbo_para.acquisition import gaussian_ei
    joint = [[.16, 0., .02], [0., .16, .12], [.02, .12, .16]]
    assert np.linalg.eigvalsh(joint).min() > 0
    result = tilt()
    assert result['signed_delta'] == pytest.approx([.0325, .195])
    assert result['adjusted_mean'] == pytest.approx([-.3325, -.445])
    assert result['lambda'] == pytest.approx(1.625)
    assert result['region_variance'] == pytest.approx(.16)
    assert np.argmax(gaussian_ei([-.3, -.25], [.4, .4], -.5)) == 0
    assert np.argmax(gaussian_ei(result['adjusted_mean'], [.4, .4], -.5)) == 1


def test_negative_cross_covariance_is_signed_instead_of_clipped():
    result = tilt(cov_xa=[[-.02], [.12]])
    assert result['signed_delta'] == pytest.approx([-.0325, .195])
    assert result['adjusted_mean'] == pytest.approx([-.2675, -.445])


def test_zero_confidence_is_exact_plain_even_with_zero_regional_variance():
    result = tilt(confidence=0., cov_xa=[[0.], [0.]], cov_aa=[[0.]])
    assert result['signed_delta'] == [0., 0.]
    assert result['adjusted_mean'] == [-.3, -.25]
    assert result['lambda'] == 0.


def test_uniform_multi_anchor_functional_shifts_by_c_standard_deviations():
    # Independent regional variables: mean variance (.16+.36)/4=.13.
    result = tilt(mean=[0., 0.], std=[.4, .6],
                  cov_xa=[[.16, 0.], [0., .36]],
                  cov_aa=[[.16, 0.], [0., .36]], confidence=.5)
    assert result['anchor_weights'] == [.5, .5]
    assert result['region_variance'] == pytest.approx(.13)
    assert sum(result['signed_delta'])/2 == pytest.approx(.5*np.sqrt(.13))
    assert np.all(np.abs(result['signed_delta']) <= .5*np.array([.4, .6]))


@pytest.mark.parametrize('changes', [
    {'confidence': True}, {'confidence': '0.5'}, {'confidence': float('nan')},
    {'confidence': float('inf')}, {'confidence': -.1}, {'confidence': 1.1},
    {'std': [-.4, .4]}, {'mean': [0.]}, {'cov_xa': [[.1, .2]]},
    {'cov_aa': [[0.]]}, {'cov_aa': [[-1.]]},
    {'cov_xa': [[float('nan')], [.12]]}, {'cov_aa': [[float('inf')]]},
])
def test_invalid_gaussian_or_confidence_is_not_silently_repaired(changes):
    with pytest.raises(ValueError):
        tilt(**changes)


def setup_region():
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_config import electrothermal_space_from_config
    space = electrothermal_space_from_config(et_config())
    signatures = dict(fit_rates=['0.5C', '1C'], algorithm='current', source='current')
    pool = ((.1,)*6, (.55,)*6)
    context = SimpleNamespace(ordinal=13, context_id='current-context',
        signatures_json=json.dumps(signatures), fit_rates=('0.5C', '1C'),
        pool=pool, scalarization=SimpleNamespace(best=-.5))
    response = dict(schema_version=2, parameter_profile='electrothermal_4e2t',
        fit_rates=['0.5C', '1C'], signatures=signatures,
        context_id='current-context', region_method='lgbo_v1',
        region=dict(kind='region', lb=[.4]*6, ub=[.7]*6, confidence=.65))
    return space, context, response


class PSDGP:
    """One valid finite Gaussian process; not a mock of the tilt computation."""
    def __init__(self):
        self.x = [[.05]*6]
        self.labels = [-.5]
    def predict(self, x):
        x = np.asarray(x)
        return .01*x[:, 0], np.full(len(x), .5)
    def posterior_covariance(self, a, b=None):
        a = np.asarray(a); b = a if b is None else np.asarray(b)
        return .25*np.exp(-np.sum((a[:, None]-b[None, :])**2, axis=2)/.04)


def test_region_applies_at_round_13_with_uniform_anchors_and_unchanged_gp():
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    space, context, response = setup_region()
    gp = PSDGP(); before = deepcopy(gp.__dict__); original = deepcopy(response)
    result = apply_lgbo_region(gp, context, context.pool, response, space=space)
    assert result['action_valid'] and result['tilt_applied']
    assert result['plain_index'] == 0 and result['selected_index'] == 1
    assert result['selection_changed'] and result['accepted']
    assert result['std'] == [.5, .5]
    assert len(result['sampled_anchors']) == len(result['anchors']) == 32
    assert result['anchor_weights'] == [1/32]*32
    assert np.max(np.abs(result['signed_delta'])) <= .65*.5 + 1e-12
    assert gp.__dict__ == before and response == original


def test_small_confidence_is_used_without_legacy_threshold():
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    space, context, response = setup_region()
    response['region']['confidence'] = .1
    result = apply_lgbo_region(PSDGP(), context, context.pool, response, space=space)
    assert result['action_valid'] and result['tilt_applied']
    assert max(result['signed_delta']) > 0


def test_no_legal_anchors_preserves_sampling_evidence_and_plain():
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    _, context, response = setup_region()
    class NoLegalSpace:
        def denormalize(self, value):
            raise ValueError('physical domain violation')
    result = apply_lgbo_region(PSDGP(), context, context.pool, response, space=NoLegalSpace())
    assert result['selected_index'] == result['plain_index'] == 0
    assert result['fallback_reason'] == 'no_feasible_anchors'
    assert len(result['sampled_anchors']) == 32
    assert result['anchor_feasible_mask'] == [False]*32


def test_degenerate_covariance_falls_back_without_adding_noise():
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    space, context, response = setup_region()
    class ZeroCovariance(PSDGP):
        def posterior_covariance(self, a, b=None):
            return np.zeros((len(a), len(a) if b is None else len(b)))
    result = apply_lgbo_region(ZeroCovariance(), context, context.pool, response, space=space)
    assert result['fallback_reason'] == 'degenerate_region_variance'
    assert result['selected_index'] == result['plain_index']


@pytest.mark.parametrize('damage', ['method', 'context', 'signature', 'legacy',
                                  'extra_reason', 'bool_coordinate', 'nan_coordinate'])
def test_stale_or_invalid_region_cannot_enter_acquisition(damage):
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    space, context, response = setup_region()
    if damage == 'method': response['region_method'] = 'old'
    elif damage == 'context': response['context_id'] = 'old'
    elif damage == 'signature': response['signatures']['source'] = 'old'
    elif damage == 'legacy': response.pop('region_method')
    elif damage == 'extra_reason': response['region']['reason'] = 'unrequested'
    elif damage == 'bool_coordinate': response['region']['lb'][0] = True
    elif damage == 'nan_coordinate': response['region']['lb'][0] = float('nan')
    result = apply_lgbo_region(PSDGP(), context, context.pool, response, space=space)
    assert result['fallback_reason'] == 'invalid_lgbo_action'
    assert not result['action_valid']
    assert result['selected_index'] == result['plain_index']
