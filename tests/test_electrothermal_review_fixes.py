from pathlib import Path
import json
import pytest
from electrothermal_fixtures import et_config


def test_reservation_refuses_unaffordable_candidate_before_any_partial_solve(tmp_path):
    from test_mo_optimizer import make_optimizer
    from llmbo_para.electrothermal_workflow import SolverBudget
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    opt=make_optimizer(tmp_path);budget=SolverBudget(7,60);opt.execution_budget=budget
    class FakeDFN(SyntheticElectrothermalSimulator):
        backend_kind='dfn';native_solver_calls=0
        def simulate(self,p,case):
            budget.before_solve();self.native_solver_calls+=1;return super().simulate(p,case)
    opt.evaluator.simulator=FakeDFN()
    with pytest.raises(RuntimeError,match='budget|reservation'):opt.optimize(4)
    assert budget.calls==6 and opt.attempts==2 and len(opt.history)==2


def test_global_deadline_stops_software_before_candidate_work(tmp_path):
    from test_mo_optimizer import make_optimizer
    from llmbo_para.electrothermal_workflow import SolverBudget
    opt=make_optimizer(tmp_path);opt.execution_budget=SolverBudget(0,1.)
    opt.execution_budget.deadline-=2.
    with pytest.raises(RuntimeError,match='budget|deadline'):opt.optimize(4)
    assert opt.attempts==0 and opt.store.ledger.summary()['software_calls']==0


def test_shared_plan_preserves_full_screening_costs_separately_from_new_calls(tmp_path):
    from test_electrothermal_llm import Proposed
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment,run_electrothermal_experiment
    from llmbo_para.runstore import sha256_file
    cfg=et_config();cfg['optimization'].update(mode='warmstart_only',total_candidate_budget=2)
    _,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    ctl=ElectrothermalLLMController(transport=Proposed(p.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6]),is_mock=True)
    original=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,llm_controller=ctl)
    path=Path(original['run_directory'])/'initial-plan.json'
    cfg['optimization']['mode']='full_llmbo_mo';cfg['optimization']['initial_plan']={'path':str(path),'sha256':sha256_file(path)}
    imported=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path)
    assert imported['costs']['software_calls']==0 and imported['API_calls']==0
    attributed=imported['initialization_cost_attribution']
    assert attributed['historical_costs']['software_calls']==12 and attributed['historical_costs']['mock_llm_requests']==1
    assert not attributed['included_in_current_costs']
    payload=json.loads(path.read_text());assert len(payload['history_evidence']['screening_records'])==4


def test_region_remains_available_after_warmstart_uses_its_request_cap(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    cfg=et_config();_,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    store=ElectrothermalRunStore(tmp_path,cfg,dataset=p.dataset,signatures=p.signatures,command='review request test')
    class Transport:
        def __init__(self):self.calls=0
        def post(self,payload):self.calls+=1;return {}
    transport=Transport();ctl=ElectrothermalLLMController(transport=transport,is_mock=True)
    for _ in range(3):ctl.request({'task':'warm_start_electrothermal'},prepared=p,store=store,budgets=cfg['budgets'],request_cap=3)
    assert ctl.request({'task':'region_preference_electrothermal'},prepared=p,store=store,budgets=cfg['budgets'],request_cap=2)=={}
    assert transport.calls==4


def test_missing_initialization_file_cannot_bypass_algorithm_audit(tmp_path):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    result=run_electrothermal_experiment(et_config(),tmp_path,base_dir=tmp_path)
    file=Path(result['run_directory'])/'initialization.json';file.rename(file.with_name('initialization.removed-for-test.json'))
    assert not audit_electrothermal_run(result['run_directory'],deep=True)['passed']


@pytest.mark.parametrize('kind',['synthetic_dfn','research'])
def test_nonsoftware_run_kind_cannot_select_algebraic_backend(kind):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg=et_config();cfg['run_kind']=kind
    errors=electrothermal_configuration_errors(cfg)
    assert any('provider' in e or 'PyBaMM' in e for e in errors)


@pytest.mark.parametrize('phase',['preparation','solve'])
def test_native_subprocess_deadline_stops_only_its_worker_and_counts_started_solves(phase):
    import time
    from electrothermal_process_fixtures import stalled_worker
    from llmbo_para.electrothermal_execution import run_with_deadline
    calls=[];started=time.monotonic()
    with pytest.raises(TimeoutError,match='deadline'):
        run_with_deadline(stalled_worker,(phase,),deadline=started+1.,on_solve_start=lambda:calls.append(1))
    assert len(calls)==int(phase=='solve') and time.monotonic()-started<2.


def test_live_payload_supplies_the_exact_machine_response_contract(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    _,p=prepare_electrothermal_experiment(et_config(),base_dir=tmp_path)
    payload=build_electrothermal_payload('warm_start_electrothermal',prepared=p,history=[])
    schema=payload['response_contract']
    assert schema['additionalProperties'] is False and set(schema['required'])=={'schema_version','parameter_profile','fit_rates','signatures','candidates'}
    assert schema['properties']['signatures']['const']['data']==p.signatures.data
    parameters=schema['properties']['candidates']['items']['properties']['parameters']
    assert parameters['required']==['eps_s_n','eps_s_p','D_s_n_ref','D_s_p_ref','C_th','G_th']
    assert payload['requested_candidate_count']==4 and payload['simulation_kind']=='synthetic_software'


def test_live_payload_uses_actual_input_and_target_summaries_without_truth_or_curves(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    _,p=prepare_electrothermal_experiment(et_config(),base_dir=tmp_path)
    payload=build_electrothermal_payload('warm_start_electrothermal',prepared=p,history=[])
    case=payload['case_summaries']['0.5C']
    assert case['current_A']['first']==.5 and case['ambient_temperature_K']['first']==298.15
    assert case['initial_temperature_K']==300.15 and case['temperature_target_K']['last']==300.55
    assert case['voltage_target_V']['last']==4.0 and case['voltage_target_V']['sample_count']==3
    assert 'values' not in case['temperature_target_K'] and 'known_parameters' not in case
