"""Real stock algorithms on an analytic objective, never DFN/network."""
import json
from pathlib import Path
import random
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
POLICY_PY=Path(r'D:\Users\aa133\Desktop\LLMBO_Para\bo-repair-work\environments\baselines312-20261102\Scripts\python.exe')
sys.path.insert(0,str(ROOT/'scripts'))


def test_policy_rejects_network_and_pybamm_import():
    code = "import sys; sys.path.insert(0, sys.argv[1]); import et_classical_policy as p; p.install_restrictions(); import socket; socket.socket()"
    result = subprocess.run([str(POLICY_PY), '-c', code, str(ROOT/'scripts')], capture_output=True, text=True)
    assert result.returncode != 0 and 'policy operation forbidden' in result.stderr
    code = "import sys; sys.path.insert(0, sys.argv[1]); import et_classical_policy as p; p.install_restrictions(); import pybamm"
    result = subprocess.run([str(POLICY_PY), '-c', code, str(ROOT/'scripts')], capture_output=True, text=True)
    assert result.returncode != 0 and 'policy operation forbidden' in result.stderr


def toy_initial():
    rng=random.Random(7)
    return [[rng.random() for _ in range(6)] for _ in range(16)]


def policy_session(method,*,seed=93,rounds=50,break_pair=False):
    script=ROOT/'scripts/et_classical_policy.py'
    assert script.is_file(),'stock baseline policy service missing'
    process=subprocess.Popen([str(POLICY_PY),'-u',str(script)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    initial=toy_initial();seen={tuple(x) for x in initial};events=[];new=0
    spec={'method':method,'seed':seed,'rounds':rounds,'initial_x':initial}
    process.stdin.write(json.dumps(spec)+'\n');process.stdin.flush()
    try:
        while True:
            line=process.stdout.readline()
            assert line,process.stderr.read()
            message=json.loads(line);events.append(message)
            if message['type']!='evaluate':break
            x=message['x'];key=tuple(x);cached=key in seen
            if not cached:new+=1;seen.add(key)
            f=[sum(v*v for v in x)/6+.0001,sum((v-1)**2 for v in x)/6+.0001]
            broken=break_pair and not cached
            feedback={'complete_pair_valid':not broken,'objectives':None if broken else f,'cached':cached,'evaluation_id':'toy-'+str(len(events))}
            process.stdin.write(json.dumps(feedback)+'\n');process.stdin.flush()
        process.wait(timeout=20)
        return {'events':events,'new':new,'exit_code':process.returncode,'stderr':process.stderr.read()}
    finally:
        if process.poll() is None:process.kill();process.wait(timeout=10)


@pytest.mark.parametrize('method,stock',[('nsga2','NSGAII'),('smpso','SMPSO')])
def test_stock_policy_exact_budget_and_initial_order(method,stock):
    result=policy_session(method)
    assert result['exit_code']==0,result['stderr']
    assert result['events'][-1]['type']=='completed'
    assert result['events'][-1]['state']['new_evaluations']==50==result['new']
    assert [r['x'] for r in result['events'][:16]]==toy_initial()
    assert result['events'][-1]['state']['library_class'].endswith('.'+stock)
    assert all(0<=v<=1 for r in result['events'] if r['type']=='evaluate' for v in r['x'])


@pytest.mark.parametrize('method',['nsga2','smpso'])
def test_stock_policy_reproducible_and_seed_conditioned(method):
    first=policy_session(method,rounds=5)
    same=policy_session(method,rounds=5)
    other=policy_session(method,seed=94,rounds=5)
    assert first['events']==same['events']
    assert first['events'][16:]!=other['events'][16:]


@pytest.mark.parametrize('method',['nsga2','smpso'])
def test_partial_objective_stops_without_fake_fitness(method):
    result=policy_session(method,rounds=5,break_pair=True)
    assert result['exit_code']!=0
    assert result['events'][-1]['type']=='failed'
    assert result['events'][-1]['reason']=='incomplete_objective_pair'
    assert result['new']==1


def test_smpso_partial_generation_is_explicit():
    result=policy_session('smpso',rounds=50)
    assert result['events'][-1]['state']['partial_generation'] is True
    assert result['events'][-1]['state']['library_evaluations']==64


def test_baseline_configuration_uses_sixteen_and_zero_api():
    import importlib
    assert (ROOT/'scripts/et_classical_worker.py').exists(),'classical evaluator worker missing'
    m=importlib.import_module('et_classical_worker')
    base=json.loads((ROOT/'configs/electrothermal-lgbo-numerical-ablation-software.json').read_text(encoding='utf8'))
    cfg=m.config_for(base,seed=872104,rounds=50,software=False)
    assert cfg['optimization']['initial_count']==16
    assert cfg['optimization']['total_candidate_budget']==66
    assert cfg['optimization']['warmstart']['count']==16
    assert cfg['budgets']['max_llm_requests']==0 and not cfg['llm']['enabled']
    assert cfg['fit_rates']==['0.5C','1C']
