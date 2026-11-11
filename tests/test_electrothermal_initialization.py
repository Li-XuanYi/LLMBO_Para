import json
from pathlib import Path
import pytest
from electrothermal_fixtures import et_config,clone


def test_shared_valid_plan_avoids_new_warmstart_and_solves(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment,prepare_electrothermal_experiment
    from llmbo_para.runstore import sha256_file
    from test_electrothermal_llm import Proposed
    cfg=et_config();cfg['optimization']['mode']='warmstart_only';cfg['optimization']['total_candidate_budget']=2
    _,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    mock=Proposed(p.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6]);ctl=ElectrothermalLLMController(transport=mock,is_mock=True)
    first=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,llm_controller=ctl)
    from pathlib import Path
    plan=Path(first['run_directory'])/'initial-plan.json'
    cfg['optimization']['mode']='full_llmbo_mo';cfg['optimization']['initial_plan']={'path':str(plan),'sha256':sha256_file(plan)}
    second=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path)
    assert second['costs']['software_calls']==0 and second['API_calls']==0
    assert first['initial_plan_sha256']==second['initial_plan_sha256']
    assert first['pareto']==second['pareto'] and mock.calls==1


def test_v2_mock_warmstart_archives_rule_and_v1_v2_plans_cannot_mix(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment,prepare_electrothermal_experiment
    from llmbo_para.runstore import sha256_file
    from test_electrothermal_llm import Proposed

    cfg=et_config();cfg['optimization']['mode']='warmstart_only'
    cfg['optimization']['total_candidate_budget']=2
    cfg['optimization']['warmstart']['selection_rule']='pareto_core_spacefill_v2'
    report,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert report['ready'] and prepared is not None
    transport=Proposed(prepared.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6])
    run=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=transport,is_mock=True))
    root=Path(run['run_directory'])
    selection=json.loads((root/'warmstart-selection.json').read_text(encoding='utf8'))
    assert selection['rule']=='pareto_core_spacefill_v2'
    assert len(selection['selected_ids'])==2 and transport.calls==1
    assert run['API_calls']==0 and run['costs']['solver_calls']==0

    old=clone(cfg)
    old['optimization']['warmstart']['selection_rule']='pareto_maximin_v1'
    plan=root/'initial-plan.json'
    old['optimization']['initial_plan']={'path':str(plan),'sha256':sha256_file(plan)}
    report,prepared=prepare_electrothermal_experiment(old,base_dir=tmp_path)
    assert prepared is None and any('initialization signatures incompatible' in error for error in report['errors'])

    old['optimization'].pop('initial_plan')
    old_report,old_prepared=prepare_electrothermal_experiment(old,base_dir=tmp_path)
    assert old_report['ready']
    old_transport=Proposed(old_prepared.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6])
    old_run=run_electrothermal_experiment(old,tmp_path,base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=old_transport,is_mock=True))
    old_plan=Path(old_run['run_directory'])/'initial-plan.json'
    future=clone(cfg)
    future['optimization']['initial_plan']={'path':str(old_plan),'sha256':sha256_file(old_plan)}
    report,prepared=prepare_electrothermal_experiment(future,base_dir=tmp_path)
    assert prepared is None and any('initialization signatures incompatible' in error for error in report['errors'])


def test_v2_initial_plan_import_replays_the_archived_selection_rule(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment,prepare_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.runstore import sha256_file
    from test_electrothermal_llm import Proposed

    cfg=et_config();cfg['optimization']['mode']='warmstart_only'
    cfg['optimization']['total_candidate_budget']=2
    cfg['optimization']['warmstart']['selection_rule']='pareto_core_spacefill_v2'
    _,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    mock=Proposed(prepared.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6])
    first=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=mock,is_mock=True))
    plan=Path(first['run_directory'])/'initial-plan.json'
    cfg['optimization']['mode']='full_llmbo_mo'
    cfg['optimization']['initial_plan']={'path':str(plan),'sha256':sha256_file(plan)}
    second=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path)
    assert first['initial_plan_sha256']==second['initial_plan_sha256']
    assert second['costs']['software_calls']==0 and second['API_calls']==0
    assert audit_electrothermal_run(Path(second['run_directory']),deep=True)['passed']


def test_v3_plan_rejects_rehashed_quality_gate_tampering(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment,prepare_electrothermal_experiment
    from llmbo_para.runstore import digest_value,sha256_file
    from test_electrothermal_llm import Proposed

    cfg=et_config();cfg['optimization']['mode']='warmstart_only'
    cfg['optimization']['total_candidate_budget']=2
    cfg['optimization']['warmstart']['selection_rule']='pareto_quality_gated_spacefill_v3'
    _,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    mock=Proposed(prepared.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6])
    first=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=mock,is_mock=True))
    plan=Path(first['run_directory'])/'initial-plan.json'
    payload=json.loads(plan.read_text(encoding='utf8'))
    assert payload['history_evidence']['selection']['rule']=='pareto_quality_gated_spacefill_v3'
    payload['history_evidence']['selection']['q_gate']+=1.
    payload.pop('plan_sha256')
    payload['plan_sha256']=digest_value(payload)
    forged=tmp_path/'forged-v3-plan.json'
    forged.write_text(json.dumps(payload),encoding='utf8')
    cfg['optimization']['initial_plan']={'path':str(forged),'sha256':sha256_file(forged)}
    report,accepted=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert accepted is None
    assert any('historical selection' in error for error in report['errors'])


@pytest.mark.parametrize('actual_rule,forged_rule',[
    ('pareto_maximin_v1','pareto_core_spacefill_v2'),
    ('pareto_core_spacefill_v2','pareto_maximin_v1'),
])
def test_rehashed_initial_plan_cannot_claim_a_different_selection_rule(tmp_path,actual_rule,forged_rule):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController,warmstart_selection_details
    from llmbo_para.electrothermal_evaluation import result_from_dict
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment,prepare_electrothermal_experiment
    from llmbo_para.runstore import digest_value,sha256_file
    from test_electrothermal_llm import Proposed

    cfg=et_config();cfg['optimization']['mode']='warmstart_only'
    cfg['optimization']['total_candidate_budget']=2
    cfg['optimization']['warmstart'].update(pool_size=2,max_requests=1,max_candidates=2,max_evaluations=2,
                                           selection_rule=actual_rule)
    _,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    mock=Proposed(prepared.space,[[.2]*6,[.8]*6])
    original=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=mock,is_mock=True))
    plan=Path(original['run_directory'])/'initial-plan.json'
    forged=json.loads(plan.read_text(encoding='utf8'))
    pool=[result_from_dict(raw) for raw in forged['history_evidence']['screening_records']]
    replay=warmstart_selection_details(pool,space=prepared.space,count=2,
        objective_scales=cfg['optimization']['objective_scales'],
        rho_aug=cfg['optimization']['rho_aug'],rule=forged_rule)
    forged['history_evidence']['selection'].update(replay)
    by_id={raw['evaluation_id']:raw for raw in forged['records']}
    forged['records']=[by_id[ident] for ident in replay['selected_ids']]
    forged.pop('plan_sha256')
    forged['plan_sha256']=digest_value(forged)
    forged_path=tmp_path/(actual_rule+'-forged-plan.json')
    forged_path.write_text(json.dumps(forged),encoding='utf8')
    cfg['optimization']['initial_plan']={'path':str(forged_path),'sha256':sha256_file(forged_path)}
    report,accepted=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    assert accepted is None and any('selection rule' in error for error in report['errors'])
