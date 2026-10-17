import pytest


def test_costs_separate_failure_screening_cache_and_fresh_solves():
    from llmbo_para.electrothermal_store import CostLedger
    ledger=CostLedger()
    event={'event_id':'a','kind':'solver_call','phase':'warmstart','outcome':'failed'}
    ledger.record(event);ledger.record(event)
    ledger.record({'event_id':'b','kind':'screening_rejected','phase':'warmstart'})
    ledger.record({'event_id':'c','kind':'cache_hit','phase':'initialization'})
    assert ledger.summary()['solver_calls']==1 and ledger.summary()['cache_hits']==1
    assert ledger.summary()['screening_rejections']==1
    with pytest.raises(ValueError):ledger.record({**event,'outcome':'success'})


def test_electrothermal_store_archives_recomputable_results(tmp_path):
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset,SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.config import parameter_space_from_config
    from electrothermal_fixtures import et_config,R3
    cfg=et_config();ds=make_synthetic_dataset(R3);sp=parameter_space_from_config(cfg)
    sig=build_electrothermal_signatures(cfg,ds)
    store=ElectrothermalRunStore(tmp_path,cfg,dataset=ds,signatures=sig,command='mock ET store')
    result=ElectrothermalEvaluator(sp,SyntheticElectrothermalSimulator(),fit_rates=R3).evaluate(sp.denormalize([.5]*6),ds)
    relative=store.save_evaluation(result)
    assert (store.path/relative).exists() and store.ledger.summary()['solver_calls']==0
    assert store.ledger.summary()['software_calls']==3
