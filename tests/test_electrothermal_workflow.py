import pytest
from electrothermal_fixtures import et_config,R3,R4


def test_v2_dispatch_and_pending_research_preflight():
    from llmbo_para.workflow import prepare_experiment
    cfg=et_config();report,prepared=prepare_experiment(cfg)
    assert report['ready'] and prepared.dataset.fit_rates==R3
    cfg['run_kind']='research';report,prepared=prepare_experiment(cfg)
    assert not report['ready'] and prepared is None
    assert any('temperature_probe' in e for e in report['errors'])


def test_software_fixed_candidates_archive_recomputable_pairs(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment,run_electrothermal_fixed_candidates
    cfg=et_config();report,prepared=prepare_electrothermal_experiment(cfg,base_dir=tmp_path)
    result=run_electrothermal_fixed_candidates(prepared,[prepared.space.denormalize([.5]*6)],tmp_path)
    assert result['complete_pairs']==1 and result['costs']['solver_calls']==0
    assert result['costs']['software_calls']==len(R3) and result['API_calls']==0


def test_new_schema_does_not_enter_old_optimizer(tmp_path):
    from llmbo_para.workflow import run_experiment
    with pytest.raises(NotImplementedError,match='Stage B'):
        run_experiment(et_config(),tmp_path)
