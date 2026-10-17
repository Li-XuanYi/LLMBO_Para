import pytest
from llmbo_para.config import configuration_errors,parameter_space_from_config
from llmbo_para.synthetic import synthetic_config
from electrothermal_fixtures import et_config,R3,R4,clone


def test_v2_requires_explicit_fit_rates_and_old_v1_stays_four_rate():
    assert configuration_errors(et_config())==[]
    assert configuration_errors(et_config(R4))==[]
    old=synthetic_config();assert configuration_errors(old)==[]
    old['fit_rates']=list(R3);assert configuration_errors(old)
    cfg=et_config();del cfg['fit_rates'];assert configuration_errors(cfg)


@pytest.mark.parametrize('rates',[None,[],['1C','1C'],['bad'],True,['0.5C',False]])
def test_invalid_rates_rejected(rates):
    cfg=et_config();cfg['fit_rates']=rates;assert configuration_errors(cfg)


def test_pending_research_and_excluded_source_are_not_assumed_confirmed():
    cfg=et_config();cfg['run_kind']='research'
    errors=configuration_errors(cfg)
    assert any('current' in e for e in errors) and any('cooling' in e for e in errors)
    cfg=et_config(R4);cfg['data']['by_rate']['3C']['source_id']='xlsx:6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7:3C'
    cfg['data']['exclusions']=[{'source_id':cfg['data']['by_rate']['3C']['source_id'],'reason':'user_confirmed_unreliable_2026-10-17'}]
    assert any('excluded' in e for e in configuration_errors(cfg))


def test_strict_schema_units_and_integer_budgets():
    for section,key,value in [(None,'surprise',1),('optimization','total_candidate_budget',True),('budgets','max_solver_calls',True),
                              ('parameters','C_th',{'lower':20,'upper':80,'unit':'S.m-1','transform':'log10'})]:
        cfg=et_config();(cfg if section is None else cfg[section])[key]=value
        assert configuration_errors(cfg)
    cfg=et_config();cfg['parameter_profile']='voltage_6p';assert configuration_errors(cfg)


def test_profile_and_rate_order_are_explicit():
    space=parameter_space_from_config(et_config())
    assert space.profile=='electrothermal_4e2t'
    assert parameter_space_from_config(synthetic_config()).profile=='voltage_6p'
