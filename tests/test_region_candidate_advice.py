"""Candidate-aware Region contracts; all predictions and transports are local."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from electrothermal_fixtures import et_config


def advice_fixture(tmp_path, monkeypatch, *, pool=None, mean=None, std=None):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.informed import InformedSettings
    from llmbo_para.runstore import canonical_json
    cfg = et_config()
    cfg['optimization']['region_advice'] = 'candidate_aware_v1'
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    # On old code this is a behavior assertion, before using the new helper.
    assert prepared is not None, 'candidate-aware v2 configuration must be accepted'
    pool = tuple(tuple(x) for x in (pool or [[.2]*6, [.5]*6, [.8]*6]))
    mean = np.asarray(mean if mean is not None else [0., .05, 3.], dtype=float)
    std = np.asarray(std if std is not None else [1.]*len(pool), dtype=float)
    scalar = SimpleNamespace(best=0., x=((.05,)*6,))
    context = SimpleNamespace(pool=pool, scalarization=scalar, context_id='frozen-test-context',
                              gp_state_json=canonical_json({'fixture': 'fixed posterior'}).decode())
    class FixedPosterior:
        def predict(self, x):
            assert tuple(map(tuple, x)) == pool
            return mean.copy(), std.copy()
    monkeypatch.setattr(Matern52GP, 'from_state', lambda state: FixedPosterior())
    return prepared, context, InformedSettings()


def test_candidate_advice_contains_exact_frozen_predictions_and_gates(tmp_path, monkeypatch):
    p, c, settings = advice_fixture(tmp_path, monkeypatch)
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    before = deepcopy(c.__dict__)
    a = build_region_candidate_advice(c, space=p.space, settings=settings)
    assert a['version'] == 'candidate_aware_v1' and a['context_id'] == c.context_id
    assert a['plain_index'] == 0 and a['eligible_alternative_count'] == 1
    assert [r['pool_index'] for r in a['candidates']] == [0, 1]
    row = a['candidates'][1]
    assert row['eligible_alternative'] and not row['is_plain']
    assert row['mean_standardized'] == .05 and row['std_standardized'] == 1.
    assert row['normalized_parameters'] == [.5]*6
    assert row['parameters'] == pytest.approx(p.space.denormalize([.5]*6))
    assert row['plain_log_ei_gap'] <= .25 and row['sigma_ratio'] >= .85
    assert a['guards'] == {'max_plain_log_ei_gap': .25, 'min_sigma_ratio': .85, 'ei_log_floor': 1e-12}
    assert c.__dict__ == before


def test_candidate_advice_is_bounded_deterministic_and_maximin(tmp_path, monkeypatch):
    pool = [[i/32]*6 for i in range(1, 26)]
    p, c, settings = advice_fixture(tmp_path, monkeypatch, pool=pool, mean=[0.]*25)
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    a = build_region_candidate_advice(c, space=p.space, settings=settings)
    b = build_region_candidate_advice(c, space=p.space, settings=settings)
    assert a == b and len(a['candidates']) == 12
    assert a['eligible_alternative_count'] == 24
    assert [r['pool_index'] for r in a['candidates'][:2]] == [0, 24]
    assert len({r['candidate_id'] for r in a['candidates']}) == 12
    assert a['candidates'][0]['is_plain'] and not a['candidates'][0]['eligible_alternative']
    selected = [0]
    for row in a['candidates'][1:]:
        remaining = [i for i in range(25) if i not in selected]
        def distance_sq(i):
            return min(sum((u-v)**2 for u,v in zip(pool[i],pool[j])) for j in selected)
        best_distance = max(map(distance_sq, remaining))
        assert distance_sq(row['pool_index']) == best_distance
        tied_rows = [r for r in a['candidates'] if r['pool_index'] not in selected
                     and distance_sq(r['pool_index']) == best_distance]
        if len(tied_rows) > 1:
            assert row['candidate_id'] == min(r['candidate_id'] for r in tied_rows)
        selected.append(row['pool_index'])


def test_exact_EI_floor_and_sigma_guard_not_unfloored_ratio(tmp_path, monkeypatch):
    p, c, settings = advice_fixture(tmp_path, monkeypatch, mean=[10., 11., 12.])
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    # All EI values are below 1e-12: the old logarithmic guard regards them as tied.
    a = build_region_candidate_advice(c, space=p.space, settings=settings)
    assert a['eligible_alternative_count'] == 2
    assert all(r['plain_log_ei_gap'] == 0. for r in a['candidates'])


def test_sigma_guard_excludes_high_EI_low_uncertainty_point(tmp_path, monkeypatch):
    p, c, settings = advice_fixture(tmp_path, monkeypatch, mean=[0., -.1, 3.], std=[1., .8, 1.])
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    a = build_region_candidate_advice(c, space=p.space, settings=settings)
    # Point 1 has almost the same original EI, but sigma=.8 < .85*sigma_plain.
    assert a['plain_index'] == 0 and a['eligible_alternative_count'] == 0


def test_observed_and_duplicate_points_are_not_advice(tmp_path, monkeypatch):
    pool = [[.2]*6, [.5]*6, [.5]*6, [.05]*6]
    p, c, settings = advice_fixture(tmp_path, monkeypatch, pool=pool, mean=[0.]*4)
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    a = build_region_candidate_advice(c, space=p.space, settings=settings)
    assert a['eligible_alternative_count'] == 1
    assert {r['pool_index'] for r in a['candidates']} == {0, 1}


@pytest.mark.parametrize('mode', ['candidate_aware_v1', 'legacy_v1'])
def test_explicit_policy_is_strict_and_algorithm_signature_isolated(tmp_path, mode):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = et_config()
    _, old = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    cfg['optimization']['region_advice'] = mode
    _, new = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert new is not None, 'explicit region advice policy must validate'
    assert new.signatures.algorithm != old.signatures.algorithm
    assert new.signatures.initialization_compatibility == old.signatures.initialization_compatibility
    assert new.signatures.comparison_protocol == old.signatures.comparison_protocol
    cfg['optimization']['region_advice'] = 'unreviewed_rule'
    report, invalid = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert invalid is None and not report['ready']


def real_context(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.mo_optimizer import MOOptimizer
    cfg = et_config()
    cfg['optimization']['region_advice'] = 'candidate_aware_v1'
    _, p = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert p is not None, 'candidate-aware v2 configuration must be accepted'
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=p.dataset, signatures=p.signatures, command='test')
    evaluator = ElectrothermalEvaluator(p.space, SyntheticElectrothermalSimulator(), fit_rates=p.dataset.fit_rates)
    opt = MOOptimizer(p.space, evaluator, p.dataset, store, cfg['optimization'])
    opt.step()
    return opt, p, opt.last_context


def changed_context(context, **changes):
    from llmbo_para.runstore import digest_value
    context = replace(context, **changes)
    raw = context.to_dict()
    raw.pop('context_id')
    return replace(context, context_id=digest_value(raw))


def test_payload_has_current_GP_candidates_and_explicit_acceptance_gates(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    opt, p, c = real_context(tmp_path)
    payload = build_electrothermal_payload('region_preference_electrothermal', prepared=p, history=opt.history[:2], context=c)
    assert 'candidate_advice' in payload, 'Region needs current acquisition candidates'
    assert payload['candidate_advice']['context_id'] == c.context_id
    assert payload['region_requirements']['max_plain_log_ei_gap'] == .25
    assert payload['region_requirements']['min_sigma_ratio'] == .85
    assert payload['region_requirements']['must_cover_eligible_alternative'] is True
    assert 200 <= len(payload['instructions'].split()) <= 300


def test_no_eligible_alternative_skips_transport_without_spending_request(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    opt, p, c = real_context(tmp_path)
    # A one-point frozen pool cannot offer an alternative, independent of GP quality.
    c = changed_context(c, pool=(c.pool[0],))
    class Forbidden:
        def post(self, payload):
            pytest.fail('no alternative must skip transport')
    ctl = ElectrothermalLLMController(transport=Forbidden(), is_mock=True)
    ctl.last_request_outcome = {'ordinal': 99, 'context_id': 'stale'}
    assert ctl.request_region(p, opt.history[:2], c, opt.store) is None
    assert ctl.requests == 0 and not ctl.task_requests
    assert ctl.last_request_outcome == {'task': 'region_preference_electrothermal', 'context_id': c.context_id,
                                       'status': 'skipped', 'reason': 'no_eligible_alternative'}
    assert not list((opt.store.path/'llm').glob('*.payload.json'))
    assert opt.store.ledger.summary()['mock_llm_requests'] == 0


@pytest.mark.parametrize('covered', ['none', 'plain_only', 'alternative'])
def test_region_must_cover_a_shortlisted_eligible_alternative(tmp_path, monkeypatch, covered):
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    from test_electrothermal_region import response
    opt, p, c = real_context(tmp_path)
    # PSD posterior fixture: same numeric Lift test as the legacy acquisition test.
    class GP:
        x = np.full((2,6), .05)
        def predict(self, x): return .01*np.asarray(x)[:,0], np.full(len(x), .5)
        def posterior_covariance(self, a, b=None):
            a=np.asarray(a); b=a if b is None else np.asarray(b)
            return .25*np.exp(-np.sum((a[:,None]-b[None,:])**2,axis=2)/.04)
    from llmbo_para.surrogate import Matern52GP
    monkeypatch.setattr(Matern52GP, 'from_state', lambda state: GP())
    c = changed_context(c, pool=((.1,)*6, (.55,)*6), ordinal=0)
    r = response(c)
    bounds = {'none': (.75,.95), 'plain_only': (.05,.2), 'alternative': (.4,.7)}[covered]
    r['region'].update(lb=[bounds[0]]*6, ub=[bounds[1]]*6)
    before = deepcopy(c.__dict__)
    result = apply_electrothermal_region(GP(), c, c.pool, r, settings=InformedSettings(), trust=1.,
                                         space=p.space, advice_mode='candidate_aware_v1')
    assert result['candidate_advice']['eligible_alternative_count'] == 1
    if covered == 'alternative':
        assert result['accepted'] and result['selected_index'] == 1
        assert result['std'] == [.5,.5] and max(result['shift']) <= .25
        legacy = apply_electrothermal_region(GP(), c, c.pool, r, settings=InformedSettings(), trust=1., space=p.space)
        for key in ('mean','std','shift','adjusted_mean','lifted_ei','anchors','anchor_weights','correlation'):
            np.testing.assert_array_equal(result[key], legacy[key])
        assert result['selected_index'] == legacy['selected_index']
    else:
        assert result['fallback_reason'] == 'no_eligible_candidate_in_region'
        assert not result['accepted'] and result['selected_index'] == result['plain_index']
    assert c.__dict__ == before


def candidate_run(root):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    cfg = _shared_initialization(root)
    cfg['optimization']['region_advice'] = 'candidate_aware_v1'
    # Broad original guard keeps this fixture focused on the advice contract.
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100., min_sigma_ratio=0.)
    class Abstain:
        def post(self, payload):
            assert payload['candidate_advice']['eligible_alternative_count'] > 0
            return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')} | {
                'region': {'kind':'none','coordinate_space':'normalized','confidence':0.,'reason':'offline abstention'}}
    result = run_electrothermal_experiment(cfg, root, base_dir=root,
                    llm_controller=ElectrothermalLLMController(transport=Abstain(), is_mock=True))
    return Path(result['run_directory'])


@pytest.mark.parametrize('damage', ['none','missing_advice','mean','std','index','threshold','count','missing_payload_advice','fake_no_ordinal','false_skip'])
def test_candidate_aware_run_audits_and_detects_advice_tampering(tmp_path, damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    root = candidate_run(tmp_path)
    audit = audit_electrothermal_run(root, deep=True)
    assert audit['passed'], audit
    if damage == 'none': return
    payload_file = next((root/'llm').glob('*.payload.json'))
    payload = json.loads(payload_file.read_text(encoding='utf8'))
    if damage == 'missing_payload_advice': del payload['candidate_advice']
    elif damage == 'mean': payload['candidate_advice']['candidates'][0]['mean_standardized'] += 1.
    elif damage == 'std': payload['candidate_advice']['candidates'][0]['std_standardized'] += 1.
    elif damage == 'index': payload['candidate_advice']['candidates'][0]['pool_index'] += 1
    elif damage == 'threshold': payload['region_requirements']['max_plain_log_ei_gap'] += 1.
    elif damage == 'count': payload['candidate_advice']['eligible_alternative_count'] += 1
    else:
        file = next((root/'mo-rounds').glob('*.json'))
        event = json.loads(file.read_text(encoding='utf8'))
        if damage == 'missing_advice': del event['region']['candidate_advice']
        else:
            del event['region']['request_outcome']['ordinal']
            if damage == 'false_skip':
                event['region']['request_outcome'].update(status='skipped', reason='no_eligible_alternative')
        file.write_text(json.dumps(event), encoding='utf8')
    payload_file.write_text(json.dumps(payload), encoding='utf8')
    audit = audit_electrothermal_run(root, deep=True)
    assert not audit['passed'], (damage, audit)


def test_optimizer_no_alternative_skips_and_replay_detects_false_skip(tmp_path, monkeypatch):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.mo_optimizer import MOOptimizer
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    cfg = _shared_initialization(tmp_path)
    cfg['optimization']['region_advice'] = 'candidate_aware_v1'
    original = MOOptimizer.candidate_pool
    monkeypatch.setattr(MOOptimizer, 'candidate_pool', lambda self, center: original(self, center)[:1])
    class Forbidden:
        def post(self, payload): pytest.fail('no alternative must not request')
    ctl = ElectrothermalLLMController(transport=Forbidden(), is_mock=True)
    result = run_electrothermal_experiment(cfg, tmp_path, base_dir=tmp_path, llm_controller=ctl)
    root = Path(result['run_directory'])
    assert result['BO_rounds'] == 2 and ctl.requests == result['costs']['mock_llm_requests'] == 0
    assert result['region_diagnostics']['fallback_counts'] == {'no_eligible_alternative': 2}
    audit = audit_electrothermal_run(root, deep=True)
    assert audit['passed'], audit
    file = next((root/'mo-rounds').glob('*.json'))
    event = json.loads(file.read_text(encoding='utf8'))
    event['region']['request_outcome']['reason'] = 'disabled'
    file.write_text(json.dumps(event), encoding='utf8')
    assert not audit_electrothermal_run(root, deep=True)['passed']


def test_region_coverage_uses_exact_coordinates_and_inclusive_bounds():
    from llmbo_para.electrothermal_region_advice import region_covers_advised_alternative
    advice = {'candidates': [{'eligible_alternative': True, 'normalized_parameters':[.50000049]*6}]}
    region = {'lb':[.4]*6, 'ub':[.5]*6}
    assert not region_covers_advised_alternative(advice, region)
    region['ub'] = [.50000049]*6
    assert region_covers_advised_alternative(advice, region)
    region['lb'] = [.50000049]*6
    region['ub'] = [.6]*6
    assert region_covers_advised_alternative(advice, region)
    advice['candidates'][0]['eligible_alternative'] = False
    assert not region_covers_advised_alternative(advice, region)


def test_legacy_prompt_stays_separate_from_candidate_prompt(tmp_path):
    from test_electrothermal_region import context_fixture
    import llmbo_para.electrothermal_llm as llm
    old_opt, old_p, old_c = context_fixture(tmp_path/'old')
    old = llm.build_electrothermal_payload('region_preference_electrothermal', prepared=old_p,
                                         history=old_opt.history[:2], context=old_c)
    assert old['instructions'] == (Path(llm.__file__).parent/'prompts/region_preference_electrothermal.txt').read_text(encoding='utf8')
    opt, p, c = real_context(tmp_path/'new')
    new = llm.build_electrothermal_payload('region_preference_electrothermal', prepared=p, history=opt.history[:2], context=c)
    assert new['instructions'] != old['instructions']
