"""Reject → direct Agent feedback → validate; all raw proposals and requests are bounded."""
from copy import deepcopy
import importlib.util
import json

import pytest

from llmbo_para.config import parameter_space_from_config
from llmbo_para.evaluation import CallableSimulator,FourRateEvaluator
from llmbo_para.feasibility import InventoryGate,simulation_signature
from llmbo_para.initialization import validated_cached_results
from llmbo_para.llm import LLMClient
from llmbo_para.runstore import RunStore,sha256_file
from llmbo_para.synthetic import synthetic_config,synthetic_series


def fixture(tmp_path,*,all_invalid=False,empty=False,early=False,contract=False,max_requests=3):
    assert importlib.util.find_spec('llmbo_para.rejection_initialization'),'bounded rejection feedback is missing'
    from llmbo_para.rejection_initialization import RejectionFeedbackBudget,RejectionFeedbackInitializer
    config=synthetic_config();space=parameter_space_from_config(config);series=synthetic_series()
    points=[space.denormalize([v]*6) for v in (.15,.3,.45,.6,.75,.9)]
    illegal=[0]*6;requests=[];solves=[]
    def reply(parameters):return {'candidates':[{'parameters':list(p)} for p in parameters]}
    class Transport:
        def post(self,payload):
            requests.append(deepcopy(payload));index=len(requests)
            if empty:return reply([])
            if all_invalid:return reply([illegal,illegal])
            if early:return reply(points[2:4])
            if contract:return {'bad_schema':True} if index==1 else reply(points[2:4])
            return reply(([illegal,points[0]],[points[1],points[2]],[points[2],points[3]])[index-1])
    def factory(stage,index,context):
        assert stage=='generate'
        store=RunStore(tmp_path/'requests',{'index':index,'context':context},command='fake Agent transport')
        return LLMClient(Transport(),context=context,run_store=store)
    def simulate(parameters,row):
        solves.append(row.rate)
        if row.rate=='3C' and parameters[space.specs[0].name]==points[1][0]:
            return row.time_s[:-1],row.voltage_v[:-1]
        return row.time_s,[v+.01 for v in row.voltage_v]
    budget=RejectionFeedbackBudget(target=2,min_evaluations=2,max_evaluations=6,warm_batch_size=2,max_warm_batches=max_requests)
    init=RejectionFeedbackInitializer(config,space,series,FourRateEvaluator(space,CallableSimulator(simulate)),
        RunStore(tmp_path/'screen',config,command='bounded Agent regression'),gate=InventoryGate(10,10,3.3),
        source='llm',llm_factory=factory,budget=budget)
    return init,points,requests,solves,config,space,series


def test_invalid_inventory_cutoff_and_duplicate_feedback_reach_next_request(tmp_path):
    init,points,requests,solves,config,space,series=fixture(tmp_path)
    plan=init.run()
    assert plan['complete'] and len(requests)==3 and len(solves)==12
    cost=plan['screening_cost']
    assert cost['generated_draws']==6 and cost['candidate_evaluations']==3 and cost['analytical_rejections']==3
    assert cost['api_requests']==3 and cost['selection_requests']==0
    second=requests[1]['context']['initialization_recovery']['failed_candidates']
    assert any(r['parameters']==[0]*6 for r in second)
    assert any(r['reason']=='necessary_inventory_bound' and r['inventory']['required_discharge_ah']==3.3 for r in second)
    third=requests[2]['context']['initialization_recovery']['failed_candidates']
    cutoff=next(r for r in third if r['reason']=='four_rate_incomplete')
    assert cutoff['coverage_shortfall_s']['3C']>0 and cutoff['rmse_v']['0.5C'] is not None
    assert all(r['task']=='warm_start' for r in requests)
    assert len(validated_cached_results(config,series,plan,init.store.path/'initial-plan.json'))==2


def test_raw_invalid_points_consume_candidate_budget_without_DFN_or_extra_API(tmp_path):
    init,_,requests,solves,*_=fixture(tmp_path,all_invalid=True)
    plan=init.run()
    assert not plan['complete'] and len(requests)==3 and solves==[]
    assert plan['screening_cost']['generated_draws']==6 and plan['screening_cost']['analytical_rejections']==6
    assert plan['stop_reason']=='candidate_budget_exhausted'


def test_empty_responses_stop_at_request_cap_even_when_no_candidates_generated(tmp_path):
    init,_,requests,solves,*_=fixture(tmp_path,empty=True,max_requests=2)
    plan=init.run()
    assert not plan['complete'] and len(requests)==2 and solves==[]
    assert plan['screening_cost']['generated_draws']==0 and plan['stop_reason']=='request_budget_exhausted'


def test_success_stops_immediately_without_spending_remaining_budget(tmp_path):
    init,_,requests,solves,*_=fixture(tmp_path,early=True)
    plan=init.run()
    assert plan['complete'] and len(requests)==1 and len(solves)==8
    assert plan['stop_reason']=='target_reached'


def test_schema_rejection_is_archived_and_returned_within_same_API_cap(tmp_path):
    init,_,requests,solves,*_=fixture(tmp_path,contract=True)
    plan=init.run()
    assert plan['complete'] and len(requests)==2 and len(solves)==8
    assert any(r['reason']=='response_contract' for r in requests[1]['context']['initialization_recovery']['failed_candidates'])


def test_prior_failed_plan_is_verified_and_used_as_feedback_without_replaying_DFN(tmp_path):
    init,points,requests,solves,config,space,series=fixture(tmp_path,early=True)
    old=RunStore(tmp_path/'old',config,command='old failed fixture; paid once')
    evaluator=FourRateEvaluator(space,CallableSimulator(lambda p,row:(row.time_s[:-1],row.voltage_v[:-1])))
    record=evaluator.evaluate(points[4],series).to_dict();path=old.save_attempt(0,1,record)
    plan={'screening_directory':str(old.path),'simulation_signature':simulation_signature(config,series),
        'quality_observation_sources':[{'path':str(path),'sha256':sha256_file(path)}],
        'seen_parameters':[list(points[4])],'screening_cost':{'generated_draws':1,'candidate_evaluations':1,
            'analytical_rejections':0,'rate_solve_attempts':4,'api_requests':1}}
    source=old.write_json('initial-plan.json',plan)
    init.seed_feedback_from_plan(source)
    result=init.run()
    assert result['complete'] and len(requests)==1 and len(solves)==8
    assert requests[0]['context']['initialization_recovery']['failed_candidates'][0]['parameters']==list(points[4])
    assert result['screening_cost']['generated_draws']==2
    assert result['screening_cost']['attributed_total_rate_solves']==12
    assert result['prior_feedback_plan']['sha256']==sha256_file(source)


def test_tampered_prior_feedback_record_fails_before_request_or_DFN(tmp_path):
    init,_,requests,solves,config,_,series=fixture(tmp_path,early=True)
    old=RunStore(tmp_path/'old',config,command='tampered record fixture')
    path=old.write_json('bad.json',{'tampered':True})
    plan={'screening_directory':str(old.path),'simulation_signature':simulation_signature(config,series),
        'quality_observation_sources':[{'path':str(path),'sha256':'0'*64}],
        'seen_parameters':[],'screening_cost':{}}
    source=old.write_json('initial-plan.json',plan)
    with pytest.raises(ValueError,match='feedback record hash'):
        init.seed_feedback_from_plan(source)
    assert requests==[] and solves==[]


def test_second_continuation_keeps_inherited_rejections_successes_and_all_costs(tmp_path):
    old,*_=fixture(tmp_path/'old',all_invalid=True)
    assert not old.run()['complete']
    middle,_,_,_,_,_,_=fixture(tmp_path/'middle',early=True)
    middle.seed_feedback_from_plan(old.store.path/'initial-plan.json')
    assert middle.run()['complete']
    latest,_,requests,solves,*_=fixture(tmp_path/'latest',early=True)
    latest.seed_feedback_from_plan(middle.store.path/'initial-plan.json')
    assert len(latest.feedback)==8  # six analytic rejections and two actual successes
    cost=latest.progress()
    assert cost['attributed_total_returned_candidates']==8 and cost['attributed_total_API_requests']==4
    assert cost['attributed_total_rate_solves']==8 and latest.accepted==[]
    context=latest._context()['initialization_recovery']
    assert context['best_completed_observation']['complete'] and len(context['failed_candidates'])==6
    assert requests==[] and solves==[]


def saved_reference(tmp_path,init,point,*,complete=True):
    old=RunStore(tmp_path/'reference',init.config,command='verified old positive reference')
    def simulate(p,row):
        return (row.time_s,row.voltage_v) if complete else (row.time_s[:-1],row.voltage_v[:-1])
    result=FourRateEvaluator(init.space,CallableSimulator(simulate)).evaluate(point,init.series)
    return old.save_attempt(0,1,result.to_dict())


def test_positive_reference_is_context_only_and_does_not_preseed_or_rerun(tmp_path):
    init,points,requests,solves,*_=fixture(tmp_path,early=True)
    path=saved_reference(tmp_path,init,points[4])
    init.add_verified_success_example(path,expected_sha256=sha256_file(path))
    assert init.accepted==[] and init.evaluations==0 and init.draws==0 and solves==[]
    plan=init.run()
    assert plan['complete'] and len(requests)==1 and len(solves)==8
    assert requests[0]['context']['initialization_recovery']['best_completed_observation']['complete']
    assert len(plan['positive_reference_examples'])==1
    assert plan['screening_cost']['candidate_evaluations']==2
    assert all(p!=list(points[4]) for p in plan['parameters'])


def test_copied_positive_reference_is_rejected_instead_of_counted_as_new_seed(tmp_path):
    init,points,requests,solves,*_=fixture(tmp_path,early=True)
    path=saved_reference(tmp_path,init,points[2])
    init.add_verified_success_example(path,expected_sha256=sha256_file(path))
    plan=init.run()
    assert not plan['complete'] and len(plan['parameters'])==1 and len(solves)==4
    assert plan['screening_cost']['generated_draws']==6 and len(requests)==3
    assert plan['screening_cost']['analytical_rejections']==5


def test_incomplete_positive_reference_cannot_be_supplied_as_success(tmp_path):
    init,points,requests,solves,*_=fixture(tmp_path,early=True)
    path=saved_reference(tmp_path,init,points[4],complete=False)
    with pytest.raises(ValueError,match='positive reference must be complete'):
        init.add_verified_success_example(path,expected_sha256=sha256_file(path))
    assert requests==[] and solves==[] and init.accepted==[]


def test_tampered_ancestor_plan_is_rejected_before_new_request(tmp_path):
    old,*_=fixture(tmp_path/'old',all_invalid=True)
    old.run();middle,*_=fixture(tmp_path/'middle',early=True)
    middle.seed_feedback_from_plan(old.store.path/'initial-plan.json');middle.run()
    path=old.store.path/'initial-plan.json'
    value=json.loads(path.read_text(encoding='utf-8'));value['tampered']=True
    path.write_text(json.dumps(value),encoding='utf-8')
    latest,_,requests,solves,*_=fixture(tmp_path/'latest',early=True)
    with pytest.raises(ValueError,match='chain plan hash'):
        latest.seed_feedback_from_plan(middle.store.path/'initial-plan.json')
    assert requests==[] and solves==[]


def test_rounded_near_copy_of_reference_is_not_a_new_initial_point(tmp_path):
    init,points,_,solves,*_=fixture(tmp_path,early=True)
    path=saved_reference(tmp_path,init,points[2])
    init.add_verified_success_example(path,expected_sha256=sha256_file(path))
    near=init.space.denormalize([.45001]*6)
    class Transport:
        def post(self,payload):return {'candidates':[{'parameters':list(p)} for p in (near,points[3])]}
    init.llm_factory=lambda stage,index,context:LLMClient(Transport(),context=context)
    plan=init.run()
    assert not plan['complete'] and len(plan['parameters'])==1 and len(solves)==4
    assert plan['screening_cost']['analytical_rejections']==5
    assert any(r['reason']=='minimum_history_diversity' for r in plan['rejection_feedback'])
