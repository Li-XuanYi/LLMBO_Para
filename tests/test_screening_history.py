"""History reuse must change information, not simulation counts or provenance."""
import copy
import json
from pathlib import Path
import shutil

import numpy as np
import pytest

from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run
from llmbo_para.config import parameter_space_from_config, configuration_errors
from llmbo_para.evaluation import CallableSimulator, FourRateEvaluator
from llmbo_para.initialization import FeasibleInitializer, ScreeningBudget
from llmbo_para.runstore import RunStore, sha256_file
from llmbo_para.screening_history import load_screening_history
from llmbo_para.surrogate import Matern52GP
from llmbo_para.synthetic import synthetic_config, synthetic_series
from llmbo_para.workflow import run_experiment, prepare_experiment


def fixture(tmp_path, *, partial=True, failures=(1, 2)):
    config = synthetic_config()
    config['optimization'].update(candidate_pool_size=8, composite_ei_draws=16, gp_sweeps=2)
    space = parameter_space_from_config(config)
    series = synthetic_series()
    counter = {'candidate': 0}
    def simulate(params, row):
        if row.rate == '0.5C':
            counter['candidate'] += 1
        if partial and counter['candidate'] in failures and row.rate == '3C':
            return row.time_s[:-1], row.voltage_v[:-1]
        return row.time_s, [v + .01 * counter['candidate'] for v in row.voltage_v]
    store = RunStore(tmp_path/'screen', config, command='screening history fixture')
    initializer = FeasibleInitializer(config, space, series,
        FourRateEvaluator(space, CallableSimulator(simulate)), store, gate=None, source='random',
        budget=ScreeningBudget(target=2, max_evaluations=max(4,len(failures)+2)))
    plan = initializer.run()
    plan_path = store.path/'initial-plan.json'
    case = arm_config(config, plan, plan_path, warm_start=False, gp_groups=False, bo_iterations=2)
    case['optimization'].update(reuse_screening_history=True,
        bo_repair={'training_data':'per_rate', 'candidate_policy':'local', 'feasibility_weighting':True})
    return case, space, series, plan, plan_path, initializer


def test_partial_history_trains_rates_and_classifier_without_extra_solves(tmp_path):
    case, space, series, plan, path, init = fixture(tmp_path)
    calls = []
    def simulation(params, row):
        calls.append(row.rate)
        return row.time_s, [v + .01 for v in row.voltage_v]
    result = run_experiment(case, tmp_path/'run', simulator=CallableSimulator(simulation))
    run = Path(result['run_directory'])
    assert len(calls) == 8
    assert result['cache_hits'] == 2 and result['new_candidate_evaluations'] == 2
    assert result['screening_history']['reused_failed_candidates'] == 2
    assert result['screening_history']['attributed_total_candidate_evaluations'] == 6
    assert result['screening_history']['attributed_total_rate_solves'] == 24
    state = json.loads((run/'models/after-000002.json').read_text())
    assert {k:len(v['x']) for k,v in state['models'].items()} == {'0.5C':4,'1C':4,'2C':4,'3C':2}
    assert state['training']['0.5C']['record_ids'] == [-2,-1,0,1]
    assert state['completion_model']['sample_count'] == 4
    assert state['completion_model']['positive_count'] == 2
    assert audit_run(run, deep=True)['passed']
    # Auditing the new run must remain self-contained after the old directory moves.
    init.store.path.rename(init.store.path.with_name(init.store.path.name+'-offline'))
    assert audit_run(run, deep=True)['passed']
    report, prepared = prepare_experiment(case)
    assert prepared is None and report['errors']
    damaged = run/'screening-history/record-000000.json'
    record = json.loads(damaged.read_text()); record['rates'][0]['rmse_v'] *= 2
    damaged.write_text(json.dumps(record))
    assert not audit_run(run, deep=True)['passed']


def test_history_recalculates_labels_even_if_file_hash_is_new(tmp_path):
    case, space, series, plan, path, init = fixture(tmp_path)
    source = init.store.path/'attempts/candidate-000000-attempt-001.json'
    record = json.loads(source.read_text()); record['rates'][0]['rmse_v'] *= 2
    source.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='labels'):
        load_screening_history(case, series, plan, path)


def test_history_missing_attempt_or_wrong_cost_fails_closed(tmp_path):
    case, space, series, plan, path, init = fixture(tmp_path)
    altered = copy.deepcopy(plan); altered['screening_cost']['rate_solve_attempts'] += 4
    with pytest.raises(ValueError, match='cost'):
        load_screening_history(case, series, altered, path)
    source = init.store.path/'attempts/candidate-000000-attempt-001.json'
    source.rename(source.with_suffix('.hidden'))
    with pytest.raises(ValueError, match='sequence/cost'):
        load_screening_history(case, series, plan, path)


def test_history_can_be_empty_and_does_not_duplicate_initial_points(tmp_path):
    case, space, series, plan, path, init = fixture(tmp_path, partial=False)
    history = load_screening_history(case, series, plan, path)
    assert history.results == []
    assert history.catalog['initial_points_excluded'] == 2
    result = run_experiment(case, tmp_path/'run', simulator=CallableSimulator(lambda p,s:(s.time_s,s.voltage_v)))
    assert result['screening_history']['attributed_total_candidate_evaluations'] == 4
    assert audit_run(result['run_directory'], deep=True)['passed']


def test_history_pool_continuation_is_cached_and_requires_no_llm(tmp_path):
    case, _, _, plan, _, init = fixture(tmp_path)
    plan = copy.deepcopy(plan)
    plan['source'] = 'history'
    plan['continuation_provenance'] = {'purpose': 'mixed historical observations; not a new ablation arm'}
    path = init.store.write_json('historical-plan.json', plan)
    case = arm_config(case, plan, path, warm_start=False, gp_groups=False, bo_iterations=2)
    assert configuration_errors(case) == []
    calls = []
    def simulate(parameters, series):
        calls.append(series.rate)
        return series.time_s, [v + .005 for v in series.voltage_v]
    result = run_experiment(case, tmp_path/'continuation', simulator=CallableSimulator(simulate))
    run = Path(result['run_directory'])
    assert result['cache_hits'] == 2 and len(calls) == 8
    assert result['initial_best_objective_v'] == min(r['objective_v'] for r in plan['evaluations'])
    assert json.loads((run/'initial-set.json').read_text())['sources'] == ['history', 'history']
    assert not (run/'llm').exists()
    assert audit_run(run, deep=True)['passed']


def test_history_source_rejects_uncached_initial_parameters():
    from llmbo_para.optimizer import Optimizer
    case = synthetic_config()
    space = parameter_space_from_config(case)
    series = synthetic_series()
    points = [space.denormalize([value] * 6) for value in (.3, .4)]
    with pytest.raises(ValueError, match='verified cached'):
        Optimizer(space, FourRateEvaluator(space, CallableSimulator(lambda p,s:(s.time_s,s.voltage_v))),
            series, initial_llm_count=0, initial_sobol_count=2, initial_candidates=points,
            initial_candidates_source='history', llm_warm_start_enabled=False, llm_gp_groups_enabled=False)


def test_history_follows_resumed_screening_lineage(tmp_path):
    case, space, series, plan, path, first = fixture(tmp_path)
    cfg = first.config
    store = RunStore(tmp_path/'continued',cfg,command='continued screening fixture')
    resumed = FeasibleInitializer(cfg,space,series,FourRateEvaluator(space,CallableSimulator(lambda p,s:(s.time_s,s.voltage_v))),
        store,gate=None,source='random',budget=ScreeningBudget(target=3,max_evaluations=5))
    resumed.restore_random(plan,path)
    new_plan = resumed.run()
    history = load_screening_history(cfg,series,new_plan,store.path/'initial-plan.json')
    assert len(history.results) == 2
    assert len(history.catalog['segments']) == 2
    assert history.catalog['attributed_screening_cost']['candidate_evaluations'] == 5


@pytest.mark.parametrize('change', ['no_plan','single','complete','not_bool'])
def test_history_configuration_is_explicit(tmp_path, change):
    case, *_ = fixture(tmp_path)
    if change == 'no_plan':case['optimization'].pop('initial_candidates')
    if change == 'single':case['optimization']['surrogate_mode']='single_objective'
    if change == 'complete':case['optimization']['bo_repair']['training_data']='complete'
    if change == 'not_bool':case['optimization']['reuse_screening_history']='true'
    assert configuration_errors(case)


def test_gp_fit_diagnostics_are_monotonic_and_prediction_replays():
    rng=np.random.default_rng(8)
    x=rng.random((10,6)); y=np.sin(x[:,0]*3)+x[:,1]
    gp=Matern52GP(max_sweeps=20).fit(x,y)
    d=gp.state_dict()['fit_diagnostics']
    assert len(d['marginal_log_likelihood_trace']) == d['sweeps_completed']+1
    assert np.all(np.diff(d['marginal_log_likelihood_trace']) >= -1e-10)
    restored=Matern52GP.from_state(gp.state_dict())
    assert np.allclose(gp.predict(x),restored.predict(x))


def test_imported_failures_activate_weighting_and_decisions_replay(tmp_path):
    case, space, series, plan, path, init = fixture(tmp_path,failures=tuple(range(1,7)))
    result=run_experiment(case,tmp_path/'run',simulator=CallableSimulator(lambda p,s:(s.time_s,s.voltage_v)))
    run=Path(result['run_directory'])
    state=json.loads((run/'models/after-000002.json').read_text())
    assert state['completion_model']['ready']
    assert state['completion_model']['sample_count']==8
    row=json.loads((run/'acquisition/candidate-000002.json').read_text())
    assert row['p_complete'] is not None and row['fallback'] is None
    np.testing.assert_allclose(row['decision_scores'],np.asarray(row['composite_ei'])*row['p_complete'])
    assert audit_run(run,deep=True)['passed']
    # Even rewriting the catalog hash cannot conceal a changed training label.
    file=run/'screening-history/record-000000.json'
    record=json.loads(file.read_text()); record['rates'][0]['rmse_v'] *= 2
    file.write_text(json.dumps(record))
    catalog_file=run/'screening-history/catalog.json'
    catalog=json.loads(catalog_file.read_text()); catalog['sources'][0]['sha256']=sha256_file(file)
    catalog_file.write_text(json.dumps(catalog))
    assert not audit_run(run,deep=True)['passed']
