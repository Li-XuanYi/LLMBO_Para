"""Same raw-Lift baseline guards, without unobserved objective lookahead."""
from dataclasses import asdict
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pytest

from test_region_competition import fixture

def fair(p,c,s,m,v,raw,region=None):
    from llmbo_para.electrothermal_region_selection import eligible_region_competition
    return eligible_region_competition(c,region or {'lb':[.4]*6,'ub':[.6]*6},
        mean=m,std=v,raw_shift=raw,space=p.space,settings=s,selection_mode='fair_region_v1')

def test_strategy_is_explicit_and_does_not_change_init_or_metric_protocol(tmp_path):
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg=et_config();cfg['optimization'].update(region_advice='candidate_aware_v1',region_selection='eligible_region_v1')
    _,old=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    cfg['optimization']['region_selection']='fair_region_v1'
    report,new=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert new is not None,report['errors']
    assert old.signatures.algorithm!=new.signatures.algorithm
    assert old.signatures.initialization_compatibility==new.signatures.initialization_compatibility
    assert old.signatures.comparison_protocol==new.signatures.comparison_protocol
    cfg['optimization']['region_advice']='legacy_v1'
    assert prepare_electrothermal_experiment(cfg,base_dir=tmp_path)[1] is None

@pytest.mark.parametrize('plain_inside',[False,True])
def test_regional_bonus_does_not_win_by_removing_same_bonus_from_plain(tmp_path,monkeypatch,plain_inside):
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=[[.5 if plain_inside else .1]*6,[.55]*6,[.9]*6])
    from llmbo_para.electrothermal_region_selection import eligible_region_competition
    old=eligible_region_competition(c,{'lb':[.4]*6,'ub':[.6]*6},mean=m,std=v,raw_shift=[.25,.15,0.],space=p.space,settings=s)
    assert old['selected_index']==1
    new=fair(p,c,s,m,v,[.25,.15,0.])
    assert new['selected_index']==new['plain_index']==0
    assert new['baseline']['same_lift_plain_ei']>new['lifted_ei'][1]>new['plain_original_ei']
    assert new['reason']=='not_above_fair_plain_ei'
    assert new['shift'][0]==0.

def test_real_same_context_numeric_reversal_is_blocked_without_true_objectives(tmp_path,monkeypatch):
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=[[.1]*6,[.5]*6,[.55]*6],
        mean=[-1.1726868589147406,-1.142040222904165,-1.1524805309769817],
        std=[.19816554588804217,.19444113264373045,.1890161677505137])
    c.scalarization.best=-1.112217693670529
    result=fair(p,c,s,m,v,[.020627509371095403,.028476954073944884,.027782284127132805])
    assert result['selected_index']==0
    assert result['baseline']['same_lift_plain_ei']==pytest.approx(.12613408659345152)
    assert result['lifted_ei'][2]==pytest.approx(.1142632508951979)
    assert result['baseline']['required_ei']>=result['plain_original_ei']

def test_fair_strategy_can_adopt_despite_larger_unqualified_outside_winner(tmp_path,monkeypatch):
    p,c,s,m,v=fixture(tmp_path,monkeypatch)
    result=fair(p,c,s,m,v,[0.,.15,.25])
    assert result['selected_index']==1 and result['unrestricted_lifted_index']==2
    assert result['reason']=='strict_improvement'
    assert result['baseline']['advantage']>0

def test_exact_fair_tie_keeps_plain_and_alternative_ties_use_stable_ID(tmp_path,monkeypatch):
    from llmbo_para.runstore import digest_value
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=[[.1]*6,[.5]*6,[.55]*6],mean=[0.,0.,0.])
    tie=fair(p,c,s,m,v,[.2,.2,.2]);assert tie['selected_index']==0
    win=fair(p,c,s,m,v,[0.,.2,.2])
    expected=min((1,2),key=lambda i:digest_value({'context_id':c.context_id,'point':list(c.pool[i])}))
    assert win['selected_index']==expected

def test_empty_region_keeps_plain_and_records_the_fair_baseline(tmp_path,monkeypatch):
    p,c,s,m,v=fixture(tmp_path,monkeypatch)
    result=fair(p,c,s,m,v,[.2,.2,.2],{'lb':[.6]*6,'ub':[.8]*6})
    assert result['selected_index']==0 and result['reason']=='no_challenger'
    assert result['baseline']['advantage'] is None

def test_original_competition_default_remains_identical(tmp_path,monkeypatch):
    from llmbo_para.electrothermal_region_selection import eligible_region_competition
    p,c,s,m,v=fixture(tmp_path,monkeypatch)
    args=dict(mean=m,std=v,raw_shift=[.25,.15,0.],space=p.space,settings=s)
    region={'lb':[.4]*6,'ub':[.6]*6}
    old=eligible_region_competition(c,region,**args)
    explicit=eligible_region_competition(c,region,selection_mode='eligible_region_v1',**args)
    assert old==explicit and old['selected_index']==1 and 'baseline' not in old

def test_psd_covariance_allows_fair_adoption_without_changing_raw_GP(tmp_path,monkeypatch):
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.surrogate import Matern52GP
    from test_electrothermal_region import response
    pool=np.asarray([[.1]*6,[.41]*6,[.701]+[.64]*5])
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=pool.tolist(),mean=[-.01,-.005,-.006],std=[.5]*3)
    c.ordinal=0;c.fit_rates=p.dataset.fit_rates;c.signatures_json=json.dumps(asdict(p.signatures))
    class GP:
        x=np.full((2,6),.05)
        def predict(self,x):
            x=np.asarray(x);mu=-.05*np.sum(x,axis=1)
            for point,value in zip(pool,[-.01,-.005,-.006]):mu[np.all(x==point,axis=1)]=value
            return mu,np.full(len(x),.5)
        def posterior_covariance(self,a,b=None):
            a=np.asarray(a);b=a if b is None else np.asarray(b)
            return .25*np.exp(-np.sum((a[:,None]-b[None,:])**2,axis=2)/.16)
    monkeypatch.setattr(Matern52GP,'from_state',lambda state:GP())
    reply=response(c);reply['region'].update(lb=[.4]*6,ub=[.7]*6)
    before=pool.copy()
    old=apply_electrothermal_region(GP(),c,c.pool,reply,settings=s,trust=.5,space=p.space,
        advice_mode='candidate_aware_v1',selection_mode='eligible_region_v1')
    new=apply_electrothermal_region(GP(),c,c.pool,reply,settings=s,trust=.5,space=p.space,
        advice_mode='candidate_aware_v1',selection_mode='fair_region_v1')
    assert new['accepted'] and new['selected_index']==1
    for field in ('mean','std','raw_shift','anchors','anchor_weights','correlation'):
        np.testing.assert_array_equal(new[field],old[field])
    np.testing.assert_array_equal(pool,before)
    assert new['shift'][0]==0.
    assert np.linalg.eigvalsh(GP().posterior_covariance(np.vstack([pool,new['anchors']]))).min()>0.

def fair_run(root):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    cfg=_shared_initialization(root)
    cfg['optimization'].update(region_advice='candidate_aware_v1',region_selection='fair_region_v1')
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100.,min_sigma_ratio=0.)
    class Advice:
        def post(self,payload):
            requirements=payload['region_requirements']
            assert requirements['selection_policy']=='fair_region_v1'
            assert requirements['plain_baseline']=='max_original_and_same_raw_lift_EI'
            row=next(r for r in payload['candidate_advice']['candidates'] if r['eligible_alternative'])
            x=np.asarray(row['normalized_parameters']);lb=np.clip(x-.05,0.,.9);ub=lb+.1
            return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}|{
                'region':{'kind':'region','coordinate_space':'normalized','lb':lb.tolist(),'ub':ub.tolist(),
                    'confidence':.9,'reason':'scripted software fixture; no unobserved objectives'}}
    result=run_electrothermal_experiment(cfg,root,base_dir=root,
        llm_controller=ElectrothermalLLMController(transport=Advice(),is_mock=True))
    return Path(result['run_directory'])

@pytest.mark.parametrize('damage',['none','baseline','raw_plain_lift','policy','payload_baseline'])
def test_fair_run_and_audit_reject_comparison_tampering(tmp_path,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    root=fair_run(tmp_path)
    assert audit_electrothermal_run(root,deep=True)['passed']
    if damage=='none':return
    files=sorted((root/'mo-rounds').glob('*.json'))
    path=next(f for f in files if 'selection_details' in json.loads(f.read_text())['region'])
    event=json.loads(path.read_text())
    if damage=='payload_baseline':
        n=event['region']['request_outcome']['ordinal'];path=root/'llm'/f'{n:06d}.payload.json';event=json.loads(path.read_text())
        event['region_requirements']['plain_baseline']='original_EI'
    elif damage=='baseline':event['region']['selection_details']['baseline']['required_ei']+=.001
    elif damage=='raw_plain_lift':event['region']['raw_shift'][event['region']['plain_index']]+=.001
    else:event['region']['selection_policy']='eligible_region_v1'
    path.write_text(json.dumps(event))
    assert not audit_electrothermal_run(root,deep=True)['passed']
