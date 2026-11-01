"""Zero-call experiment design checks; these do not test battery physics."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def module():
    script = ROOT / 'scripts/prepare_et_ablation_benchmarks.py'
    assert script.is_file(), 'ablation/benchmark bundle preparer is missing'
    spec = importlib.util.spec_from_file_location('ablation_design', script)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def template():
    return json.loads((ROOT/'configs/electrothermal-lgbo-numerical-ablation-software.json').read_text(encoding='utf8'))


def bundle():
    return module().build_design(template(), template_path='fixture.json')


def test_factorial_definitions_and_signed_plan_requirements():
    result = bundle(); arms = result['protocol']['ablation_arms']
    assert [(a['warmstart'], a['region']) for a in arms] == [(False,False),(True,False),(False,True),(True,True)]
    assert arms[0]['initialization_group'] == arms[2]['initialization_group'] == 'numeric'
    assert arms[1]['initialization_group'] == arms[3]['initialization_group'] == 'llm_v3'
    assert all(a['initial_plan_required'] for a in arms)


@pytest.mark.parametrize('rounds,costs', [(10,(720,115,600,1320)),(50,(2320,515,3000,5320))])
def test_exact_candidate_solve_and_request_budgets(rounds,costs):
    m=module(); p=m.build_design(template(),template_path='fixture.json',rounds=rounds)['protocol']
    b=p['resource_estimate']; assert (b['ablation_DFN'],b['API'],b['baseline_extra_DFN'],b['combined_DFN'])==costs
    assert p['live_authorization']=={'API':0,'DFN':0}


def test_configs_preserve_observations_mapping_and_block_live_calls():
    m=module(); original=template(); before=deepcopy(original)
    result=m.build_design(original,template_path='fixture.json')
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    assert original==before and len(result['configs'])==20
    for cfg in result['configs'].values():
        assert cfg['data']==original['data'] and cfg['parameters']==original['parameters'] and cfg['fixed']==original['fixed']
        assert cfg['budgets']['max_solver_calls']==cfg['budgets']['max_llm_requests']==0 and cfg['llm']['enabled'] is False
        assert cfg['optimization']['warmstart']['selection_rule']=='pareto_quality_gated_spacefill_v3'
        assert cfg['optimization']['region_method']=='lgbo_v2'
        assert not electrothermal_configuration_errors(cfg)


def test_seeds_and_orders_are_deterministic_and_old_seeds_excluded():
    m=module(); first=bundle(); second=bundle(); assert first==second
    p=first['protocol']; all_seeds=p['screening_seeds']+p['confirmation_seeds']
    assert len(set(all_seeds))==10 and not set(all_seeds)&set(m.EXCLUDED_SEEDS)
    assert len(first['jobs'])==50
    assert len(first['initialization_jobs'])==10
    assert sum(j['candidate_evaluation_cap'] for j in first['initialization_jobs'])==160
    for orders in p['ablation_order'].values(): assert set(orders)=={'A00','A10','A01','A11'}
    for seed in p['active_seeds']:
        stream=p['sobol_streams'][str(seed)]
        assert stream=={'numeric_start':seed*1024,'fill_start':seed*1024+256,'baseline_start':seed*1024+512}
        assert stream['baseline_start']+128 < 2**32


def test_early_metrics_use_one_point_and_all_actual_pool_observations():
    p=bundle()['protocol']; metric=p['metrics']
    assert metric['rounds']==list(range(11)) and metric['objective_scales']==[0.1,1.0]
    assert metric['initial_metric_archive']=='all_16_complete_evaluated_candidates'
    assert metric['representative']['weights']==[0.5,0.5]
    assert p['baseline_methods']['B1']['training_initial_count']==16
    assert p['baseline_methods']['A11']['reuse_ablation_arm']=='A11'


def test_no_credential_values_and_no_overwriting(tmp_path):
    m=module(); cfg=template(); cfg['llm']['api_key']='must_not_be_archived'
    with pytest.raises(ValueError):m.build_design(cfg,template_path='fixture.json')
    result=bundle(); path=tmp_path/'new-bundle';m.write_bundle(result,path)
    assert (path/'protocol.json').is_file() and len(list((path/'configs').glob('*.json')))==20
    assert (path/'initialization-jobs.json').is_file()
    assert json.loads((path/'manifest.json').read_text(encoding='utf8'))['actual_calls']=={'API':0,'DFN':0}
    with pytest.raises(FileExistsError):m.write_bundle(result,path)
