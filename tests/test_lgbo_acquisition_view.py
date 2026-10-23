"""A frozen round owns one base prediction/EI; Region only adds adjusted EI."""
from copy import deepcopy
from dataclasses import replace
import importlib
import numpy as np
import pytest


def feature():
    module = importlib.import_module('llmbo_para.acquisition')
    assert hasattr(module, 'FrozenAcquisitionView'), 'frozen acquisition view is missing'
    return module


def test_full_step_predict_and_plain_ei_once(tmp_path, monkeypatch):
    from test_lgbo_region_workflow import optimizer
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para import acquisition, mo_optimizer, electrothermal_lgbo
    calls = {'predict': 0, 'ei': 0}
    original_predict, original_ei = Matern52GP.predict, acquisition.gaussian_ei
    def predict(self, pool):
        calls['predict'] += 1
        return original_predict(self, pool)
    def ei(*args, **kwargs):
        calls['ei'] += 1
        return original_ei(*args, **kwargs)
    for module in (acquisition, mo_optimizer, electrothermal_lgbo):
        monkeypatch.setattr(module, 'gaussian_ei', ei)
    monkeypatch.setattr(Matern52GP, 'predict', predict)
    event = optimizer(tmp_path).step()
    assert calls == {'predict': 1, 'ei': 1}
    assert event['region']['fallback_reason'] == 'abstained'


def inputs(tmp_path):
    from electrothermal_payload_fixtures import payload_case
    from llmbo_para.surrogate import Matern52GP
    import json
    prepared, rows, context = payload_case('lgbo_v1', tmp_path)
    return prepared, rows, context, Matern52GP.from_state(json.loads(context.gp_state_json))


def action(context, kind='region', confidence=.65):
    import json
    value = {'schema_version': 2, 'parameter_profile': 'electrothermal_4e2t',
        'fit_rates': list(context.fit_rates), 'signatures': json.loads(context.signatures_json),
        'context_id': context.context_id, 'region_method': 'lgbo_v1', 'region': {'kind': kind}}
    if kind == 'region':
        value['region'].update(lb=[.3]*6, ub=[.8]*6, confidence=confidence)
    return value


def test_known_ei_oracle_and_owned_immutable_values(tmp_path, monkeypatch):
    module = feature()
    _, _, context, gp = inputs(tmp_path)
    pool = np.array([[0.]*6, [.5]*6, [1.]*6])
    context = replace(context, pool=tuple(map(tuple, pool.tolist())),
        scalarization=replace(context.scalarization, best=0.))
    mean, std = np.array([-1., 0., 1.]), np.array([0., 1., 0.])
    monkeypatch.setattr(gp, 'predict', lambda x: (mean, std))
    view = module.build_acquisition_view(gp, context, pool)
    assert view.plain_ei == pytest.approx((1., .3989422804014327, 0.))
    assert view.plain_index == 0
    pool[0, 0] = .2
    mean[0] = 99.
    std[0] = 99.
    assert view.pool[0] == (0.,)*6 and view.mean == (-1., 0., 1.) and view.std == (0., 1., 0.)
    with pytest.raises(TypeError):
        view.pool[0][0] = .9
    with pytest.raises(TypeError):
        view.mean[0] = .9
    with pytest.raises(AttributeError):
        view.best = 1.


def test_ties_and_same_order_new_allocation_do_not_predict_again(tmp_path, monkeypatch):
    module = feature()
    _, _, context, gp = inputs(tmp_path)
    monkeypatch.setattr(gp, 'predict', lambda pool: (np.zeros(len(pool)), np.ones(len(pool))))
    view = module.build_acquisition_view(gp, context, context.pool)
    assert view.plain_index == 0
    monkeypatch.setattr(gp, 'predict', lambda pool: pytest.fail('validation re-predicts'))
    monkeypatch.setattr(module, 'gaussian_ei', lambda *args: pytest.fail('validation recalculates EI'))
    module.validate_acquisition_view(view, gp, context, np.array(context.pool, copy=True))


@pytest.mark.parametrize('pool', [(), ((0.,)*5,), ((float('nan'),)*6,), ((1.1,)*6,)])
def test_invalid_frozen_pool_is_rejected_before_prediction(tmp_path, monkeypatch, pool):
    module = feature()
    _, _, context, gp = inputs(tmp_path)
    context = replace(context, pool=pool)
    monkeypatch.setattr(gp, 'predict', lambda pool: pytest.fail('invalid input was predicted'))
    with pytest.raises(ValueError):
        module.build_acquisition_view(gp, context, pool)


@pytest.mark.parametrize('damage', ['context', 'weights', 'gp_retrained', 'pool_order',
    'best', 'nan_mean', 'negative_std', 'negative_ei', 'wrong_argmax', 'mutable_view', 'failed_round'])
def test_stale_or_invalid_view_is_rejected_without_evaluation(tmp_path, monkeypatch, damage):
    module = feature()
    prepared, _, context, gp = inputs(tmp_path)
    view = module.build_acquisition_view(gp, context, context.pool)
    pool = context.pool
    if damage == 'context':
        context = replace(context, context_id='other-round')
    elif damage == 'weights':
        context = replace(context, scalarization=replace(context.scalarization, weights=(.2, .8)))
    elif damage == 'gp_retrained':
        gp.fit(context.scalarization.x, tuple(-v for v in context.scalarization.labels), group=())
    elif damage == 'pool_order':
        pool = tuple(reversed(pool))
    elif damage == 'best':
        context = replace(context, scalarization=replace(context.scalarization, best=-99.))
    elif damage == 'nan_mean':
        view = replace(view, mean=(float('nan'), *view.mean[1:]))
    elif damage == 'negative_std':
        view = replace(view, std=(-1., *view.std[1:]))
    elif damage == 'negative_ei':
        view = replace(view, plain_ei=(-1., *view.plain_ei[1:]))
    elif damage == 'wrong_argmax':
        view = replace(view, plain_index=(view.plain_index+1) % len(pool))
    elif damage == 'mutable_view':
        view = replace(view, mean=list(view.mean))
    elif damage == 'failed_round':
        context = replace(context, ordinal=context.ordinal+1, context_id='next-round-with-no-new-Y')
    monkeypatch.setattr(gp, 'predict', lambda pool: pytest.fail('stale view silently refreshed'))
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    with pytest.raises(ValueError):
        apply_lgbo_region(gp, context, pool, None, space=prepared.space, acquisition_view=view)


@pytest.mark.parametrize('kind', ['region', 'none', 'zero', 'missing', 'negative_cross',
                                  'degenerate', 'negative_variance', 'no_anchors'])
def test_optional_view_preserves_all_outputs_and_gp_state(tmp_path, monkeypatch, kind):
    module = feature()
    prepared, _, context, gp = inputs(tmp_path)
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    view = module.build_acquisition_view(gp, context, context.pool)
    response = None if kind == 'missing' else action(context, kind='none' if kind == 'none' else 'region',
                                                   confidence=0. if kind == 'zero' else .65)
    space = prepared.space
    if kind in ('negative_cross', 'degenerate', 'negative_variance'):
        def covariance(a, b=None):
            shape = (len(a), len(a) if b is None else len(b))
            if kind == 'degenerate':
                return np.zeros(shape)
            if kind == 'negative_variance':
                return -np.ones(shape)
            return np.ones(shape)*(.1 if b is None else -.01)
        monkeypatch.setattr(gp, 'posterior_covariance', covariance)
    if kind == 'no_anchors':
        class NoSpace:
            def denormalize(self, point):
                raise ValueError('no legal anchors')
        space = NoSpace()
    before = deepcopy(gp.state_dict())
    legacy = apply_lgbo_region(gp, context, context.pool, response, space=space)
    actual = apply_lgbo_region(gp, context, context.pool, response, space=space, acquisition_view=view)
    assert actual == legacy
    assert gp.state_dict() == before
    assert actual['std'] == list(view.std)


def test_confidence_reuses_context_but_valid_tilt_adds_only_adjusted_ei(tmp_path, monkeypatch):
    module = feature()
    prepared, _, context, gp = inputs(tmp_path)
    from llmbo_para import electrothermal_lgbo as lgbo
    calls = {'predict': 0, 'ei': 0}
    predict, ei = gp.predict, module.gaussian_ei
    def count_predict(pool):
        calls['predict'] += 1
        return predict(pool)
    def count_ei(*args):
        calls['ei'] += 1
        return ei(*args)
    monkeypatch.setattr(gp, 'predict', count_predict)
    monkeypatch.setattr(module, 'gaussian_ei', count_ei)
    monkeypatch.setattr(lgbo, 'gaussian_ei', count_ei)
    view = module.build_acquisition_view(gp, context, context.pool)
    assert calls == {'predict': 1, 'ei': 1}
    for confidence in (.25, .65):
        result = lgbo.apply_lgbo_region(gp, context, context.pool, action(context, confidence=confidence),
            space=prepared.space, acquisition_view=view)
        assert result['tilt_applied']
    assert calls == {'predict': 1, 'ei': 3}
