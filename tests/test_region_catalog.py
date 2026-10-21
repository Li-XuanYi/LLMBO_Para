"""Host geometry and request-bound IDs cannot fabricate preference or outcomes."""
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from electrothermal_fixtures import et_config


def feature():
    name = 'llmbo_para.electrothermal_region_catalog'
    assert importlib.util.find_spec(name) is not None, 'request-bound Region catalog is not implemented'
    return importlib.import_module(name)


def context_advice():
    from test_region_decision_evidence import numeric_context,numeric_advice
    from llmbo_para.runstore import digest_value
    context = numeric_context(); advice = numeric_advice(context)
    advice['pool_digest'] = digest_value(context.pool)
    for row in advice['candidates']:
        row['candidate_id'] = digest_value({'context_id':context.context_id,'point':row['normalized_parameters']})
    return context,advice


def payload(*,wire='full_v1',width=.03,maximum=.8):
    module = feature(); context,advice = context_advice()
    catalog = module.build_region_catalog(context,advice=advice,settings=SimpleNamespace(min_width=width,max_width=maximum))
    value = {'task':'region_preference_electrothermal','schema_version':2,'parameter_profile':'electrothermal_4e2t',
        'fit_rates':['0.5C','1C'],'signatures':{'fit_rates':['0.5C','1C'],'source':'controlled-software-context'},
        'context_id':context.context_id,'context':{'weights':[.2,.8]},'objective_scales':[.1,1.],
        'history':[{'evaluation_id':'past-a'},{'evaluation_id':'past-b'}],
        'dynamic_history_evidence':{'version':'dynamic_residual_v1'},'candidate_advice':advice,
        'region_catalog':catalog,'region_proposal':'catalog_v1','instructions':'Controlled formal JSON fixture.',
        'simulation_kind':'synthetic_software','model_provider':'software'}
    if wire=='compact_v1':value['region_wire_format'] = wire
    value['proposal_binding'] = module.catalog_proposal_binding(value)
    value['response_contract'] = {'type':'object','additionalProperties':False,
        'required':['schema_version','parameter_profile','fit_rates','signatures','context_id','region'],
        'properties':{**{k:{'const':value[k]} for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')},
                      'region':module.catalog_region_contract(value)}}
    return value


def reply(value,kind='region'):
    region = {'kind':kind,'coordinate_space':'normalized','proposal_binding':value['proposal_binding'],
              'confidence':.9,'reason':'Controlled hypothesis supported by past evidence.'}
    if kind=='region':region.update(region_id=value['region_catalog']['entries'][0]['region_id'],evidence_ids=['past-a'])
    return {**{k:deepcopy(value[k]) for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')},'region':region}


def config():
    cfg = et_config(); cfg['optimization'].update(region_evidence='dynamic_decision_v3',region_proposal='catalog_v1',
        region_advice='candidate_aware_v1',region_selection='fair_region_v1')
    return cfg


def test_catalog_is_deterministic_bounded_and_contains_no_plain_entry():
    from llmbo_para.runstore import digest_value
    module = feature(); context,advice = context_advice(); settings=SimpleNamespace(min_width=.03,max_width=.8)
    before = digest_value({'context':context.to_dict(),'advice':advice})
    catalog = module.build_region_catalog(context,advice=advice,settings=settings)
    assert catalog == module.build_region_catalog(context,advice=advice,settings=settings)
    assert catalog['version'] == 'region_catalog_v1' and catalog['context_id'] == context.context_id
    entries = catalog['entries']; assert len(entries)==6 and len({e['region_id'] for e in entries})==6
    assert [e['width'] for e in entries] == [.03,.06,.12,.03,.06,.12]
    assert [e['pool_index'] for e in entries] == [1,1,1,2,2,2]
    assert all(e['candidate_id']!=advice['candidates'][0]['candidate_id'] and 'confidence' not in e for e in entries)
    for e in entries:
        lo=np.asarray(e['lb']);hi=np.asarray(e['ub']);point=np.asarray(context.pool[e['pool_index']])
        assert np.all(0<=lo) and np.all(hi<=1) and np.all(lo<=point) and np.all(point<=hi)
        np.testing.assert_allclose(hi-lo,[e['width']]*6,rtol=0,atol=2e-16)
    assert entries[0]['lb'][0]==0. and entries[0]['ub'][-1]==1.
    assert before == digest_value({'context':context.to_dict(),'advice':advice})


@pytest.mark.parametrize('width,maximum,expected',[(.03,.03,[.03]),(.03,.05,[.03,.05]),(1.,1.,[1.])])
def test_catalog_deduplicates_clamped_widths_without_shrinking(width,maximum,expected):
    catalog=payload(width=width,maximum=maximum)['region_catalog']
    assert [e['width'] for e in catalog['entries'] if e['pool_index']==1] == expected


def test_catalog_rejects_stale_advice_and_keeps_empty_catalog_honest():
    module=feature();context,advice=context_advice();settings=SimpleNamespace(min_width=.03,max_width=.8)
    wrong=deepcopy(advice);wrong['context_id']='different'
    with pytest.raises(ValueError):module.build_region_catalog(context,advice=wrong,settings=settings)
    advice['candidates']=advice['candidates'][:1];advice['eligible_alternative_count']=0
    assert module.build_region_catalog(context,advice=advice,settings=settings)['entries']==[]


def test_catalog_maximum_shortlist_produces_33_unranked_regions():
    from llmbo_para.runstore import digest_value
    module=feature();_,template=context_advice()
    pool=tuple((i/13.,)*6 for i in range(1,13))
    context=SimpleNamespace(context_id='controlled-12-point-pool',pool=pool)
    candidates=[]
    for index,point in enumerate(pool):
        row=deepcopy(template['candidates'][0 if index==0 else 1])
        row.update(pool_index=index,normalized_parameters=list(point),is_plain=index==0,eligible_alternative=index!=0,
            candidate_id=digest_value({'context_id':context.context_id,'point':list(point)}))
        candidates.append(row)
    advice={**template,'context_id':context.context_id,'pool_digest':digest_value(pool),'pool_count':12,
        'eligible_alternative_count':11,'candidates':candidates}
    catalog=module.build_region_catalog(context,advice=advice,settings=SimpleNamespace(min_width=.03,max_width=.8))
    assert len(catalog['entries'])==33
    assert all('confidence' not in e and 'quality' not in e for e in catalog['entries'])


def test_new_proposal_mode_is_explicit_and_does_not_change_metric_or_initialization_signatures(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg=config();report,new=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert new is not None,report['errors']
    cfg['optimization']['region_proposal']='bounds_v1';_,old=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert new.signatures.algorithm!=old.signatures.algorithm
    assert new.signatures.comparison_protocol==old.signatures.comparison_protocol
    assert new.signatures.initialization_compatibility==old.signatures.initialization_compatibility


@pytest.mark.parametrize('value',[None,True,[], 'unknown'])
def test_unknown_proposal_format_is_rejected(value):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg=config();cfg['optimization']['region_proposal']=value
    assert electrothermal_configuration_errors(cfg)


@pytest.mark.parametrize('evidence,advice,selection',[('decision_geometry_v2','candidate_aware_v1','fair_region_v1'),
    ('dynamic_decision_v3','legacy_v1','fair_region_v1'),('dynamic_decision_v3','candidate_aware_v1','eligible_region_v1')])
def test_catalog_requires_dynamic_candidate_aware_fair_policy(evidence,advice,selection):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg=config();cfg['optimization'].update(region_evidence=evidence,region_advice=advice,region_selection=selection)
    assert electrothermal_configuration_errors(cfg)


@pytest.mark.parametrize('kind',['none','region'])
@pytest.mark.parametrize('wire',['full_v1','compact_v1'])
def test_strict_catalog_reply_resolves_to_existing_canonical_envelope(kind,wire):
    from llmbo_para.electrothermal_region_wire import region_wire_payload,decode_region_wire
    from llmbo_para.electrothermal_llm import validate_electrothermal_region
    module=feature();value=payload(wire=wire);response=reply(value,kind)
    if wire=='compact_v1':
        sent=region_wire_payload(value)
        response=decode_region_wire({'request_id':sent['request_id'],'region':response['region']},value)
    canonical,resolution=module.resolve_catalog_region(response,payload=value)
    validate_electrothermal_region(canonical,expected_context_id=value['context_id'],expected_signatures=value['signatures'])
    assert resolution['proposal_binding']==value['proposal_binding']
    assert canonical['region']['kind']==kind and 'proposal_binding' not in canonical['region']
    if kind=='region':
        entry=value['region_catalog']['entries'][0]
        assert canonical['region']['lb']==entry['lb'] and canonical['region']['ub']==entry['ub']
        assert set(canonical['region'])=={'kind','coordinate_space','confidence','reason','lb','ub'}


@pytest.mark.parametrize('damage',['binding','unknown_id','evidence_future','evidence_duplicate','evidence_many',
    'evidence_tuple','bounds','confidence_bool','confidence_nan','confidence_string','long_reason','context','rates','profile','schema'])
def test_resolver_rejects_wrong_types_old_bounds_and_stale_identity(damage):
    module=feature();value=payload();response=reply(value);region=response['region']
    if damage=='binding':region['proposal_binding']='stale'
    elif damage=='unknown_id':region['region_id']='not_in_catalog'
    elif damage=='evidence_future':region['evidence_ids']=['future']
    elif damage=='evidence_duplicate':region['evidence_ids']=['past-a','past-a']
    elif damage=='evidence_many':region['evidence_ids']=['past-a']*4
    elif damage=='evidence_tuple':region['evidence_ids']=('past-a',)
    elif damage=='bounds':region['lb']=[0.]*6;region['ub']=[1.]*6
    elif damage=='confidence_bool':region['confidence']=True
    elif damage=='confidence_nan':region['confidence']=float('nan')
    elif damage=='confidence_string':region['confidence']='0.9'
    elif damage=='long_reason':region['reason']='x'*401
    elif damage=='context':response['context_id']='old_context'
    elif damage=='rates':response['fit_rates']=['0.5C','1C','3C']
    elif damage=='profile':response['parameter_profile']='legacy_six'
    else:response['schema_version']=True
    with pytest.raises(ValueError):module.resolve_catalog_region(response,payload=value)


@pytest.mark.parametrize('kind',['none','region'])
@pytest.mark.parametrize('change',['history','instructions','weights','scales','catalog'])
def test_same_context_cannot_replay_reply_after_semantic_request_change(kind,change):
    module=feature();value=payload();response=reply(value,kind);new=deepcopy(value)
    if change=='history':new['history'][0]['changed_dynamic_residual']=1.
    elif change=='instructions':new['instructions']+=' Updated task.'
    elif change=='weights':new['context']['weights']=[.8,.2]
    elif change=='scales':new['objective_scales']=[1.,.1]
    else:new['region_catalog']['entries'][0]['lb'][0]=.001
    new['proposal_binding']=module.catalog_proposal_binding(new)
    with pytest.raises(ValueError):module.resolve_catalog_region(response,payload=new)


@pytest.mark.parametrize('kind',['none','region'])
def test_new_compact_wire_binding_does_not_rescue_an_old_proposal_binding(kind):
    from llmbo_para.electrothermal_region_wire import region_wire_payload,decode_region_wire
    module=feature();old=payload(wire='compact_v1');response=reply(old,kind);new=deepcopy(old)
    new['instructions']+=' different frozen evidence'
    new['proposal_binding']=module.catalog_proposal_binding(new)
    new['response_contract']['properties']['region']=module.catalog_region_contract(new)
    wire=region_wire_payload(new)
    decoded=decode_region_wire({'request_id':wire['request_id'],'region':response['region']},new)
    with pytest.raises(ValueError):module.resolve_catalog_region(decoded,payload=new)


class MemoryStore:
    def __init__(self):
        from llmbo_para.electrothermal_store import CostLedger
        self.ledger=CostLedger();self.files={};self.events=[]
    def write_json(self,path,value):self.files[path]=deepcopy(value)
    def append_event(self,value):self.events.append(deepcopy(value))


def test_disabled_real_controller_makes_no_catalog_transport_call():
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    value=payload();cfg=config();store=MemoryStore()
    class Forbidden:
        def post(self,sent):pytest.fail('disabled real API must not be called')
    controller=ElectrothermalLLMController(transport=Forbidden(),is_mock=False)
    assert controller.request(value,prepared=SimpleNamespace(config=cfg),store=store,budgets=cfg['budgets'],request_cap=1) is None
    assert controller.requests==store.ledger.summary()['llm_requests']==0


@pytest.mark.parametrize('behavior',['valid','none','invalid','mutated'])
def test_controller_archives_original_proposal_and_never_repairs_or_retries(behavior):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.runstore import canonical_json
    module=feature();value=payload();before=canonical_json(value);store=MemoryStore();cfg=config()
    class Transport:
        def post(self,sent):
            if behavior=='mutated':
                sent['history'][0]['changed']=True
                sent['proposal_binding']=module.catalog_proposal_binding(sent)
            response=reply(sent,'none' if behavior=='none' else 'region')
            if behavior=='invalid':response['region']['region_id']='not_in_catalog'
            return response
    controller=ElectrothermalLLMController(transport=Transport(),is_mock=True)
    result=controller.request(value,prepared=SimpleNamespace(config=cfg),store=store,budgets=cfg['budgets'],request_cap=1)
    assert canonical_json(value)==before,'transport must not mutate host-owned nested data'
    assert controller.requests==store.ledger.summary()['mock_llm_requests']==1
    assert store.ledger.summary()['llm_requests']==0
    outcome=store.files['llm/000000.outcome.json']
    if behavior in ('invalid','mutated'):
        assert result is None and outcome['status']=='failed' and outcome['reason']=='invalid_catalog_response'
        assert 'llm/000000.catalog-resolution.json' not in store.files
    else:
        assert result['region']['kind']==('none' if behavior=='none' else 'region')
        assert outcome['status']=='received' and 'llm/000000.catalog-resolution.json' in store.files
        assert 'llm/000000.catalog-response.json' in store.files
    assert controller.request(value,prepared=SimpleNamespace(config=cfg),store=store,budgets=cfg['budgets'],request_cap=1) is None
    assert controller.requests==1


@pytest.fixture(scope='module')
def cache():return {}


def run_mode(cache,tmp_path_factory,mode):
    feature()
    if mode not in cache:
        from llmbo_para.electrothermal_llm import ElectrothermalLLMController
        from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
        from test_region_failure_audit import _shared_initialization
        root=tmp_path_factory.mktemp('catalog_'+mode)
        cfg=_shared_initialization(root)
        cfg['optimization'].update(region_evidence='dynamic_decision_v3',region_proposal='catalog_v1',
            region_advice='candidate_aware_v1',region_selection='fair_region_v1',mode=mode if mode in ('parego','warmstart_only') else 'full_llmbo_mo')
        cfg['optimization']['region'].update(max_plain_log_ei_gap=100.,min_sigma_ratio=0.)
        if mode=='compact':cfg['llm']['region_wire_format']='compact_v1'
        class Advice:
            def post(self,sent):
                region={'kind':'none' if mode=='none' else 'region','coordinate_space':'normalized','confidence':.9,'reason':'offline catalog fixture',
                        'proposal_binding':sent['proposal_binding']}
                if region['kind']=='region':region.update(region_id=sent['region_catalog']['entries'][0]['region_id'],
                    evidence_ids=[sent['history'][0]['evaluation_id']])
                if mode=='nan':region['confidence']=float('nan')
                if mode=='secret':region['reason']='sk-fixture-credential000000'
                response={k:deepcopy(sent[k]) for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}|{'region':region}
                if mode=='mutation_old_reply':sent['history'][0]['transport_changed']=True
                return response
        summary=run_electrothermal_experiment(cfg,root,base_dir=root,llm_controller=ElectrothermalLLMController(transport=Advice(),is_mock=True))
        cache[mode]=summary
    return cache[mode]


def test_id_encoding_preserves_the_original_canonical_lift_and_posterior(cache,tmp_path_factory):
    from test_region_dynamic_evidence import payload_context
    from llmbo_para.electrothermal_llm import build_electrothermal_payload,apply_electrothermal_region
    from llmbo_para.informed import InformedSettings
    from llmbo_para.runstore import digest_value
    module=feature();p,opt=payload_context(cache,tmp_path_factory)
    cfg=deepcopy(p.config);cfg['optimization'].update(region_evidence='dynamic_decision_v3',region_proposal='catalog_v1')
    prepared=SimpleNamespace(config=cfg,space=p.space,dataset=p.dataset,signatures=p.signatures)
    past=[r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    value=build_electrothermal_payload('region_preference_electrothermal',prepared=prepared,history=past,context=opt.last_context)
    response=reply(value);response['region']['evidence_ids']=[value['history'][0]['evaluation_id']]
    canonical,_=module.resolve_catalog_region(response,payload=value)
    direct={k:deepcopy(value[k]) for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}
    direct['region']={'kind':'region','coordinate_space':'normalized','confidence':.9,'reason':'direct bounds control',
        'lb':value['region_catalog']['entries'][0]['lb'],'ub':value['region_catalog']['entries'][0]['ub']}
    before=digest_value({'gp':opt.gp.state_dict(),'context':opt.last_context.to_dict()})
    args=dict(settings=InformedSettings.parse(cfg['optimization']['region']),trust=.5,space=p.space,
              advice_mode='candidate_aware_v1',selection_mode='fair_region_v1')
    old=apply_electrothermal_region(opt.gp,opt.last_context,opt.last_context.pool,direct,**args)
    new=apply_electrothermal_region(opt.gp,opt.last_context,opt.last_context.pool,canonical,**args)
    assert new==old
    assert before==digest_value({'gp':opt.gp.state_dict(),'context':opt.last_context.to_dict()})


@pytest.mark.parametrize('mode',['parego','warmstart_only','none','region'])
def test_routes_complete_with_zero_real_api_and_dfn_and_auditable_catalog(cache,tmp_path_factory,mode):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    summary=run_mode(cache,tmp_path_factory,mode)
    assert summary['BO_rounds']==2 and summary['API_calls']==summary['costs']['solver_calls']==0
    root=Path(summary['run_directory'])
    assert audit_electrothermal_run(root,deep=True)['passed']
    if mode in ('region','none'):
        p=json.loads(next((root/'llm').glob('*.payload.json')).read_text())
        assert p['region_proposal']=='catalog_v1' and 200<=len(p['instructions'].split())<=300
        assert list((root/'llm').glob('*.catalog-response.json'))


@pytest.mark.parametrize('damage',['resolution','raw_reply','catalog','binding','contract','coordinated_catalog'])
def test_audit_rebuilds_catalog_and_reply_instead_of_trusting_resolutions(cache,tmp_path_factory,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    module=feature();root=Path(run_mode(cache,tmp_path_factory,'region')['run_directory'])
    paths={key:next((root/'llm').glob(pattern)) for key,pattern in [('payload','*.payload.json'),
        ('resolution','*.catalog-resolution.json'),('raw','*.catalog-response.json')]}
    originals={key:path.read_bytes() for key,path in paths.items()}
    p=json.loads(originals['payload']);r=json.loads(originals['resolution']);raw=json.loads(originals['raw'])
    try:
        if damage=='resolution':r['confidence']=.123;paths['resolution'].write_text(json.dumps(r))
        elif damage=='raw_reply':raw['response_json']='{}';paths['raw'].write_text(json.dumps(raw))
        elif damage=='binding':p['proposal_binding']='forged';paths['payload'].write_text(json.dumps(p))
        elif damage=='contract':p['response_contract']['additionalProperties']=True;paths['payload'].write_text(json.dumps(p))
        else:
            p['region_catalog']['entries'][0]['lb'][0]+=.001
            if damage=='coordinated_catalog':
                p['proposal_binding']=module.catalog_proposal_binding(p)
                r['proposal_binding']=p['proposal_binding']
                paths['resolution'].write_text(json.dumps(r))
            paths['payload'].write_text(json.dumps(p))
        assert not audit_electrothermal_run(root,deep=True)['passed']
    finally:
        for key,path in paths.items():path.write_bytes(originals[key])


def test_transport_mutation_with_original_valid_reply_is_still_auditable(cache,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    summary=run_mode(cache,tmp_path_factory,'mutation_old_reply')
    root=Path(summary['run_directory'])
    for path in (root/'llm').glob('*.outcome.json'):
        outcome=json.loads(path.read_text())
        assert outcome['status']=='failed' and outcome['reason']=='invalid_catalog_response'
    report=audit_electrothermal_run(root,deep=True)
    assert report['passed'],report['issues']


def test_formal_reply_archive_redacts_credentials_before_persisting(cache,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    root=Path(run_mode(cache,tmp_path_factory,'secret')['run_directory'])
    for path in (root/'llm').glob('*.catalog-response.json'):
        assert 'sk-fixture-credential000000' not in path.read_text()
    assert audit_electrothermal_run(root,deep=True)['passed']


@pytest.mark.parametrize('damage',['missing','unchanged','wrong_version','wrong_fields','null_clone','array_clone'])
def test_mutation_fallback_requires_independently_checkable_changed_request(cache,tmp_path_factory,damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    root=Path(run_mode(cache,tmp_path_factory,'mutation_old_reply')['run_directory'])
    path=next((root/'llm').glob('*.catalog-mutation.json'));original=path.read_bytes()
    p=json.loads(path.with_name(path.name.replace('.catalog-mutation','.payload')).read_text())
    proof=json.loads(original)
    try:
        if damage=='missing':path.unlink()
        else:
            if damage=='unchanged':proof['sent_payload_json']=json.dumps(p)
            elif damage=='wrong_version':proof['version']='untrusted'
            elif damage=='null_clone':proof['sent_payload_json']='null'
            elif damage=='array_clone':proof['sent_payload_json']='[]'
            else:proof['extra']=True
            path.write_text(json.dumps(proof))
        report=audit_electrothermal_run(root,deep=True)
        assert not report['passed'],report
    finally:path.write_bytes(original)


def test_redaction_covers_formal_keys_without_collapsing_invalid_fields():
    from llmbo_para.runstore import canonical_json
    module=feature()
    first='sk-fixture-key0001';second='sk-fixture-key0002'
    source={first:1,second:2,'*'*len(first):3,'nested':{first:'sk-fixture-value000'}}
    before=canonical_json(source)
    encoded=module.catalog_archival_json(source);redacted=json.loads(encoded)
    assert 'sk-fixture' not in encoded
    assert len(redacted)==len(source) and len(redacted['nested'])==1
    assert sorted(v for v in redacted.values() if isinstance(v,int))==[1,2,3]
    assert len(next(iter(redacted['nested'])))==len(first)
    assert encoded==module.catalog_archival_json(dict(reversed(list(source.items()))))
    assert before==canonical_json(source)


def test_controller_redacts_unknown_formal_keys_and_rejects_them():
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    module=feature();p=payload();response=reply(p)
    response['region']['sk-fixture-extra000']=True
    class Transport:
        def post(self,sent):return response
    store=MemoryStore();cfg=config()
    controller=ElectrothermalLLMController(transport=Transport(),is_mock=True)
    answer=controller.request(p,prepared=SimpleNamespace(config=cfg),store=store,budgets=cfg['budgets'],request_cap=1)
    assert answer is None
    assert all('sk-fixture-extra' not in json.dumps(value) for value in store.files.values())
    proposed=json.loads(store.files['llm/000000.catalog-response.json']['response_json'])
    with pytest.raises(ValueError):module.resolve_catalog_region(proposed,payload=p)


@pytest.mark.parametrize('mode',['region','none','compact','nan'])
def test_recorded_http_shaped_fixture_replays_full_compact_and_invalid_formal_json(cache,tmp_path_factory,mode):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    root=Path(run_mode(cache,tmp_path_factory,mode)['run_directory'])
    created=[]
    try:
        for path in (root/'llm').glob('*.payload.json'):
            p=json.loads(path.read_text());wire=region_wire_payload(p);n=int(path.name.split('.')[0])
            proposed=json.loads(json.loads((root/f'llm/{n:06d}.catalog-response.json').read_text())['response_json'])
            formal={'request_id':wire['request_id'],'region':proposed['region']} if mode=='compact' else proposed
            instructions=wire['instructions']+'\nReturn exactly one JSON object matching the supplied response contract.'
            artifacts={root/'http'/(p['artifact_task']+'.request.json'):{'body':{'messages':[
                {'role':'system','content':instructions},{'role':'user','content':json.dumps({k:v for k,v in wire.items() if k!='instructions'})}]}},
                root/'http'/(p['artifact_task']+'.response.json'):{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(formal,allow_nan=True)}}]}}
            for target,value in artifacts.items():
                target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(value),encoding='utf-8');created.append(target)
        report=audit_electrothermal_run(root,deep=True)
        assert report['passed'],report['issues']
    finally:
        # These are test-owned files created immediately above, not user archives.
        for target in created:target.unlink()


def test_audit_rejects_fully_resigned_catalog_reply_and_canonical_geometry(cache,tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.runstore import digest_value
    module=feature();root=Path(run_mode(cache,tmp_path_factory,'region')['run_directory'])
    payload_path=next((root/'llm').glob('*.payload.json'));n=int(payload_path.name.split('.')[0])
    paths=[payload_path,root/f'llm/{n:06d}.catalog-response.json',root/f'llm/{n:06d}.catalog-resolution.json']
    round_path=next(path for path in (root/'mo-rounds').glob('*.json')
        if json.loads(path.read_text())['region']['request_outcome'].get('ordinal')==n)
    paths.append(round_path);originals={p:p.read_bytes() for p in paths}
    p=json.loads(originals[payload_path]);proposed=json.loads(json.loads(originals[paths[1]])['response_json'])
    entry=next(e for e in p['region_catalog']['entries'] if e['region_id']==proposed['region']['region_id'])
    candidate=next(c for c in p['candidate_advice']['candidates'] if c['candidate_id']==entry['candidate_id'])
    width=entry['width']*1.1;lo=np.clip(np.asarray(candidate['normalized_parameters'])-width/2,0.,1.-width)
    entry.update(width=width,lb=lo.tolist(),ub=(lo+width).tolist())
    entry['region_id']=digest_value({'version':'region_catalog_v1','context_id':p['context_id'],
        'candidate_id':entry['candidate_id'],'lb':entry['lb'],'ub':entry['ub']})
    p['region_catalog']['catalog_digest']=digest_value({k:v for k,v in p['region_catalog'].items() if k!='catalog_digest'})
    p['proposal_binding']=module.catalog_proposal_binding(p)
    p['response_contract']['properties']['region']=module.catalog_region_contract(p)
    proposed['region'].update(region_id=entry['region_id'],proposal_binding=p['proposal_binding'])
    canonical,resolution=module.resolve_catalog_region(proposed,payload=p)  # internally consistent forged transcript
    event=json.loads(originals[round_path]);canonical['region']['reason']='structured_region_response';event['region']['response']=canonical
    try:
        payload_path.write_text(json.dumps(p));paths[1].write_text(json.dumps({'version':'catalog_response_v1','response_json':json.dumps(proposed,sort_keys=True,ensure_ascii=False)}))
        paths[2].write_text(json.dumps(resolution));round_path.write_text(json.dumps(event))
        report=audit_electrothermal_run(root,deep=True)
        assert not report['passed'] and report['issues']==['independently rebuilt catalog request differs']
    finally:
        for path,content in originals.items():path.write_bytes(content)
