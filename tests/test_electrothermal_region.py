import json
from dataclasses import asdict,replace
import numpy as np
import pytest


def context_fixture(tmp_path):
    from test_mo_optimizer import make_optimizer
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from electrothermal_fixtures import et_config
    opt=make_optimizer(tmp_path);opt.initialize();opt.step()
    _,prepared=prepare_electrothermal_experiment(et_config(),base_dir=tmp_path)
    return opt,prepared,opt.last_context


def response(context,**changes):
    return dict(schema_version=2,parameter_profile='electrothermal_4e2t',fit_rates=list(context.fit_rates),
        signatures=json.loads(context.signatures_json),context_id=context.context_id,
        region={'kind':'region','coordinate_space':'normalized','lb':[.1]*6,'ub':[.9]*6,'confidence':.9,'reason':'test'},**changes)


def test_region_uses_current_posterior_covariance_and_changes_only_acquisition(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload,apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    opt,p,c=context_fixture(tmp_path);before=json.dumps(opt.gp.state_dict(),sort_keys=True)
    payload=build_electrothermal_payload('region_preference_electrothermal',prepared=p,history=opt.history[:2],context=c)
    assert payload['context']['weights']==list(c.scalarization.weights) and payload['context']['ideal']==[0,0]
    assert payload['context_id']==c.context_id and payload['pareto'] and 200<=len(payload['instructions'].split())<=300
    result=apply_electrothermal_region(opt.gp,c,c.pool,response(c),settings=InformedSettings(),trust=.5,space=p.space)
    mean,std=opt.gp.predict(c.pool)
    assert result['std']==pytest.approx(std) and result['mean']==pytest.approx(mean)
    assert np.all(np.asarray(result['shift'])>=0) and max(result['shift'])<=.25
    assert 'anchors' in result and result['anchor_weights']
    assert json.dumps(opt.gp.state_dict(),sort_keys=True)==before


@pytest.mark.parametrize('damage',['legacy','stale','signature','low','outside','abstain','zero_covariance'])
def test_bad_low_confidence_outside_region_stale_context_and_abstention_fall_back(tmp_path,damage,monkeypatch):
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    from llmbo_para.acquisition import gaussian_ei
    opt,p,c=context_fixture(tmp_path);r=response(c)
    if damage=='legacy':r={'kind':'region'}
    if damage=='stale':r['context_id']='old'
    if damage=='signature':r['signatures']['comparison_protocol']='old'
    if damage=='low':r['region']['confidence']=.1
    if damage=='outside':r['region']['ub']=[1.1]*6
    if damage=='abstain':r['region']={'kind':'none','coordinate_space':'normalized','confidence':0,'reason':'abstain'}
    if damage=='zero_covariance':monkeypatch.setattr(opt.gp,'posterior_covariance',lambda a,b=None:np.zeros((len(a),len(a) if b is None else len(b))))
    result=apply_electrothermal_region(opt.gp,c,c.pool,r,settings=InformedSettings(),trust=.5,space=p.space)
    m,s=opt.gp.predict(c.pool);plain=int(np.argmax(gaussian_ei(m,s,c.scalarization.best)))
    assert not result['accepted'] and result['selected_index']==plain and result['fallback_reason']


def test_trust_compares_in_frozen_weight_and_does_not_reward_cache(tmp_path):
    from llmbo_para.electrothermal_llm import update_electrothermal_trust
    opt,p,c=context_fixture(tmp_path);r=replace(opt.history[0],objectives=(0.,0.))
    a=update_electrothermal_trust(c,r,previous_trust=.5,beta=.2,adoption={'accepted':True,'cached':False})
    assert a['trust_after']==pytest.approx(.6) and a['success']==1 and a['context_id']==c.context_id
    b=update_electrothermal_trust(c,replace(r,objectives=None,complete_pair_valid=False),previous_trust=.5,beta=.2,adoption={'accepted':True,'cached':False})
    assert b['trust_after']==pytest.approx(.4) and b['new_scalar'] is None
    for adoption in ({'accepted':False,'cached':False},{'accepted':True,'cached':True}):
        assert update_electrothermal_trust(c,r,previous_trust=.5,beta=.2,adoption=adoption)['trust_after']==.5


def test_region_can_change_pick_with_a_psd_posterior_fixture(tmp_path):
    from llmbo_para.electrothermal_llm import apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    opt,p,c=context_fixture(tmp_path)
    class GP:
        x=np.full((2,6),.05)
        def predict(self,x):return .01*np.asarray(x)[:,0],np.full(len(x),.5)
        def posterior_covariance(self,a,b=None):
            a=np.asarray(a);b=a if b is None else np.asarray(b)
            return .25*np.exp(-np.sum((a[:,None]-b[None,:])**2,axis=2)/.04)
    r=response(c);r['region'].update(lb=[.4]*6,ub=[.7]*6)
    settings=replace(InformedSettings(),min_sigma_ratio=0.,max_plain_log_ei_gap=1.)
    c=replace(c,ordinal=0)
    result=apply_electrothermal_region(GP(),c,[[.1]*6,[.55]*6],r,settings=settings,trust=1.,space=p.space)
    assert result['accepted'] and result['plain_index']==0 and result['selected_index']==1
