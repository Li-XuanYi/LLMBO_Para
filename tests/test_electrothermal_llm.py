from dataclasses import replace
from itertools import permutations
import pytest
from electrothermal_fixtures import et_config


def _selector_records(entries):
    """Complete six-parameter evaluations for the pure screening rule."""
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluationResult

    space=parameter_space_from_config(et_config())
    records=[]
    for ident,x,objectives in entries:
        complete=objectives is not None
        records.append(ElectrothermalEvaluationResult(
            evaluation_id=ident,parameters=space.denormalize([x]*6),
            parameter_profile=space.profile,fit_rates=('0.5C','1C','2C'),rates=(),
            objective_components={'F_U':objectives[0] if complete else None,
                                  'F_T':objectives[1] if complete else None},
            complete_pair_valid=complete,objectives=tuple(objectives) if complete else None,
            data_signature='selector-fixture',source_kind='fresh_simulation',
            costs={'solver_calls':0,'software_calls':0},signatures={'fixture':'v1'}))
    return space,records


def _mean_selection_distance(space,records,selected):
    from itertools import combinations
    import numpy as np
    points={r.evaluation_id:space.normalize(r.parameters) for r in records}
    return sum(float(np.linalg.norm(np.asarray(points[a])-points[b])/np.sqrt(6))
               for a,b in combinations(selected,2))/(len(selected)*(len(selected)-1)/2)


def test_core_spacefill_v2_keeps_pareto_core_and_covers_farther_parameters():
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    from llmbo_para.pareto import hypervolume_2d

    space,rows=_selector_records([
        ('A',.2,(.1,.9)),('B',.3,(.2,.5)),
        ('C',.21,(.25,1.5)),('D',.8,(.3,2.)),
    ])
    kwargs={'space':space,'count':3,'objective_scales':[.1,1.]}
    old=warmstart_selection_details(rows,**kwargs)
    new=warmstart_selection_details(rows,rule='pareto_core_spacefill_v2',**kwargs)
    assert old['selected_ids']==['A','B','C']
    assert new['selected_ids']==['A','B','D']
    assert new['rule']=='pareto_core_spacefill_v2'
    assert new['ranks']=={'A':0,'B':0,'C':1,'D':2}
    assert new['steps'][-1]['rank']==2
    by_id={r.evaluation_id:r.objectives for r in rows}
    hv=lambda ids:hypervolume_2d([by_id[i] for i in ids],objective_scales=[.1,1.],reference_point=[10.,10.])
    assert hv(new['selected_ids'])==hv(by_id)
    assert _mean_selection_distance(space,rows,new['selected_ids'])>_mean_selection_distance(space,rows,old['selected_ids'])


def test_core_spacefill_v2_front_over_budget_uses_existing_front_order():
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    from llmbo_para.pareto import hypervolume_2d

    space,rows=_selector_records([
        ('A',.2,(.1,3.)),('B',.5,(.2,2.)),('C',.8,(.3,1.)),
    ])
    kwargs={'space':space,'count':2,'objective_scales':[.1,1.]}
    old=warmstart_selection_details(rows,**kwargs)
    new=warmstart_selection_details(rows,rule='pareto_core_spacefill_v2',**kwargs)
    assert new['selected_ids']==old['selected_ids']
    by_id={r.evaluation_id:r.objectives for r in rows}
    hv=lambda ids:hypervolume_2d([by_id[i] for i in ids],objective_scales=[.1,1.],reference_point=[10.,10.])
    assert hv(new['selected_ids'])<hv(by_id)


def test_core_spacefill_v2_is_order_independent_and_keeps_equal_objective_inputs():
    from llmbo_para.electrothermal_llm import warmstart_selection_details,select_electrothermal_warmstart

    space,rows=_selector_records([
        ('A',.5,(.1,.1)),('B',.1,(.1,.1)),('C',.9,(.1,.1)),
        ('Z',.1,(.1,.1)),('P',.8,None),
    ])
    for order in permutations(rows):
        details=warmstart_selection_details(order,space=space,count=2,
            objective_scales=[.1,1.],rule='pareto_core_spacefill_v2')
        assert details['selected_ids']==['B','C']
        assert details['duplicates']['B']==['Z']
        assert 'P' not in details['pool_ids']
        assert details['ranks']=={'A':0,'B':0,'C':0}
    assert select_electrothermal_warmstart(rows,space=space,count=2,
        objective_scales=[.1,1.],rule='pareto_core_spacefill_v2')==('B','C')


def test_core_spacefill_v2_tie_uses_quality_then_rank_coordinates_and_id():
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluationResult

    class UnitSpace:
        profile='electrothermal_4e2t'
        def validate(self,point):return tuple(point)
        def normalize(self,point):return tuple(point)

    def row(ident,x,y):
        return ElectrothermalEvaluationResult(ident,tuple([x]*6),'electrothermal_4e2t',
            ('0.5C','1C'),(),{'F_U':y[0],'F_T':y[1]},True,tuple(y),
            'tie-fixture','fresh_simulation',{'solver_calls':0,'software_calls':0},{'fixture':'tie'})

    rows=[row('A',.5,(.1,.1)),row('C',.75,(.2,.2)),row('B',.25,(.2,.2))]
    details=warmstart_selection_details(rows,space=UnitSpace(),count=2,
        objective_scales=[1.,1.],rule='pareto_core_spacefill_v2')
    assert details['selected_ids']==['A','B']
    assert details['steps'][-1]['distance']==.25


def test_core_spacefill_v2_rejects_unknown_rule():
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    space,rows=_selector_records([('A',.2,(.1,.9)),('B',.8,(.2,.5))])
    with pytest.raises(ValueError,match='selection rule'):
        warmstart_selection_details(rows,space=space,count=2,
            objective_scales=[.1,1.],rule='not_a_rule')


def test_pareto_maximin_selection_is_deterministic(tmp_path):
    from test_mo_optimizer import make_optimizer
    from llmbo_para.electrothermal_llm import select_electrothermal_warmstart
    opt=make_optimizer(tmp_path);opt.initialize();base=opt.history[0]
    rows=[replace(base,evaluation_id=i,parameters=opt.space.denormalize([x]*6),objectives=tuple(y)) for i,x,y in
          [('A',.2,[.1,2]),('B',.8,[.2,1]),('D',.21,[.1,2]),('C',1.,[.3,3])]]
    for order in permutations(rows):
        assert select_electrothermal_warmstart(order,space=opt.space,count=2,objective_scales=[.1,1])==('A','B')
    duplicate=replace(rows[0],evaluation_id='Z')
    assert select_electrothermal_warmstart(rows+[duplicate],space=opt.space,count=2,objective_scales=[.1,1])==('A','B')
    with pytest.raises(ValueError):select_electrothermal_warmstart(rows+[replace(rows[0],objectives=(99,99))],space=opt.space,count=2,objective_scales=[.1,1])


def test_payload_and_new_semantics_reject_legacy_six_vector(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload,validate_warmstart_response
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    _,p=prepare_electrothermal_experiment(et_config(),base_dir=tmp_path)
    payload=build_electrothermal_payload('warm_start_electrothermal',prepared=p,history=[])
    assert payload['fit_rates']==list(p.dataset.fit_rates) and payload['parameter_profile']=='electrothermal_4e2t'
    assert payload['parameters'][4]['name']=='C_th' and payload['objective_scales']==[.1,1.]
    assert 200<=len(payload['instructions'].split())<=300
    with pytest.raises(ValueError):validate_warmstart_response({'candidates':[[1,2,3,4,5,6]]},prepared=p)


class Proposed:
    def __init__(self,space,points):self.space=space;self.points=points;self.calls=0
    def post(self,payload):
        self.calls+=1
        return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures')}|{
            'candidates':[{'parameters':dict(zip((s.name for s in self.space.specs),self.space.denormalize(x)))} for x in self.points]}


def test_budget_exhaustion_does_not_fill_or_start_mo(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    cfg=et_config();cfg['optimization']['warmstart']['max_requests']=1
    _,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    store=ElectrothermalRunStore(tmp_path,cfg,dataset=p.dataset,signatures=p.signatures,command='budget test')
    transport=Proposed(p.space,[[.2]*6]);ev=ElectrothermalEvaluator(p.space,SyntheticElectrothermalSimulator(),fit_rates=p.dataset.fit_rates)
    ctl=ElectrothermalLLMController(transport=transport,is_mock=True,evaluator=ev)
    with pytest.raises(ValueError,match='insufficient_initialization'):ctl.generate_warmstart(p,store=store,budgets=cfg['budgets'])
    import json
    status=json.loads((store.path/'initialization.json').read_text())
    assert status['status']=='insufficient_initialization' and transport.calls==1
    assert store.ledger.summary()['software_calls']==3 and store.ledger.summary()['llm_requests']==0


def test_disabled_real_transport_never_called(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    class Forbidden:
        def post(self,p):pytest.fail('paid transport invoked while disabled')
    cfg=et_config();cfg['optimization']['mode']='warmstart_only'
    with pytest.raises(ValueError,match='insufficient_initialization'):
        run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,llm_controller=ElectrothermalLLMController(transport=Forbidden()))


@pytest.mark.parametrize('setting,value',[('max_requests',True),('max_candidates',0),('pool_size',1),('count',3)])
def test_warmstart_budgets_reject_invalid_or_inconsistent_values(tmp_path,setting,value):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg=et_config();cfg['optimization']['warmstart'][setting]=value
    report,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert p is None and not report['ready']


def test_chat_retries_use_distinct_immutable_http_artifacts():
    from llmbo_para.llm import ChatCompletionsTransport
    class Capturing(ChatCompletionsTransport):
        def _post_json(self,payload,*,task):
            self.tasks.append(task)
            return {'choices':[{'finish_reason':'stop','message':{'content':'{}'}}]}
    client=Capturing('https://example.invalid/v1/chat/completions','UNUSED',model='unused',max_tokens=32,json_mode=True)
    client.tasks=[]
    for suffix in ('a','b'):
        client.post({'task':'warm_start_electrothermal','artifact_task':'warm_start_electrothermal_request_'+suffix,'instructions':'Structured JSON'})
    assert len(set(client.tasks))==2


def test_warmstart_accepts_actual_json_wire_signature_types(tmp_path):
    import json
    from llmbo_para.electrothermal_llm import build_electrothermal_payload,validate_warmstart_response
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    _,p=prepare_electrothermal_experiment(et_config(),base_dir=tmp_path)
    payload=build_electrothermal_payload('warm_start_electrothermal',prepared=p,history=[])
    reply=Proposed(p.space,[[.2]*6]).post(payload)
    reply=json.loads(json.dumps(reply))
    assert len(validate_warmstart_response(reply,prepared=p))==1
