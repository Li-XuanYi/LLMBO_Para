"""Same numeric action across Prompt versions; independent v2 archive checks."""
from copy import deepcopy
from dataclasses import replace
from functools import partial
from pathlib import Path
import json

import pytest

from test_lgbo_numerical_ablation import base,initialize
from lgbo_fixtures import region_action
from test_lgbo_region_audit import lgbo_offline_worker,ENV


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


class FixedAction:
    def __init__(self,kind='region'):self.kind=kind
    def post(self,payload):return region_action(payload,kind=self.kind)


def config(spec,*,version='lgbo_v2',rounds=2):
    cfg=base();cfg['optimization'].update(mode='full_llmbo_mo',region_method=version,
        initial_plan=spec,total_candidate_budget=8+rounds)
    return cfg


def controller(kind='region'):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    return ElectrothermalLLMController(transport=FixedAction(kind),is_mock=True)


def test_v1_v2_same_action_same_gp_ei_parameter_and_real_pair(tmp_path):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    spec,_=initialize(tmp_path/'init');events=[];plans=[]
    for version in ('lgbo_v1','lgbo_v2'):
        cfg=config(spec,version=version);cfg['optimization'].update(global_pool_size=512,gp_sweeps=4)
        result=run_electrothermal_experiment(cfg,tmp_path/version,base_dir=tmp_path,llm_controller=controller())
        run=Path(result['run_directory']);check=audit_electrothermal_run(run,deep=True)
        assert check['passed'],check['issues']
        assert result['API_calls']==result['costs']['solver_calls']==0
        assert result['costs']['software_calls']==4 and result['costs']['cache_hits']==8
        events.append([read(p) for p in sorted((run/'mo-rounds').glob('*.json'))])
        plans.append(result['initial_plan_sha256'])
    assert plans[0]==plans[1]
    for a,b in zip(*events):
        for field in ('mean','std','ei','selected_index','evaluation_id','result_complete'):
            assert a[field]==b[field]
        for field in ('gp_state','pool','scalarization'):
            assert a['context'][field]==b['context'][field]
        for field in ('mean','std','signed_delta','adjusted_mean','effective_ei','selected_index'):
            assert a['region'][field]==b['region'][field]
        assert a['feedback']['new_scalar']==b['feedback']['new_scalar']
        assert 'trust' not in a['feedback'] and 'trust' not in b['feedback']


def test_v2_round_thirteen_has_no_inactivity_gate(tmp_path):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    spec,_=initialize(tmp_path/'init');cfg=config(spec,rounds=13);client=controller('none')
    result=run_electrothermal_experiment(cfg,tmp_path/'r13',base_dir=tmp_path,llm_controller=client)
    assert client.requests==13 and result['region_diagnostics']['valid_actions']==13
    rounds=[read(p) for p in sorted((Path(result['run_directory'])/'mo-rounds').glob('*.json'))]
    assert rounds[-1]['region']['fallback_reason']=='abstained'
    assert all('trust' not in e['feedback'] for e in rounds)


def test_v2_failed_pair_refreshes_all_frozen_context_fields(tmp_path,monkeypatch):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.mo_optimizer import MOOptimizer
    spec,_=initialize(tmp_path/'init');cfg=config(spec)
    _,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    sim=SyntheticElectrothermalSimulator();original=sim.simulate
    monkeypatch.setattr(sim,'simulate',lambda theta,case:replace(original(theta,case),temperature_k=None))
    store=ElectrothermalRunStore(tmp_path/'failed',cfg,dataset=prepared.dataset,signatures=prepared.signatures,command='v2 partial software fixture')
    client=controller('none');client.prepared=prepared
    opt=MOOptimizer(prepared.space,ElectrothermalEvaluator(prepared.space,sim,fit_rates=prepared.dataset.fit_rates),prepared.dataset,
        store,cfg['optimization'],initial_plan=prepared.initial_plan,llm_controller=client)
    first=opt.step();gp=opt.gp;second=opt.step()
    a,b=first['context']['scalarization'],second['context']['scalarization']
    assert len(opt.history)==8 and opt.gp is not gp and a['weights']!=b['weights']
    assert a['observation_ids']==b['observation_ids'] and a['labels']!=b['labels']
    assert b['best']==min(b['labels']) and b['local_center']==b['x'][b['incumbent_index']]
    assert first['feedback']['new_scalar'] is second['feedback']['new_scalar'] is None


@pytest.fixture(scope='module')
def archives():return {}


def http_archive(archives,monkeypatch,tmp_path_factory,*,protocol='responses',kind='region',mode='full_llmbo_mo'):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para import electrothermal_requests,electrothermal_responses
    key=(protocol,kind,mode)
    if key in archives:return archives[key]
    if 'spec' not in archives:archives['spec'],_=initialize(tmp_path_factory.mktemp('v2i'))
    cfg=config(archives['spec']);cfg['optimization']['mode']=mode
    cfg['llm'].update(transport='openai_responses' if protocol=='responses' else 'openai_chat_completions',enabled=False,
        endpoint='https://provider.invalid/v1/'+('responses' if protocol=='responses' else 'chat/completions'),
        api_key_env=ENV,model='offline',max_tokens=2048,timeout_s=15.)
    monkeypatch.setenv(ENV,'offline-lgbo-fixture')
    module=electrothermal_responses if protocol=='responses' else electrothermal_requests
    cls=module.BoundedResponsesTransport if protocol=='responses' else module.BoundedChatCompletionsTransport
    monkeypatch.setattr(module,'_responses_request_worker' if protocol=='responses' else '_chat_request_worker',partial(lgbo_offline_worker,protocol,kind))
    client=ElectrothermalLLMController(transport=cls(cfg['llm']['endpoint'],ENV,model='offline',max_tokens=2048,timeout_s=15.,json_mode=True),is_mock=True)
    root=tmp_path_factory.mktemp('v2r');result=run_electrothermal_experiment(cfg,root,base_dir=root,llm_controller=client)
    archives[key]=Path(result['run_directory']),result
    return archives[key]


@pytest.mark.parametrize('protocol',['chat','responses'])
@pytest.mark.parametrize('kind',['region','none','incomplete','nonjson','invalid_binding'])
def test_v2_production_workers_offline_and_deep_replay(archives,monkeypatch,tmp_path_factory,protocol,kind):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run,result=http_archive(archives,monkeypatch,tmp_path_factory,protocol=protocol,kind=kind)
    check=audit_electrothermal_run(run,deep=True);assert check['passed'],check['issues']
    assert result['BO_rounds']==2 and result['API_calls']==result['costs']['solver_calls']==0
    for path in (run/'mo-rounds').glob('*.json'):
        event=read(path);assert event['region']['region_method']=='lgbo_v2'
        assert event['region']['action_valid']==(kind in ('region','none'))


@pytest.mark.parametrize('protocol',['chat','responses'])
@pytest.mark.parametrize('kind',['incomplete','nonjson','invalid_binding'])
def test_v2_missing_decoded_reply_cannot_be_hidden(archives,monkeypatch,tmp_path_factory,protocol,kind):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run,_=http_archive(archives,monkeypatch,tmp_path_factory,protocol=protocol,kind=kind)
    assert audit_electrothermal_run(run,deep=True)['passed']
    path=sorted((run/'http').glob('*.response.json'))[0];held=path.with_suffix('.held')
    path.rename(held)
    try:assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:held.rename(path)


@pytest.mark.parametrize('protocol',['chat','responses'])
@pytest.mark.parametrize('kind',['startup_failure','transport_failure','timeout','invalid_http_json'])
def test_v2_genuine_pre_reply_failure_remains_auditable(archives,monkeypatch,tmp_path_factory,protocol,kind):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run,_=http_archive(archives,monkeypatch,tmp_path_factory,protocol=protocol,kind=kind)
    assert not list((run/'http').glob('*.response.json'))
    check=audit_electrothermal_run(run,deep=True);assert check['passed'],check['issues']


@pytest.mark.parametrize('damage',['component','active','augmentation','method','prompt','temperature'])
def test_v2_tamper_is_detected(archives,monkeypatch,tmp_path_factory,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run,_=http_archive(archives,monkeypatch,tmp_path_factory)
    assert audit_electrothermal_run(run,deep=True)['passed']
    path=(run/'source/src/llmbo_para/prompts/region_preference_lgbo_v2_electrothermal.txt' if damage=='prompt' else
        sorted((run/'electrothermal-evaluations').glob('*.json'))[0] if damage=='temperature' else run/'llm/000000.payload.json')
    original=path.read_bytes()
    try:
        if damage=='prompt':path.write_bytes(original+b'\naltered')
        else:
            value=read(path)
            if damage=='temperature':value['rates'][0]['trace']['temperature_k'][1]+=1
            elif damage=='method':value['region_method']='lgbo_v1'
            else:
                weighted=value['history'][0]['weighted_objective_evidence']
                if damage=='component':weighted['weighted_components'][0]+=.1
                elif damage=='active':weighted['active_objectives']=['not_an_objective']
                else:weighted['augmented_scalar']+=.1
            path.write_text(json.dumps(value),encoding='utf-8')
        assert not audit_electrothermal_run(run,deep=True)['passed']
    finally:path.write_bytes(original)


@pytest.mark.parametrize('damage',['component','active','augmentation'])
def test_audit_independently_recomputes_producer_evidence(tmp_path,monkeypatch,damage):
    from llmbo_para import electrothermal_region_context as evidence
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    spec,_=initialize(tmp_path/'init');original=evidence.weighted_objective_evidence
    def faulty(*args,**kwargs):
        value=original(*args,**kwargs)
        if damage=='component':value['weighted_components'][0]+=.1
        elif damage=='active':value['active_objectives']=['not_an_objective']
        else:value['augmented_scalar']+=.1
        return value
    monkeypatch.setattr(evidence,'weighted_objective_evidence',faulty)
    result=run_electrothermal_experiment(config(spec),tmp_path/'faulty',base_dir=tmp_path,llm_controller=controller('none'))
    check=audit_electrothermal_run(result['run_directory'],deep=True)
    assert not check['passed'] and any('weighted' in issue.lower() for issue in check['issues']),check


def test_v2_zero_budget_template_keeps_r2_software_physics(tmp_path):
    path=Path(__file__).parents[1]/'configs/electrothermal-sub2api-lgbo-v2-software-template.json'
    assert path.is_file(),'v2 runnable software template is missing'
    cfg=read(path);reference=base()
    for key in ('parameters','fixed','property_law','conditions_by_rate','data','model','fit_rates'):
        assert cfg[key]==reference[key]
    assert cfg['optimization']['region_method']=='lgbo_v2' and cfg['optimization']['mode']=='parego'
    assert cfg['optimization']['global_pool_size']==512 and cfg['optimization']['gp_sweeps']==4
    assert cfg['budgets']['max_llm_requests']==cfg['budgets']['max_solver_calls']==0 and not cfg['llm']['enabled']
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    report,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert report['ready'],report['errors']
