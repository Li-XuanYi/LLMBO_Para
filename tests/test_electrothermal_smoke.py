import pytest
from electrothermal_fixtures import et_config,R3,R4


@pytest.mark.parametrize('rates',[R3,R4])
def test_smoke_dry_run_and_missing_budget_make_zero_solves(rates):
    from llmbo_para.electrothermal_workflow import plan_electrothermal_smoke
    cfg=et_config(rates);cfg['model']['provider']='pybamm';cfg['run_kind']='synthetic_dfn'
    plan=plan_electrothermal_smoke(cfg,[[.5,.5,1e-13,1e-13,40,.1]],None)
    assert not plan['ready'] and plan['actual_solver_calls']==0
    assert plan['maximum_solver_calls']==2*len(rates)
    assert any('budget' in e for e in plan['errors'])


def test_software_smoke_does_not_need_physical_solve_budget():
    from llmbo_para.electrothermal_workflow import plan_electrothermal_smoke
    plan=plan_electrothermal_smoke(et_config(),[[.5,.5,1e-13,1e-13,40,.1]],None)
    assert plan['ready'] and plan['maximum_solver_calls']==0
