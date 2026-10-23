"""Deterministic software inputs; freeze trusted identities before producing payloads."""
from dataclasses import asdict, replace
from pathlib import Path

from electrothermal_fixtures import et_config

CASES = ('warmstart', 'legacy_bounds', 'candidate_aware', 'fair_dynamic',
         'catalog_full', 'catalog_compact_action', 'lgbo_v1', 'lgbo_v2')


def payload_case(case: str, tmp_path: Path) -> tuple:
    if case not in CASES:
        raise ValueError('unknown golden payload case')
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.mo_optimizer import MORoundContext
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.runstore import canonical_json
    from test_region_decision_evidence import numeric_context

    cfg = et_config(('0.5C', '1C'))
    if case.startswith('lgbo_'):
        cfg['optimization'].pop('region')
        cfg['optimization']['region_method'] = case
    elif case not in ('warmstart', 'legacy_bounds'):
        cfg['optimization']['region_advice'] = 'candidate_aware_v1'
        # Ensure a nonempty catalog without replacing scientific GP predictions.
        cfg['optimization']['region'].update(max_plain_log_ei_gap=100., min_sigma_ratio=0.)
        if case != 'candidate_aware':
            cfg['optimization'].update(region_selection='fair_region_v1', region_evidence='dynamic_decision_v3')
        if case.startswith('catalog_'):
            cfg['optimization']['region_proposal'] = 'catalog_v1'
        if case == 'catalog_compact_action':
            cfg['llm']['region_wire_format'] = 'compact_action_v2'
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is not None, report['errors']
    # Only trusted test identities are frozen, before the builder is called.
    prepared.signatures = replace(prepared.signatures, **{
        key: 'frozen' for key in asdict(prepared.signatures) if key != 'fit_rates'})
    evaluator = ElectrothermalEvaluator(prepared.space, SyntheticElectrothermalSimulator(),
                                        fit_rates=prepared.dataset.fit_rates)
    history = [evaluator.evaluate(prepared.space.denormalize([v] * 6), prepared.dataset) for v in (.2, .8)]
    if case == 'warmstart':
        return prepared, history, None
    scalar = build_scalarization_context(
        [prepared.space.normalize(r.parameters) for r in history], [r.objectives for r in history],
        [r.evaluation_id for r in history], weights=(.8, .2), objective_scales=(.1, 1.),
        rho_aug=.05, protocol_signature='frozen')
    gp = Matern52GP(max_sweeps=0).fit(scalar.x, scalar.labels, group=())
    pool = numeric_context().pool
    context = MORoundContext(scalar, prepared.dataset.fit_rates,
        canonical_json(asdict(prepared.signatures)).decode(), canonical_json(gp.state_dict()).decode(),
        pool, 13, 'context-fixed')
    return prepared, history, context
