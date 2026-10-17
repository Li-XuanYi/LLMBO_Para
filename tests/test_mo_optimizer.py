from dataclasses import replace
import json
import pytest
from electrothermal_fixtures import et_config


def make_optimizer(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.mo_optimizer import MOOptimizer
    cfg=et_config();_,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    store=ElectrothermalRunStore(tmp_path,cfg,dataset=p.dataset,signatures=p.signatures,command='test')
    evaluator=ElectrothermalEvaluator(p.space,SyntheticElectrothermalSimulator(),fit_rates=p.dataset.fit_rates)
    return MOOptimizer(p.space,evaluator,p.dataset,store,cfg['optimization'])


def test_failed_round_still_switches_weight_and_refits(tmp_path,monkeypatch):
    opt=make_optimizer(tmp_path);opt.initialize()
    original=opt.evaluator.simulator.simulate
    def fail(theta,case):return replace(original(theta,case),temperature_k=None)
    monkeypatch.setattr(opt.evaluator.simulator,'simulate',fail)
    first=opt.step();gp1=opt.gp;second=opt.step()
    assert len(opt.history)==2 and opt.gp is not gp1
    assert first['context']['scalarization']['weights']!=second['context']['scalarization']['weights']
    assert first['context']['scalarization']['observation_ids']==second['context']['scalarization']['observation_ids']
    assert first['feedback']['new_scalar'] is None and second['feedback']['new_scalar'] is None


def test_duplicate_input_not_duplicate_training_but_equal_y_distinct_parameters_are(tmp_path):
    opt=make_optimizer(tmp_path);opt.initialize();record=opt.history[0]
    before=opt.store.ledger.summary()['software_calls']
    again,cached=opt.evaluate(record.parameters)
    assert cached and len(opt.history)==2 and opt.store.ledger.summary()['software_calls']==before
    other=replace(record,evaluation_id='different-input',parameters=opt.space.denormalize([.9]*6))
    opt.remember(other)
    assert len(opt.history)==3 and opt.history[0].objectives==opt.history[-1].objectives


def test_round_context_frozen_through_selection_and_feedback(tmp_path):
    opt=make_optimizer(tmp_path);opt.initialize();old=list(opt.history);round=opt.step()
    c=round['context']['scalarization']
    assert len(c['y'])==2 and c['observation_ids']==tuple(r.evaluation_id for r in old)
    assert round['feedback']['context_id']==round['context']['context_id']
    assert round['feedback']['previous_best']==pytest.approx(min(c['raw_labels']))
    state=json.loads(opt.last_context.gp_state_json)
    assert state['y']==list(c['labels']) and state['group']==[] and state['lengthscale_prior'] is None
