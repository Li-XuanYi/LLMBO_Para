"""Task-specific electrothermal requests sharing scientific metadata, not policy."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

from .electrothermal_lgbo import is_lgbo_method, lgbo_prompt_filename
from .pareto import pareto_indices
from .runstore import digest_value


def _observations(history) -> tuple[list, list]:
    valid = [record for record in history if record.complete_pair_valid]
    front = [valid[index] for index in pareto_indices([record.objectives for record in valid])]
    return valid, front


def _history_rows(records) -> list[dict]:
    return [{'evaluation_id': record.evaluation_id, 'parameters': list(record.parameters),
        'objectives': record.objectives, 'complete_pair_valid': record.complete_pair_valid,
        'objective_components': record.objective_components,
        'rates': {row.rate: {'voltage_valid': row.voltage.valid,
            'temperature_valid': row.cell_temperature.valid, 'rmse_v': row.voltage.rmse_v,
            'rmse_k': row.cell_temperature.rmse_k,
            'failure': row.cell_temperature.reason or row.voltage.reason} for row in record.rates}}
        for record in records]


def _base_payload(task: str, prepared, rows: list[dict], front: list, prompt_name: str) -> dict:
    cfg = prepared.config
    return {'task': task, 'schema_version': 2, 'parameter_profile': prepared.space.profile,
        'fit_rates': list(prepared.dataset.fit_rates), 'signatures': asdict(prepared.signatures),
        'parameters': [{'name': spec.name, 'unit': spec.unit, 'lower': spec.lower,
            'upper': spec.upper, 'transform': spec.transform} for spec in prepared.space.specs],
        'fixed': cfg['fixed'], 'property_law': cfg['property_law'],
        'conditions_by_rate': cfg['conditions_by_rate'],
        'objective_scales': cfg['optimization']['objective_scales'], 'objective_order': ['F_U_V', 'F_T_K'],
        'history': rows, 'pareto': [{'evaluation_id': record.evaluation_id, 'objectives': record.objectives}
                                   for record in front],
        'instructions': (Path(__file__).parent / 'prompts' / (prompt_name + '.txt')).read_text(encoding='utf8')}


def _identity_properties(prepared) -> dict:
    return {key: {'const': value} for key, value in (
        ('schema_version', 2), ('parameter_profile', prepared.space.profile),
        ('fit_rates', list(prepared.dataset.fit_rates)),
        ('signatures', json.loads(json.dumps(asdict(prepared.signatures)))))}


def _attach_context(payload: dict, context, *, region: bool) -> None:
    scalar = context.scalarization
    payload['context_id'] = context.context_id
    payload['context'] = {'weights': list(scalar.weights), 'objective_scales': list(scalar.objective_scales),
        'ideal': list(scalar.ideal), 'rho_aug': scalar.rho_aug, 'mean': scalar.mean, 'std': scalar.std,
        'incumbent_id': scalar.incumbent_id, 'best': scalar.best, 'history_ids': list(scalar.observation_ids),
        'current_scalar_top': [{'evaluation_id': scalar.observation_ids[index], 'g': scalar.raw_labels[index]}
            for index in sorted(range(len(scalar.y)),
                key=lambda index: (scalar.raw_labels[index], scalar.observation_ids[index]))[:8]]}
    if region:
        payload['context'].pop('history_ids')
        payload['context'].update(history_count=len(scalar.observation_ids),
                                  history_digest=digest_value(list(scalar.observation_ids)))
        payload['context']['current_scalar_top'] = payload['context']['current_scalar_top'][:4]


def _finish(payload: dict, prepared, properties: dict) -> dict:
    def summary(signal) -> dict:
        return {'first': signal.values[0], 'last': signal.values[-1], 'minimum': min(signal.values),
            'maximum': max(signal.values), 'sample_count': len(signal.values),
            'time_span_s': [signal.time_s[0], signal.time_s[-1]], 'unit': signal.unit}

    payload['simulation_kind'] = prepared.config['run_kind']
    payload['model_provider'] = prepared.config['model']['provider']
    payload['case_summaries'] = {rate: {'current_A': summary(case.current_a),
        'ambient_temperature_K': summary(case.ambient_temperature_k),
        'initial_temperature_K': case.initial_state['temperature_k'],
        'voltage_target_V': summary(case.voltage), 'temperature_target_K': summary(case.cell_temperature_k),
        'cooling_group_id': case.cooling_group_id} for rate, case in prepared.dataset.cases.items()}
    payload['response_contract'] = {'type': 'object', 'additionalProperties': False,
                                   'required': list(properties), 'properties': properties}
    return payload


def build_warmstart_payload(*, prepared, history) -> dict:
    """Build candidate semantics; host evaluation/Pareto/diversity selection stays separate."""
    valid, front = _observations(history)
    selected = {record.evaluation_id: record for record in [*front[:8], *history[-8:]]}
    payload = _base_payload('warm_start_electrothermal', prepared, _history_rows(selected.values()),
                            front, 'warm_start_electrothermal')
    properties = _identity_properties(prepared)
    names = [spec.name for spec in prepared.space.specs]
    parameters = {'type': 'object', 'additionalProperties': False, 'required': names,
        'properties': {spec.name: {'type': 'number', 'minimum': spec.lower, 'maximum': spec.upper}
                       for spec in prepared.space.specs}}
    properties['candidates'] = {'type': 'array', 'minItems': 1,
        'maxItems': prepared.config['optimization']['warmstart']['max_candidates'],
        'items': {'type': 'object', 'additionalProperties': False, 'required': ['parameters'],
                 'properties': {'parameters': parameters}}}
    payload['requested_candidate_count'] = max(0, prepared.config['optimization']['warmstart']['pool_size'] - len(valid))
    return deepcopy(_finish(payload, prepared, properties))


def _regional_payload(prepared, history, context, prompt_name: str, *,
                      lgbo: bool = False, signed: bool = False, dynamic: bool = False) -> dict:
    if context is None:
        raise ValueError('frozen context required for Region request')
    _, front = _observations(history)
    valid = [record for record in history if record.complete_pair_valid]
    scalar = context.scalarization
    if (signed or lgbo) and any(record.evaluation_id not in scalar.observation_ids for record in history):
        raise ValueError('history contains observations outside the frozen context')
    by_id = {record.evaluation_id: record for record in history}
    labels = dict(zip(scalar.observation_ids, scalar.raw_labels))
    top = sorted(scalar.observation_ids, key=lambda ident: (labels[ident], ident))[:4]
    extremes = [min(valid, key=lambda record: (record.objectives[index], record.evaluation_id))
                for index in range(2)] if valid else []
    selected = {record.evaluation_id: record for record in
                [*[by_id[ident] for ident in top], *extremes, *history[-3:]]}
    rows = _history_rows(selected.values())
    for row, record in zip(rows, selected.values()):
        row.pop('objective_components')
        row['normalized_parameters'] = [round(float(value), 6) for value in prepared.space.normalize(row['parameters'])]
        row['current_scalar_g'] = labels.get(row['evaluation_id']) if row['complete_pair_valid'] else None
        if prepared.config['optimization'].get('region_method') == 'lgbo_v2' and row['complete_pair_valid']:
            # Runtime module lookup preserves independent producer fault injection.
            from .electrothermal_region_context import weighted_objective_evidence
            row['weighted_objective_evidence'] = weighted_objective_evidence(row['objectives'],
                weights=scalar.weights, objective_scales=scalar.objective_scales,
                ideal=scalar.ideal, rho_aug=scalar.rho_aug)
        if signed:
            from .electrothermal_residuals import signed_record_summary
            row['signed_residuals'] = signed_record_summary(record)
        if dynamic:
            from .electrothermal_dynamic_evidence import dynamic_record_summary
            row['dynamic_residuals'] = dynamic_record_summary(record)
    payload = _base_payload('region_preference_electrothermal', prepared, rows, front, prompt_name)
    if signed:
        from .electrothermal_residuals import residual_evidence_contract
        payload['history_evidence'] = residual_evidence_contract()
    if dynamic:
        from .electrothermal_dynamic_evidence import dynamic_evidence_contract
        payload['dynamic_history_evidence'] = dynamic_evidence_contract()
    _attach_context(payload, context, region=True)
    return payload


def _coordinate_mapping(prepared) -> dict:
    return {'space': 'normalized', 'order': [spec.name for spec in prepared.space.specs],
        'linear': 'x=(theta-lower)/(upper-lower)',
        'log10': 'x=(log10(theta)-log10(lower))/(log10(upper)-log10(lower))',
        'bounds': 'Use each named parameter definition and its transform; history includes computed normalized coordinates.'}


def build_lgbo_payload(*, prepared, history, context) -> dict:
    """Construct the direct LGBO action contract without constructing legacy policy."""
    from .electrothermal_lgbo_wire import lgbo_region_contract
    method = prepared.config['optimization']['region_method']
    payload = _regional_payload(prepared, history, context,
        lgbo_prompt_filename(method).removesuffix('.txt'), lgbo=True, dynamic=True)
    payload['coordinate_mapping'] = _coordinate_mapping(prepared)
    properties = _identity_properties(prepared)
    properties['context_id'] = {'const': context.context_id}
    properties['region'] = lgbo_region_contract()
    _finish(payload, prepared, properties)
    payload['region_method'] = method
    properties['region_method'] = {'const': method}
    payload['response_contract']['required'] = list(properties)
    return deepcopy(payload)


def build_legacy_region_payload(*, prepared, history, context) -> dict:
    """Retain legacy bounds, candidate-aware and catalog request semantics."""
    cfg = prepared.config
    options = cfg['optimization']
    candidate = options.get('region_advice', 'legacy_v1') == 'candidate_aware_v1'
    evidence = options.get('region_evidence', 'legacy_v1')
    dynamic = evidence == 'dynamic_decision_v3'
    decision = evidence in ('decision_geometry_v2', 'dynamic_decision_v3')
    signed = evidence in ('signed_residual_v1', 'decision_geometry_v2', 'dynamic_decision_v3')
    catalog = options.get('region_proposal', 'bounds_v1') == 'catalog_v1'
    prompt = 'region_preference_candidate_aware_electrothermal' if candidate else 'region_preference_electrothermal'
    if candidate and options.get('region_selection') == 'fair_region_v1':
        prompt = 'region_preference_fair_electrothermal'
    if signed:
        if not candidate or options.get('region_selection') != 'fair_region_v1':
            raise ValueError('signed evidence requires candidate-aware fair selection')
        prompt = 'region_preference_residual_electrothermal'
    if decision:
        prompt = 'region_preference_decision_electrothermal'
    if dynamic:
        prompt = 'region_preference_dynamic_electrothermal'
    if catalog:
        if not dynamic:
            raise ValueError('Region catalog requires dynamic evidence')
        prompt = ('region_preference_action_electrothermal' if cfg['llm'].get('region_wire_format') == 'compact_action_v2'
                  else 'region_preference_catalog_electrothermal')
    payload = _regional_payload(prepared, history, context, prompt, signed=signed, dynamic=dynamic)
    from .informed import InformedSettings
    settings = InformedSettings.parse(options['region'])
    payload['region_requirements'] = {'min_confidence': settings.min_confidence,
                                     'min_width': settings.min_width, 'max_width': settings.max_width}
    if candidate:
        from .electrothermal_region_advice import build_region_candidate_advice, candidate_region_requirements
        payload['candidate_advice'] = build_region_candidate_advice(context, space=prepared.space, settings=settings)
        payload['region_requirements'] = candidate_region_requirements(settings,
            selection_mode=options.get('region_selection', 'global_lift_v1'))
        if decision:
            from .electrothermal_region_evidence import build_region_decision_evidence
            payload['decision_evidence'] = build_region_decision_evidence(context,
                advice=payload['candidate_advice'], settings=settings,
                observation_ids=[row['evaluation_id'] for row in payload['history']])
    payload['coordinate_mapping'] = _coordinate_mapping(prepared)
    properties = _identity_properties(prepared)
    properties['context_id'] = {'const': context.context_id}
    base = {'kind': {'enum': ['region', 'none']}, 'coordinate_space': {'const': 'normalized'},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1}, 'reason': {'type': 'string', 'maxLength': 2000}}
    bounds = {'type': 'array', 'minItems': 6, 'maxItems': 6,
              'items': {'type': 'number', 'minimum': 0, 'maximum': 1}}
    properties['region'] = {'oneOf': [
        {'type': 'object', 'additionalProperties': False, 'required': list(base),
         'properties': {**base, 'kind': {'const': 'none'}}},
        {'type': 'object', 'additionalProperties': False, 'required': [*base, 'lb', 'ub'],
         'properties': {**base, 'kind': {'const': 'region'}, 'lb': bounds, 'ub': bounds}}]}
    _finish(payload, prepared, properties)
    if cfg['llm'].get('region_wire_format', 'full_v1') in ('compact_v1', 'compact_action_v2'):
        payload['region_wire_format'] = cfg['llm']['region_wire_format']
    if catalog:
        from .electrothermal_region_catalog import build_region_catalog, catalog_proposal_binding, catalog_region_contract
        payload['region_proposal'] = 'catalog_v1'
        payload['region_catalog'] = build_region_catalog(context, advice=payload['candidate_advice'], settings=settings)
        payload['proposal_binding'] = catalog_proposal_binding(payload)
        properties['region'] = catalog_region_contract(payload)
    return deepcopy(payload)


def build_electrothermal_payload(task: str, *, prepared, history, context=None) -> dict:
    """Dispatch task semantics while preserving the existing public call boundary."""
    if task == 'warm_start_electrothermal':
        payload = build_warmstart_payload(prepared=prepared, history=history)
        if context is not None:
            _attach_context(payload, context, region=False)
        return payload
    if task != 'region_preference_electrothermal':
        raise ValueError('unknown electrothermal LLM task')
    if is_lgbo_method(prepared.config['optimization'].get('region_method')):
        return build_lgbo_payload(prepared=prepared, history=history, context=context)
    return build_legacy_region_payload(prepared=prepared, history=history, context=context)
