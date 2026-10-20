"""Past curve signs distinguish equal-RMSE physical directions without new labels."""
from dataclasses import replace
import json
import math
from pathlib import Path

import pytest

from electrothermal_fixtures import et_config


def output(*, valid=True, sign=1, unit='K'):
    from llmbo_para.electrothermal_evaluation import ObservedOutputResult
    return ObservedOutputResult(valid, None, math.sqrt(7.5) if valid else None, (0., 1., 3., 8.), (300.,)*4,
        tuple(300. + sign*v for v in (1., 2., 3., 4.)) if valid else None, unit, 'fixture', None if valid else 'solver_error')


def test_mirrored_residuals_have_same_rmse_but_opposite_signed_evidence():
    from llmbo_para.electrothermal_residuals import signed_output_summary
    positive = signed_output_summary(output())
    negative = signed_output_summary(output(sign=-1))
    errors = [math.hypot(*[a-b for a,b in zip(row.predicted,row.observed)])/math.sqrt(len(row.observed))
              for row in (output(),output(sign=-1))]
    assert errors[0] == errors[1] == pytest.approx(math.sqrt(7.5))
    assert positive['valid'] and positive['unit'] == 'K' and positive['sample_count'] == 4
    assert positive['signed_mean'] == 2.5 and positive['early_signed_mean'] == 1.
    assert positive['late_signed_mean'] == 4.
    for key in ('signed_mean', 'early_signed_mean', 'late_signed_mean'):
        assert negative[key] == -positive[key]


def test_failed_temperature_summary_has_no_fabricated_zero_error():
    from llmbo_para.electrothermal_residuals import signed_output_summary
    summary = signed_output_summary(output(valid=False))
    assert summary['valid'] is False
    assert all(summary[key] is None for key in ('signed_mean', 'early_signed_mean', 'late_signed_mean'))


@pytest.mark.parametrize('damage', ['shape', 'nonfinite', 'time', 'unit'])
def test_valid_but_inconsistent_curve_is_rejected(damage):
    from llmbo_para.electrothermal_residuals import signed_output_summary
    row = output()
    if damage == 'shape': row = replace(row, predicted=(1.,))
    elif damage == 'nonfinite': row = replace(row, predicted=(300., 301., float('nan'), 302.))
    elif damage == 'time': row = replace(row, time_s=(0., 0., 3., 8.))
    else: row = replace(row, unit='degC')
    with pytest.raises(ValueError): signed_output_summary(row)


@pytest.mark.parametrize('mode', ['unknown', None, [], True])
def test_unknown_evidence_policy_is_rejected(mode):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = et_config(); cfg['optimization']['region_evidence'] = mode
    assert electrothermal_configuration_errors(cfg)


def test_signed_evidence_requires_existing_candidate_and_fair_strategy():
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = et_config(); cfg['optimization']['region_evidence'] = 'signed_residual_v1'
    assert electrothermal_configuration_errors(cfg)
    cfg['optimization'].update(region_advice='candidate_aware_v1', region_selection='fair_region_v1')
    assert not electrothermal_configuration_errors(cfg)


def make_context(root, evidence='signed_residual_v1'):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.mo_optimizer import MOOptimizer
    cfg = et_config(); cfg['optimization'].update(region_evidence=evidence,
        region_advice='candidate_aware_v1', region_selection='fair_region_v1')
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=root)
    assert prepared is not None, report['errors']
    store = ElectrothermalRunStore(root, cfg, dataset=prepared.dataset, signatures=prepared.signatures, command='residual payload fixture')
    optimizer = MOOptimizer(prepared.space, ElectrothermalEvaluator(prepared.space,
        SyntheticElectrothermalSimulator(), fit_rates=prepared.dataset.fit_rates), prepared.dataset, store, cfg['optimization'])
    optimizer.step()
    return prepared, optimizer


def test_payload_uses_only_past_observed_curves_and_does_not_change_labels(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.electrothermal_residuals import signed_record_summary
    from llmbo_para.runstore import digest_value
    p, opt = make_context(tmp_path)
    context = opt.last_context
    old = [r for r in opt.history if r.evaluation_id in context.scalarization.observation_ids]
    before = digest_value({'gp': opt.gp.state_dict(), 'history': [r.to_dict() for r in opt.history]})
    payload = build_electrothermal_payload('region_preference_electrothermal', prepared=p, history=old, context=context)
    assert payload['history_evidence']['sign_convention'] == 'prediction_minus_observation'
    assert 200 <= len(payload['instructions'].split()) <= 300
    for row in payload['history']:
        actual = next(r for r in old if r.evaluation_id == row['evaluation_id'])
        assert row['signed_residuals'] == signed_record_summary(actual)
    assert opt.history[-1].evaluation_id not in {r['evaluation_id'] for r in payload['history']}
    assert before == digest_value({'gp': opt.gp.state_dict(), 'history': [r.to_dict() for r in opt.history]})
    warm = build_electrothermal_payload('warm_start_electrothermal', prepared=p, history=old)
    assert 'history_evidence' not in warm and all('signed_residuals' not in r for r in warm['history'])
    with pytest.raises(ValueError, match='frozen'):
        build_electrothermal_payload('region_preference_electrothermal', prepared=p,
            history=opt.history, context=context)
    future = opt.history[-1]
    partial = replace(future, complete_pair_valid=False, objectives=None,
        objective_components={'F_U': future.objective_components['F_U'], 'F_T': None},
        rates=tuple(replace(row, cell_temperature=replace(row.cell_temperature, valid=False,
            predicted=None, rmse_k=None, reason='solver_error')) for row in future.rates))
    with pytest.raises(ValueError, match='frozen'):
        build_electrothermal_payload('region_preference_electrothermal', prepared=p,
            history=[*old, partial], context=context)


def test_legacy_evidence_default_keeps_old_prompt_and_no_extra_fields(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    p, opt = make_context(tmp_path, 'legacy_v1')
    history = [r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    payload = build_electrothermal_payload('region_preference_electrothermal', prepared=p, history=history, context=opt.last_context)
    assert 'history_evidence' not in payload and all('signed_residuals' not in r for r in payload['history'])
    assert payload['instructions'] == (Path(__file__).parents[1] / 'src/llmbo_para/prompts/region_preference_fair_electrothermal.txt').read_text()


@pytest.mark.parametrize('damage', ['none', 'sign', 'unit', 'evidence_policy'])
def test_audit_recomputes_signed_evidence_and_rejects_tampering(tmp_path, damage):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from test_region_failure_audit import _shared_initialization
    cfg = _shared_initialization(tmp_path); cfg['optimization'].update(mode='full_llmbo_mo', region_evidence='signed_residual_v1',
        region_advice='candidate_aware_v1', region_selection='fair_region_v1')
    # Wide fixture guards only force the advice branch; these are not the research defaults.
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100., min_sigma_ratio=0.)
    class Advice:
        def post(self, payload):
            assert payload['history_evidence']['version'] == 'signed_residual_v1'
            return {k: payload[k] for k in ('schema_version', 'parameter_profile', 'fit_rates', 'signatures', 'context_id')} | {
                'region': {'kind': 'none', 'coordinate_space': 'normalized', 'confidence': .5, 'reason': 'offline fixture'}}
    result = run_electrothermal_experiment(cfg, tmp_path, base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(transport=Advice(), is_mock=True))
    root = Path(result['run_directory'])
    assert audit_electrothermal_run(root, deep=True)['passed']
    path = next((root/'llm').glob('*.payload.json')); payload = json.loads(path.read_text())
    if damage == 'none': return
    row = payload['history'][0]['signed_residuals'][cfg['fit_rates'][0]]['temperature']
    if damage == 'sign': row['signed_mean'] *= -1.
    elif damage == 'unit': row['unit'] = 'degC'
    else: payload['history_evidence']['sign_convention'] = 'observation_minus_prediction'
    path.write_text(json.dumps(payload))
    assert not audit_electrothermal_run(root, deep=True)['passed']
