"""Versioned Prompt evidence; the frozen scalar GP is not an explanation target."""
from copy import deepcopy
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

PACKAGE=Path(__file__).resolve().parents[1]/'src/llmbo_para'


def evidence(y,**changes):
    assert (PACKAGE/'electrothermal_region_context.py').is_file(),'weighted objective evidence is missing'
    from llmbo_para.electrothermal_region_context import weighted_objective_evidence
    args=dict(weights=[.8,.2],objective_scales=[.1,1.],ideal=[0.,0.],rho_aug=.05)
    args.update(changes)
    return weighted_objective_evidence(y,**args)


def test_known_weighted_bottleneck_and_exact_ties():
    actual=evidence([.04,.3])
    assert actual['version']=='weighted_tchebycheff_v1'
    assert actual['weighted_components']==pytest.approx([.32,.06])
    assert actual['max_component']==pytest.approx(.32)
    assert actual['augmented_scalar']==pytest.approx(.339)
    assert actual['active_objectives']==['F_U_V']
    tied=evidence([.05,.5],weights=[.5,.5])
    assert tied['weighted_components']==[.25,.25]
    assert tied['augmented_scalar']==.275 and tied['active_objectives']==['F_U_V','F_T_K']
    assert evidence([.050000000001,.5],weights=[.5,.5])['active_objectives']==['F_U_V']


@pytest.mark.parametrize('y,weights',[([0.,0.],[.8,.2]),([.04,.3],[1.,0.]),([.04,.3],[0.,1.]),([.8,.4],[.5,.5])])
def test_matches_unrounded_frozen_scalarization(y,weights):
    from llmbo_para.scalarization import augmented_tchebycheff
    actual=evidence(tuple(y),weights=tuple(weights))
    assert actual['augmented_scalar']==float(augmented_tchebycheff([y],weights,[.1,1.],rho_aug=.05)[0])


def test_voltage_unit_change_with_matching_scale_preserves_interpretation():
    first=evidence([.04,.3]);second=evidence([40.,.3],objective_scales=[100.,1.])
    np.testing.assert_allclose(first['weighted_components'],second['weighted_components'],rtol=1e-14)
    assert first['active_objectives']==second['active_objectives']
    assert first['augmented_scalar']==pytest.approx(second['augmented_scalar'],rel=1e-14)


@pytest.mark.parametrize('y,changes',[
    ([True,.3],{}),([np.float64(.04),.3],{}),([float('nan'),.3],{}),([-.1,.3],{}),([.1],{}),
    ([.1,.2,.3],{}),('bad',{}),([.1,.2],{'weights':[True,False]}),([.1,.2],{'weights':[.8,.3]}),
    ([.1,.2],{'weights':[-.1,1.1]}),([.1,.2],{'objective_scales':[0.,1.]}),
    ([.1,.2],{'objective_scales':[1.,float('inf')]}),([.1,.2],{'ideal':[1.,0.]}),
    ([.1,.2],{'ideal':[False,0.]}),([.1,.2],{'rho_aug':True}),([.1,.2],{'rho_aug':-.1}),
    ([1e308,.2],{'objective_scales':[1e-308,1.]}),([1e308,.2],{'rho_aug':1e308})])
def test_invalid_or_overflowing_evidence_is_rejected(y,changes):
    with pytest.raises(ValueError):evidence(y,**changes)


def frozen_identities(payload):
    fixed=deepcopy(payload)
    sig={k:('frozen' if k!='fit_rates' else v) for k,v in fixed['signatures'].items()}
    fixed['signatures']=sig;fixed['context_id']='context-fixed'
    props=fixed['response_contract']['properties']
    props['signatures']['const']=deepcopy(sig);props['context_id']['const']='context-fixed'
    return fixed


def v2_request(tmp_path):
    from lgbo_fixtures import prepared_request
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.runstore import digest_value
    old,rows,context,_=prepared_request(tmp_path)
    cfg=deepcopy(old.config);cfg['optimization']['region_method']='lgbo_v2'
    report,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert report['ready'],report['errors']
    context=replace(context,signatures_json=json.dumps(asdict(prepared.signatures)),
        context_id=digest_value({'previous':context.context_id,'signatures':asdict(prepared.signatures)}))
    return prepared,rows,context,build_electrothermal_payload('region_preference_electrothermal',prepared=prepared,history=rows,context=context)


def test_v1_payload_and_prompt_bytes_preserve_pre_change_golden(tmp_path):
    from lgbo_fixtures import prepared_request
    from llmbo_para.runstore import canonical_json
    *_,payload=prepared_request(tmp_path)
    assert hashlib.sha256(canonical_json(frozen_identities(payload))).hexdigest()=='77f3a8ca4e03e024578fff5bf9f9a35350bdb4a2b5272a7afdd153b34dbb39c2'
    assert hashlib.sha256((PACKAGE/'prompts/region_preference_lgbo_electrothermal.txt').read_bytes()).hexdigest()=='07ff091094194b9355cca1537b1a6d7bd2f4c185a121612011481ecd8bbaede7'


def test_method_version_is_single_and_rejects_legacy_policy_mix(tmp_path):
    from llmbo_para import electrothermal_lgbo as lgbo
    assert hasattr(lgbo,'is_lgbo_method'),'method dispatcher is missing'
    assert lgbo.METHOD=='lgbo_v1'
    assert all(lgbo.is_lgbo_method(x) for x in ('lgbo_v1','lgbo_v2'))
    assert not any(lgbo.is_lgbo_method(x) for x in ('lgbo_v3',True,None,{},['lgbo_v1']))
    assert lgbo.lgbo_prompt_filename('lgbo_v1')=='region_preference_lgbo_electrothermal.txt'
    assert lgbo.lgbo_prompt_filename('lgbo_v2')=='region_preference_lgbo_v2_electrothermal.txt'
    with pytest.raises(ValueError):lgbo.lgbo_prompt_filename('lgbo_v3')
    prepared,*_=v2_request(tmp_path)
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    for key,value in [('region',{'min_confidence':.8}),('region_evidence','dynamic_decision_v3'),('region_proposal','catalog_v1')]:
        cfg=deepcopy(prepared.config);cfg['optimization'][key]=value
        assert electrothermal_configuration_errors(cfg)
    cfg=deepcopy(prepared.config);cfg['llm']['region_wire_format']='compact_v1'
    assert electrothermal_configuration_errors(cfg)


def test_v2_explains_rows_without_changing_warmstart_or_scalar_labels(tmp_path):
    prepared,rows,context,payload=v2_request(tmp_path)
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    for row in payload['history']:
        checked=evidence(row['objectives'],weights=context.scalarization.weights,objective_scales=context.scalarization.objective_scales,
            ideal=context.scalarization.ideal,rho_aug=context.scalarization.rho_aug)
        assert row['weighted_objective_evidence']==checked
        assert checked['augmented_scalar']==row['current_scalar_g']
    warm=build_electrothermal_payload('warm_start_electrothermal',prepared=prepared,history=rows)
    assert all('weighted_objective_evidence' not in row for row in warm['history'])
    assert 'region_method' not in warm
    prompt=payload['instructions']
    assert 200<=len(prompt.split())<=300
    assert 'wide' in prompt.lower() and 'temperature' in prompt.lower() and 'request_id' in prompt
