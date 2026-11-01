"""New factorial orchestration, no live network or battery calls."""
import importlib
import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))


def worker():
    assert (ROOT/'scripts/et_factorial_worker.py').is_file(), 'factorial worker missing'
    return importlib.import_module('et_factorial_worker')


def base():
    return json.loads((ROOT/'configs/electrothermal-lgbo-numerical-ablation-software.json').read_text(encoding='utf8'))


def test_four_modes_and_explicit_shared_initialization():
    m=worker()
    assert m.ARMS=={'A00':('numeric','parego'),'A10':('llm_v3','warmstart_only'),
                    'A01':('numeric','full_llmbo_mo'),'A11':('llm_v3','full_llmbo_mo')}
    for arm in m.ARMS:
        cfg=m.config_for(base(),kind='arm',arm=arm,seed=872104,rounds=50,initial={'path':'p','sha256':'a'*64},software=True)
        assert cfg['optimization']['mode']==m.ARMS[arm][1]
        assert cfg['optimization']['initial_plan']['path']=='p'
        assert cfg['optimization']['warmstart']['selection_rule']=='pareto_quality_gated_spacefill_v3'
    with pytest.raises(ValueError):m.config_for(base(),kind='arm',arm='A01',seed=1,rounds=50,initial=None,software=True)


def test_pool_completion_deduplicates_then_fills_without_fake_targets():
    m=worker(); accepted=[];seen=set()
    def evaluate(point,origin):
        accepted.append((point,origin));return {'complete_pair_valid':True}
    items=m.complete_pool([(i,) for i in range(15)]+[(0,)]*2,
                          [(i,) for i in range(128)],evaluate=evaluate,
                          valid=lambda p:p,key=lambda p:p,target=16)
    assert len(items)==16 and len(accepted)==16
    assert accepted[-1][0]==(15,) and accepted[-1][1]=='sobol_fill'
    assert len({p for p,o in accepted})==16


def test_failed_pool_result_is_not_substituted_as_zero():
    m=worker()
    with pytest.raises(ValueError,match='incomplete'):
        m.complete_pool([(1,)],[],evaluate=lambda p,o:{'complete_pair_valid':False},valid=lambda p:p,key=lambda p:p,target=1)


def test_ledger_allows_next_task_after_failure_and_never_resets_counts(tmp_path):
    assert (ROOT/'scripts/et_factorial_budget.py').is_file()
    from et_factorial_budget import FactorialBudget
    phases={'one':{'DFN':2,'API':1},'two':{'DFN':2,'API':1}}
    b=FactorialBudget.start(tmp_path/'ledger',phases=phases,protocol_sha='a'*64)
    b.begin('one');b.charge('API','request1');b.finish(False)
    b.begin('two');b.charge('DFN','solve1')
    assert b.counts()=={'DFN':1,'API':1}
    with pytest.raises(RuntimeError):b.charge('DFN','solve1')
    b.finish(True);state=b.state();assert len(state['finished'])==2 and state['closed']
    assert FactorialBudget(tmp_path/'ledger',phases=phases).counts()==b.counts()


def test_all_initial_pool_points_contribute_to_metrics():
    assert (ROOT/'scripts/analyze_et_factorial_validation.py').is_file()
    from analyze_et_factorial_validation import metric_trajectory
    pool=[{'evaluation_id':'selected','parameters':[.5]*6,'objectives':[.04,.4]},
          {'evaluation_id':'discarded','parameters':[.2]*6,'objectives':[.01,.1]}]
    rows=metric_trajectory(pool,[],normalize=lambda p:p)
    assert rows[0]['F_U_V']==.01 and rows[0]['F_T_K']==.1
    assert rows[0]['representative_id']=='discarded'
    assert rows[0]['HV']==pytest.approx(98.01)


def test_metrics_count_failed_attempt_cost_without_forging_an_objective():
    from analyze_et_factorial_validation import metric_trajectory
    pool=[{'evaluation_id':'a','parameters':[.5]*6,'objectives':[.01,.1],'costs':{'solver_calls':2}},
          {'evaluation_id':'bad','parameters':[.3]*6,'objectives':None,'costs':{'solver_calls':1}}]
    failed={'evaluation_id':'b','parameters':[.4]*6,'objectives':None,'costs':{'solver_calls':1}}
    rows=metric_trajectory(pool,[failed],normalize=lambda p:p)
    assert rows[0]['candidate_attempts']==2 and rows[0]['solver_calls']==3
    assert rows[1]['candidate_attempts']==3 and rows[1]['solver_calls']==4
    assert rows[1]['HV']==rows[0]['HV'] and rows[1]['F_U_V']==.01


def test_factorial_effect_known_interaction():
    from analyze_et_factorial_validation import factorial_effects
    assert factorial_effects({'A00':1.,'A10':3.,'A01':4.,'A11':10.})=={'WarmStart':4.,'Region':5.,'interaction':4.}


def test_runner_reload_keeps_scientific_namespace_cold():
    import subprocess
    path=ROOT/'scripts/run_et_factorial_validation.py'
    assert path.is_file(),'cold factorial supervisor missing'
    code="import runpy,sys;runpy.run_path(sys.argv[1],run_name='__mp_main__');assert not any(n=='llmbo_para' or n.startswith('llmbo_para.') for n in sys.modules)"
    result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_short_software_smoke_does_not_invent_ten_round_effects(monkeypatch):
    import analyze_et_factorial_validation as m
    monkeypatch.setattr(m,'analyze_arm',lambda c,p:{'AUC_HV_0_10':None,'weights':[[.5,.5]]*2,'first_numeric_context':'same','trajectory':[{}]*3})
    result=m.analyze_trial({'status':'partial','seeds':[{'seed':1,'pools':{'numeric':{},'llm_v3':{}},
        'arms':{a:{'status':'completed'} for a in ('A00','A10','A01','A11')}}]})
    assert 'effects_HV_10' not in result['seeds'][0]
    assert 'mean_effects_AUC_HV_0_10' not in result


def test_real_pool_keeps_failed_attempt_then_selects_eight_complete_points(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    m=worker();cfg=m.config_for(base(),kind='numeric',arm=None,seed=872104,rounds=10,software=True)
    report,prepared=prepare_electrothermal_experiment(cfg,base_dir=ROOT)
    assert prepared is not None,report
    class OnceBroken(SyntheticElectrothermalSimulator):
        broken=False
        def simulate(self,p,case):
            if not self.broken:
                self.broken=True
                raise ValueError('deliberate diagnostic failure')
            return super().simulate(p,case)
    class Budget:
        def require_candidate(self,calls):assert calls==0
    store=ElectrothermalRunStore(tmp_path/'pool',cfg,dataset=prepared.dataset,signatures=prepared.signatures,command='factorial initialization')
    result=m.initialize_pool({'kind':'numeric','seed':872104,'software_fixture':True},prepared,store,Budget(),OnceBroken())
    records=[json.loads(p.read_text(encoding='utf8')) for p in sorted((store.path/'electrothermal-evaluations').glob('*.json'))]
    assert result['pool_count']==16 and result['attempted_pool_points']==17
    assert records[0]['objectives'] is None and records[0]['complete_pair_valid'] is False
    assert len(result['selected_ids'])==8 and records[0]['evaluation_id'] not in result['selected_ids']
    assert sum(r['complete_pair_valid'] for r in records)==16
    assert len({tuple(r['parameters']) for r in records})==17
