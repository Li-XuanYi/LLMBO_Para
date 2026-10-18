"""Compact Region history must preserve the current scalarization's evidence."""
from dataclasses import asdict, replace
from types import SimpleNamespace
import math

import pytest


def _payload_fixture(tmp_path, *, partial=False, midpoint_incumbent=False):
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.runstore import canonical_json, digest_value

    _, prepared = prepare_electrothermal_experiment(et_config(), base_dir=tmp_path)
    evaluator = ElectrothermalEvaluator(
        prepared.space, SyntheticElectrothermalSimulator(),
        fit_rates=prepared.dataset.fit_rates,
    )
    base = evaluator.evaluate(prepared.space.denormalize([.5] * 6), prepared.dataset)
    # Only the objective pairs are constructed for deterministic history ranking;
    # these records are never submitted as audited physical observations.
    history = []
    for i in range(26):
        # A unique crossing at i=12 avoids a mathematically tied adjacent
        # incumbent whose binary rounding could choose hist013 instead.
        objectives = (.001 * (i + 1), .01 * (25 - i))
        theta = prepared.space.denormalize([(i + 1) / 27] * 6)
        if midpoint_incumbent and i == 12:
            theta = (.5, .475, math.sqrt(1e-15 * 1e-12),
                     math.sqrt(1e-15 * 1e-12), 40., math.sqrt(.02 * .3))
        history.append(replace(
            base, evaluation_id=f'hist{i:03d}', parameters=theta,
            objectives=objectives,
            objective_components={'F_U': objectives[0], 'F_T': objectives[1]},
        ))
    scalar = build_scalarization_context(
        [prepared.space.normalize(r.parameters) for r in history],
        [r.objectives for r in history], [r.evaluation_id for r in history],
        weights=[.5, .5], objective_scales=[.1, 1.], rho_aug=.05,
        protocol_signature=prepared.signatures.comparison_protocol,
    )
    assert scalar.incumbent_id == 'hist012'
    if partial:
        rates = tuple(replace(
            rate,
            cell_temperature=replace(
                rate.cell_temperature, valid=False, rmse_k=None,
                predicted=None, reason='synthetic diagnostic missing temperature',
            ),
        ) for rate in base.rates)
        history.append(replace(
            base, evaluation_id='partial026', rates=rates,
            complete_pair_valid=False, objectives=None,
            objective_components={'F_U': base.objective_components['F_U'], 'F_T': None},
        ))
    context = SimpleNamespace(
        scalarization=scalar,
        context_id=digest_value(scalar.to_dict()),
        signatures_json=canonical_json(asdict(prepared.signatures)).decode(),
    )
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    payload = build_electrothermal_payload(
        'region_preference_electrothermal', prepared=prepared,
        history=history, context=context,
    )
    return prepared, history, context, payload


def test_region_compact_history_keeps_current_incumbent_parameters(tmp_path):
    prepared, history, context, payload = _payload_fixture(tmp_path)
    rows = payload['history']
    ids = [row['evaluation_id'] for row in rows]
    # The incumbent is deliberately outside old first-8 Pareto + recent-8 rows.
    assert 'hist012' in ids
    assert ids[0] == context.scalarization.incumbent_id
    assert len(rows) <= 9
    scalar = context.scalarization
    top = sorted(range(26), key=lambda i: (scalar.raw_labels[i], scalar.observation_ids[i]))[:4]
    expected = list(dict.fromkeys([
        *(history[i].evaluation_id for i in top),
        min(history, key=lambda r: (r.objectives[0], r.evaluation_id)).evaluation_id,
        min(history, key=lambda r: (r.objectives[1], r.evaluation_id)).evaluation_id,
        *(r.evaluation_id for r in history[-3:]),
    ]))
    assert ids == expected
    incumbent = next(row for row in rows if row['evaluation_id'] == scalar.incumbent_id)
    assert incumbent['parameters'] == list(history[scalar.incumbent_index].parameters)
    assert incumbent['objectives'] == history[scalar.incumbent_index].objectives
    assert payload['context']['history_count'] == 26
    assert isinstance(payload['context']['history_digest'], str)
    assert len(payload['context']['history_digest']) == 64
    assert 'history_ids' not in payload['context']
    assert payload['context']['weights'] == [.5, .5]
    assert payload['context']['objective_scales'] == [.1, 1.]
    assert payload['context_id'] == context.context_id and payload['pareto']


def test_region_history_coordinates_follow_linear_and_log10_transforms(tmp_path):
    prepared, history, context, payload = _payload_fixture(tmp_path, midpoint_incumbent=True)
    rows = payload['history']
    assert all('normalized_parameters' in row for row in rows)
    original = {record.evaluation_id: record for record in history}
    for row in rows:
        assert row['normalized_parameters'] == pytest.approx(
            prepared.space.normalize(original[row['evaluation_id']].parameters),
            abs=5.1e-7,
        )
        assert len(row['normalized_parameters']) == 6
    incumbent = next(row for row in rows if row['evaluation_id'] == context.scalarization.incumbent_id)
    # C_th=40 is the logarithmic midpoint of [20,80], and sqrt(.006) likewise
    # for G_th=[.02,.3]. Linear thermal normalization would be observably wrong.
    assert incumbent['normalized_parameters'] == pytest.approx([.5] * 6, abs=5.1e-7)


def test_region_current_scalar_values_preserve_partial_diagnostics(tmp_path):
    _, history, context, payload = _payload_fixture(tmp_path, partial=True)
    scalar_by_id = dict(zip(context.scalarization.observation_ids, context.scalarization.raw_labels))
    original = {record.evaluation_id: record for record in history}
    for row in payload['history']:
        record = original[row['evaluation_id']]
        assert 'objective_components' not in row
        assert row['parameters'] == list(record.parameters)
        assert row['complete_pair_valid'] is record.complete_pair_valid
        assert row['rates']
        assert 'current_scalar_g' in row
        if record.complete_pair_valid:
            assert row['current_scalar_g'] == pytest.approx(scalar_by_id[record.evaluation_id])
        else:
            assert row['current_scalar_g'] is None
    partial_row = next(row for row in payload['history'] if row['evaluation_id'] == 'partial026')
    assert partial_row['objectives'] is None
    assert all(not rate['temperature_valid'] and rate['rmse_k'] is None
               for rate in partial_row['rates'].values())
