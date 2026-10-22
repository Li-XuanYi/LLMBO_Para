"""Factorial controls run through the actual software evaluation and BO stack."""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import importlib.util
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pytest

WT = Path(__file__).resolve().parents[1]
SCRIPT = WT/'scripts/run_lgbo_numerical_ablation.py'
CONFIG = WT/'configs/electrothermal-lgbo-numerical-ablation-software.json'

def load():
    assert SCRIPT.is_file(), 'approved numerical ablation entry is missing'
    spec = importlib.util.spec_from_file_location('lgbo_numerical_entry', SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module

def base():
    from electrothermal_fixtures import et_config
    cfg = et_config(('0.5C','1C'))
    cfg['optimization'].pop('region')
    cfg['optimization'].update(region_method='lgbo_v1', initial_count=8,
        total_candidate_budget=28, global_pool_size=16, local_pool_size=8, gp_sweeps=0)
    cfg['optimization']['warmstart'].update(count=8,pool_size=16,max_requests=1,max_candidates=16,max_evaluations=16)
    cfg['budgets']['wall_clock_s'] = 120.
    return cfg

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def test_factorial_matrix_and_no_config_mutation():
    m = load(); cfg=base(); before=deepcopy(cfg); p=m.ablation_protocol(cfg)
    assert cfg == before
    assert [(c['cell'],c['global_pool_size'],c['gp_sweeps']) for c in p['matrix']] == [
        ('G016_S0',16,0),('G512_S0',512,0),('G016_S4',16,4),('G512_S4',512,4)]
    assert p['seeds']==[17,41,59] and len(p['cases'])==24
    assert p['max_software_candidates']==496 and p['max_software_calls']==992
    assert p['wall_clock_s']==3600 and p['per_run_wall_clock_s']==120
    for cell in p['matrix']:
        for seed in p['seeds']:
            cases=[c for c in p['cases'] if c['cell']==cell['cell'] and c['seed']==seed]
            assert [c['mode'] for c in cases] == (['full_llmbo_mo','warmstart_only'] if seed==41 else ['warmstart_only','full_llmbo_mo'])
            for c in cases:
                spec={'path':'new-plan.json','sha256':'a'*64}
                out=m.make_case_config(cfg,global_pool_size=c['global_pool_size'],gp_sweeps=c['gp_sweeps'],seed=seed,mode=c['mode'],initial_plan=spec)
                assert cfg==before and out['optimization']['local_pool_size']==8
                assert out['optimization']['initial_count']==8 and out['optimization']['total_candidate_budget']==28
                assert out['optimization']['initial_plan']==spec
                assert out['llm']['enabled'] is False and out['budgets']['max_llm_requests']==out['budgets']['max_solver_calls']==0
    p['base_config']['fixed']['cell_volume_m3']=999
    assert cfg==before

@pytest.mark.parametrize('damage', ['provider','run_kind','rates','API','solver','enabled','retry','parallel','method'])
def test_unsafe_or_unselected_protocol_is_rejected(damage):
    m=load(); cfg=base()
    if damage=='provider': cfg['model']['provider']='pybamm'
    elif damage=='run_kind': cfg['run_kind']='synthetic_dfn'
    elif damage=='rates': cfg['fit_rates'].append('3C')
    elif damage=='API': cfg['budgets']['max_llm_requests']=1
    elif damage=='solver': cfg['budgets']['max_solver_calls']=1
    elif damage=='enabled': cfg['llm']['enabled']=True
    elif damage=='retry': cfg['optimization']['max_rate_attempts']=2
    elif damage=='parallel': cfg['optimization']['parallel_workers']=2
    else: cfg['optimization']['region_method']='lgbo_v2'
    with pytest.raises(ValueError):m.ablation_protocol(cfg)

@pytest.mark.parametrize('overrides',[{'global_pool_size':32},{'gp_sweeps':1},{'seed':101},{'mode':'parego'}])
def test_make_case_rejects_unselected_settings(overrides):
    m=load();kw=dict(global_pool_size=16,gp_sweeps=0,seed=17,mode='warmstart_only',initial_plan={'path':'p','sha256':'a'*64})
    kw.update(overrides)
    with pytest.raises(ValueError):m.make_case_config(base(),**kw)

def test_cli_default_dry_run_does_not_create_an_experiment(tmp_path):
    load(); assert CONFIG.is_file(), 'software comparison config missing'
    env={**os.environ,'PYTHONPATH':str(WT/'src'),'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PYBAMM_DISABLE_TELEMETRY':'true'}
    for key in ('SUB2API_API_KEY','OPENAI_API_KEY'):env.pop(key,None)
    out=tmp_path/'not-created'
    proc=subprocess.run([sys.executable,str(SCRIPT),'--base-config',str(CONFIG),'--output',str(out)],capture_output=True,text=True,env=env,timeout=30)
    assert proc.returncode==0,proc.stderr
    result=json.loads(proc.stdout)
    assert result['dry_run'] is True and len(result['cases'])==24
    assert result['API_requests']==result['DFN_solves']==result['new_objective_evaluations']==0
    assert not out.exists()


def test_windows_archive_layout_snapshots_all_sources_before_any_evaluation(tmp_path):
    m=load();assert hasattr(m,'case_output_root'),'compact archive layout is missing'
    import tempfile,uuid
    # Reproduce the failed batch's output-root length, independent of pytest's
    # longer per-test name. This is filesystem-only: no objective evaluations.
    parent=Path(tempfile.mkdtemp(prefix='np-',dir=os.environ['TEMP']))
    root=parent/('p'*max(1,112-len(str(parent))-1))
    cfg=base();protocol=m.ablation_protocol(cfg)
    check=m.validate_archive_paths(root)
    assert check['maximum_path_length']<260
    from llmbo_para.runstore import RunStore
    store=RunStore(m.case_output_root(root,protocol['cases'][0]),cfg,command='Windows archive path regression')
    hashes=read(store.path/'source-sha256.json')
    assert 'src/llmbo_para/prompts/region_preference_candidate_aware_electrothermal.txt' in {Path(k).as_posix() for k in hashes}
    assert m.case_output_root(root,protocol['cases'][0])!=m.case_output_root(root,protocol['cases'][1])


def test_impossible_windows_archive_path_is_rejected_before_creating_a_batch(tmp_path):
    m=load();assert hasattr(m,'validate_archive_paths'),'archive path preflight is missing'
    if os.name!='nt':pytest.skip('Windows path-length preflight')
    root=tmp_path/('p'*180)
    with pytest.raises(ValueError,match='archive path'):
        m.run_software_ablation(base(),root)
    assert not root.exists()

class Proposals:
    def __init__(self,space):self.space=space
    def post(self,payload):
        from llmbo_para.sobol import Sobol6
        return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures')}|{
            'candidates':[{'parameters':dict(zip([s.name for s in self.space.specs],self.space.denormalize(x)))} for x in Sobol6(17).draw(16)]}

def initialize(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment,run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    cfg=base();cfg['optimization'].update(mode='warmstart_only',total_candidate_budget=8)
    _, prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    result=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=Proposals(prepared.space),is_mock=True))
    path=Path(result['run_directory'])/'initial-plan.json'
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()},result


def test_controlled_recovery_reuses_verified_screening_and_subtracts_prior_costs(tmp_path):
    m=load();assert hasattr(m,'recovery_protocol'),'controlled recovery contract is missing'
    spec,_=initialize(tmp_path/'origin');original=Path(spec['path']).read_bytes()
    recovery=dict(initial_plan=spec,prior_costs={'new_objective_evaluations':16,'software_calls':32})
    protocol=m.recovery_protocol(base(),recovery)
    assert protocol['max_software_candidates']==480 and protocol['max_software_calls']==960
    assert protocol['recovery']==recovery and len(protocol['cases'])==24
    assert Path(spec['path']).read_bytes()==original
    bad=deepcopy(recovery);bad['prior_costs']['new_objective_evaluations']=0
    with pytest.raises(ValueError):m.recovery_protocol(base(),bad)
    bad=deepcopy(recovery);bad['initial_plan']['sha256']='0'*64
    with pytest.raises(ValueError):m.recovery_protocol(base(),bad)


def test_recovery_worker_never_repeats_initialization_evaluation(tmp_path,monkeypatch):
    m=load();assert hasattr(m,'recovery_protocol'),'controlled recovery contract is missing'
    spec,_=initialize(tmp_path/'origin')
    recovery=dict(initial_plan=spec,prior_costs={'new_objective_evaluations':16,'software_calls':32})
    protocol=m.recovery_protocol(base(),recovery);protocol['cases']=[]
    from llmbo_para.electrothermal_provenance import source_fingerprint
    from llmbo_para import electrothermal_workflow as workflow
    def unexpected_run(*args,**kwargs):pytest.fail('recovery must not start a screening workflow')
    monkeypatch.setattr(workflow,'run_electrothermal_experiment',unexpected_run)
    protocol.update(monotonic_deadline=time.monotonic()+60,source_fingerprint=source_fingerprint(),script_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
    class Connection:
        messages=[]
        def send(self,message):self.messages.append(message)
        def recv(self):return 'continue'
    connection=Connection();m._ablation_worker(protocol,str(tmp_path/'reused'),connection)
    _,result=connection.messages[-1]
    assert result['costs']=={'new_objective_evaluations':0,'software_calls':0}
    assert result['failure'] is None and not (tmp_path/'reused/init').exists()
    ref=read(tmp_path/'reused/initialization-reference.json')
    assert ref['spec']==spec and ref['prior_costs']==recovery['prior_costs']

def test_initialization_semantics_and_no_screening_leak(tmp_path):
    m=load();spec,initial=initialize(tmp_path/'init');original=Path(spec['path']).read_bytes()
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    signatures=[]
    for global_count,sweeps,mode in [(16,0,'warmstart_only'),(512,0,'full_llmbo_mo'),(16,4,'full_llmbo_mo'),(512,4,'warmstart_only')]:
        cfg=m.make_case_config(base(),global_pool_size=global_count,gp_sweeps=sweeps,seed=17,mode=mode,initial_plan=spec)
        report,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
        assert report['ready'],report['errors']
        assert len(p.initial_plan.records)==8 and len(p.initial_plan.history_evidence['screening_records'])==16
        signatures.append(p.signatures)
    assert len({s.initialization_compatibility for s in signatures})==1
    assert len({s.algorithm for s in signatures})==4
    assert Path(spec['path']).read_bytes()==original
    corrupted=read(spec['path']); corrupted['signatures']['source']='8'*64
    for r in corrupted['records']:r['signatures']['source']='8'*64
    from llmbo_para.runstore import digest_value
    corrupted.pop('plan_sha256');corrupted['plan_sha256']=digest_value(corrupted)
    bad=tmp_path/'foreign-source-plan.json';bad.write_text(json.dumps(corrupted),encoding='utf-8')
    cfg['optimization']['initial_plan']={'path':str(bad),'sha256':hashlib.sha256(bad.read_bytes()).hexdigest()}
    report,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert not report['ready'] and p is None

@pytest.mark.parametrize('sweeps',[0,4])
def test_fit_observer_preserves_scientific_state_and_records_real_policy(tmp_path,sweeps):
    m=load()
    from llmbo_para.surrogate import Matern52GP
    x=[[.2]*6,[.5]*6,[.8]*6];y=[1.,-1.,.5]
    expected=Matern52GP(max_sweeps=sweeps).fit(x,y,group=()).state_dict()
    path=tmp_path/'fits.jsonl'
    with m.FitObserver(path,phase='BO'):
        actual=Matern52GP(max_sweeps=sweeps).fit(x,y,group=()).state_dict()
    assert actual==expected
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows)==1 and rows[0]['phase']=='BO' and rows[0]['max_sweeps']==sweeps
    assert rows[0]['elapsed_s']>=0
    assert rows[0]['sweeps_completed']==0 if sweeps==0 else 1<=rows[0]['sweeps_completed']<=4

def test_actual_workflow_budget_stops_before_extra_candidate(tmp_path):
    m=load()
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment,run_electrothermal_fixed_candidates
    _,p=prepare_electrothermal_experiment(base(),base_dir=tmp_path)
    budget=m.SoftwareBudget(tmp_path/'budget.jsonl',max_candidates=1,max_rate_calls=2)
    with budget.observe():
        with pytest.raises(RuntimeError):
            run_electrothermal_fixed_candidates(p,[p.space.denormalize([.2]*6),p.space.denormalize([.7]*6)],tmp_path/'runs')
    assert budget.candidate_evaluations==1 and budget.rate_calls==2
    runs=list((tmp_path/'runs').iterdir());assert len(runs)==1
    assert len(list((runs[0]/'electrothermal-evaluations').glob('*.json')))==1
    assert read(runs[0]/'terminal.json')['status']=='failed'


def test_worker_guard_blocks_network_and_battery_before_execution():
    m=load()
    import socket
    import pybamm
    with m.SoftwareBoundary() as guard:
        with pytest.raises(RuntimeError):socket.create_connection(('example.invalid',443))
        with pytest.raises(RuntimeError):pybamm.Simulation(pybamm.lithium_ion.DFN()).solve([0,1])
    assert guard.counts()=={'network_attempts':1,'battery_solve_attempts':1}

def sleepy_worker(protocol,output,connection):
    time.sleep(10)


def unsealed_worker(protocol,output,connection):
    connection.send(('result',dict(status='completed',cases=[],boundary={'network_attempts':0,'battery_solve_attempts':0})))


def tuple_seal_reply(protocol,output,connection,*,tamper=False):
    rows=fake_complete_cases()
    for row in rows:row['summary']['pareto']=[{'parameters':(.5,)*6,'objectives':(.04,.3)}]
    result=dict(status='completed',cases=rows,boundary={'network_attempts':0,'battery_solve_attempts':0})
    root=Path(output);summary=root/'summary.json'
    summary.write_text(json.dumps(result),encoding='utf-8')
    (root/'stage-a-seal.json').write_text(json.dumps(dict(status='completed',
        source_fingerprint=protocol['source_fingerprint'],script_sha256=protocol['script_sha256'],
        files={'summary.json':hashlib.sha256(summary.read_bytes()).hexdigest()})),encoding='utf-8')
    if tamper:rows[0]['summary']['pareto'][0]['objectives']=(.9,.8)
    connection.send(('result',result))


def tuple_worker(protocol,output,connection):
    tuple_seal_reply(protocol,output,connection)


def tampered_tuple_worker(protocol,output,connection):
    tuple_seal_reply(protocol,output,connection,tamper=True)


@pytest.mark.parametrize('worker,expected',[(tuple_worker,'completed'),(tampered_tuple_worker,'incomplete')])
def test_real_pipe_seal_compares_scientific_json_without_losing_tamper_checks(tmp_path,monkeypatch,worker,expected):
    m=load();monkeypatch.setattr(m,'_ablation_worker',worker)
    result=m.run_software_ablation(base(),tmp_path/expected)
    assert result['status']==expected


def blocking_case_worker(protocol,output,connection):
    connection.send(('case_started','G016_S0_17_warmstart_only'))
    assert connection.recv()=='continue'
    time.sleep(10)


def late_case_worker(protocol,output,connection):
    connection.send(('case_started','G016_S0_17_warmstart_only'))
    assert connection.recv()=='continue'
    time.sleep(.5)
    connection.send(('case_finished','G016_S0_17_warmstart_only'))
    assert connection.recv()=='continue'
    (Path(output)/'next-case-started').write_text('must not happen',encoding='utf-8')


@pytest.mark.parametrize('worker',[blocking_case_worker,late_case_worker])
def test_per_case_hard_deadline_terminates_owned_worker_before_next_case(tmp_path,monkeypatch,worker):
    m=load();monkeypatch.setattr(m,'_ablation_worker',worker)
    monkeypatch.setattr(m,'PER_RUN_WALL_CLOCK_S',.2,raising=False)
    monkeypatch.setattr(m,'STAGE_WALL_CLOCK_S',10)
    before={p.pid for p in multiprocessing.active_children()};started=time.monotonic()
    result=m.run_software_ablation(base(),tmp_path/'per-case-timeout')
    assert result['status']=='incomplete' and result['failure']=='CaseTimeout'
    assert result['timed_out_case']=='G016_S0_17_warmstart_only'
    assert .1<=time.monotonic()-started<5
    assert result['boundary'] is None and not (tmp_path/'per-case-timeout/next-case-started').exists()
    assert {p.pid for p in multiprocessing.active_children()}==before


def test_stage_elapsed_includes_initialization_and_all_cases(tmp_path,monkeypatch):
    m=load()
    from llmbo_para import electrothermal_workflow as workflow,electrothermal_audit as audit
    from llmbo_para.electrothermal_provenance import source_fingerprint
    real_run,real_audit=workflow.run_electrothermal_experiment,audit.audit_electrothermal_run
    clock=[0.]
    def run(*args,**kwargs):
        result=real_run(*args,**kwargs);clock[0]+=10.;return result
    def check(*args,**kwargs):
        result=real_audit(*args,**kwargs);clock[0]+=1.;return result
    monkeypatch.setattr(workflow,'run_electrothermal_experiment',run)
    monkeypatch.setattr(audit,'audit_electrothermal_run',check)
    monkeypatch.setattr(m.time,'perf_counter',lambda:clock[0])
    protocol=m.ablation_protocol(base());protocol['cases']=protocol['cases'][:2]
    protocol.update(monotonic_deadline=time.monotonic()+90,source_fingerprint=source_fingerprint(),script_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
    class Connection:
        messages=[]
        def send(self,message):self.messages.append(message)
        def recv(self):return 'continue'
    connection=Connection();m._ablation_worker(protocol,str(tmp_path/'time'),connection)
    kind,result=connection.messages[-1]
    assert kind=='result' and len(result['cases'])==2
    assert [c['elapsed_s'] for c in result['cases']]==[11.,11.]
    assert result['elapsed_s']==33.


def test_workflow_exception_closes_phase_before_preserving_failure(tmp_path,monkeypatch):
    m=load()
    from llmbo_para import electrothermal_workflow as workflow
    from llmbo_para.electrothermal_provenance import source_fingerprint
    def failed_snapshot(*args,**kwargs):raise OSError('fixture snapshot failed before evaluation')
    monkeypatch.setattr(workflow,'run_electrothermal_experiment',failed_snapshot)
    protocol=m.ablation_protocol(base())
    protocol.update(monotonic_deadline=time.monotonic()+60,source_fingerprint=source_fingerprint(),script_sha256=hashlib.sha256(SCRIPT.read_bytes()).hexdigest())
    class Connection:
        messages=[]
        def send(self,message):self.messages.append(message)
        def recv(self):return 'continue'
    connection=Connection();m._ablation_worker(protocol,str(tmp_path/'failure'),connection)
    assert connection.messages[:2]==[('case_started','initialization'),('case_finished','initialization')]
    kind,result=connection.messages[-1]
    assert kind=='result' and result['status']=='incomplete' and result['boundary']=={'network_attempts':0,'battery_solve_attempts':0}
    assert result['costs']=={'new_objective_evaluations':0,'software_calls':0}


def test_completion_requires_worker_seal_inside_owned_deadline(tmp_path,monkeypatch):
    m=load();monkeypatch.setattr(m,'_ablation_worker',unsealed_worker)
    result=m.run_software_ablation(base(),tmp_path/'unsealed')
    assert result['status']=='incomplete' and len(result['missing_cases'])==24
    assert not (tmp_path/'unsealed/stage-a-seal.json').exists()

def test_benchmark_timeout_is_incomplete_without_fabricated_boundary(tmp_path,monkeypatch):
    m=load();monkeypatch.setattr(m,'STAGE_WALL_CLOCK_S',.25)
    monkeypatch.setattr(m,'_ablation_worker',sleepy_worker)
    before={p.pid for p in multiprocessing.active_children()}
    result=m.run_software_ablation(base(),tmp_path/'timeout')
    assert result['status']=='incomplete' and result['boundary'] is None
    assert result['cases']==[] and result['HV'] is None
    assert len(result['missing_cases'])==24
    assert {p.pid for p in multiprocessing.active_children()}==before


@pytest.mark.parametrize('failure',['case_timeout','stage_timeout','worker_exit','EOF'])
@pytest.mark.parametrize('ledger',['missing','valid','torn'])
@pytest.mark.parametrize('existing_summary',[False,True])
def test_recovery_supervisor_failure_preserves_prior_and_persisted_costs(tmp_path,monkeypatch,failure,ledger,existing_summary):
    m=load()
    prior={'new_objective_evaluations':16,'software_calls':32}
    recovery=dict(initial_plan={'path':'unit-only','sha256':'a'*64},prior_costs=prior)
    protocol=m.ablation_protocol(base());protocol['recovery']=deepcopy(recovery)
    monkeypatch.setattr(m,'recovery_protocol',lambda cfg,spec:deepcopy(protocol))
    def interrupted(worker,args,*,deadline):
        root=Path(args[1])
        if existing_summary:
            (root/'summary.json').write_text('{"worker_evidence":"preserve"}',encoding='utf8')
            (root/'stage-a-seal.json').write_text('{"partial_worker_seal":"preserve"}',encoding='utf8')
        if ledger!='missing':
            events=[dict(kind='candidate_started',new_objective_evaluations=1,software_calls=0),
                    dict(kind='software_call',rate='0.5C',new_objective_evaluations=1,software_calls=1)]
            content=''.join(json.dumps(event)+'\n' for event in events)
            if ledger=='torn':content+='{"kind":"software_call","software_calls":'
            (root/'software-costs.jsonl').write_text(content,encoding='utf8')
        if failure=='case_timeout':raise m.CaseTimeout('G016_S0_17_warmstart_only')
        if failure=='stage_timeout':raise TimeoutError('unit total deadline')
        if failure=='EOF':raise EOFError('unit closed pipe')
        raise RuntimeError('unit worker exited')
    monkeypatch.setattr(m,'_supervise_ablation',interrupted)
    root=tmp_path/'interrupted'
    result=m.run_software_ablation(base(),root,recovery=recovery)
    expected={'new_objective_evaluations':int(ledger!='missing'),'software_calls':int(ledger!='missing')}
    assert result['status']=='incomplete' and result['boundary'] is None
    assert result['prior_costs']==prior
    assert result['costs']==expected and result['costs_complete'] is False
    assert result['cumulative_costs']=={key:prior[key]+expected[key] for key in prior}
    assert result['costs_attribution']=='persisted_lower_bound_after_termination'
    assert result['cost_ledger_issue']==({'missing':'missing','valid':None,'torn':'invalid_or_truncated_record'}[ledger])
    assert read(root/'supervisor-incomplete.json')==result
    if existing_summary:
        assert read(root/'summary.json')=={'worker_evidence':'preserve'}
        assert read(root/'stage-a-seal.json')=={'partial_worker_seal':'preserve'}
    else:assert read(root/'summary.json')==result
    assert len(result['missing_cases'])==24 and result['HV'] is None

def test_summary_keeps_missing_cases_and_missing_objectives(tmp_path):
    m=load();result=m.summarize_numerical_ablation([])
    assert result['status']=='incomplete' and len(result['missing_cases'])==24
    assert result['contrasts']==[] and result['HV'] is None

def fake_complete_cases():
    rows=[]
    for cell,delta in [('G016_S0',1.),('G512_S0',3.),('G016_S4',2.),('G512_S4',6.)]:
        for seed in (17,41,59):
            for mode in ('warmstart_only','full_llmbo_mo'):
                rows.append(dict(cell=cell,seed=seed,mode=mode,case_id=f'{cell}_{seed}_{mode}',status='completed',
                    initial_plan_sha256='1'*64,source_fingerprint='2'*64,comparison_protocol='3'*64,
                    initialization_ids=[f'initial-{i}' for i in range(8)],audit_passed=True,
                    summary={'HV':10.+(delta if mode=='full_llmbo_mo' else 0.),'BO_rounds':20}))
    return rows

def test_run_level_factorial_contrasts_use_paired_differences():
    m=load(); result=m.summarize_numerical_ablation(fake_complete_cases())
    assert result['status']=='completed' and result['missing_cases']==[]
    contrasts={r['cell']:r['delta_HV'] for r in result['contrasts'] if r['seed']==17}
    assert contrasts=={'G016_S0':1.,'G512_S0':3.,'G016_S4':2.,'G512_S4':6.}
    effect=next(r for r in result['factorial_effects'] if r['seed']==17)
    assert {k:effect[k] for k in ('density_S0','density_S4','fit_G016','fit_G512','interaction')}=={
        'density_S0':2.,'density_S4':4.,'fit_G016':1.,'fit_G512':3.,'interaction':2.}

@pytest.mark.parametrize('damage',['duplicate','initial_plan','source','comparison','initialization_ids','audit','BO_rounds'])
def test_inconsistent_cases_cannot_be_certified_as_complete(damage):
    m=load();rows=fake_complete_cases()
    if damage=='duplicate':rows[-1]=deepcopy(rows[0])
    elif damage=='initial_plan':rows[-1]['initial_plan_sha256']='9'*64
    elif damage=='source':rows[-1]['source_fingerprint']='9'*64
    elif damage=='comparison':rows[-1]['comparison_protocol']='9'*64
    elif damage=='initialization_ids':rows[-1]['initialization_ids']=['not-the-shared-plan']*8
    elif damage=='audit':rows[-1]['audit_passed']=False
    else:rows[-1]['summary']['BO_rounds']=19
    with pytest.raises(ValueError):m.summarize_numerical_ablation(rows)


@pytest.mark.parametrize('hv',[None,-1.])
def test_completed_cases_require_actual_fixed_space_hv(hv):
    m=load();rows=fake_complete_cases();rows[-1]['summary']['HV']=hv
    with pytest.raises(ValueError):m.summarize_numerical_ablation(rows)

class NoPreference:
    def post(self,payload):
        # Deliberate unrelated draws must not consume MO's owned streams.
        import random
        random.random();np.random.random(10)
        from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id
        return {'request_id':lgbo_request_id(payload),'region':{'kind':'none'}}

@pytest.mark.parametrize('global_count,sweeps',[(16,0),(512,4)])
def test_real_seeded_workflow_reproduces_no_preference_and_no_pool_leak(tmp_path,global_count,sweeps):
    m=load();spec,_=initialize(tmp_path/'init')
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    budget=m.SoftwareBudget(tmp_path/'costs.jsonl',max_candidates=4,max_rate_calls=8)
    events=[]
    for mode in ('warmstart_only','full_llmbo_mo'):
        cfg=m.make_case_config(base(),global_pool_size=global_count,gp_sweeps=sweeps,seed=17,mode=mode,initial_plan=spec)
        cfg['optimization']['total_candidate_budget']=10 # Only two rounds in a unit fixture, not a benchmark override.
        with budget.observe():
            result=run_electrothermal_experiment(cfg,tmp_path/mode,base_dir=tmp_path,
                llm_controller=ElectrothermalLLMController(transport=NoPreference(),is_mock=True))
        run=Path(result['run_directory']);assert audit_electrothermal_run(run,deep=True)['passed']
        rounds=[read(p) for p in sorted((run/'mo-rounds').glob('*.json'))]
        assert [len(e['context']['scalarization']['x']) for e in rounds]==[8,9]
        assert result['costs']['software_calls']==4 and result['costs']['cache_hits']==8
        assert all(global_count<=len(e['context']['pool'])<=global_count+8 for e in rounds)
        assert all(e['context']['gp_state']['group']==[] and e['context']['gp_state']['lengthscale_prior'] is None for e in rounds)
        events.append(rounds)
    assert budget.candidate_evaluations==4 and budget.rate_calls==8
    for a,b in zip(*events):
        for field in ('pool','gp_state','scalarization'):
            assert a['context'][field]==b['context'][field]
        assert a['selected_index']==b['selected_index'] and a['evaluation_id']==b['evaluation_id']


def test_partial_temperature_does_not_create_a_target_or_consume_replacement(tmp_path):
    m=load();spec,_=initialize(tmp_path/'init')
    from dataclasses import replace
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    class PartialFirst(SyntheticElectrothermalSimulator):
        calls=0
        def simulate(self,parameters,case):
            self.calls+=1
            trace=super().simulate(parameters,case)
            return replace(trace,temperature_k=[float('nan')]*len(trace.time_s)) if self.calls==1 else trace
    cfg=m.make_case_config(base(),global_pool_size=16,gp_sweeps=0,seed=17,mode='warmstart_only',initial_plan=spec)
    cfg['optimization']['total_candidate_budget']=10
    budget=m.SoftwareBudget(tmp_path/'costs.jsonl',max_candidates=2,max_rate_calls=4)
    with budget.observe():
        result=run_electrothermal_experiment(cfg,tmp_path/'partial',base_dir=tmp_path,simulator=PartialFirst())
    run=Path(result['run_directory']);rounds=[read(p) for p in sorted((run/'mo-rounds').glob('*.json'))]
    records=[read(p) for p in (run/'electrothermal-evaluations').glob('*.json')]
    partial=next(r for r in records if not r['complete_pair_valid'])
    assert partial['objectives'] is None and partial['objective_components']['F_T'] is None
    assert partial['rates'][0]['voltage']['valid'] and not partial['rates'][0]['cell_temperature']['valid']
    assert [len(e['context']['scalarization']['x']) for e in rounds]==[8,8]
    assert rounds[0]['context']['scalarization']['weights']!=rounds[1]['context']['scalarization']['weights']
    assert budget.candidate_evaluations==2 and budget.rate_calls==4
    assert result['BO_rounds']==2 and result['complete_pairs']==9
    assert audit_electrothermal_run(run,deep=True)['passed']
