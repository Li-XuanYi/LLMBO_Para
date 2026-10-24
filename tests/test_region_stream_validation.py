"""Fixed staged transport comparison and no DFN before authentic influence."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


def feature():
    root=Path(__file__).resolve().parents[1]
    script=root/'scripts/run_region_stream_validation.py'
    assert script.is_file(), 'staged SSE validation entry missing'
    name='run_region_stream_validation'
    sys.path.insert(0,str(root/'scripts'))
    spec=importlib.util.spec_from_file_location(name,script)
    module=importlib.util.module_from_spec(spec)
    sys.modules[name]=module
    spec.loader.exec_module(module)
    return module


def protocol():
    return {'contexts':[{'context_id':str(i)*64} for i in (1,2,3)],
        'comparison':{'seeds':[1709,3253,5501]}}


def proof(context):
    return {'passed':True,'complete':True,'context_id':context,'wire_verified':True,
        'effect':{'action_valid':True,'state_preserved':True,'EI_matches':True,
                  'tilt_applied':True,'max_abs_shift':.1}}


class PhaseFixture:
    def __init__(self,module,tmp_path,hook=None):
        self.module=module;self.calls=[];self.hook=hook
        self.budget=module.ValidationBudget.start(tmp_path/'budget.jsonl',protocol_sha='a'*64)
        self.plan=tmp_path/'plan.json';self.plan.write_text('{}',encoding='utf8')
        self.sha=hashlib.sha256(self.plan.read_bytes()).hexdigest()

    def run(self,spec):
        self.calls.append(deepcopy(spec));label=spec['label'];kind=spec['kind']
        if kind in ('minimal','historical'):
            self.budget.charge('API',label+':API')
            result=({'passed':True,'complete':True,'wire_verified':True} if kind=='minimal'
                else proof(protocol()['contexts'][spec['context_index']]['context_id']))
            result.update(label=label,owned_tree_stopped=True,
                body_without_stream_sha256='a'*64,
                diagnostic={'http_status':200,'http_request_started':True})
        elif kind=='initialization':
            for i in range(16): self.budget.charge('DFN',label+':'+str(i))
            result={'status':'completed','audit_passed':True,'candidate_count':8,
                    'plan_path':str(self.plan),'plan_file_sha256':self.sha}
        else:
            for i in range(40): self.budget.charge('DFN',label+':'+str(i))
            if spec['arm']=='full':
                for i in range(20): self.budget.charge('API',label+':API:'+str(i))
            result={'status':'completed','audit_passed':True,'BO_rounds':20,'seed':spec['seed'],
                'arm':spec['arm'],'initial_file_sha':self.sha,
                'first_numerical_context_sha':'b'*64,'request_failure_streak':0}
        if self.hook: self.hook(spec,result)
        return result

    def execute(self):
        return self.module.execute_sequence(protocol(),self.budget,run_phase=self.run)


def cutoff(result,stage='origin_response'):
    result.update(passed=False,complete=False,
        diagnostic={'reason':'deadline_exceeded','configured_timeout_s':120.,
                    'effective_timeout_s':120.,'elapsed_s':120.,
                    'http_request_started':True,'http_status':None},
        wait_observation={'stage':stage,'samples':3})


def test_fixed_sequence_and_budgets_match_approval(tmp_path):
    module=feature();f=PhaseFixture(module,tmp_path)
    result=f.execute()
    assert result['status']=='completed'
    assert f.budget.counts()=={'API':66,'DFN':256}
    calls=f.calls[:6]
    assert [c['label'] for c in calls]==['p0','p1','p2','p3','p4','p5']
    assert [c['responses_stream'] for c in calls]==[False,False,True,True,True,True]
    assert [c.get('context_index') for c in calls]==[None,0,0,1,2,0]
    assert [c['timeout_s'] for c in calls]==[60.,120.,120.,120.,120.,120.]
    assert len(f.calls)==13


def test_registered_p1_origin_wait_cutoff_can_compare_sse_once(tmp_path):
    def hook(spec,result):
        if spec['label']=='p1': cutoff(result)
    f=PhaseFixture(feature(),tmp_path,hook)
    assert f.execute()['status']=='completed'
    assert [c['label'] for c in f.calls].count('p1')==1


@pytest.mark.parametrize('label',['p0','p2','p3','p4','p5'])
def test_any_other_probe_failure_stops_before_dfn(tmp_path,label):
    def hook(spec,result):
        if spec['label']==label: cutoff(result)
    f=PhaseFixture(feature(),tmp_path,hook)
    result=f.execute()
    assert result['status']=='failed' and f.budget.counts()['DFN']==0
    assert not any(c['kind'] in ('initialization','arm') for c in f.calls)


@pytest.mark.parametrize('damage',['proxy','tls','send','unknown','no_samples','not_started',
    'network_timeout','http_error','tree_running','wire_unverified'])
def test_p1_exception_requires_exact_origin_wait_evidence(tmp_path,damage):
    def hook(spec,result):
        if spec['label']!='p1': return
        cutoff(result)
        if damage in ('proxy','tls','send','unknown'): result['wait_observation']['stage']=damage
        if damage=='no_samples': result['wait_observation']['samples']=0
        if damage=='not_started': result['diagnostic']['http_request_started']=False
        if damage=='network_timeout': result['diagnostic']['reason']='timeout'
        if damage=='http_error': result['diagnostic']['http_status']=503
        if damage=='tree_running': result['owned_tree_stopped']=False
        if damage=='wire_unverified': result['wire_verified']=False
    f=PhaseFixture(feature(),tmp_path,hook)
    assert f.execute()['status']=='failed'
    assert [c['label'] for c in f.calls]==['p0','p1'] and f.budget.counts()['DFN']==0


@pytest.mark.parametrize('damage',['same_context','all_zero_tilt','bad_ei','changed_variance','fourth_incomplete'])
def test_gate_requires_four_bound_replies_three_contexts_and_nonzero_influence(damage):
    module=feature();p=[proof(str(i)*64) for i in (1,2,3,1)]
    assert module.stream_gate_passed(p)
    if damage=='same_context':
        for item in p: item['context_id']='1'*64
    if damage=='all_zero_tilt':
        for item in p: item['effect'].update(tilt_applied=False,max_abs_shift=0.)
    if damage=='bad_ei': p[0]['effect']['EI_matches']=False
    if damage=='changed_variance': p[1]['effect']['state_preserved']=False
    if damage=='fourth_incomplete': p[-1]['complete']=False
    assert not module.stream_gate_passed(p)


def test_mismatched_stream_comparator_stops_before_dfn(tmp_path):
    def hook(spec,result):
        if spec['label']=='p2': result['body_without_stream_sha256']='c'*64
    f=PhaseFixture(feature(),tmp_path,hook)
    assert f.execute()['status']=='failed' and f.budget.counts()['DFN']==0


@pytest.mark.parametrize('stage,frames',[
    ('proxy','  File "http/client.py", line 1 in _tunnel\n  File "http/client.py", line 2 in _read_status'),
    ('tls','  File "ssl.py", line 1 in do_handshake'),
    ('send','  File "http/client.py", line 1 in send'),
    ('origin_response','  File "http/client.py", line 1 in _read_status\n  File "http/client.py", line 2 in getresponse'),
    ('unknown','unclassified text'),
])
def test_wait_stack_classifier_does_not_label_everything_model_wait(stage,frames):
    result=feature().classify_wait_stacks('Timeout (0:00:30)!\nThread 0x123:\n'+frames)
    assert result['stage']==stage


def test_dry_run_never_reads_a_key_or_starts_a_worker(monkeypatch,tmp_path):
    module=feature()
    monkeypatch.setattr(module,'read_credential',lambda:pytest.fail('dry read credential'))
    monkeypatch.setattr(module,'supervise',lambda *a,**k:pytest.fail('dry supervise'))
    result=module.run_validation({},tmp_path,execute=False)
    assert result['dry_run'] is True and result['actual_API']==result['actual_DFN']==0


def test_execution_without_bound_approval_and_full_release_cannot_read_key(monkeypatch,tmp_path):
    module=feature()
    monkeypatch.setattr(module,'read_credential',lambda:pytest.fail('unapproved read credential'))
    monkeypatch.setattr(module,'supervise',lambda *a,**k:pytest.fail('unapproved supervise'))
    with pytest.raises((ValueError,RuntimeError)):
        module.run_validation(protocol(),tmp_path,execute=True)


@pytest.mark.parametrize('status',[401,403,404,429,500,503])
def test_formal_http_errors_stop_immediately_without_a_new_solve(status):
    with pytest.raises(RuntimeError):
        feature().check_request_status({'http_status':status,'status':'failed'})


def memory_observed_worker(spec,payload,run_path,connection):
    from unittest.mock import patch
    import faulthandler
    import os
    from test_responses_stream_controls import stream_worker
    observed={}
    def start(timeout,*,repeat,file,**kwargs):
        observed.update(timeout=timeout,repeat=repeat,pid=os.getpid(),file=file,
                        open_at_start=not file.closed)
    def cancel():
        observed.update(cancelled=True,open_at_cancel=not observed['file'].closed)
    pending=[]
    class BufferedConnection:
        def send(self,message):
            if message[0] in ('result','error'): pending.append(message)
            else: connection.send(message)
        def recv(self): return connection.recv()
        def close(self): pass
    with patch.object(faulthandler,'dump_traceback_later',start),patch.object(faulthandler,'cancel_dump_traceback_later',cancel):
        stream_worker('success',spec,payload,run_path,BufferedConnection(),entry=feature().observed_responses_worker)
    file=observed.pop('file')
    observed['closed_after_worker']=file.closed
    (Path(run_path)/'timer-observation.json').write_text(json.dumps(observed),encoding='utf8')
    for message in pending: connection.send(message)
    connection.close()


def test_timer_is_scoped_to_actual_owned_http_child_and_cancelled_before_close(monkeypatch,tmp_path):
    import os
    from test_electrothermal_responses import payload
    from test_electrothermal_responses_requests import config,store,ENV
    from llmbo_para import electrothermal_responses as responses
    module=feature();cfg=config();archive=store(tmp_path,cfg)
    monkeypatch.setenv(ENV,'offline-stack-timer-placeholder')
    monkeypatch.setattr(responses,'_responses_request_worker',memory_observed_worker)
    client=responses.BoundedResponsesTransport(cfg['llm']['endpoint'],ENV,
        model=cfg['llm']['model'],max_tokens=1536,json_mode=True,responses_stream=True,
        timeout_s=15.,run_store=archive)
    assert client.post(payload())['candidates']==[]
    note=json.loads((archive.path/'timer-observation.json').read_text())
    assert note['pid']!=os.getpid() and note['timeout']==30 and note['repeat'] is True
    assert note['open_at_start'] and note['open_at_cancel'] and note['cancelled'] and note['closed_after_worker']


def test_transport_readiness_is_retained_if_later_initialization_fails(tmp_path):
    def hook(spec,result):
        if spec['kind']=='initialization': result['status']='failed'
    f=PhaseFixture(feature(),tmp_path,hook)
    result=f.execute()
    assert result['status']=='failed' and result['transport_ready'] is True
    assert result['failure_stage']=='initialization' and result['gain_status']=='inconclusive'


def test_only_repeat_nonzero_influence_is_allowed_after_three_valid_abstentions():
    module=feature();p=[proof(str(i)*64) for i in (1,2,3,1)]
    for item in p[:3]: item['effect'].update(tilt_applied=False,max_abs_shift=0.)
    assert module.stream_gate_passed(p)


def test_replay_round_uses_the_bound_original_manifest_layout(tmp_path):
    module=feature()
    original=tmp_path/'original';(original/'mo-rounds').mkdir(parents=True)
    round_file=original/'mo-rounds/round.json';round_file.write_text('{}',encoding='utf8')
    (original/'manifest.json').write_text('{}',encoding='utf8')
    flat=tmp_path/'flat.json';flat.write_bytes(round_file.read_bytes())
    context={'round_path':str(round_file),'frozen_round':str(flat),
             'round_sha256':hashlib.sha256(round_file.read_bytes()).hexdigest()}
    path=module.replay_round_path(context)
    assert path==round_file and (path.parent.parent/'manifest.json').is_file()
    round_file.write_text('{"changed":true}',encoding='utf8')
    with pytest.raises(ValueError): module.replay_round_path(context)


def release_fixture(module,tmp_path,monkeypatch):
    contexts=[];pins={}
    for i in range(3):
        context={'context_id':str(i+1)*64}
        for name in ('frozen_payload','frozen_round','frozen_manifest'):
            path=tmp_path/(str(i)+'-'+name+'.json');path.write_text('{}',encoding='utf8')
            context[name]=str(path);pins[str(path)]=module.sha(path)
        contexts.append(context)
    fixed={'contexts':contexts,'input_pins':pins,'original_run':str(tmp_path/'original')}
    monkeypatch.setattr(module,'_fixed_inputs',lambda:fixed,raising=False)
    runtime={'observed-runtime.py':'a'*64}
    monkeypatch.setattr(module,'_pins',lambda evidence:runtime)
    head=module.subprocess.check_output(['git','-C',str(module.WT),'rev-parse','HEAD'],text=True).strip()
    protocol={'version':'region_stream_validation_v1','limits':module.CAPS,'provider':module.PROVIDER,
        'probes':module.PROBES,'comparison':{'seeds':[1709,3253,5501]},**fixed}
    approval={'approved':True,'approved_commit':module.APPROVED_COMMIT,'limits':module.CAPS,
        'plan_sha256':module.sha(module.PLAN),'spec_sha256':module.sha(module.SPEC)}
    def put(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf8')
    put(tmp_path/'approval.json',approval);put(tmp_path/'validation-protocol.json',protocol)
    folder=tmp_path/'tests/ge-st-final-full'
    manifest={'command':[str(tmp_path/'run_tests.py'),'test','ge-st-final-full','tests'],
        'head':head,'executable':sys.executable,'python':sys.version,'dependencies':module.environment()['dependencies']}
    result={'exit_code':0,'junit_counts':{'tests':1560,'passed':1560,'failures':0,'errors':0,'skipped':0},
        'runtime_unchanged_during_run':True,'runtime_pins':runtime,'source_unchanged_during_run':True,
        'protected_unchanged_during_run':True,'head_after':head,'command_args':['tests','-q'],
        'boundary':{'network_attempts':0,'battery_solve_attempts':0}}
    put(folder/'manifest-before.json',manifest);put(folder/'result.json',result)
    (folder/'exit-code.txt').write_text('0\n',encoding='utf8')
    (folder/'junit.xml').write_text('<testsuites><testsuite tests="1560" failures="0" errors="0" skipped="0"/></testsuites>',encoding='utf8')
    release={'head':head,'source_fingerprint':module.fingerprint(module.WT),'runtime_pins':runtime,
        'full_label':'ge-st-final-full','result_sha256':module.sha(folder/'result.json'),
        'protocol_sha256':module.sha(tmp_path/'validation-protocol.json'),'environment':module.environment()}
    put(tmp_path/'software-release.json',release)
    return protocol,folder,release,put


def test_exact_full_release_can_be_validated_without_reading_key(monkeypatch,tmp_path):
    module=feature();protocol,folder,release,put=release_fixture(module,tmp_path,monkeypatch)
    monkeypatch.setattr(module,'read_credential',lambda:pytest.fail('release check read key'))
    module._validate_release(protocol,tmp_path)


@pytest.mark.parametrize('damage',['junit','exit_code','partial_target','collected_only','head_after','runtime','python','scope','input'])
def test_release_tampering_stops_before_key_or_worker(monkeypatch,tmp_path,damage):
    module=feature();protocol,folder,release,put=release_fixture(module,tmp_path,monkeypatch)
    module._validate_release(protocol,tmp_path)
    if damage=='junit': (folder/'junit.xml').write_text('<testsuite tests="1560" failures="1" errors="0" skipped="0"/>',encoding='utf8')
    elif damage=='exit_code': (folder/'exit-code.txt').write_text('1\n',encoding='utf8')
    elif damage=='input': Path(next(iter(protocol['input_pins']))).write_text('{"changed":true}',encoding='utf8')
    elif damage=='scope':
        a=module.read(tmp_path/'approval.json');a['limits']['API']=67;put(tmp_path/'approval.json',a)
    elif damage in ('partial_target','python'):
        m=module.read(folder/'manifest-before.json')
        if damage=='partial_target': m['command'][-1]='tests/test_responses_sse.py'
        else: m['python']='other-python'
        put(folder/'manifest-before.json',m)
    else:
        r=module.read(folder/'result.json')
        if damage=='collected_only': r['command_args']=['tests','--collect-only']
        elif damage=='head_after': r['head_after']='different'
        else: r['runtime_pins']={'other':'b'*64}
        put(folder/'result.json',r);release['result_sha256']=module.sha(folder/'result.json')
        put(tmp_path/'software-release.json',release)
    monkeypatch.setattr(module,'read_credential',lambda:pytest.fail('invalid release read key'))
    monkeypatch.setattr(module,'supervise',lambda *a,**k:pytest.fail('invalid release worker'))
    with pytest.raises((ValueError,RuntimeError)):
        module._validate_release(protocol,tmp_path)
