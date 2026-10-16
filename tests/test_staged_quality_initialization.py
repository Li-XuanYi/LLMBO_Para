"""The explicitly approved follow-up changes priorities, never the physical objective."""
from dataclasses import replace
import json

import pytest

from test_quality_initialization import fixture
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
from llmbo_para.llm import LLMClient
from llmbo_para.runstore import RunStore


def staged(init):
    from llmbo_para.staged_initialization import StagedQualityWarmInitializer
    return StagedQualityWarmInitializer(init.config,init.space,init.series,init.evaluator,init.store,
        gate=init.gate,source='llm',budget=init.budget,llm_factory=init.llm_factory)


def test_staged_context_exposes_actual_coverage_and_switches_after_two_complete(tmp_path):
    init,*_=fixture(tmp_path,partial=True);init=staged(init)
    init._fill_pool()
    init._evaluate(init.pending_pool.pop(0))
    context=init._context();policy=context['staged_screening']
    assert policy['phase']=='coverage_bootstrap'
    closest=policy['closest_coverage_observations'][0]
    assert closest['minimum_coverage_ratio']<1 and closest['rmse_v']['3C'] is None
    assert closest['coverage_shortfall_s']['3C']>0
    assert closest['terminal_voltage_headroom_v']['3C'] is None
    init._evaluate(init.pending_pool.pop(0));init._evaluate(init.pending_pool.pop(0))
    assert init._context()['staged_screening']['phase']=='quality_refinement'
    assert len(init._context()['staged_screening']['best_complete_observations'])==2


def test_phase_change_refreshes_untried_pool_and_preserves_rejection_evidence(tmp_path):
    init,*_=fixture(tmp_path);init=staged(init)
    init._fill_pool();init._evaluate(init.pending_pool.pop(0));init._evaluate(init.pending_pool.pop(0))
    abandoned=list(init.pending_pool)
    new=[init.space.denormalize([value]*6) for value in (.87,.9,.93,.96)]
    class Client:
        def warm_start(self,space,count):return new
    init.llm_factory=lambda *args:Client();init.budget=replace(init.budget,max_warm_batches=3)
    init._fill_pool()
    assert init.pending_pool==new and not any(p in init.pending_pool for p in abandoned)
    events=[json.loads(line) for line in (init.store.path/'events.jsonl').read_text(encoding='utf-8').splitlines()]
    transition=[e for e in events if e['type']=='staged_priority_changed'][-1]
    assert transition['abandoned_untried_parameters']==[list(p) for p in abandoned]
    assert transition['phase']=='quality_refinement'


def test_followup_retains_paid_records_and_honors_incremental_candidate_cap(tmp_path):
    init,config,space,series,points,*_=fixture(tmp_path)
    def simulate(parameters,row):
        return (row.time_s[:-1],row.voltage_v[:-1]) if row.rate=='3C' else (row.time_s,row.voltage_v)
    init.evaluator=FourRateEvaluator(space,CallableSimulator(simulate))
    init.budget=replace(init.budget,max_evaluations=4,max_selection_requests=1)
    with pytest.raises(RuntimeError):init.run()
    old_path=init.store.path/'initial-plan.json';old=json.loads(old_path.read_text(encoding='utf-8'))
    from llmbo_para.staged_initialization import StagedQualityWarmInitializer
    new=[space.denormalize([value]*6) for value in (.86,.875,.89,.905,.92,.935,.95,.965)]
    class Client:
        def warm_start(self,space,count):return new
        def select_warm_start(self,space,pool,count):return tuple(pool[:count])
    followup=StagedQualityWarmInitializer(config,space,series,init.evaluator,
        RunStore(tmp_path/'followup',config,command='bounded staged regression'),gate=None,source='llm',
        llm_factory=lambda *args:Client(),budget=replace(init.budget,max_evaluations=6,max_warm_batches=3,max_selection_requests=3))
    followup.restore_llm(old,old_path)
    with pytest.raises(RuntimeError):followup.run()
    plan=json.loads((followup.store.path/'initial-plan.json').read_text(encoding='utf-8'))
    assert plan['screening_cost']['candidate_evaluations']==6
    assert plan['screening_cost']['new_candidate_evaluations']==4
    assert len(plan['quality_observation_sources'])==6 and not plan['complete']
    assert len(list((followup.store.path/'attempts').glob('*.json')))==4


def test_staged_prompt_is_separate_and_meets_json_provider_contract(tmp_path):
    init,*_=fixture(tmp_path);init=staged(init);requests=[]
    class Transport:
        def post(self,payload):requests.append(payload);return {'candidates':[]}
    LLMClient(Transport(),context=init._context()).warm_start(init.space,2)
    prompt=requests[-1]['instructions']
    assert 'coverage_bootstrap' in prompt and 'quality_refinement' in prompt and 'JSON' in prompt
    LLMClient(Transport(),context={'initialization_policy':'quality_feedback'}).warm_start(init.space,2)
    assert 'coverage_bootstrap' not in requests[-1]['instructions']
