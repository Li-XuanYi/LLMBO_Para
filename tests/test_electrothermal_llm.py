from dataclasses import replace
from itertools import permutations
import pytest
from electrothermal_fixtures import et_config


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
