"""Decision-only host arithmetic and legal geometry; no new BO model or labels."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from electrothermal_fixtures import et_config
from test_region_signed_residuals import make_context


MODE = 'decision_geometry_v2'
OBJECTIVES = ['F_U_V', 'F_T_K']
SIGNED_PROMPT_SHA256 = '93b6a353ddc4567709c5f542429b96eec6b634d22416b84b9b2420aec4892e52'
FAIR_PROMPT_SHA256 = 'c0ae1a2b0501ee3b129d8e46179a8bb8b4f82b6421b8cc1b4092774d5ce1ae5e'


def builder():
    # Runtime assertion keeps RED about the missing feature, not collection/setup.
    name = 'llmbo_para.electrothermal_region_evidence'
    assert importlib.util.find_spec(name) is not None, 'decision_geometry_v2 evidence builder is not implemented'
    return importlib.import_module(name).build_region_decision_evidence


def numeric_context(*, y=((.02, .01), (.01, .0025)), weights=(.2, .8), scales=(.1, 1.)):
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.mo_optimizer import MORoundContext
    from llmbo_para.runstore import canonical_json, digest_value
    scalar = build_scalarization_context([[.2]*6, [.8]*6], y, ['past-a', 'past-b'],
        weights=weights, objective_scales=scales, rho_aug=.05, protocol_signature='arithmetic-only-fixture')
    pool = ((.5,)*6, (0., .001, .02, .98, .999, 1.), (.9,)*6)
    raw = {'scalarization':scalar.to_dict(), 'fit_rates':('0.5C','1C'), 'signatures':{}, 'gp_state':{}, 'pool':pool, 'ordinal':1}
    return MORoundContext(scalar, raw['fit_rates'], '{}', '{}', pool, 1, digest_value(raw))


def numeric_advice(context):
    candidates = []
    for i, (point, mean) in enumerate(zip(context.pool, (-1., -1.2, -.8))):
        candidates.append({'candidate_id':'candidate-'+str(i), 'pool_index':i,
            'normalized_parameters':list(point), 'parameters':[.5,.5,1e-13,2e-13,40.,.1],
            'mean_standardized':mean, 'std_standardized':1., 'plain_ei':1.-i*.05,
            'relative_plain_ei':1.-i*.05, 'plain_log_ei_gap':i*.05, 'sigma_ratio':1.,
            'is_plain':i==0, 'eligible_alternative':i!=0})
    return {'version':'candidate_aware_v1', 'context_id':context.context_id,
        'plain_index':0, 'pool_count':3, 'eligible_alternative_count':2, 'candidates':candidates}


def evidence(context=None, observation_ids=('past-a','past-b')):
    context = context or numeric_context()
    return builder()(context, advice=numeric_advice(context),
        settings=SimpleNamespace(min_width=.03, max_width=.8), observation_ids=observation_ids)


def decision_config():
    cfg = et_config()
    cfg['optimization'].update(region_evidence=MODE, region_advice='candidate_aware_v1', region_selection='fair_region_v1')
    return cfg


def test_new_mode_is_strict_and_preserves_metric_and_initialization_protocol(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = decision_config()
    report, new = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert new is not None, 'decision_geometry_v2 must be an explicit accepted evidence mode: '+repr(report['errors'])
    cfg['optimization']['region_evidence'] = 'signed_residual_v1'
    _, old = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert old is not None
    assert new.signatures.algorithm != old.signatures.algorithm
    assert new.signatures.initialization_compatibility == old.signatures.initialization_compatibility
    assert new.signatures.comparison_protocol == old.signatures.comparison_protocol


@pytest.mark.parametrize('advice,selection', [('legacy_v1','fair_region_v1'), ('candidate_aware_v1','eligible_region_v1')])
def test_new_mode_requires_existing_candidate_aware_fair_policy(advice, selection):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = decision_config(); cfg['optimization'].update(region_advice=advice, region_selection=selection)
    assert electrothermal_configuration_errors(cfg)


@pytest.mark.parametrize('value', ['decision_geometry_v3', None, True, []])
def test_new_mode_does_not_relax_unknown_or_malformed_evidence_validation(value):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = decision_config(); cfg['optimization']['region_evidence'] = value
    assert electrothermal_configuration_errors(cfg)


def test_host_components_identify_voltage_dominance_despite_larger_temperature_weight():
    context = numeric_context(); result = evidence(context)
    assert result['version'] == MODE and result['context_id'] == context.context_id
    row = result['observations'][0]
    assert row['evaluation_id'] == 'past-a'
    np.testing.assert_allclose(row['scaled_objectives'], [.2,.01], rtol=0, atol=1e-15)
    np.testing.assert_allclose(row['weighted_components'], [.04,.008], rtol=0, atol=1e-15)
    assert row['dominant_objectives'] == ['F_U_V']
    assert row['maximum_component'] == pytest.approx(.04)
    assert row['augmentation'] == pytest.approx(.0024)
    assert row['g'] == pytest.approx(.0424)
    assert row['g'] == pytest.approx(context.scalarization.raw_labels[0])
    assert result.get('rules') or any(k.endswith('_rule') and isinstance(v,str) and v for k,v in result.items())


def test_exact_component_tie_lists_both_objectives_in_defined_order():
    result = evidence(numeric_context(y=((.25,.25),(.125,.5)), weights=(.5,.5), scales=(1.,1.)))
    assert result['observations'][0]['dominant_objectives'] == OBJECTIVES
    assert result['observations'][0]['maximum_component'] == .125


def test_voltage_unit_and_scale_conversion_preserves_decision_arithmetic():
    old = evidence(numeric_context())
    converted = evidence(numeric_context(y=((20.,.01),(10.,.0025)), scales=(100.,1.)))
    for a,b in zip(old['observations'], converted['observations']):
        assert a['evaluation_id'] == b['evaluation_id']
        assert a['dominant_objectives'] == b['dominant_objectives']
        for field in ('scaled_objectives','weighted_components','maximum_component','augmentation','g'):
            np.testing.assert_allclose(a[field], b[field], rtol=0, atol=1e-14)


def test_requested_history_order_is_preserved_not_resorted():
    rows = evidence(observation_ids=('past-b','past-a'))['observations']
    assert [r['evaluation_id'] for r in rows] == ['past-b','past-a']


@pytest.mark.parametrize('ids', [('past-a','future'), ('past-a','past-a')])
def test_unknown_or_duplicate_selected_observation_ids_are_rejected(ids):
    build = builder(); context = numeric_context()
    with pytest.raises(ValueError):
        build(context, advice=numeric_advice(context), settings=SimpleNamespace(min_width=.03,max_width=.8), observation_ids=ids)


def test_candidate_mean_difference_sign_and_plain_example_are_explicit():
    result = evidence(); rows = {r['candidate_id']:r for r in result['candidates']}
    assert rows['candidate-0']['mean_delta_to_plain'] == 0.
    assert rows['candidate-0']['region_example'] is None
    assert rows['candidate-1']['mean_delta_to_plain'] == pytest.approx(-.2)
    assert rows['candidate-2']['mean_delta_to_plain'] == pytest.approx(.2)


def test_minimum_width_examples_shift_inside_bounds_and_do_not_mutate_input():
    from llmbo_para.runstore import digest_value
    build = builder(); context = numeric_context(); advice = numeric_advice(context)
    before = digest_value({'context':context.to_dict(), 'advice':advice})
    result = build(context, advice=advice, settings=SimpleNamespace(min_width=.03,max_width=.8), observation_ids=('past-a','past-b'))
    by_id = {r['candidate_id']:r for r in result['candidates']}
    for original in advice['candidates']:
        example = by_id[original['candidate_id']]['region_example']
        if original['is_plain']:
            assert example is None
            continue
        assert set(example) == {'lb','ub'}, 'example geometry must not force a confidence or adoption'
        lb = np.asarray(example['lb']); ub = np.asarray(example['ub']); point = np.asarray(original['normalized_parameters'])
        assert lb.shape == ub.shape == (6,)
        assert np.all(lb>=0) and np.all(ub<=1) and np.all(lb<=point) and np.all(point<=ub)
        np.testing.assert_allclose(ub-lb, np.full(6,.03), rtol=0, atol=1e-14)
    edge = by_id['candidate-1']['region_example']
    assert edge['lb'][0] == 0. and edge['ub'][-1] == 1.
    assert before == digest_value({'context':context.to_dict(), 'advice':advice})


def test_full_unit_cube_is_geometry_only_not_a_physical_anchor_guarantee():
    build = builder(); context = numeric_context(); advice = numeric_advice(context)
    result = build(context,advice=advice,settings=SimpleNamespace(min_width=1.,max_width=1.),observation_ids=('past-a',))
    for row in result['candidates']:
        if row['candidate_id'] == 'candidate-0':
            assert row['region_example'] is None
        else:
            # A normalized example never promises feasible anchors or fair adoption.
            assert row['region_example'] == {'lb':[0.]*6,'ub':[1.]*6}
            assert set(row['region_example']) == {'lb','ub'}


def test_geometry_keeps_requested_precision_without_rounding_width():
    build = builder(); context = numeric_context(); width = .031234567891234
    result = build(context,advice=numeric_advice(context),settings=SimpleNamespace(min_width=width,max_width=.8),observation_ids=('past-a',))
    row = next(r for r in result['candidates'] if r['candidate_id']=='candidate-1')
    lb = np.asarray(row['region_example']['lb']);ub = np.asarray(row['region_example']['ub'])
    np.testing.assert_allclose(ub-lb,np.full(6,width),rtol=0,atol=2e-16)
    assert lb[-1] == pytest.approx(1-width,rel=0,abs=1e-15)
    assert abs(lb[-1]-round(float(lb[-1]),6)) > 1e-8


def test_log_parameters_use_existing_normalized_coordinates_without_another_transform():
    result = evidence(); row = next(r for r in result['candidates'] if r['candidate_id']=='candidate-1')
    # D_s_n_ref/D_s_p_ref coordinates are already log-normalized, not physical diffusivities.
    assert (row['region_example']['lb'][2]+row['region_example']['ub'][2])/2 == pytest.approx(.02)
    assert (row['region_example']['lb'][3]+row['region_example']['ub'][3])/2 == pytest.approx(.98)


@pytest.fixture(scope='module')
def signed_context(tmp_path_factory):
    # Exactly one software GP step shared by payload/legacy compatibility tests.
    return make_context(tmp_path_factory.mktemp('decision_context'), 'signed_residual_v1')


def payload_for(p, opt, mode, *, history=None):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    context = opt.last_context
    old = [r for r in opt.history if r.evaluation_id in context.scalarization.observation_ids]
    cfg = deepcopy(p.config); cfg['optimization']['region_evidence'] = mode
    prepared = SimpleNamespace(config=cfg,space=p.space,dataset=p.dataset,signatures=p.signatures)
    return build_electrothermal_payload('region_preference_electrothermal', prepared=prepared,
        history=old if history is None else history, context=context)


def test_new_payload_adds_only_decision_and_keeps_signed_past_curve_evidence(signed_context):
    build = builder(); p,opt = signed_context
    from llmbo_para.informed import InformedSettings
    from llmbo_para.runstore import digest_value
    before = digest_value({'context':opt.last_context.to_dict(),'gp':opt.gp.state_dict(),'history':[r.to_dict() for r in opt.history]})
    mean,std = opt.gp.predict(opt.last_context.pool)
    signed = payload_for(p,opt,'signed_residual_v1'); new = payload_for(p,opt,MODE)
    assert new['history_evidence'] == signed['history_evidence']
    assert new['history'] == signed['history']
    assert all('signed_residuals' in row for row in new['history'])
    assert new['decision_evidence'] == build(opt.last_context,advice=new['candidate_advice'],
        settings=InformedSettings.parse(p.config['optimization']['region']), observation_ids=[r['evaluation_id'] for r in new['history']])
    assert [r['evaluation_id'] for r in new['decision_evidence']['observations']] == [r['evaluation_id'] for r in new['history']]
    assert 200 <= len(new['instructions'].split()) <= 300
    assert new['instructions'] != signed['instructions']
    assert {k:v for k,v in new.items() if k not in ('decision_evidence','instructions')} == {k:v for k,v in signed.items() if k!='instructions'}
    assert before == digest_value({'context':opt.last_context.to_dict(),'gp':opt.gp.state_dict(),'history':[r.to_dict() for r in opt.history]})
    after_mean,after_std = opt.gp.predict(opt.last_context.pool)
    np.testing.assert_array_equal(after_mean,mean); np.testing.assert_array_equal(after_std,std)


@pytest.mark.parametrize('partial', [False,True])
def test_new_payload_rejects_future_history_before_exposing_evidence(signed_context, partial):
    builder(); p,opt = signed_context
    past = [r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    future = opt.history[-1]
    if partial:
        future = replace(future,complete_pair_valid=False,objectives=None,
            objective_components={'F_U':future.objective_components['F_U'],'F_T':None})
    with pytest.raises(ValueError, match='frozen'):
        payload_for(p,opt,MODE,history=[*past,future])


def test_old_evidence_payloads_keep_byte_behavior_and_existing_prompts(signed_context):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.runstore import canonical_json
    p,opt = signed_context
    prompt_root = Path(__file__).parents[1]/'src/llmbo_para/prompts'
    for name,expected in [('region_preference_residual_electrothermal.txt',SIGNED_PROMPT_SHA256),('region_preference_fair_electrothermal.txt',FAIR_PROMPT_SHA256)]:
        assert hashlib.sha256((prompt_root/name).read_bytes()).hexdigest() == expected
    legacy = payload_for(p,opt,'legacy_v1'); signed = payload_for(p,opt,'signed_residual_v1')
    assert 'decision_evidence' not in legacy and 'decision_evidence' not in signed
    assert legacy['instructions'] == (prompt_root/'region_preference_fair_electrothermal.txt').read_text()
    assert signed['instructions'] == (prompt_root/'region_preference_residual_electrothermal.txt').read_text()
    cfg = deepcopy(p.config); cfg['optimization'].pop('region_evidence')
    prepared = SimpleNamespace(config=cfg,space=p.space,dataset=p.dataset,signatures=p.signatures)
    old = [r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    default = build_electrothermal_payload('region_preference_electrothermal',prepared=prepared,history=old,context=opt.last_context)
    assert canonical_json(default) == canonical_json(legacy)
    assert canonical_json(signed) == canonical_json(payload_for(p,opt,'signed_residual_v1'))


@pytest.fixture(scope='module')
def audit_cache():
    return {}


def decision_audit_run(cache,tmp_path_factory):
    builder()  # Tests fail about missing feature before attempting new-mode setup.
    if 'root' in cache:
        return cache['root']
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from test_region_failure_audit import _shared_initialization
    root = tmp_path_factory.mktemp('decision_audit'); cfg = _shared_initialization(root)
    cfg['optimization'].update(region_evidence=MODE,region_advice='candidate_aware_v1',region_selection='fair_region_v1')
    # Fixture-only wide guards ensure the advice branch; research defaults stay unchanged.
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100.,min_sigma_ratio=0.)
    class Advice:
        def post(self,payload):
            assert payload['decision_evidence']['version'] == MODE
            assert payload['history_evidence']['version'] == 'signed_residual_v1'
            return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}|{
                'region':{'kind':'none','coordinate_space':'normalized','confidence':.5,'reason':'offline decision fixture'}}
    summary = run_electrothermal_experiment(cfg,root,base_dir=root,
        llm_controller=ElectrothermalLLMController(transport=Advice(),is_mock=True))
    archive = Path(summary['run_directory'])
    assert summary['API_calls'] == summary['costs']['solver_calls'] == 0
    assert audit_electrothermal_run(archive,deep=True)['passed']
    cache['root'] = archive
    return archive


@pytest.mark.parametrize('damage', ['weighted_components','augmentation','g','mean_delta','box','delete',
    'rate_rmse','complete_flag','drop_history','reorder'])
def test_deep_audit_recomputes_decision_numbers_and_geometry(audit_cache,tmp_path_factory,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    archive = decision_audit_run(audit_cache,tmp_path_factory)
    path = next((archive/'llm').glob('*.payload.json')); original = path.read_bytes(); payload = json.loads(original)
    decision = payload['decision_evidence']
    if damage == 'weighted_components': decision['observations'][0]['weighted_components'][0] += .001
    elif damage in ('augmentation','g'): decision['observations'][0][damage] += .001
    elif damage == 'mean_delta': decision['candidates'][-1]['mean_delta_to_plain'] += .1
    elif damage == 'box':
        row = next(r for r in decision['candidates'] if r['region_example'] is not None)
        row['region_example']['lb'][0] += .001
    elif damage == 'rate_rmse':
        rate = next(iter(payload['history'][0]['rates']))
        payload['history'][0]['rates'][rate]['rmse_v'] += .001
    elif damage == 'complete_flag':
        payload['history'][0]['complete_pair_valid'] = not payload['history'][0]['complete_pair_valid']
    elif damage == 'drop_history':
        incumbent = payload['context']['incumbent_id']
        removed = next(r['evaluation_id'] for r in payload['history'] if r['evaluation_id'] != incumbent)
        payload['history'] = [r for r in payload['history'] if r['evaluation_id'] != removed]
        decision['observations'] = [r for r in decision['observations'] if r['evaluation_id'] != removed]
        assert any(r['evaluation_id'] == incumbent for r in payload['history'])
    elif damage == 'reorder':
        assert len(payload['history']) >= 2 and len(decision['observations']) >= 2
        payload['history'].reverse()
        decision['observations'].reverse()
    else: payload.pop('decision_evidence')
    try:
        path.write_text(json.dumps(payload))
        assert not audit_electrothermal_run(archive,deep=True)['passed']
    finally:
        path.write_bytes(original)
