from dataclasses import asdict
import pytest
from llmbo_para.config import parameter_space_from_config
from electrothermal_fixtures import et_config,R3,R4,clone


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


def test_warmstart_rule_binds_initialization_without_changing_physical_protocol():
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset

    dataset=make_synthetic_dataset(R3)
    absent=et_config();v1=clone(absent);v2=clone(absent);v3=clone(absent)
    v1['optimization']['warmstart']['selection_rule']='pareto_maximin_v1'
    v2['optimization']['warmstart']['selection_rule']='pareto_core_spacefill_v2'
    v3['optimization']['warmstart']['selection_rule']='pareto_quality_gated_spacefill_v3'
    base=build_electrothermal_signatures(absent,dataset)
    explicit=build_electrothermal_signatures(v1,dataset)
    changed=build_electrothermal_signatures(v2,dataset)
    gated=build_electrothermal_signatures(v3,dataset)
    assert len({base.config,explicit.config,changed.config,gated.config})==4
    assert base.initialization_compatibility==explicit.initialization_compatibility
    assert len({base.initialization_compatibility,changed.initialization_compatibility,
                gated.initialization_compatibility})==3
    assert len({base.algorithm,explicit.algorithm,changed.algorithm,gated.algorithm})==4
    for name in ('source','data','model_evaluation','evaluation_protocol','comparison_protocol','fit_rates'):
        assert getattr(base,name)==getattr(explicit,name)==getattr(changed,name)==getattr(gated,name)


def test_initial_plan_recomputes_curves_and_rejects_legacy_or_corruption(tmp_path):
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures,write_initial_plan,load_initial_plan
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset,SyntheticElectrothermalSimulator
    import json
    cfg=et_config();ds=make_synthetic_dataset(R3);sp=parameter_space_from_config(cfg)
    sig=build_electrothermal_signatures(cfg,ds);ev=ElectrothermalEvaluator(sp,SyntheticElectrothermalSimulator(),fit_rates=R3)
    records=[ev.evaluate(sp.denormalize([v]*6),ds) for v in (.4,.6)]
    path=tmp_path/'plan.json';write_initial_plan(path,records,signatures=sig)
    assert len(load_initial_plan(path,space=sp,dataset=ds,signatures=sig,expected_selection_rule='pareto_maximin_v1').records)==2
    value=json.loads(path.read_text());value['records'][0]['rates'][0]['trace']['temperature_k'][1]+=3;path.write_text(json.dumps(value))
    with pytest.raises(ValueError):load_initial_plan(path,space=sp,dataset=ds,signatures=sig,expected_selection_rule='pareto_maximin_v1')
    path.write_text(json.dumps({'schema_version':1,'parameters':[[.5]*6]*2}))
    with pytest.raises(ValueError):load_initial_plan(path,space=sp,dataset=ds,signatures=sig,expected_selection_rule='pareto_maximin_v1')
