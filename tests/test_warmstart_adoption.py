"""Public WarmStart naming, unchanged core/coverage selection, strict provenance."""
from electrothermal_fixtures import et_config, clone


def test_default_rule_has_no_release_suffix_and_legacy_names_stay_explicit():
    from llmbo_para.config import configuration_errors
    from llmbo_para.electrothermal_config import effective_warmstart_selection_rule

    cfg = et_config()
    assert effective_warmstart_selection_rule(cfg) == 'pareto_core_spacefill'
    for rule in ('pareto_core_spacefill', 'pareto_core_spacefill_v2', 'pareto_maximin_v1'):
        explicit = clone(cfg)
        explicit['optimization']['warmstart']['selection_rule'] = rule
        assert configuration_errors(explicit) == []
        assert effective_warmstart_selection_rule(explicit) == rule


def test_unversioned_default_preserves_approved_core_and_coverage_selection():
    from llmbo_para.electrothermal_llm import warmstart_selection_details, select_electrothermal_warmstart
    from test_electrothermal_llm import _selector_records

    space, rows = _selector_records([
        ('A', .2, (.1, .9)), ('B', .3, (.2, .5)),
        ('C', .21, (.25, 1.5)), ('D', .8, (.3, 2.)),
    ])
    kwargs = {'space': space, 'count': 3, 'objective_scales': [.1, 1.]}
    old = warmstart_selection_details(rows, rule='pareto_core_spacefill_v2', **kwargs)
    current = warmstart_selection_details(rows, **kwargs)
    assert current['rule'] == 'pareto_core_spacefill'
    assert current['selected_ids'] == ['A', 'B', 'D']
    assert {k: v for k, v in current.items() if k != 'rule'} == {
        k: v for k, v in old.items() if k != 'rule'}
    assert select_electrothermal_warmstart(rows, **kwargs) == tuple(current['selected_ids'])


def test_default_and_legacy_rule_initialization_signatures_cannot_mix():
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset

    cfg = et_config()
    dataset = make_synthetic_dataset(tuple(cfg['fit_rates']))
    implicit = build_electrothermal_signatures(cfg, dataset)
    cfg['optimization']['warmstart']['selection_rule'] = 'pareto_core_spacefill'
    explicit = build_electrothermal_signatures(cfg, dataset)
    assert implicit.initialization_compatibility == explicit.initialization_compatibility
    identities = {implicit.initialization_compatibility}
    for rule in ('pareto_maximin_v1', 'pareto_core_spacefill_v2'):
        cfg['optimization']['warmstart']['selection_rule'] = rule
        historical = build_electrothermal_signatures(cfg, dataset)
        identities.add(historical.initialization_compatibility)
        assert implicit.evaluation_protocol == historical.evaluation_protocol
    assert len(identities) == 3


def test_default_mock_run_archives_unversioned_rule_and_passes_deep_audit(tmp_path):
    import json
    from pathlib import Path
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment, run_electrothermal_experiment
    from test_electrothermal_llm import Proposed

    cfg = et_config()
    cfg['optimization'].update(mode='warmstart_only', total_candidate_budget=2)
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    transport = Proposed(prepared.space, [[.2] * 6, [.8] * 6, [.21] * 6, [.7] * 6])
    result = run_electrothermal_experiment(cfg, tmp_path, base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=transport, is_mock=True))
    root = Path(result['run_directory'])
    selection = json.loads((root / 'warmstart-selection.json').read_text(encoding='utf8'))
    assert selection['rule'] == 'pareto_core_spacefill'
    assert result['API_calls'] == result['costs']['solver_calls'] == 0
    assert audit_electrothermal_run(root, deep=True)['passed']
