from copy import deepcopy
from dataclasses import replace
import json

import pytest

from lgbo_fixtures import lgbo_config, prepared_request, region_action


def test_new_policy_has_direct_geometry_and_frozen_dynamic_evidence(tmp_path):
    prepared, rows, context, payload = prepared_request(tmp_path)
    assert payload['region_method'] == 'lgbo_v1'
    assert payload['context']['weights'] == [.8, .2]
    assert payload['context']['objective_scales'] == [.1, 1.]
    assert payload['context_id'] == context.context_id
    assert payload['fit_rates'] == ['0.5C', '1C']
    assert 200 <= len(payload['instructions'].split()) <= 300
    assert all(row['dynamic_residuals'] for row in payload['history'])
    assert not {'candidate_advice', 'region_catalog', 'decision_evidence',
                'proposal_binding', 'region_requirements'} & set(payload)
    assert {row['evaluation_id'] for row in payload['history']} == {r.evaluation_id for r in rows}


@pytest.mark.parametrize('key,value', [
    ('region', {'min_confidence': .6}), ('region_advice', 'legacy_v1'),
    ('region_selection', 'global_lift_v1'), ('region_evidence', 'legacy_v1'),
    ('region_proposal', 'bounds_v1'), ('wire', 'full_v1'),
    ('region_method', None), ('region_method', True), ('region_method', 'unknown'),
])
def test_new_method_rejects_conflicting_or_unknown_policy_settings(tmp_path, key, value):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = lgbo_config()
    if key == 'wire': cfg['llm']['region_wire_format'] = value
    else: cfg['optimization'][key] = value
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert prepared is None and not report['ready']


@pytest.mark.parametrize('kind', ['region', 'none'])
def test_direct_wire_round_trip_requires_only_bound_action(tmp_path, kind):
    from llmbo_para.electrothermal_region_wire import region_wire_payload, decode_region_wire
    _, _, context, payload = prepared_request(tmp_path)
    before = deepcopy(payload)
    wire = region_wire_payload(payload)
    reply = region_action(payload, kind=kind)
    result = decode_region_wire(reply, payload)
    assert set(wire['response_contract']['required']) == {'request_id', 'region'}
    assert 'signatures' not in wire
    assert result['region_method'] == 'lgbo_v1'
    assert result['context_id'] == context.context_id
    assert result['region'] == reply['region']
    assert payload == before
    result['fit_rates'].append('changed')
    assert payload == before


@pytest.mark.parametrize('damage', ['binding', 'extra', 'reason', 'boolean', 'nan',
                                  'reversed', 'outside', 'dimension', 'confidence'])
def test_malformed_action_is_rejected_without_repair(tmp_path, damage):
    from llmbo_para.electrothermal_region_wire import decode_region_wire
    _, _, _, payload = prepared_request(tmp_path)
    reply = region_action(payload)
    if damage == 'binding': reply['request_id'] = 'old'
    elif damage == 'extra': reply['schema_version'] = 2
    elif damage == 'reason': reply['region']['reason'] = 'unrequested'
    elif damage == 'boolean': reply['region']['lb'][0] = True
    elif damage == 'nan': reply['region']['confidence'] = float('nan')
    elif damage == 'reversed': reply['region']['lb'][0] = .9
    elif damage == 'outside': reply['region']['ub'][0] = 1.1
    elif damage == 'dimension': reply['region']['lb'].pop()
    elif damage == 'confidence': reply['region']['confidence'] = '0.8'
    with pytest.raises(ValueError):
        decode_region_wire(reply, payload)


@pytest.mark.parametrize('field', ['weights', 'scales', 'prompt', 'history', 'rates', 'parameters'])
def test_reply_binding_covers_all_scientific_context(tmp_path, field):
    from llmbo_para.electrothermal_region_wire import decode_region_wire
    _, _, _, payload = prepared_request(tmp_path)
    reply = region_action(payload)
    altered = deepcopy(payload)
    if field == 'weights': altered['context']['weights'] = [.2, .8]
    elif field == 'scales': altered['objective_scales'][0] = .2
    elif field == 'prompt': altered['instructions'] += ' altered'
    elif field == 'history': altered['history'][0]['objectives'] = [0., 0.]
    elif field == 'rates': altered['fit_rates'].append('2C')
    elif field == 'parameters': altered['parameters'][4]['unit'] = 'wrong'
    with pytest.raises(ValueError):
        decode_region_wire(reply, altered)


def test_small_and_zero_confidence_are_valid_actions(tmp_path):
    from llmbo_para.electrothermal_region_wire import decode_region_wire
    _, _, _, payload = prepared_request(tmp_path)
    for c in (0., .1, 1.):
        assert decode_region_wire(region_action(payload, confidence=c), payload)['region']['confidence'] == c


def test_warmstart_keeps_its_existing_contract_and_wire(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    prepared, _, _, _ = prepared_request(tmp_path)
    payload = build_electrothermal_payload('warm_start_electrothermal', prepared=prepared, history=[])
    assert 'region_method' not in payload
    assert 'candidates' in payload['response_contract']['required']
    assert region_wire_payload(payload) == payload


def test_controller_freezes_request_decodes_direct_mock_and_rejects_mutation(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    prepared, rows, context, _ = prepared_request(tmp_path)
    for mutate in (False, True):
        class Transport:
            def post(self, payload):
                answer = region_action(payload)
                if mutate: payload['context']['weights'][0] = .123
                return answer
        store = ElectrothermalRunStore(tmp_path, prepared.config, dataset=prepared.dataset,
                                       signatures=prepared.signatures, command='LGBO wire test')
        controller = ElectrothermalLLMController(transport=Transport(), is_mock=True)
        result = controller.request_region(prepared, rows, context, store)
        assert (result is None) == mutate
        assert controller.last_request_outcome['status'] == ('failed' if mutate else 'received')
        assert store.ledger.summary()['llm_requests'] == 0


def test_future_history_is_not_sent_in_a_frozen_request(tmp_path):
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    prepared, rows, context, _ = prepared_request(tmp_path)
    future = replace(rows[0], evaluation_id='not-in-context')
    with pytest.raises(ValueError):
        build_electrothermal_payload('region_preference_electrothermal',
            prepared=prepared, history=[*rows, future], context=context)


def test_native_decoded_action_survives_controller_validation(tmp_path, monkeypatch):
    """Controller seam only; full production workers are exercised in Task3."""
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_requests import BoundedChatCompletionsTransport
    from llmbo_para.electrothermal_lgbo_wire import decode_lgbo_action
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    prepared, rows, context, _ = prepared_request(tmp_path)
    def completed(self, payload, *, deadline=None):
        self.last_request_diagnostic = {'http_request_started': False,
                                       'effective_timeout_s': self.timeout_s}
        return decode_lgbo_action(region_action(payload), payload)
    monkeypatch.setattr(BoundedChatCompletionsTransport, 'post', completed)
    client = BoundedChatCompletionsTransport('https://provider.invalid/v1/chat/completions',
        'OFFLINE_LGBO_FIXTURE', model='offline', max_tokens=2048, timeout_s=30., json_mode=True)
    store = ElectrothermalRunStore(tmp_path, prepared.config, dataset=prepared.dataset,
                                   signatures=prepared.signatures, command='native controller seam')
    controller = ElectrothermalLLMController(transport=client, is_mock=True)
    result = controller.request_region(prepared, rows, context, store)
    assert result is not None, controller.last_request_outcome
    assert result['region_method'] == 'lgbo_v1'
    assert controller.last_request_outcome['status'] == 'received'


@pytest.mark.parametrize('damage',['version','component','prompt'])
def test_v2_action_binds_version_explanation_and_prompt(tmp_path,damage):
    from test_lgbo_weighted_context import v2_request
    _,_,_,payload=v2_request(tmp_path)
    from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id,decode_lgbo_action,WIRE_VERSION
    from llmbo_para.electrothermal_region_wire import region_wire_payload,decode_region_wire
    assert WIRE_VERSION=='lgbo_action_v1'
    reply={'request_id':lgbo_request_id(payload),'region':{'kind':'none'}}
    wire=region_wire_payload(payload)
    assert set(wire['response_contract']['properties'])=={'request_id','region'}
    canonical=decode_region_wire(reply,payload)
    assert canonical['region_method']=='lgbo_v2' and canonical['region']=={'kind':'none'}
    changed=deepcopy(payload)
    if damage=='version':changed['region_method']='lgbo_v1'
    elif damage=='component':changed['history'][0]['weighted_objective_evidence']['weighted_components'][0]+=.01
    else:changed['instructions']+=' altered'
    with pytest.raises(ValueError):decode_lgbo_action(reply,changed)
