from dataclasses import asdict
import pytest
from llmbo_para.config import parameter_space_from_config
from electrothermal_fixtures import et_config,R3,R4


def test_three_four_rate_signatures_reject_cache_even_with_same_6d_2d_shape():
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures,candidate_key
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    a=build_electrothermal_signatures(et_config(),make_synthetic_dataset(R3))
    b=build_electrothermal_signatures(et_config(R4),make_synthetic_dataset(R4))
    assert a.data!=b.data and a.model_evaluation!=b.model_evaluation
    assert candidate_key([.5,.5,1e-13,1e-13,40,.1],'electrothermal_4e2t',a)!=candidate_key([.5,.5,1e-13,1e-13,40,.1],'electrothermal_4e2t',b)
    with pytest.raises(ValueError):candidate_key([.5]*6,'voltage_6p',a)


def test_region_switch_changes_run_identity_but_shared_init_is_compatible():
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    ds=make_synthetic_dataset(R3);cfg=et_config();cfg['optimization']['mode']='warmstart_only'
    a=build_electrothermal_signatures(cfg,ds);cfg['optimization']['mode']='full_llmbo_mo'
    b=build_electrothermal_signatures(cfg,ds)
    assert a.config!=b.config and a.initialization_compatibility==b.initialization_compatibility
    cfg['optimization']['objective_scales'][0]*=2
    c=build_electrothermal_signatures(cfg,ds);assert c.initialization_compatibility!=a.initialization_compatibility


def test_initial_plan_recomputes_curves_and_rejects_legacy_or_corruption(tmp_path):
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures,write_initial_plan,load_initial_plan
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset,SyntheticElectrothermalSimulator
    import json
    cfg=et_config();ds=make_synthetic_dataset(R3);sp=parameter_space_from_config(cfg)
    sig=build_electrothermal_signatures(cfg,ds);ev=ElectrothermalEvaluator(sp,SyntheticElectrothermalSimulator(),fit_rates=R3)
    records=[ev.evaluate(sp.denormalize([v]*6),ds) for v in (.4,.6)]
    path=tmp_path/'plan.json';write_initial_plan(path,records,signatures=sig)
    assert len(load_initial_plan(path,space=sp,dataset=ds,signatures=sig).records)==2
    value=json.loads(path.read_text());value['records'][0]['rates'][0]['trace']['temperature_k'][1]+=3;path.write_text(json.dumps(value))
    with pytest.raises(ValueError):load_initial_plan(path,space=sp,dataset=ds,signatures=sig)
    path.write_text(json.dumps({'schema_version':1,'parameters':[[.5]*6]*2}))
    with pytest.raises(ValueError):load_initial_plan(path,space=sp,dataset=ds,signatures=sig)
