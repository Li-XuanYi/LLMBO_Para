"""Network-free regressions for compact identities and actionable request stages."""
from copy import deepcopy
import json
import pytest

TASK='region_preference_electrothermal'
ENV='REGION_REPAIR_UNIT_CREDENTIAL'

def payload():
    return {'task':TASK,'artifact_task':TASK+'_request_a','instructions':'Use physical evidence. Return JSON.',
        'schema_version':2,'parameter_profile':'electrothermal_4e2t','fit_rates':['0.5C','1C'],
        'signatures':{'source':'a'*64,'data':'b'*64,'fit_rates':['0.5C','1C']},
        'context_id':'c'*64,'context':{'weights':[.8,.2],'objective_scales':[.1,1.]},
        'candidate_advice':{'eligible_alternative_count':1,'shortlist':[{'point':[.2]*6}]},
        'response_contract':{'type':'object','properties':{'region':{'type':'object'}}}}

def region():return {'kind':'none','coordinate_space':'normalized','confidence':0.,'reason':'insufficient evidence'}

def test_compact_option_is_validated_without_relaxing_unknown_settings(tmp_path):
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg=et_config();cfg['llm']['region_wire_format']='compact_v1'
    report,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert prepared is not None,report['errors']
    cfg['llm']['region_wire_format']='accept_any_reply'
    report,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert prepared is None and report['errors']

@pytest.mark.parametrize('malformed',[[],None,'not-an-object'])
def test_malformed_llm_section_returns_validation_errors(malformed):
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg=et_config();cfg['llm']=malformed
    assert electrothermal_configuration_errors(cfg)

def test_legacy_default_and_warmstart_payload_are_unchanged():
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    original=payload();assert region_wire_payload(original)==original
    original.update(task='warm_start_electrothermal',region_wire_format='compact_v1')
    assert region_wire_payload(original)==original

def test_compact_contract_removes_signature_echo_but_retains_advice_and_frozen_binding():
    from llmbo_para.electrothermal_region_wire import region_wire_payload,decode_region_wire
    original=payload();original['region_wire_format']='compact_v1';before=deepcopy(original)
    wire=region_wire_payload(original)
    assert original==before
    assert 'signatures' not in wire
    assert set(wire['response_contract']['properties'])=={'request_id','region'}
    assert wire['response_contract']['properties']['request_id']=={'const':wire['request_id']}
    assert wire['candidate_advice']==original['candidate_advice']
    decoded=decode_region_wire({'request_id':wire['request_id'],'region':region()},original)
    assert decoded=={**{k:original[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')},'region':region()}

@pytest.mark.parametrize('damage',['context','weight','scale','rates','source'])
def test_compact_reply_cannot_cross_frozen_context_or_semantic_signatures(damage):
    from llmbo_para.electrothermal_region_wire import region_wire_payload,decode_region_wire
    original=payload();original['region_wire_format']='compact_v1'
    reply={'request_id':region_wire_payload(original)['request_id'],'region':region()}
    changed=deepcopy(original)
    if damage=='context':changed['context_id']='d'*64
    elif damage=='weight':changed['context']['weights']=[.2,.8]
    elif damage=='scale':changed['context']['objective_scales']=[100.,1.]
    elif damage=='rates':changed['fit_rates'].append('2C')
    else:changed['signatures']['source']='e'*64
    with pytest.raises(ValueError):decode_region_wire(reply,changed)

@pytest.mark.parametrize('extra',[{'signatures':{}},{'context_id':'old'},{'extra':1}])
def test_compact_reply_rejects_hybrid_or_extra_fields(extra):
    from llmbo_para.electrothermal_region_wire import region_wire_payload,decode_region_wire
    original=payload();original['region_wire_format']='compact_v1'
    with pytest.raises(ValueError):decode_region_wire({'request_id':region_wire_payload(original)['request_id'],'region':region(),**extra},original)

class Connection:
    def __init__(self):self.messages=[]
    def send(self,value):self.messages.append(value)
    def recv(self):return 'continue'
    def close(self):pass

def install_provider(monkeypatch,reply):
    sent=[]
    class Response:
        status=200
        def read(self,count):return json.dumps({'choices':[{'finish_reason':'stop','message':{'content':reply(sent[-1])}}]}).encode()[:count]
        def __enter__(self):return self
        def __exit__(self,*args):return False
    class Provider:
        def open(self,request,**kwargs):sent.append(json.loads(request.data));return Response()
    monkeypatch.setenv(ENV,'unit-only-not-a-real-key')
    monkeypatch.setattr('llmbo_para.llm.build_opener',lambda *args:Provider())
    return sent

def spec():return {'endpoint':'https://offline.example.test/v1/chat/completions','api_key_env':ENV,
    'model':'offline-test-model','max_tokens':512,'json_mode':True,'timeout_s':1.}

def test_actual_worker_uses_compact_wire_and_returns_strict_canonical_envelope(monkeypatch):
    from llmbo_para.electrothermal_requests import _chat_request_worker
    def reply(body):
        user=json.loads(body['messages'][1]['content'])
        assert 'signatures' not in user
        return json.dumps({'request_id':user['request_id'],'region':region()})
    sent=install_provider(monkeypatch,reply)
    original=payload();original['region_wire_format']='compact_v1';connection=Connection()
    _chat_request_worker(spec(),original,None,connection)
    result=connection.messages[-1][1]
    assert len(sent)==1 and result['ok']
    assert result['response']['signatures']==original['signatures']
    assert result['response']['context_id']==original['context_id']
    assert sent[0]['max_tokens']==512

@pytest.mark.parametrize('headers_received',[False,True])
def test_deadline_diagnostic_distinguishes_waiting_headers_from_body(monkeypatch,tmp_path_factory,headers_received):
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.runstore import RunStore
    store=RunStore(tmp_path_factory.mktemp('rstage'),{'kind':'offline-diagnostic'},command='test')
    monkeypatch.setenv(ENV,'unit-only-not-a-real-key')
    def blocked(*args,**kwargs):
        kwargs['on_solve_start']()
        if headers_received:store.append_event({'type':'llm_http_headers_received','task':TASK+'_request_a','http_status':200,'elapsed_s':.1})
        raise TimeoutError('unit blocked provider')
    monkeypatch.setattr(requests,'run_with_deadline',blocked)
    transport=requests.BoundedChatCompletionsTransport(**spec(),run_store=store)
    with pytest.raises(requests.LLMRequestFailure) as exc:transport.post(payload())
    d=exc.value.diagnostic
    assert exc.value.kind=='deadline_exceeded'
    assert d['failure_stage']==('reading_body' if headers_received else 'awaiting_headers')
    assert d['http_request_started'] and d['request_start_elapsed_s']>=0
    assert d['http_status']==(200 if headers_received else None)

def test_empty_content_is_not_reported_as_unclassified_protocol_failure(monkeypatch):
    from llmbo_para.electrothermal_requests import _chat_request_worker
    install_provider(monkeypatch,lambda wire:None)
    connection=Connection();_chat_request_worker(spec(),payload(),None,connection)
    result=connection.messages[-1][1]
    assert not result['ok']
    assert result['diagnostic']['protocol_issue']=='empty_content'

def test_invalid_wire_format_is_rejected_before_worker_or_HTTP(monkeypatch):
    from llmbo_para import electrothermal_requests as requests
    calls=[]
    monkeypatch.setenv(ENV,'unit-only-not-a-real-key')
    monkeypatch.setattr(requests,'run_with_deadline',lambda *a,**kw:calls.append(1) or {'ok':True,'response':{}})
    transport=requests.BoundedChatCompletionsTransport(**spec())
    original=payload();original['region_wire_format']='invalid-unit-mode'
    with pytest.raises(requests.LLMRequestFailure) as exc:transport.post(original)
    assert exc.value.kind=='configuration_error' and not calls
    assert exc.value.diagnostic['wire_format']=='invalid'

@pytest.mark.parametrize('damage',[None,'response_binding','request_advice'])
def test_compact_exchange_is_replayed_by_audit_and_tampering_is_detected(monkeypatch,tmp_path_factory,damage):
    from pathlib import Path
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from test_region_failure_audit import _shared_initialization
    root=tmp_path_factory.mktemp('rcwire')
    cfg=_shared_initialization(root);cfg['llm']['region_wire_format']='compact_v1'
    def reply(body):
        user=json.loads(body['messages'][1]['content'])
        return json.dumps({'request_id':user['request_id'],'region':region()})
    install_provider(monkeypatch,reply)
    def execute(worker,args,**kwargs):
        kwargs['on_solve_start']();connection=Connection();worker(*args,connection)
        return connection.messages[-1][1]
    monkeypatch.setattr(requests,'run_with_deadline',execute)
    transport=requests.BoundedChatCompletionsTransport(**spec())
    result=run_electrothermal_experiment(cfg,root,base_dir=root,
        llm_controller=ElectrothermalLLMController(transport=transport,is_mock=True))
    directory=Path(result['run_directory'])
    assert result['BO_rounds']==2 and result['API_calls']==result['costs']['solver_calls']==0
    assert audit_electrothermal_run(directory,deep=True)['passed']
    if damage is not None:
        if damage=='response_binding':
            path=next((directory/'http').glob('*.response.json'));value=json.loads(path.read_text())
            content=json.loads(value['choices'][0]['message']['content']);content['request_id']='forged'
            value['choices'][0]['message']['content']=json.dumps(content)
        else:
            path=next((directory/'http').glob('*.request.json'));value=json.loads(path.read_text())
            content=json.loads(value['body']['messages'][1]['content']);content['context']['weights']=[.123,.877]
            value['body']['messages'][1]['content']=json.dumps(content)
        path.write_text(json.dumps(value))
        assert not audit_electrothermal_run(directory,deep=True)['passed']
