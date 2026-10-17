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


@pytest.mark.parametrize('rates',[R3,R4])
def test_parego_software_r3_r4_end_to_end(tmp_path,rates,monkeypatch):
    from pathlib import Path
    import json
    from llmbo_para.workflow import run_experiment
    from llmbo_para.optimizer import Optimizer
    monkeypatch.setattr(Optimizer,'optimize',lambda *a,**k:pytest.fail('old optimizer entered'))
    result=run_experiment(et_config(rates),tmp_path)
    assert result['candidate_evaluations']==4 and result['BO_rounds']==2 and result['complete_pairs']==4
    assert result['fit_rates']==list(rates) and result['API_calls']==0
    assert result['costs']['software_calls']==4*len(rates) and result['pareto']
    root=Path(result['run_directory'])
    assert len(list((root/'mo-rounds').glob('*.json')))==2
    for p in (root/'electrothermal-evaluations').glob('*.json'):
        assert [r['rate'] for r in json.loads(p.read_text())['rates']]==list(rates)


def test_training_contains_real_complete_pairs_only_and_budget_counts_failures(tmp_path):
    from dataclasses import replace
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.workflow import run_experiment
    class Partial(SyntheticElectrothermalSimulator):
        def __init__(self):self.calls=0
        def simulate(self,p,case):
            self.calls+=1;trace=super().simulate(p,case)
            return replace(trace,temperature_k=None) if self.calls>6 else trace
    result=run_experiment(et_config(),tmp_path,simulator=Partial())
    assert result['candidate_evaluations']==4 and result['complete_pairs']==2 and result['BO_rounds']==2
