"""Pure prompting has one request; failures cannot turn into extra proposals or Sobol."""
import importlib.util
import json
from pathlib import Path

import pytest

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run
from llmbo_para.config import parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator,FourRateEvaluator
from llmbo_para.runstore import RunStore
from llmbo_para.screening_history import load_screening_history
from llmbo_para.synthetic import synthetic_config,synthetic_series
from llmbo_para.workflow import run_experiment


def fixture(tmp_path,*,all_fail=False,wrong_count=False,gate=None):
    assert importlib.util.find_spec('llmbo_para.prompt_initialization'), 'production prompt-only initializer is missing'
    from llmbo_para.prompt_initialization import PromptOnlyBudget,PromptOnlyInitializer
    config=synthetic_config();config['optimization'].update(candidate_pool_size=8,composite_ei_draws=8,gp_sweeps=0)
    space=parameter_space_from_config(config);series=synthetic_series()
    points=[space.denormalize([v]*6) for v in (.2,.4,.6,.8)]
    calls=[];solves=[]
    class Client:
        last_warm_statistics={'received':5 if wrong_count else 4}
        def warm_start(self,space,count):calls.append(('count',count));return points
        def select_warm_start(self,*args):raise AssertionError('pure prompting must not call a selector')
    def factory(stage,index,context):
        calls.append((stage,index,context))
        assert stage=='generate' and index==1
        assert set(context['initialization_recovery'])=={'inventory_check','derived_necessary_parameter_ranges'}
        return Client()
    def simulate(parameters,row):
        solves.append(row.rate)
        if row.rate=='3C' and (all_fail or parameters[space.specs[0].name]==points[0][0]):
            return row.time_s[:-1],row.voltage_v[:-1]
        error=.02*(1-parameters[space.specs[0].name])
        return row.time_s,[v+error for v in row.voltage_v]
    budget=PromptOnlyBudget(target=2,min_evaluations=2,max_evaluations=4,warm_batch_size=4)
    initializer=PromptOnlyInitializer(config,space,series,FourRateEvaluator(space,CallableSimulator(simulate)),
        RunStore(tmp_path/'screen',config,command='prompt-only production regression'),gate=gate,source='llm',
        llm_factory=factory,budget=budget)
    return initializer,config,space,series,points,calls,solves


def test_one_request_all_fixed_proposals_scored_and_surplus_history_reused(tmp_path,monkeypatch):
    init,config,space,series,points,calls,solves=fixture(tmp_path)
    plan=init.run();path=init.store.path/'initial-plan.json'
    assert plan['complete'] and plan['warm_start_method']=='prompt_only'
    assert len(calls)==2 and calls[1]==('count',4)
    assert len(solves)==16 and plan['screening_cost']['api_requests']==1
    assert plan['screening_cost']['selection_requests']==0 and plan['screening_cost']['submitted_points']==4
    assert plan['screening_cost']['initialization_policy']=='prompt_only'
    assert list(points[-1]) in plan['parameters'] and len(plan['parameters'])==2
    history=load_screening_history(config,series,plan,path)
    assert len(history.results)==2 and history.catalog['reused_valid_candidates']==1
    case=arm_config(config,plan,path,warm_start=True,gp_groups=False,bo_iterations=1)
    case['optimization'].update(reuse_screening_history=True,
        bo_repair={'training_data':'per_rate','candidate_policy':'local','feasibility_weighting':True})
    case['llm'].update(transport='structured_json_service',endpoint='https://example.invalid/fixture',
        api_key_env='PROMPT_ONLY_TEST_KEY',model='test-only',timeout_s=1,min_diversity_distance=.001)
    monkeypatch.setenv('PROMPT_ONLY_TEST_KEY','test-fixture-no-network-credential')
    new_solves=[]
    def simulate(p,row):new_solves.append(row.rate);return row.time_s,[v+.01 for v in row.voltage_v]
    result=run_experiment(case,tmp_path/'BO',simulator=CallableSimulator(simulate))
    assert result['cache_hits']==2 and len(new_solves)==4 and result['new_candidate_evaluations']==1
    assert result['screening_history']['attributed_total_rate_solves']==20
    assert audit_run(result['run_directory'],deep=True)['passed']


def test_infeasible_fixed_design_stops_without_refill_and_preserves_all_paid_curves(tmp_path):
    init,_,_,_,_,calls,solves=fixture(tmp_path,all_fail=True)
    with pytest.raises(RuntimeError,match='pure-prompt fixed design'):
        init.run()
    plan=json.loads((init.store.path/'initial-plan.json').read_text(encoding='utf-8'))
    assert len(calls)==2 and len(solves)==16 and not plan['complete']
    assert len(plan['quality_observation_sources'])==4 and plan['screening_cost']['submitted_points']==4
    assert plan['screening_cost']['api_requests']==1 and plan['screening_cost']['selection_requests']==0


def test_wrong_generation_count_fails_before_any_DFN_and_never_repairs_request(tmp_path):
    init,_,_,_,_,calls,solves=fixture(tmp_path,wrong_count=True)
    with pytest.raises(ValueError,match='response count'):
        init.run()
    assert len(calls)==2 and solves==[] and init.api_requests==1


def test_prompt_only_cannot_resume_old_feedback_or_paid_records(tmp_path):
    init,*_=fixture(tmp_path)
    with pytest.raises(ValueError,match='does not resume'):
        init.restore_llm({},tmp_path/'old-plan.json')


def test_inventory_reject_consumes_submission_without_refill(tmp_path):
    from llmbo_para.feasibility import InventoryGate
    space=parameter_space_from_config(synthetic_config())
    capacities=[min(space.denormalize([v]*6)[:2])*10 for v in (.2,.4)]
    gate=InventoryGate(10,10,sum(capacities)/2)
    init,_,_,_,_,calls,solves=fixture(tmp_path,gate=gate)
    plan=init.run()
    assert plan['screening_cost']['submitted_points']==4 and plan['screening_cost']['candidate_evaluations']==3
    assert plan['screening_cost']['analytical_rejections']==1 and len(solves)==12 and len(calls)==2


def test_real_client_uses_original_prompt_once_without_observation_feedback(tmp_path):
    from importlib import resources
    from llmbo_para.llm import LLMClient
    init,_,_,_,points,_,solves=fixture(tmp_path)
    requests=[]
    class Transport:
        def post(self,payload):
            requests.append(payload)
            return {'candidates':[{'parameters':list(p)} for p in points]}
    init.llm_factory=lambda stage,index,context:LLMClient(Transport(),context=context,run_store=init.store)
    plan=init.run()
    assert plan['complete'] and len(requests)==1 and len(solves)==16
    request=requests[0]
    assert request['task']=='warm_start' and request['requested_count']==4
    assert request['instructions']==resources.files('llmbo_para').joinpath('prompts/warm_start.txt').read_text(encoding='utf-8')
    assert set(request['context'])=={'prompt_only_policy','initialization_recovery'}
    assert set(request['context']['initialization_recovery'])=={'inventory_check','derived_necessary_parameter_ranges'}
