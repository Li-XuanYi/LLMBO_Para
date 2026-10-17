import json
from electrothermal_fixtures import et_config


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
