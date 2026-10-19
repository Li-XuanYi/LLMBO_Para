"""Explicit Region competition policy, independent of LLM quality or DFN."""
from dataclasses import asdict, replace
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest


def fixture(tmp_path, monkeypatch, *, pool=None, mean=None, std=None):
    from test_region_candidate_advice import advice_fixture
    pool = pool if pool is not None else [[.1]*6,[.5]*6,[.9]*6]
    mean = mean if mean is not None else [0.,.1,.15]
    std = std if std is not None else [1.]*len(pool)
    p,c,settings = advice_fixture(tmp_path,monkeypatch,pool=pool,mean=mean,std=std)
    return p,c,settings,np.asarray(mean),np.asarray(std)


def compete(p,c,settings,mean,std,shift,*,region=None):
    from llmbo_para.electrothermal_region_selection import eligible_region_competition
    return eligible_region_competition(c,region or {'lb':[.4]*6,'ub':[.6]*6},
        mean=mean,std=std,raw_shift=shift,space=p.space,settings=settings)


def test_inside_challenger_survives_larger_outside_lift(tmp_path,monkeypatch):
    p,c,s,m,v = fixture(tmp_path,monkeypatch)
    before=(m.copy(),v.copy())
    result=compete(p,c,s,m,v,[0.,.15,.25])
    assert result['unrestricted_lifted_index']==2
    assert result['selected_index']==1 and result['plain_index']==0
    assert result['challenger_indices']==[1]
    assert result['shift']==[0.,.15,0.]
    assert result['lifted_ei'][1]>result['lifted_ei'][0]
    assert result['reason']=='strict_improvement'
    np.testing.assert_array_equal(m,before[0]);np.testing.assert_array_equal(v,before[1])


def test_plain_uses_original_EI_even_when_inside_region(tmp_path,monkeypatch):
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=[[.5]*6,[.55]*6,[.9]*6])
    result=compete(p,c,s,m,v,[.25,.15,0.])
    assert result['unrestricted_lifted_index']==0
    assert result['selected_index']==1 and result['shift'][0]==0.


@pytest.mark.parametrize('raw',[0.,.001])
def test_no_strict_advantage_keeps_plain(tmp_path,monkeypatch,raw):
    p,c,s,m,v=fixture(tmp_path,monkeypatch,mean=[0.,.1,.15])
    result=compete(p,c,s,m,v,[0.,raw,.25])
    assert result['selected_index']==0 and result['reason']=='not_above_plain_ei'


def test_exact_tie_prefers_plain_and_alternative_ties_use_stable_ID(tmp_path,monkeypatch):
    from llmbo_para.runstore import digest_value
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=[[.1]*6,[.5]*6,[.55]*6],mean=[0.,0.,0.])
    tied=compete(p,c,s,m,v,[0.,0.,0.])
    assert tied['selected_index']==0
    lifted=compete(p,c,s,m,v,[0.,.2,.2])
    expected=min((1,2),key=lambda i:digest_value({'context_id':c.context_id,'point':list(c.pool[i])}))
    assert lifted['selected_index']==expected


def test_mask_excludes_outside_low_sigma_bad_EI_observed_duplicate_and_illegal(tmp_path,monkeypatch):
    pool=[[.1]*6,[.5]*6,[.5]*6,[.05]*6,[.6]*6,[.7]*6,[.9]*6,[.95]*6]
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=pool,mean=[0.,.05,.05,0.,-.1,2.,.01,.01],std=[1.,1.,1.,1.,.8,1.,1.,1.])
    original=p.space
    def legal(x):
        if x[0]==.9:raise ValueError('injected physical exclusion')
        return original.denormalize(x)
    p.space=SimpleNamespace(denormalize=legal)
    result=compete(p,c,s,m,v,[.25]*8,region={'lb':[.4]*6,'ub':[.92]*6})
    assert result['eligible_indices']==[1,7] and result['challenger_indices']==[1]
    assert result['selected_index']==1
    assert result['shift']==[0.,.25,0.,0.,0.,0.,0.,0.]


def test_competition_uses_full_pool_not_only_display_shortlist(tmp_path,monkeypatch):
    from llmbo_para.electrothermal_region_advice import build_region_candidate_advice
    pool=[[i/32]*6 for i in range(1,27)]
    p,c,s,m,v=fixture(tmp_path,monkeypatch,pool=pool,mean=[0.]+[.05]*25)
    advice=build_region_candidate_advice(c,space=p.space,settings=s)
    shown={row['pool_index'] for row in advice['candidates']}
    hidden=next(i for i in range(1,26) if i not in shown)
    raw=np.full(26,.1);raw[hidden]=.25
    result=compete(p,c,s,m,v,raw,region={'lb':[.03]*6,'ub':[.83]*6})
    assert len(advice['candidates'])==12 and hidden not in shown
    assert result['selected_index']==hidden


def test_region_boundaries_are_inclusive_and_empty_region_keeps_plain(tmp_path,monkeypatch):
    p,c,s,m,v=fixture(tmp_path,monkeypatch)
    for lb,ub in ((.4,.5),(.5,.6)):
        result=compete(p,c,s,m,v,[0.,.2,0.],region={'lb':[lb]*6,'ub':[ub]*6})
        assert result['selected_index']==1
    result=compete(p,c,s,m,v,[0.,.2,0.],region={'lb':[.6]*6,'ub':[.8]*6})
    assert result['selected_index']==0 and result['reason']=='no_challenger'


@pytest.mark.parametrize('raw',[[0.,-.1,.2],[0.,.26,.2],[0.,float('nan'),.2],[0.,.2]])
def test_raw_shift_must_be_aligned_finite_and_bounded(tmp_path,monkeypatch,raw):
    p,c,s,m,v=fixture(tmp_path,monkeypatch)
    with pytest.raises(ValueError):compete(p,c,s,m,v,raw)


def test_zero_EI_uses_original_floored_qualification(tmp_path,monkeypatch):
    p,c,s,m,v=fixture(tmp_path,monkeypatch,mean=[100.,100.,100.])
    result=compete(p,c,s,m,v,[0.,.2,0.])
    assert result['eligible_indices']==[1,2] and result['selected_index']==0


def test_selection_config_is_explicit_strict_and_algorithm_only(tmp_path):
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg=et_config();cfg['optimization']['region_advice']='candidate_aware_v1'
    _,before=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    cfg['optimization']['region_selection']='eligible_region_v1'
    report,after=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert after is not None,report
    assert before.signatures.algorithm!=after.signatures.algorithm
    assert before.signatures.initialization_compatibility==after.signatures.initialization_compatibility
    assert before.signatures.comparison_protocol==after.signatures.comparison_protocol
    cfg['optimization']['region_advice']='legacy_v1'
    assert prepare_electrothermal_experiment(cfg,base_dir=tmp_path)[1] is None
    cfg['optimization']['region_advice']='candidate_aware_v1'
    cfg['optimization']['region_selection']='unknown'
    assert prepare_electrothermal_experiment(cfg,base_dir=tmp_path)[1] is None


def test_new_selection_preserves_raw_lift_and_original_GP(tmp_path,monkeypatch):
    from test_region_candidate_advice import real_context,changed_context
    from test_electrothermal_region import response
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.informed import InformedSettings
    opt,p,c=real_context(tmp_path)
    before=json.dumps(opt.gp.state_dict(),sort_keys=True)
    class GP:
        x=np.full((2,6),.05)
        def predict(self,x):return .01*np.asarray(x)[:,0],np.full(len(x),.5)
        def posterior_covariance(self,a,b=None):
            a=np.asarray(a);b=a if b is None else np.asarray(b)
            return .25*np.exp(-np.sum((a[:,None]-b[None,:])**2,axis=2)/.04)
    monkeypatch.setattr(Matern52GP,'from_state',lambda state:GP())
    c=changed_context(c,pool=((.1,)*6,(.55,)*6),ordinal=0)
    reply=response(c);reply['region'].update(lb=[.4]*6,ub=[.7]*6)
    settings=InformedSettings()
    old=apply_electrothermal_region(GP(),c,c.pool,reply,settings=settings,trust=1.,space=p.space,advice_mode='candidate_aware_v1')
    new=apply_electrothermal_region(GP(),c,c.pool,reply,settings=settings,trust=1.,space=p.space,
        advice_mode='candidate_aware_v1',selection_mode='eligible_region_v1')
    assert new['selection_policy']=='eligible_region_v1' and new['accepted']
    np.testing.assert_array_equal(new['raw_shift'],old['shift'])
    for key in ('mean','std','anchors','anchor_weights','correlation'):
        np.testing.assert_array_equal(new[key],old[key])
    assert new['shift'][0]==0. and new['shift'][1]==old['shift'][1]
    assert 'selection_policy' not in old
    assert json.dumps(opt.gp.state_dict(),sort_keys=True)==before


def test_psd_covariance_reproduces_outside_winner_rejection_and_inside_recovery(tmp_path,monkeypatch):
    from test_electrothermal_region import response
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.surrogate import Matern52GP
    pool=np.asarray([[.1]*6,[.41]*6,[.701]+[.64]*5])
    p,c,settings,m,v=fixture(tmp_path,monkeypatch,pool=pool.tolist(),mean=[-.01,-.005,-.006],std=[.5]*3)
    c.ordinal=0;c.fit_rates=p.dataset.fit_rates;c.signatures_json=json.dumps(asdict(p.signatures))
    class GP:
        x=np.full((2,6),.05)
        def predict(self,x):
            x=np.asarray(x);mean=-.05*np.sum(x,axis=1)
            for point,value in zip(pool,[-.01,-.005,-.006]):mean[np.all(x==point,axis=1)]=value
            return mean,np.full(len(x),.5)
        def posterior_covariance(self,a,b=None):
            a=np.asarray(a);b=a if b is None else np.asarray(b)
            return .25*np.exp(-np.sum((a[:,None]-b[None,:])**2,axis=2)/.16)
    monkeypatch.setattr(Matern52GP,'from_state',lambda state:GP())
    r=response(c);r['region'].update(lb=[.4]*6,ub=[.7]*6)
    old=apply_electrothermal_region(GP(),c,c.pool,r,settings=settings,trust=.5,space=p.space,advice_mode='candidate_aware_v1')
    assert old['fallback_reason']=='outside_region' and old['lifted_index']==2 and old['selected_index']==0
    new=apply_electrothermal_region(GP(),c,c.pool,r,settings=settings,trust=.5,space=p.space,
        advice_mode='candidate_aware_v1',selection_mode='eligible_region_v1')
    assert new['accepted'] and new['selected_index']==1
    assert new['lifted_ei'][1]>old['plain_ei'][0]
    np.testing.assert_array_equal(new['raw_shift'],old['shift'])
    combined=np.vstack([pool,old['anchors']])
    assert np.linalg.eigvalsh(GP().posterior_covariance(combined)).min()>0.


def test_apply_rejects_new_selection_without_candidate_aware_advice(tmp_path):
    from test_region_candidate_advice import real_context
    from test_electrothermal_region import response
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    opt,p,c=real_context(tmp_path)
    with pytest.raises(ValueError):
        apply_electrothermal_region(opt.gp,c,c.pool,response(c),settings=InformedSettings(),trust=.5,space=p.space,
            selection_mode='eligible_region_v1')


def competition_run(root):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    cfg=_shared_initialization(root)
    cfg['optimization'].update(region_advice='candidate_aware_v1',region_selection='eligible_region_v1')
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100.,min_sigma_ratio=0.)
    class Advice:
        def post(self,payload):
            assert payload['region_requirements']['selection_policy']=='eligible_region_v1'
            row=next(r for r in payload['candidate_advice']['candidates'] if r['eligible_alternative'])
            x=np.asarray(row['normalized_parameters']);lb=np.clip(x-.05,0.,.9);ub=lb+.1
            return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}|{
                'region':{'kind':'region','coordinate_space':'normalized','confidence':.9,'reason':'scripted software fixture',
                          'lb':lb.tolist(),'ub':ub.tolist()}}
    result=run_electrothermal_experiment(cfg,root,base_dir=root,
        llm_controller=ElectrothermalLLMController(transport=Advice(),is_mock=True))
    return Path(result['run_directory'])


@pytest.mark.parametrize('damage',['none','policy','raw_shift','active_shift','challengers','winner','payload_policy'])
def test_competition_run_replays_and_rejects_policy_or_mask_tampering(tmp_path,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    root=competition_run(tmp_path)
    assert audit_electrothermal_run(root,deep=True)['passed']
    if damage=='none':return
    files=sorted((root/'mo-rounds').glob('*.json'))
    file=next(f for f in files if 'selection_details' in json.loads(f.read_text(encoding='utf8'))['region'])
    event=json.loads(file.read_text(encoding='utf8'))
    if damage=='payload_policy':
        ordinal=event['region']['request_outcome']['ordinal'];file=root/'llm'/f'{ordinal:06d}.payload.json'
        event=json.loads(file.read_text(encoding='utf8'));event['region_requirements']['selection_policy']='global_lift_v1'
    elif damage=='policy':event['region']['selection_policy']='global_lift_v1'
    elif damage=='raw_shift':event['region']['raw_shift'][0]+=.001
    elif damage=='active_shift':event['region']['shift'][event['region']['plain_index']]=.001
    elif damage=='challengers':event['region']['selection_details']['challenger_indices']=[]
    else:event['selected_index']=(event['selected_index']+1)%len(event['ei'])
    file.write_text(json.dumps(event),encoding='utf8')
    assert not audit_electrothermal_run(root,deep=True)['passed']
