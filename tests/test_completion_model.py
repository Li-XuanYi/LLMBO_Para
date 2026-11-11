"""Completion-model leakage, persistence, fallbacks and workflow audit checks."""
import json
from pathlib import Path

import numpy as np
import pytest

from llmbo_para.bo_repair import CompletionModel, RepairSettings
from llmbo_para.audit import audit_run
from llmbo_para.runstore import sha256_file
from llmbo_para.workflow import run_experiment
from test_bo_repair import setup_problem, artificial_simulator


def narrow_training():
    rng = np.random.default_rng(37)
    x = rng.uniform(.45,.55,(48,6))
    x[:,0] = rng.uniform(.85,.92,len(x))
    x[:,5] = .3  # Constant dimensions must remain finite.
    y = (x[:,0]>.895) & (x[:,1]>.47)
    return x,y


def test_scaling_is_fit_inside_each_training_fold_and_saved_model_replays():
    x,y = narrow_training()
    model = CompletionModel('standardized_linear_cv').fit(x,y)
    assert model.state['ready']
    folds = model.state['cv_folds']
    assert sorted(i for fold in folds for i in fold) == list(range(len(x)))
    for row in model.state['cv_results']:
        for fold in row['fits']:
            tr,val = fold['training_indexes'],fold['validation_indexes']
            assert not set(tr)&set(val)
            assert set(tr)|set(val) == set(range(len(x)))
            np.testing.assert_allclose(fold['feature_mean'],x[tr].mean(axis=0),atol=1e-15)
            assert not np.allclose(fold['feature_mean'],x.mean(axis=0),atol=1e-8)
            assert fold['feature_scale'][5] == 1
            assert sum(y[tr]) and sum(~y[tr])
    p = model.predict(x)
    assert np.all(np.isfinite(p)) and np.mean((p-y)**2) < .08
    restored = CompletionModel()
    restored.state = json.loads(json.dumps(model.state))
    np.testing.assert_array_equal(restored.predict(x),p)
    assert CompletionModel('standardized_linear_cv').fit(x,y).state == model.state


def test_too_few_classes_and_degenerate_features_have_explicit_fallback():
    x,y = narrow_training()
    for labels in ([True]*8,[False]*8,[True]*7+[False],[]):
        model = CompletionModel('standardized_linear_cv').fit(x[:len(labels)],labels)
        assert not model.state['ready'] and model.predict(x) is None
    model = CompletionModel('standardized_linear_cv').fit(np.full((12,6),.5),[True]*6+[False]*6)
    assert not model.state['ready']


@pytest.mark.parametrize('value',[None,[],{},'bogus',42])
def test_invalid_model_choice_is_rejected(value):
    with pytest.raises(ValueError):
        RepairSettings.parse({'completion_model':value})


@pytest.mark.parametrize('bad',[[float('nan')]*6,[-.1]*6,[1.1]*6])
def test_invalid_normalized_training_is_rejected(bad):
    with pytest.raises(ValueError):
        CompletionModel('standardized_linear_cv').fit([bad]*8,[True]*4+[False]*4)


def test_new_workflow_deep_audit_rejects_tampered_standardization(tmp_path):
    config,space,_ = setup_problem()
    points = [list(space.denormalize([v]*6)) for v in (.47,.49,.53,.55,.65,.68,.72,.75)]
    plan = tmp_path/'points.json';plan.write_text(json.dumps({'source':'random','parameters':points}))
    config['optimization'].update(sobol_points=8,total_candidate_budget=10,
        bo_repair={'training_data':'per_rate','feasibility_weighting':True,'completion_model':'standardized_linear_cv'},
        initial_candidates=points,initial_candidates_source='random',
        initial_candidates_evidence={'path':str(plan),'sha256':sha256_file(plan)})
    result = run_experiment(config,tmp_path/'runs',simulator=artificial_simulator(space))
    run = Path(result['run_directory'])
    assert audit_run(run,deep=True)['passed']
    states = sorted((run/'models').glob('*.json'))
    state = json.loads(states[0].read_text())
    assert state['completion_model']['ready']
    state['completion_model']['feature_mean'][0] += .05
    states[0].write_text(json.dumps(state))
    assert not audit_run(run,deep=True)['passed']


def test_old_neighborhood_settings_parse_to_legacy_model():
    assert RepairSettings.parse({'feasibility_weighting':True}).completion_model == 'legacy_diagonal'
