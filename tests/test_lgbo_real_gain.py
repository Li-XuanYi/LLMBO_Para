"""Boundaries for the independently approved real gain experiment (no live calls)."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import time

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/run_lgbo_real_gain.py'


def load():
    assert SCRIPT.is_file(), 'approved real-gain research entry is missing'
    if str(SCRIPT.parent) not in sys.path:sys.path.insert(0,str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location('run_lgbo_real_gain', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def pair(seed, *, delta=0., du=0., dt=0.):
    return {'seed': seed, 'old_full': {'HV': 95., 'F_U': .01, 'F_T': .2,
                'completed': True, 'audit_passed': True, 'BO_rounds': 20},
            'new_full': {'HV': 95.+delta, 'F_U': .01+du, 'F_T': .2+dt,
                'completed': True, 'audit_passed': True, 'BO_rounds': 20}}


@pytest.mark.parametrize('deltas,want', [([0,0,0],False), ([.1,.2,.3],False),
    ([-.1,.01,-.2],True), ([-.1,.5,-.2],False), ([-.1,.2,.3],False)])
def test_regression_gate_requires_majority_and_mean(deltas, want):
    m=load()
    rows=[pair(s,delta=d) for s,d in zip((1709,3253,5501),deltas)]
    result=m.decide(rows)
    assert result['needs_confirmation'] is want
    assert result['revert'] is False


def test_joint_rmse_loss_with_tied_hv_requires_independent_confirmation():
    m=load(); rows=[pair(s,du=.00001,dt=.001) for s in (1709,3253,5501)]
    assert m.decide(rows)['needs_confirmation'] is True
    assert m.decide(rows,pair(7919,du=.00001,dt=.001))['revert'] is True
    assert m.decide(rows,pair(7919,delta=.01))['revert'] is False
    voltage_only=[pair(s,du=.001) for s in (1709,3253,5501)]
    assert m.decide(voltage_only)['needs_confirmation'] is False


@pytest.mark.parametrize('damage', ['missing','duplicate','audit','rounds','nan','wrong_confirmation'])
def test_incomplete_or_invalid_comparison_cannot_trigger_revert(damage):
    m=load(); rows=[pair(s,delta=-.1) for s in (1709,3253,5501)]
    confirmation=None
    if damage=='missing': rows.pop()
    elif damage=='duplicate': rows[2]['seed']=1709
    elif damage=='audit': rows[0]['new_full']['audit_passed']=False
    elif damage=='rounds': rows[0]['new_full']['BO_rounds']=19
    elif damage=='nan': rows[0]['new_full']['HV']=float('nan')
    else: confirmation=pair(1709,delta=-.1)
    r=m.decide(rows,confirmation)
    assert r['status']=='inconclusive' and not r['revert']


def test_parent_budget_persists_failed_requests_and_cannot_restart(tmp_path):
    m=load(); path=tmp_path/'journal.jsonl'
    b=m.ExperimentBudget.start(path,protocol_sha='a'*64)
    b.begin('preflight'); b.charge('API','p0')
    with pytest.raises(RuntimeError): b.charge('API','p0')
    with pytest.raises(RuntimeError): b.charge('DFN','d0')
    with pytest.raises(RuntimeError): b.charge('API','p1')
    b.finish(False)
    restored=m.ExperimentBudget.load(path)
    assert restored.counts()=={'DFN':0,'API':1}
    with pytest.raises(RuntimeError): restored.begin('initialization')
    with pytest.raises(FileExistsError): m.ExperimentBudget.start(path,protocol_sha='a'*64)


def test_reservation_phase_caps_and_hash_chain_are_enforced(tmp_path):
    m=load(); path=tmp_path/'journal.jsonl'
    b=m.ExperimentBudget.start(path,protocol_sha='a'*64)
    b.begin('preflight');b.charge('API','p');b.finish(True)
    b.begin('initialization')
    for i in range(32): b.charge('DFN','i'+str(i))
    assert m.ExperimentBudget.load(path).counts()=={'DFN':32,'API':1}
    with pytest.raises(RuntimeError): b.require(1)
    with pytest.raises(RuntimeError): b.charge('DFN','extra')
    raw=path.read_text(encoding='utf-8').replace('"DFN":472','"DFN":473')
    # Damage a persisted count event, independently of whitespace formatting.
    lines=raw.splitlines(); event=json.loads(lines[-1]);event['event_id']='tampered'
    lines[-1]=json.dumps(event);path.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    with pytest.raises(ValueError): m.ExperimentBudget.load(path)


def test_deadline_cannot_extend_after_clock_change_or_reload(tmp_path,monkeypatch):
    m=load(); clocks={'unix':100.,'mono':50.}
    monkeypatch.setattr(m.time,'time',lambda:clocks['unix'])
    monkeypatch.setattr(m.time,'monotonic',lambda:clocks['mono'])
    p=tmp_path/'j'; b=m.ExperimentBudget.start(p,protocol_sha='a'*64)
    b.begin('preflight')
    clocks.update(unix=1.,mono=10851.)
    with pytest.raises(RuntimeError): m.ExperimentBudget.load(p).charge('API','late')


def blocked_worker(spec,connection):
    time.sleep(30)


def charging_worker(spec,connection):
    connection.send(('charge',('API','offline-fixture')))
    assert connection.recv()[0]=='ok'
    connection.send(('result',{'status':'failed-fixture'}))


def test_owned_worker_has_hard_deadline_and_no_survivor(tmp_path):
    m=load(); p=tmp_path/'j';b=m.ExperimentBudget.start(p,protocol_sha='a'*64)
    b.begin('preflight');started=time.monotonic()
    with pytest.raises(TimeoutError):
        m.supervise(blocked_worker,{},b,deadline=time.monotonic()+.5,metadata=tmp_path/'m.json')
    assert time.monotonic()-started<12
    result=json.loads((tmp_path/'m.json').read_text())
    assert result['owned_tree_stopped'] is True
    assert b.counts()=={'API':0,'DFN':0}


def test_parent_charges_before_permitting_owned_worker(tmp_path):
    m=load();b=m.ExperimentBudget.start(tmp_path/'j',protocol_sha='a'*64)
    b.begin('preflight')
    result=m.supervise(charging_worker,{},b,deadline=time.monotonic()+20,metadata=tmp_path/'m.json')
    assert result=={'status':'failed-fixture'}
    assert b.counts()=={'API':1,'DFN':0}
    assert json.loads((tmp_path/'m.json').read_text())['exit_code']==0


def test_credential_disabled_dry_run_creates_no_experiment(tmp_path,monkeypatch):
    m=load();monkeypatch.setattr(m,'read_credential',lambda:pytest.fail('dry run read credentials'))
    out=tmp_path/'unused'
    report=m.dry_run(output=out)
    assert report['dry_run'] is True and report['actual_API']==report['actual_DFN']==0
    assert len(report['cases'])==9 and not out.exists()


def test_cross_source_plans_remain_separate_and_initial_values_must_match():
    m=load()
    a=[{'parameters':[.5,.5,1e-13,1e-13,40.,.1],'objectives':[.01,.2]}]
    b=deepcopy(a)
    assert m.check_initialization(a,b) is True
    b[0]['objectives'][1]+=.001
    with pytest.raises(ValueError): m.check_initialization(a,b)
    with pytest.raises(ValueError): m.check_initialization(a,a+a)


@pytest.mark.parametrize('damage',['nan','missing_component','negative'])
def test_invalid_initial_targets_are_rejected_before_comparison(damage):
    m=load()
    a=[{'parameters':[.5,.5,1e-13,1e-13,40.,.1],'objectives':[.01,.2]}]
    b=deepcopy(a)
    if damage=='nan':b[0]['objectives'][1]=float('nan')
    elif damage=='missing_component':b[0]['objectives'].pop()
    else:b[0]['objectives'][0]=-.01
    with pytest.raises(ValueError):m.check_initialization(a,b)


def test_request_does_not_leak_synthetic_true_parameters():
    m=load();m.check_payload({'task':'region_preference_electrothermal','history':[]})
    with pytest.raises(ValueError):
        m.check_payload({'summary':{'known_parameters':[.5]*6}})


def worker_module():
    path=SCRIPT.with_name('lgbo_real_gain_worker.py')
    assert path.is_file(), 'source-isolated worker is missing'
    spec=importlib.util.spec_from_file_location('real_gain_worker_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_independent_hv_and_same_parameter_representative():
    w=worker_module()
    assert w.independent_hv([[1.,3.],[2.,1.],[3.,4.],[1.,3.]],[4.,5.])==10.
    assert w.independent_hv([[6.,1.]],[4.,5.])==0.
    rows=[{'parameters':[1.]*6,'evaluation_id':'a','objectives':[.01,1.]},
          {'parameters':[.5]*6,'evaluation_id':'b','objectives':[.04,.4]},
          {'parameters':[0.]*6,'evaluation_id':'c','objectives':[.08,.1]}]
    assert w.representative(rows,normalize=lambda x:x)['evaluation_id']=='b'


def test_config_isolation_preserves_data_physics_and_disables_plain_api():
    m=load();w=worker_module();base=m.read(m.PROPOSAL/'new_full.disabled-config.json')
    before=deepcopy(base)
    out=w.config_for(base,kind='arm',arm='plain',seed=1709,remaining=70.,initial=None)
    assert base==before
    assert out['data']==base['data'] and out['fixed']==base['fixed'] and out['model']==base['model']
    assert out['llm']['enabled'] is False and out['budgets']['max_llm_requests']==0
    assert out['budgets']['max_solver_calls']==40
    assert out['optimization']['total_candidate_budget']==28
    assert out['optimization']['mode']=='warmstart_only'
    for rate in out['fit_rates']:assert out['data']['by_rate'][rate]==base['data']['by_rate'][rate]


def test_live_launch_without_software_release_makes_zero_calls(tmp_path,monkeypatch):
    m=load(); assert hasattr(m,'execute'), 'approved live gate is missing'
    monkeypatch.setattr(m,'EVIDENCE',tmp_path)
    monkeypatch.setattr(m,'read_credential',lambda:pytest.fail('gated live launch read credentials'))
    with pytest.raises(ValueError):m.execute()
    assert not (tmp_path/'budget-journal.jsonl').exists()


def test_cli_rejects_missing_release_before_creating_live_markers(tmp_path,monkeypatch):
    m=load();monkeypatch.setattr(m,'EVIDENCE',tmp_path)
    monkeypatch.setattr(sys,'argv',[str(SCRIPT),'--execute'])
    with pytest.raises(ValueError):m.main()
    assert list(tmp_path.iterdir())==[]


def test_preflight_context_has_actual_identities_and_compact_body_without_truth(tmp_path):
    m=load();w=worker_module()
    assert hasattr(w,'prepare_preflight'), 'fresh v2 preflight preparation missing'
    payload,body=w.prepare_preflight(tmp_path)
    m.check_payload(payload)
    assert payload['region_method']=='lgbo_v2'
    assert payload['signatures']['source'] not in ('frozen','')
    assert len(payload['context_id'])==64
    data=json.loads(body['input'])
    assert len(data['request_id'])==64 and 'signatures' not in data
    assert body['max_output_tokens']==8192 and body['stream'] is False and body['store'] is False


def test_source_bound_initialization_and_two_arm_none_control_close_without_live_calls():
    # The actual spawned worker, stores, signatures, twenty rounds and deep
    # audits are real; only the battery/API leaves are algebraic/none fixtures.
    import tempfile
    m=load()
    # Exercise this checkout; the historical runner's hard-coded worktree may
    # contain unrelated local changes and is not the source under test.
    m.WT=SCRIPT.parents[1]
    root=Path(tempfile.mkdtemp(prefix='rg-',dir=m.MAIN/'runs'))
    b=m.ExperimentBudget.start(root/'j',protocol_sha='a'*64)
    b.begin('preflight');b.charge('API','fixture-gate');b.finish(True);b.begin('initialization')
    base=m.read(m.PROPOSAL/'new_full.disabled-config.json')
    base['optimization'].update(gp_sweeps=0,global_pool_size=16,local_pool_size=8)
    spec={'kind':'initialization','arm':'new_full','seed':1709,'label':'test-i',
          'solve_cap':0,'base_config':base,'source_root':str(m.WT),
          'source':m.fingerprint(m.WT),'deadline':b.deadline,'software_fixture':True,
          'output':str(root/'i'),'coordinates':m.read(m.PROPOSAL/'fixed-eight-coordinates.json')['parameters']}
    first=m.supervise(m.worker_entry,spec,b,deadline=time.monotonic()+90,metadata=root/'mi.json')
    assert first['audit_passed'] and first['candidate_count']==8
    b.finish(True);b.begin('main');arms=[]
    for arm in ('plain','new_full'):
        cfg=deepcopy(spec);cfg.update(kind='arm',arm=arm,label=arm,output=str(root/arm[0]),
            initial={'path':first['plan_path'],'sha256':m.sha(first['plan_path'])})
        arms.append(m.supervise(m.worker_entry,cfg,b,deadline=time.monotonic()+90,metadata=root/(arm+'.json')))
    assert all(r['BO_rounds']==20 and r['audit_passed'] for r in arms)
    assert arms[0]['HV']==arms[1]['HV']
    assert arms[0]['first_numerical_context_sha']==arms[1]['first_numerical_context_sha']
    assert [r['objectives'] for r in arms[0]['rounds']]==[r['objectives'] for r in arms[1]['rounds']]
    assert b.counts()=={'API':1,'DFN':0}  # The one persisted fixture gate, no actual API.
    assert arms[1]['summary']['API_calls']==0
    assert arms[1]['summary']['costs']['mock_llm_requests']==20


def test_worker_rejects_wrong_source_before_any_budget_charge():
    import tempfile
    m=load(); root=Path(tempfile.mkdtemp(prefix='rgs-',dir=m.MAIN/'runs'))
    b=m.ExperimentBudget.start(root/'j',protocol_sha='a'*64);b.begin('preflight')
    spec={'kind':'preflight','label':'wrong-source','source_root':str(m.WT),
          'source':'a'*64,'output':str(root/'x'),'solve_cap':0,'deadline':b.deadline}
    with pytest.raises(RuntimeError):
        m.supervise(m.worker_entry,spec,b,deadline=time.monotonic()+30,metadata=root/'m.json')
    assert b.counts()=={'API':0,'DFN':0}


def test_old_materialization_and_wrong_plan_are_not_relabelled():
    import tempfile
    m=load();root=Path(tempfile.mkdtemp(prefix='rgo-',dir=m.MAIN/'runs'))
    protocol=m.validate_proposal();old=m.materialize_old(protocol)
    assert m.fingerprint(old)==protocol['sources']['old_full']['fingerprint']
    b=m.ExperimentBudget.start(root/'j',protocol_sha='a'*64)
    b.begin('preflight');b.charge('API','fixture-gate');b.finish(True);b.begin('initialization')
    base=m.read(m.PROPOSAL/'new_full.disabled-config.json')
    base['optimization'].update(gp_sweeps=0,global_pool_size=16,local_pool_size=8)
    common={'kind':'initialization','arm':'new_full','seed':1709,'solve_cap':0,
            'base_config':base,'deadline':b.deadline,'software_fixture':True,
            'coordinates':m.read(m.PROPOSAL/'fixed-eight-coordinates.json')['parameters']}
    initial=[]
    for label,source in (('new',m.WT),('old',old)):
        spec={**common,'source_root':str(source),'source':m.fingerprint(source),
              'label':label,'output':str(root/label)}
        initial.append(m.supervise(m.worker_entry,spec,b,deadline=time.monotonic()+60,metadata=root/(label+'.json')))
    assert m.check_initialization(initial[0]['ordered_records'],initial[1]['ordered_records'])
    # The old worker must reject a current-source initial plan, with zero solves.
    spec.update(kind='arm',arm='old_full',label='reject',output=str(root/'reject'),
        initial={'path':initial[0]['plan_path'],'sha256':m.sha(initial[0]['plan_path'])})
    b.finish(True);b.begin('main')
    with pytest.raises(RuntimeError):
        m.supervise(m.worker_entry,spec,b,deadline=time.monotonic()+60,metadata=root/'reject.json')
    assert b.counts()=={'API':1,'DFN':0}


def test_wake_lease_restores_previous_thread_state_on_failure(tmp_path):
    from types import SimpleNamespace
    m=load();assert hasattr(m,'keep_awake'), 'bounded experiment wake lease missing'
    calls=[]
    def set_state(value):calls.append(value);return 0x80000000
    fake=SimpleNamespace(SetThreadExecutionState=set_state)
    with pytest.raises(RuntimeError):
        with m.keep_awake(tmp_path/'lease.json',kernel=fake):
            raise RuntimeError('fixture abort')
    assert calls==[0x80000001,0x80000000]
    state=json.loads((tmp_path/'lease.json').read_text())
    assert state['active'] is False and state['released'] is True


@pytest.mark.parametrize('status,want',[(401,True),(403,True),(404,True),(503,True),(500,False),(429,False),(None,False)])
def test_unavailable_model_or_route_stops_without_provider_free_text(status,want):
    w=worker_module(); assert hasattr(w,'permanent_api_failure'), 'permanent API stop gate missing'
    assert w.permanent_api_failure({'http_status':status}) is want


@pytest.mark.parametrize('status',[404,503])
def test_permanent_region_failure_stops_before_next_candidate(tmp_path,status):
    from test_lgbo_region_workflow import optimizer
    from llmbo_para.electrothermal_requests import LLMRequestFailure
    w=worker_module();opt=optimizer(tmp_path);opt.initialize();before=opt.attempts
    class Budget:
        deadline=time.monotonic()+30
        def require_candidate(self,n):assert n==0
    controller=w._controller(opt.llm_controller.prepared,Budget(),software_fixture=True)
    class Unavailable:
        def __init__(self):self.calls=0
        def post(self,payload):
            self.calls+=1
            raise LLMRequestFailure('http_error',{'http_status':status,'http_request_started':True})
    transport=Unavailable();controller.transport=transport;opt.llm_controller=controller
    with pytest.raises(RuntimeError):opt.step()
    assert opt.attempts==before and opt.rounds==[] and transport.calls==1


def child_sleep(ready):
    Path(ready).write_text('ready')
    time.sleep(30)


def orphaning_worker(spec, connection):
    import multiprocessing,os
    ready=spec['child_pid']+'.ready'
    p=multiprocessing.get_context('spawn').Process(target=child_sleep,args=(ready,))
    p.start();Path(spec['child_pid']).write_text(str(p.pid))
    until=time.monotonic()+10
    while not Path(ready).exists() and time.monotonic()<until:time.sleep(.01)
    assert Path(ready).exists()
    os._exit(7)


def pid_alive(pid, wait_ms=0):
    import ctypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[ctypes.c_ulong,ctypes.c_int,ctypes.c_ulong];k.OpenProcess.restype=ctypes.c_void_p
    h=k.OpenProcess(0x100000,False,pid)
    if not h:return False
    try:
        k.WaitForSingleObject.argtypes=[ctypes.c_void_p,ctypes.c_ulong]
        return k.WaitForSingleObject(h,wait_ms)==0x102
    finally:
        k.CloseHandle.argtypes=[ctypes.c_void_p];k.CloseHandle(h)


def test_abrupt_parent_exit_cannot_leave_sleeping_grandchild(tmp_path):
    m=load();b=m.ExperimentBudget.start(tmp_path/'j',protocol_sha='a'*64);b.begin('preflight')
    with pytest.raises(RuntimeError):
        m.supervise(orphaning_worker,{'child_pid':str(tmp_path/'pid')},b,
            deadline=time.monotonic()+15,metadata=tmp_path/'m.json')
    assert (tmp_path/'pid').exists()
    child_pid=int((tmp_path/'pid').read_text())
    try:
        # Job accounting can reach zero before the original process object is
        # signaled. Wait for that OS postcondition, with a strict finite limit.
        assert not pid_alive(child_pid,2000), 'owned orphan survived parent death'
        assert json.loads((tmp_path/'m.json').read_text())['owned_tree_stopped'] is True
    finally:
        if pid_alive(child_pid):
            import subprocess
            subprocess.run(['taskkill','/PID',str(child_pid),'/T','/F'],capture_output=True)


def successful_worker(spec,connection):
    connection.send(('result',{'status':'completed'}))


def test_late_integrity_failure_cannot_accept_successful_worker(tmp_path):
    m=load();b=m.ExperimentBudget.start(tmp_path/'j',protocol_sha='a'*64);b.begin('preflight')
    assert 'integrity_check' in __import__('inspect').signature(m.supervise).parameters, 'late integrity gate missing'
    calls=[]
    def check():
        calls.append(1)
        if len(calls)>1:raise ValueError('fixture late source mutation')
    with pytest.raises(ValueError):
        m.supervise(successful_worker,{},b,deadline=time.monotonic()+20,
            metadata=tmp_path/'m.json',integrity_check=check)
    assert json.loads((tmp_path/'m.json').read_text())['status']!='returned'
    assert b.counts()=={'API':0,'DFN':0}


def test_new_source_and_harness_are_owned_snapshots_with_exact_bytes():
    m=load(); assert hasattr(m,'materialize_new'), 'owned current-source snapshot missing'
    p=m.validate_proposal();source=m.materialize_new(p)
    assert source.resolve()!=m.WT.resolve()
    assert m.fingerprint(source)==p['sources']['new_full_and_plain']['fingerprint']
    assert hasattr(m,'freeze_runtime'), 'owned runtime snapshot missing'
    frozen=m.freeze_runtime()
    assert frozen.resolve()!=SCRIPT.parent.resolve()
    for name in ('run_lgbo_real_gain.py','lgbo_real_gain_worker.py'):
        assert (frozen/name).read_bytes()==(SCRIPT.parent/name).read_bytes()


def test_final_source_mismatch_cancels_completed_revert():
    m=load(); assert hasattr(m,'final_integrity_gate'), 'final source decision gate missing'
    original={'status':'completed','decision':{'revert':True,'needs_confirmation':True}}
    result=m.final_integrity_gate(original,expected={'source':'a'*64},actual={'source':'b'*64})
    assert result['status']=='inconclusive' and result['decision']['revert'] is False
    assert original['decision']['revert'] is True


def test_changed_sealed_config_is_rejected_instead_of_used(tmp_path,monkeypatch):
    import shutil
    m=load();original=m.PROPOSAL
    for path in original.iterdir():
        if path.is_file():shutil.copy2(path,tmp_path/path.name)
    monkeypatch.setattr(m,'PROPOSAL',tmp_path)
    cfg=json.loads((tmp_path/'new_full.disabled-config.json').read_text())
    cfg['llm']['task_options']['region_preference_electrothermal']['timeout_s']=120.
    (tmp_path/'new_full.disabled-config.json').write_text(json.dumps(cfg),encoding='utf-8')
    with pytest.raises(ValueError):m._configuration('new_full')


def test_initialization_hash_is_pinned_once_and_never_refreshed(tmp_path):
    m=load();assert hasattr(m,'checked_initial'), 'fixed initialization reference check missing'
    path=tmp_path/'initial.json';path.write_text('{"value":1}')
    reference={'path':str(path),'sha256':m.sha(path)}
    assert m.checked_initial(reference)==reference
    path.write_text('{"value":2}')
    with pytest.raises(ValueError):m.checked_initial(reference)
