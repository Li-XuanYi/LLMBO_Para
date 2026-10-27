import json
from pathlib import Path
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
    old['optimization']['warmstart'].pop('selection_rule')
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
