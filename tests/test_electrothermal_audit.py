import json
from pathlib import Path
import pytest
from electrothermal_fixtures import et_config,R3,R4


@pytest.mark.parametrize('damage',['none','temperature','mapping','rates','weight','scale','labels','cost'])
def test_tampering_temperature_mapping_rates_weight_or_scales_fails(tmp_path,damage):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    result=run_electrothermal_experiment(et_config(),tmp_path,base_dir=tmp_path);root=Path(result['run_directory'])
    if damage in ('temperature','mapping'):
        file=next((root/'electrothermal-evaluations').glob('*.json'));v=json.loads(file.read_text())
        if damage=='temperature':v['rates'][0]['trace']['temperature_k'][2]+=1
        else:v['rates'][0]['trace']['applied_parameters']={'native':{'Cell heat capacity [J.K-1.m-3]':1}}
    elif damage in ('weight','labels'):
        file=next((root/'mo-rounds').glob('*.json'));v=json.loads(file.read_text())
        if damage=='weight':v['context']['scalarization']['weights']=[.99,.01]
        else:v['context']['scalarization']['labels'][0]+=1
    elif damage in ('rates','scale'):
        file=root/'manifest.json';v=json.loads(file.read_text())
        if damage=='rates':v['config']['fit_rates']=['0.5C','1C']
        else:v['config']['optimization']['objective_scales'][0]*=1000
    elif damage=='cost':
        file=root/'electrothermal-summary.json';v=json.loads(file.read_text());v['costs']['software_calls']=0
    if damage!='none':file.write_text(json.dumps(v),encoding='utf8')
    audit=audit_electrothermal_run(root,deep=True)
    assert audit['passed']==(damage=='none'),audit


def test_three_modes_share_backbone_and_region_ablation_initial_plan(tmp_path):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment,prepare_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.runstore import sha256_file
    from test_electrothermal_llm import Proposed
    cfg=et_config();plain=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path)
    cfg['optimization']['mode']='warmstart_only';_,p=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    mock=Proposed(p.space,[[.2]*6,[.8]*6,[.21]*6,[.7]*6])
    warm=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,llm_controller=ElectrothermalLLMController(transport=mock,is_mock=True))
    plan=Path(warm['run_directory'])/'initial-plan.json';cfg['optimization']['initial_plan']={'path':str(plan),'sha256':sha256_file(plan)}
    cfg['optimization']['mode']='full_llmbo_mo'
    class Abstain:
        def __init__(self):self.payloads=[]
        def post(self,payload):
            self.payloads.append(payload)
            return {k:payload[k] for k in ('schema_version','parameter_profile','fit_rates','signatures','context_id')}|{
                'region':{'kind':'none','coordinate_space':'normalized','confidence':0,'reason':'abstain'}}
    transport=Abstain();full=run_electrothermal_experiment(cfg,tmp_path,base_dir=tmp_path,llm_controller=ElectrothermalLLMController(transport=transport,is_mock=True))
    assert len(transport.payloads)==2
    assert warm['pareto']==full['pareto'] and warm['initial_plan_sha256']==full['initial_plan_sha256']
    for result in (plain,warm,full):
        assert result['API_calls']==0 and audit_electrothermal_run(Path(result['run_directory']),deep=True)['passed']
    assert full['costs']['software_calls']==6 and full['costs']['mock_llm_requests']==2


def test_r3_r4_protocol_comparison_is_rejected_and_v2_audit_dispatch(tmp_path):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.audit import audit_run
    from llmbo_para.pareto import validate_hv_comparison
    results=[run_electrothermal_experiment(et_config(rates),tmp_path,base_dir=tmp_path) for rates in (R3,R4)]
    assert all(audit_run(r['run_directory'],deep=True)['passed'] for r in results)
    with pytest.raises(ValueError):validate_hv_comparison([r['comparison_protocol'] for r in results])
