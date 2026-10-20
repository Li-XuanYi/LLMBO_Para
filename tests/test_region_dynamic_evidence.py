"""Actual noninitial residual evidence; no observations, labels or units invented."""
from copy import deepcopy
from dataclasses import replace
import importlib
import importlib.util
import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from electrothermal_fixtures import et_config


MODE = 'dynamic_decision_v3'


def feature():
    name = 'llmbo_para.electrothermal_dynamic_evidence'
    assert importlib.util.find_spec(name) is not None, 'past-only dynamic residual evidence is not implemented'
    return importlib.import_module(name)


def output(times=(0.,20.,60.), residuals=(0.,1.,-2.), *, valid=True, unit='K'):
    from llmbo_para.electrothermal_evaluation import ObservedOutputResult
    observed = (300.,)*len(times) if unit == 'K' else (4.,)*len(times)
    predicted = tuple(a+b for a,b in zip(observed,residuals)) if valid else None
    return ObservedOutputResult(valid,None,None,tuple(times),observed,predicted,unit,'controlled test',None if valid else 'solver_error')


def test_three_samples_keep_postinitial_temperature_direction():
    result = feature().dynamic_output_summary(output(),simulation_start_s=0.)
    assert result['initial_residual'] == {'time_s':0.,'residual':0.}
    assert result['dynamic_samples'] == [{'time_s':20.,'residual':1.},{'time_s':60.,'residual':-2.}]
    assert result['dynamic_sample_count'] == result['displayed_sample_count'] == 2
    assert result['dynamic_sample_mean'] == -.5 and result['status'] == 'dynamic'


def test_nonzero_origin_and_missing_initial_observation_allow_real_zero_mean():
    result = feature().dynamic_output_summary(output((10.,20.,70.),(1.,2.,-3.)),simulation_start_s=7.)
    assert result['simulation_start_s'] == 7. and result['initial_residual'] is None
    assert result['dynamic_sample_count'] == 3 and result['dynamic_sample_mean'] == 0.
    assert result['status'] == 'dynamic'


def test_near_initial_observation_is_not_swallowed_by_tolerance():
    result = feature().dynamic_output_summary(output((0.,1e-15,2.),(0.,1.,2.)),simulation_start_s=0.)
    assert result['dynamic_sample_count'] == 2
    assert result['dynamic_samples'][0] == {'time_s':1e-15,'residual':1.}
    assert result['dynamic_sample_mean'] == 1.5


@pytest.mark.parametrize('origin',[None,float('nan'),float('inf')])
def test_unknown_origin_does_not_guess_zero_or_first_observation(origin):
    result = feature().dynamic_output_summary(output(),simulation_start_s=origin)
    assert result['output_valid'] is True and result['status'] == 'origin_unavailable'
    assert result['simulation_start_s'] is result['initial_residual'] is None
    assert result['dynamic_sample_count'] is result['dynamic_sample_mean'] is None
    assert result['displayed_sample_count'] == 0 and result['dynamic_samples'] == []


@pytest.mark.parametrize('trace',[None,{}, {'time_s':[]},{'time_s':[float('nan'),0.,60.]}])
def test_record_origin_uses_only_original_trace_index_zero(trace):
    from llmbo_para.electrothermal_evaluation import ElectrothermalRateResult
    module = feature()
    rate = ElectrothermalRateResult('0.5C',output(unit='V'),output(),'test-solution',trace,())
    summary = module.dynamic_record_summary(SimpleNamespace(rates=(rate,)))['0.5C']
    assert summary['temperature']['status'] == summary['voltage']['status'] == 'origin_unavailable'


def test_voltage_and_temperature_keep_independent_observation_grids():
    from llmbo_para.electrothermal_evaluation import ElectrothermalRateResult
    module = feature()
    rate = ElectrothermalRateResult('1C',output((0.,30.,60.),(0.,.1,-.2),unit='V'),output(),
        'same-solution',{'time_s':[0.,10.,60.]},())
    before = deepcopy(rate)
    summary = module.dynamic_record_summary(SimpleNamespace(rates=(rate,)))['1C']
    assert [x['time_s'] for x in summary['voltage']['dynamic_samples']] == [30.,60.]
    assert [x['time_s'] for x in summary['temperature']['dynamic_samples']] == [20.,60.]
    assert summary['voltage']['dynamic_sample_mean'] == -.05
    assert summary['temperature']['dynamic_sample_mean'] == -.5
    assert rate == before


def test_invalid_temperature_has_null_dynamic_values_not_zero_error():
    row = output(valid=False)
    result = feature().dynamic_output_summary(row,simulation_start_s=0.)
    assert result['output_valid'] is False and result['status'] == 'invalid_output'
    assert result['initial_residual'] is result['dynamic_sample_count'] is result['dynamic_sample_mean'] is None
    assert result['dynamic_samples'] == [] and result['displayed_sample_count'] == 0
    assert row.predicted is row.rmse_k is None


def test_initial_only_has_no_fabricated_dynamic_average():
    result = feature().dynamic_output_summary(output((7.,),(2.,)),simulation_start_s=7.)
    assert result['status'] == 'initial_only' and result['initial_residual'] == {'time_s':7.,'residual':2.}
    assert result['dynamic_sample_count'] == 0 and result['dynamic_sample_mean'] is None
    assert result['dynamic_samples'] == []


@pytest.mark.parametrize('count,indices,average',[
    (1,[0],0.),(2,[0,1],.5),(8,[0,1,2,3,4,5,6,7],3.5),
    (9,[0,1,2,3,4,5,6,8],4.),(100,[0,14,28,42,56,70,84,99],49.5)])
def test_display_uses_bounded_actual_indices_with_all_dynamic_mean(count,indices,average):
    row = output(tuple(range(1,count+1)),tuple(range(count)))
    result = feature().dynamic_output_summary(row,simulation_start_s=0.)
    assert result['initial_residual'] is None and result['dynamic_sample_count'] == count
    assert result['displayed_sample_count'] == len(indices)
    assert result['dynamic_samples'] == [{'time_s':float(i+1),'residual':float(i)} for i in indices]
    assert result['dynamic_sample_mean'] == average


def test_omitted_outlier_still_contributes_to_all_dynamic_mean():
    row = output(tuple(range(1,10)),(0.,0.,0.,0.,0.,0.,0.,9.,0.))
    result = feature().dynamic_output_summary(row,simulation_start_s=0.)
    assert [x['residual'] for x in result['dynamic_samples']] == [0.]*8
    assert result['dynamic_sample_mean'] == 1. and result['dynamic_sample_count'] == 9


@pytest.mark.parametrize('damage',['missing_prediction','shape','observed_nonfinite','prediction_nonfinite','time','empty'])
@pytest.mark.parametrize('origin',[None,0.])
def test_malformed_valid_curve_raises_before_origin_dispatch(damage,origin):
    module = feature(); row = output()
    if damage == 'missing_prediction': row = replace(row,predicted=None)
    elif damage == 'shape': row = replace(row,predicted=(300.,))
    elif damage == 'observed_nonfinite': row = replace(row,observed=(300.,float('inf'),300.))
    elif damage == 'prediction_nonfinite': row = replace(row,predicted=(300.,float('nan'),298.))
    elif damage == 'time': row = replace(row,time_s=(0.,0.,60.))
    else: row = replace(row,time_s=(),observed=(),predicted=())
    with pytest.raises(ValueError): module.dynamic_output_summary(row,simulation_start_s=origin)


def test_valid_observation_before_known_simulation_origin_is_rejected():
    module = feature()
    with pytest.raises(ValueError): module.dynamic_output_summary(output(),simulation_start_s=1.)


@pytest.mark.parametrize('origin',[None,0.])
def test_null_valid_time_grid_raises_the_documented_value_error(origin):
    module = feature()
    with pytest.raises(ValueError):
        module.dynamic_output_summary(replace(output(),time_s=None),simulation_start_s=origin)


@pytest.mark.parametrize('unit',['degC','A','mV'])
def test_evidence_does_not_convert_or_guess_units(unit):
    module = feature()
    with pytest.raises(ValueError): module.dynamic_output_summary(output(unit=unit),simulation_start_s=0.)


def test_residual_precision_is_bounded_but_real_times_are_not_rounded():
    row = output((0.123456789123,),(0.123456789,),unit='V')
    result = feature().dynamic_output_summary(row,simulation_start_s=0.)
    assert result['dynamic_samples'] == [{'time_s':0.123456789123,'residual':0.12345679}]
    assert result['dynamic_sample_mean'] == .12345679


def config():
    cfg = et_config()
    cfg['optimization'].update(region_evidence=MODE,region_advice='candidate_aware_v1',region_selection='fair_region_v1')
    return cfg


def test_dynamic_mode_is_explicit_and_preserves_initialization_and_metric_semantics(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = config(); report,new = prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert new is not None, report['errors']
    cfg['optimization']['region_evidence'] = 'decision_geometry_v2'
    _,old = prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert new.signatures.algorithm != old.signatures.algorithm
    assert new.signatures.initialization_compatibility == old.signatures.initialization_compatibility
    assert new.signatures.comparison_protocol == old.signatures.comparison_protocol


@pytest.mark.parametrize('advice,selection',[('legacy_v1','fair_region_v1'),('candidate_aware_v1','eligible_region_v1')])
def test_dynamic_evidence_requires_candidate_aware_fair_policy(advice,selection):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = config(); cfg['optimization'].update(region_advice=advice,region_selection=selection)
    assert electrothermal_configuration_errors(cfg)


@pytest.fixture(scope='module')
def cache(): return {}


def payload_context(cache,tmp_path_factory):
    feature()
    if 'context' not in cache:
        from test_region_signed_residuals import make_context
        cache['context'] = make_context(tmp_path_factory.mktemp('dynamic_context'),'decision_geometry_v2')
    return cache['context']


def make_payload(prepared,opt,mode=MODE,history=None):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    cfg = deepcopy(prepared.config); cfg['optimization']['region_evidence'] = mode
    p = SimpleNamespace(config=cfg,space=prepared.space,dataset=prepared.dataset,signatures=prepared.signatures)
    past = [r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    return build_electrothermal_payload('region_preference_electrothermal',prepared=p,history=past if history is None else history,context=opt.last_context)


def test_payload_adds_dynamic_evidence_without_changing_past_signs_or_posterior(cache,tmp_path_factory):
    from llmbo_para.runstore import digest_value
    p,opt = payload_context(cache,tmp_path_factory)
    before = digest_value({'gp':opt.gp.state_dict(),'context':opt.last_context.to_dict(),'history':[r.to_dict() for r in opt.history]})
    mean,std = opt.gp.predict(opt.last_context.pool)
    old = make_payload(p,opt,'decision_geometry_v2'); new = make_payload(p,opt)
    assert new['dynamic_history_evidence']['version'] == 'dynamic_residual_v1'
    assert new['history_evidence'] == old['history_evidence'] and new['decision_evidence'] == old['decision_evidence']
    assert [{k:v for k,v in row.items() if k!='dynamic_residuals'} for row in new['history']] == old['history']
    assert all(row['dynamic_residuals'] for row in new['history'])
    assert 200 <= len(new['instructions'].split()) <= 300
    assert 'dynamic_history_evidence' not in old
    assert before == digest_value({'gp':opt.gp.state_dict(),'context':opt.last_context.to_dict(),'history':[r.to_dict() for r in opt.history]})
    later_mean,later_std = opt.gp.predict(opt.last_context.pool)
    np.testing.assert_array_equal(mean,later_mean); np.testing.assert_array_equal(std,later_std)


@pytest.mark.parametrize('partial',[False,True])
def test_dynamic_payload_rejects_future_history(cache,tmp_path_factory,partial):
    p,opt = payload_context(cache,tmp_path_factory)
    past = [r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    future = opt.history[-1]
    if partial: future = replace(future,complete_pair_valid=False,objectives=None)
    with pytest.raises(ValueError,match='frozen'): make_payload(p,opt,history=[*past,future])


def audit_run(cache,tmp_path_factory):
    feature()
    if 'archive' not in cache:
        from llmbo_para.electrothermal_llm import ElectrothermalLLMController
        from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
        from llmbo_para.electrothermal_audit import audit_electrothermal_run
        from test_region_failure_audit import _shared_initialization
        root = tmp_path_factory.mktemp('dynamic_audit'); cfg = _shared_initialization(root)
        cfg['optimization'].update(region_evidence=MODE,region_advice='candidate_aware_v1',region_selection='fair_region_v1')
        cfg['optimization']['region'].update(max_plain_log_ei_gap=100.,min_sigma_ratio=0.)
        class Advice:
            def post(self,payload):
                return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')} | {
                    'region':{'kind':'none','coordinate_space':'normalized','confidence':.5,'reason':'offline dynamic fixture'}}
        summary = run_electrothermal_experiment(cfg,root,base_dir=root,llm_controller=ElectrothermalLLMController(transport=Advice(),is_mock=True))
        archive = Path(summary['run_directory'])
        assert summary['API_calls'] == summary['costs']['solver_calls'] == 0
        assert audit_electrothermal_run(archive,deep=True)['passed']
        cache['archive'] = archive
    return cache['archive']


@pytest.mark.parametrize('damage',['none','mean','sample','time','origin','unit','schema','drop_history'])
def test_audit_reconstructs_dynamic_evidence_from_archived_curves(cache,tmp_path_factory,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    archive = audit_run(cache,tmp_path_factory)
    path = next((archive/'llm').glob('*.payload.json')); original = path.read_bytes(); payload = json.loads(original)
    if damage == 'none': return
    row = payload['history'][0]['dynamic_residuals'][next(iter(payload['history'][0]['rates']))]['temperature']
    if damage == 'mean': row['dynamic_sample_mean'] += 1.
    elif damage == 'sample': row['dynamic_samples'][0]['residual'] += 1.
    elif damage == 'time': row['dynamic_samples'][0]['time_s'] += .01
    elif damage == 'origin': row['simulation_start_s'] += .01
    elif damage == 'unit': row['unit'] = 'degC'
    elif damage == 'schema': payload['dynamic_history_evidence']['sign_convention'] = 'observation_minus_prediction'
    else:
        incumbent = payload['context']['incumbent_id']
        removed = next(r['evaluation_id'] for r in payload['history'] if r['evaluation_id'] != incumbent)
        payload['history'] = [r for r in payload['history'] if r['evaluation_id'] != removed]
        payload['decision_evidence']['observations'] = [r for r in payload['decision_evidence']['observations'] if r['evaluation_id'] != removed]
    try:
        path.write_text(json.dumps(payload),encoding='utf-8')
        assert not audit_electrothermal_run(archive,deep=True)['passed']
    finally: path.write_bytes(original)
