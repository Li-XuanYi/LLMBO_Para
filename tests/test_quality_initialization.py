"""Quality screening must learn from actual scores and retain every paid label."""
import copy
import importlib.util
import json
from pathlib import Path

import pytest

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run
from llmbo_para.config import parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
from llmbo_para.runstore import RunStore
from llmbo_para.screening_history import load_screening_history
from llmbo_para.synthetic import synthetic_config, synthetic_series
from llmbo_para.workflow import run_experiment
from llmbo_para.llm import LLMClient


def api():
    assert importlib.util.find_spec('llmbo_para.quality_initialization') is not None, 'quality-aware screening is not implemented'
    from llmbo_para import quality_initialization
    return quality_initialization


def fixture(tmp_path, *, partial=False, pool_impossible=False):
    module=api();config=synthetic_config()
    config['optimization'].update(candidate_pool_size=8,composite_ei_draws=8,gp_sweeps=0)
    space=parameter_space_from_config(config);series=synthetic_series()
    points=[space.denormalize([value]*6) for value in (.15,.25,.35,.45,.55,.65,.75,.85)]
    contexts=[];calls=[];counter={'candidate':0}
    class Client:
        def __init__(self,index):self.index=index
        def warm_start(self,space,count):
            return points[:2] if pool_impossible or self.index==1 else points[2:]
        def select_warm_start(self,space,pool,count):
            calls.append((len(pool),count));return tuple(pool[:count])
    def factory(stage,index,context):
        contexts.append((stage,copy.deepcopy(context)));return Client(index)
    def simulate(parameters,row):
        if row.rate=='0.5C':counter['candidate']+=1
        if partial and counter['candidate']==1 and row.rate=='3C':return row.time_s[:-1],row.voltage_v[:-1]
        error=.06-.01*counter['candidate']
        return row.time_s,[v+error for v in row.voltage_v]
    budget=module.QualityScreeningBudget(target=2,min_evaluations=4,min_candidate_pool=4,
        selection_batch=2,max_evaluations=6,warm_batch_size=8,max_warm_batches=2,max_selection_requests=3)
    store=RunStore(tmp_path/'screen',config,command='quality initialization regression')
    initializer=module.QualityWarmInitializer(config,space,series,FourRateEvaluator(space,CallableSimulator(simulate)),
        store,gate=None,source='llm',llm_factory=factory,budget=budget)
    return initializer,config,space,series,points,contexts,calls,counter


def test_refills_legal_pool_and_transmits_real_scores_before_next_selection(tmp_path):
    init,config,space,series,points,contexts,calls,counter=fixture(tmp_path,partial=True)
    plan=init.run()
    assert plan['complete'] and counter['candidate']==4
    assert calls==[(8,2),(6,2)]
    select_contexts=[c for stage,c in contexts if stage=='select']
    observed=select_contexts[1]['initialization_recovery']['evaluated_observations']
    assert len(observed)==2
    assert observed[0]['objective_v'] is None and observed[0]['rmse_v']['3C'] is None
    assert observed[1]['objective_v']==pytest.approx(.04)
    assert observed[1]['rmse_v']['0.5C']==pytest.approx(.04)
    assert observed[1]['tail_residuals']['0.5C']['last10_mean_v']==pytest.approx(.04)
    assert not any(key in json.dumps(observed) for key in ('simulation_time_s','simulation_voltage_v','aligned_voltage_v'))
    assert points[3] in [tuple(p) for p in plan['parameters']]
    assert plan['screening_cost']['candidate_evaluations']==4 and plan['screening_cost']['rate_solve_attempts']==16


def test_quality_selection_preserves_best_and_all_valid_history_is_reused(tmp_path,monkeypatch):
    init,config,space,series,points,contexts,calls,counter=fixture(tmp_path)
    plan=init.run();path=init.store.path/'initial-plan.json'
    assert plan['complete'] and len(plan['parameters'])==2
    assert points[3] in [tuple(p) for p in plan['parameters']]
    history=load_screening_history(config,series,plan,path)
    assert len(history.results)==2 and all(r.valid for r in history.results)
    assert history.catalog['reused_valid_candidates']==2 and history.catalog['reused_failed_candidates']==0
    case=arm_config(config,plan,path,warm_start=True,gp_groups=False,bo_iterations=1)
    case['optimization'].update(reuse_screening_history=True,
        bo_repair={'training_data':'per_rate','candidate_policy':'local','feasibility_weighting':True})
    case['llm'].update(transport='structured_json_service',endpoint='https://example.invalid/fixture',
        api_key_env='LLMBO_TEST_CREDENTIAL',model='test-only',timeout_s=1,min_diversity_distance=.001)
    monkeypatch.setenv(case['llm']['api_key_env'],'test-fixture-no-network-credential')
    solves=[]
    def simulate(parameters,row):solves.append(row.rate);return row.time_s,[v+.01 for v in row.voltage_v]
    result=run_experiment(case,tmp_path/'run',simulator=CallableSimulator(simulate))
    assert len(solves)==4 and result['cache_hits']==2
    assert result['screening_history']['reused_valid_candidates']==2
    assert result['screening_history']['attributed_total_rate_solves']==20
    run=Path(result['run_directory']);state=json.loads((run/'models/after-000002.json').read_text())
    assert {r:len(m['x']) for r,m in state['models'].items()}=={r:4 for r in series}
    assert state['completion_model']['sample_count']==4
    assert audit_run(run,deep=True)['passed']
    init.store.path.rename(init.store.path.with_name(init.store.path.name+'-offline'))
    assert audit_run(run,deep=True)['passed']


def test_insufficient_pool_never_becomes_select_all_or_random_fallback(tmp_path):
    init,_,_,_,_,_,calls,counter=fixture(tmp_path,pool_impossible=True)
    with pytest.raises(RuntimeError,match='pool'):
        init.run()
    assert calls==[] and counter['candidate']==0
    plan=json.loads((init.store.path/'initial-plan.json').read_text())
    assert not plan['complete'] and plan['screening_cost']['api_requests']==2


def test_extra_valid_records_require_reproducible_quality_selection(tmp_path):
    init,config,space,series,points,_,_,_=fixture(tmp_path)
    plan=init.run();path=init.store.path/'initial-plan.json'
    corrupted=copy.deepcopy(plan);corrupted['quality_selection']['selected_candidate_ids'].reverse()
    with pytest.raises(ValueError,match='quality selection'):
        load_screening_history(config,series,corrupted,path)


def test_quality_context_uses_quality_prompt_without_changing_legacy_prompt():
    requests=[]
    class Transport:
        def post(self,payload):requests.append(payload);return {'candidates':[]}
    space=parameter_space_from_config(synthetic_config())
    LLMClient(Transport(),context={'initialization_policy':'quality_feedback'}).warm_start(space,2)
    assert 'evaluated_observations' in requests[-1]['instructions']
    LLMClient(Transport()).warm_start(space,2)
    assert 'evaluated_observations' not in requests[-1]['instructions']


def test_quality_resume_retains_paid_records_pending_pool_and_quality_feedback(tmp_path):
    from dataclasses import replace
    init,config,space,series,points,contexts,_,_=fixture(tmp_path)
    class Client:
        def __init__(self,index):self.index=index
        def warm_start(self,space,count):return points[:4] if self.index==1 else points[4:]
        def select_warm_start(self,space,pool,count):return tuple(pool[:count])
    observed_contexts=[]
    def factory(stage,index,context):
        observed_contexts.append(copy.deepcopy(context));return Client(index)
    init.llm_factory=factory;init.budget=replace(init.budget,max_warm_batches=1)
    with pytest.raises(RuntimeError,match='pool'):init.run()
    old_path=init.store.path/'initial-plan.json';old=json.loads(old_path.read_text())
    assert old['screening_cost']['candidate_evaluations']==2 and not old['complete']
    continued=api().QualityWarmInitializer(config,space,series,init.evaluator,
        RunStore(tmp_path/'resumed',config,command='quality recovery regression'),gate=None,source='llm',
        budget=replace(init.budget,max_warm_batches=2),llm_factory=factory)
    continued.restore_llm(old,old_path);plan=continued.run()
    assert plan['complete'] and plan['screening_cost']['candidate_evaluations']==4
    assert plan['screening_cost']['new_candidate_evaluations']==2 and plan['screening_cost']['api_requests']==4
    assert len(list((continued.store.path/'attempts').glob('*.json')))==2
    assert len(observed_contexts[-1]['initialization_recovery']['evaluated_observations'])==2
    history=load_screening_history(config,series,plan,continued.store.path/'initial-plan.json')
    assert len(history.catalog['segments'])==2 and history.catalog['reused_valid_candidates']==2


def test_two_point_checkpoint_contains_both_quality_record_sources(tmp_path):
    init,_,_,_,_,_,_,_=fixture(tmp_path)
    checkpoints=[]
    init.checkpoint_callback=lambda plan,path:checkpoints.append((len(plan['evaluations']),len(plan['quality_observation_sources'])))
    init.run()
    assert checkpoints==[(2,2)]


def test_quality_generation_prompt_satisfies_provider_json_mode_requirement():
    requests=[]
    class Transport:
        def post(self,payload):requests.append(payload);return {'candidates':[]}
    LLMClient(Transport(),context={'initialization_policy':'quality_feedback'}).warm_start(
        parameter_space_from_config(synthetic_config()),2)
    assert 'json' in requests[0]['instructions'].lower()
