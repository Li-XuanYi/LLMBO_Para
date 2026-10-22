"""LGBO workflow acceptance; all observations use the algebraic software backend."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from lgbo_fixtures import lgbo_config, region_action


def optimizer(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.mo_optimizer import MOOptimizer
    cfg = lgbo_config()
    cfg['optimization'].update(mode='full_llmbo_mo', gp_sweeps=0, total_candidate_budget=16)
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
                                   signatures=prepared.signatures, command='LGBO software unit')
    evaluator = ElectrothermalEvaluator(prepared.space, SyntheticElectrothermalSimulator(),
                                       fit_rates=prepared.dataset.fit_rates)
    class Abstain:
        def post(self, payload):
            return region_action(payload, kind='none')
    controller = ElectrothermalLLMController(transport=Abstain(), is_mock=True)
    controller.prepared = prepared
    return MOOptimizer(prepared.space, evaluator, prepared.dataset, store, cfg['optimization'],
                       llm_controller=controller)


def test_every_round_including_thirteen_requests_without_trust(tmp_path):
    opt = optimizer(tmp_path)
    for _ in range(13):
        event = opt.step()
        assert event['region']['action_valid']
        assert event['region']['fallback_reason'] == 'abstained'
        assert 'trust' not in event['feedback']
    assert opt.llm_controller.requests == 13
    diagnostic = opt.summary()['region_diagnostics']
    assert diagnostic['valid_actions'] == 13
    assert diagnostic['tilt_applied'] == diagnostic['selection_changed'] == 0


def test_failed_lgbo_round_refreshes_weight_and_gp_without_new_pair(tmp_path, monkeypatch):
    from dataclasses import replace
    opt = optimizer(tmp_path); opt.initialize()
    original = opt.evaluator.simulator.simulate
    def incomplete(theta, case):
        return replace(original(theta, case), temperature_k=None)
    monkeypatch.setattr(opt.evaluator.simulator, 'simulate', incomplete)
    first = opt.step(); previous_gp = opt.gp
    second = opt.step()
    assert len(opt.history) == 2 and opt.gp is not previous_gp
    assert first['context']['scalarization']['weights'] != second['context']['scalarization']['weights']
    assert first['context']['scalarization']['observation_ids'] == second['context']['scalarization']['observation_ids']
    assert first['feedback']['new_scalar'] is second['feedback']['new_scalar'] is None
    assert opt.llm_controller.requests == 2


def test_covariance_can_select_a_candidate_outside_the_rectangle():
    from test_electrothermal_lgbo import setup_region, PSDGP
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    space, context, reply = setup_region()
    reply['region'].update(lb=[.4]*6, ub=[.5]*6)
    result = apply_lgbo_region(PSDGP(), context, context.pool, reply, space=space)
    assert result['selected_index'] == 1
    assert all(x > .5 for x in context.pool[1])
    assert result['tilt_applied'] and result['selection_changed']


def test_disabled_lgbo_mode_can_run_plain_without_credentials(tmp_path):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    cfg = lgbo_config()
    result = run_electrothermal_experiment(cfg, tmp_path, base_dir=tmp_path)
    assert result['BO_rounds'] == 2
    assert result['API_calls'] == result['costs']['solver_calls'] == 0


def test_zero_budget_template_is_valid_and_explicitly_software(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = json.loads((Path(__file__).parents[1]/'configs/electrothermal-sub2api-lgbo-software-template.json').read_text())
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is not None, report['errors']
    assert cfg['optimization']['region_method'] == 'lgbo_v1'
    assert cfg['model']['provider'] == 'software' and not cfg['llm']['enabled']
    assert cfg['budgets']['max_solver_calls'] == cfg['budgets']['max_llm_requests'] == 0


def test_lgbo_decision_is_invariant_to_voltage_units_with_matched_scales():
    """Only numeric display units change; physical internal observations stay V."""
    from types import SimpleNamespace
    import numpy as np
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region
    from test_electrothermal_lgbo import setup_region
    space, _, reply = setup_region()
    x = [[.2]*6, [.5]*6, [.8]*6]
    y = np.asarray([[.03, .10], [.05, .04], [.08, .02]])
    results = []
    for factor in (1., 1000.):
        scalar = build_scalarization_context(x, y*np.asarray([factor, 1.]), ['A', 'B', 'C'],
            weights=(.8, .2), objective_scales=(.1*factor, 1.), rho_aug=.05, protocol_signature='fixture')
        gp = Matern52GP(max_sweeps=0).fit(scalar.x, scalar.labels, group=())
        context = SimpleNamespace(ordinal=1, scalarization=scalar, context_id=reply['context_id'],
            signatures_json=json.dumps(reply['signatures']), pool=((.1,)*6, (.55,)*6, (.9,)*6))
        results.append(apply_lgbo_region(gp, context, context.pool, reply, space=space))
    assert results[0]['selected_index'] == results[1]['selected_index']
    assert results[0]['adjusted_mean'] == pytest.approx(results[1]['adjusted_mean'])
    assert results[0]['std'] == pytest.approx(results[1]['std'])


def test_lgbo_duplicate_input_is_cached_and_equal_outputs_keep_distinct_inputs(tmp_path, monkeypatch):
    opt = optimizer(tmp_path)
    original = opt.evaluator.simulator.simulate
    constant_theta = dict(zip((s.name for s in opt.space.specs), opt.space.denormalize([.5]*6)))
    monkeypatch.setattr(opt.evaluator.simulator, 'simulate',
                        lambda theta, case: original(constant_theta, case))
    opt.initialize()
    assert len(opt.history) == 2 and opt.history[0].objectives == opt.history[1].objectives
    before = opt.store.ledger.summary()['software_calls']
    _, cached = opt.evaluate(opt.history[0].parameters)
    assert cached and len(opt.history) == 2
    assert opt.store.ledger.summary()['software_calls'] == before
    _, cached = opt.evaluate(opt.space.denormalize([.9]*6))
    assert not cached and len(opt.history) == 3
