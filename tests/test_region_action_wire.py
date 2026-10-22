"""Action data remains strict while unused rationale cannot veto it."""
from copy import deepcopy
from types import SimpleNamespace
import json

import pytest

from test_region_catalog import payload, reply, config
from llmbo_para.electrothermal_region_catalog import (
    catalog_proposal_binding, catalog_region_contract, resolve_catalog_region,
)
from llmbo_para.electrothermal_region_wire import region_wire_payload, decode_region_wire
from llmbo_para.runstore import digest_value, canonical_json


MODE = 'compact_action_v2'


def action_payload():
    value = payload()
    value['region_wire_format'] = MODE
    value['proposal_binding'] = catalog_proposal_binding(value)
    value['response_contract']['properties']['region'] = catalog_region_contract(value)
    return value


def action_reply(value, kind='region'):
    region = reply(value, kind)['region']
    region.pop('reason')
    return {'request_id': region_wire_payload(value)['request_id'], 'region': region}


@pytest.mark.parametrize('kind', ['region', 'none'])
def test_action_reply_without_explanation_resolves(kind):
    value = action_payload()
    sent = region_wire_payload(value)
    result = action_reply(value, kind)
    before = canonical_json([value, result])
    canonical, resolution = resolve_catalog_region(decode_region_wire(result, value), payload=value)
    assert canonical['region']['kind'] == kind
    assert canonical['region']['reason'] == 'structured_catalog_response'
    assert resolution['kind'] == kind
    assert canonical_json([value, result]) == before
    for branch in sent['response_contract']['properties']['region']['oneOf']:
        assert 'reason' not in branch['required']
        assert branch['properties']['reason'] == {}


@pytest.mark.parametrize('metadata', [None, True, 42, [], {}, {'old': 'comment'}, 'short', 'x'*417, 'x'*10000])
def test_incidental_reason_is_ignored_without_changing_the_action(metadata):
    value = action_payload()
    plain = action_reply(value)
    verbose = deepcopy(plain)
    verbose['region']['reason'] = metadata
    before = canonical_json(verbose)
    actual = resolve_catalog_region(decode_region_wire(verbose, value), payload=value)
    expected = resolve_catalog_region(decode_region_wire(plain, value), payload=value)
    assert canonical_json(actual) == canonical_json(expected)
    assert canonical_json(verbose) == before


@pytest.mark.parametrize('metadata', [float('nan'), float('inf'), ('not', 'JSON'), {1: 'nonstring key'}])
def test_ignored_metadata_cannot_launder_nonfinite_or_non_json_values(metadata):
    value = action_payload()
    result = action_reply(value)
    result['region']['reason'] = metadata
    with pytest.raises(ValueError):
        decode_region_wire(result, value)


@pytest.mark.parametrize('damage', ['missing_confidence', 'bool_confidence', 'nan_confidence',
    'string_confidence', 'bad_binding', 'bad_ID', 'bad_evidence', 'tuple_evidence',
    'extra_bounds', 'extra_field', 'bad_space', 'null_region', 'list_region', 'bool_region'])
def test_action_validation_still_rejects_corrupt_operational_fields(damage):
    value = action_payload()
    result = action_reply(value)
    region = result['region']
    if damage == 'missing_confidence': region.pop('confidence')
    elif damage == 'bool_confidence': region['confidence'] = True
    elif damage == 'nan_confidence': region['confidence'] = float('nan')
    elif damage == 'string_confidence': region['confidence'] = '0.9'
    elif damage == 'bad_binding': region['proposal_binding'] = 'wrong'
    elif damage == 'bad_ID': region['region_id'] = 'not-in-the-catalog'
    elif damage == 'bad_evidence': region['evidence_ids'] = ['future-record']
    elif damage == 'tuple_evidence': region['evidence_ids'] = ('past-a',)
    elif damage == 'extra_bounds': region['lb'] = [0.]*6
    elif damage == 'extra_field': region['decision_override'] = 'accept'
    elif damage == 'bad_space': region['coordinate_space'] = 'physical'
    else: result['region'] = {'null_region': None, 'list_region': [], 'bool_region': True}[damage]
    with pytest.raises(ValueError):
        resolve_catalog_region(decode_region_wire(result, value), payload=value)


@pytest.mark.parametrize('change', ['weights', 'scales', 'instructions', 'history', 'old_wire'])
def test_action_reply_cannot_be_replayed_into_another_frozen_request(change):
    value = action_payload()
    result = action_reply(value)
    altered = deepcopy(value)
    if change == 'weights': altered['context']['weights'] = [.8, .2]
    elif change == 'scales': altered['objective_scales'] = [100., 1.]
    elif change == 'instructions': altered['instructions'] += ' Changed task.'
    elif change == 'history': altered['history'][0]['evaluation_id'] = 'other'
    else: altered['region_wire_format'] = 'compact_v1'
    with pytest.raises(ValueError):
        decode_region_wire(result, altered)


@pytest.mark.parametrize('reason', [None, 'x'*417])
def test_old_compact_catalog_keeps_its_strict_reason_contract(reason):
    value = payload(wire='compact_v1')
    region = reply(value)['region']
    if reason is None: region.pop('reason')
    else: region['reason'] = reason
    response = {'request_id': region_wire_payload(value)['request_id'], 'region': region}
    with pytest.raises(ValueError):
        resolve_catalog_region(decode_region_wire(response, value), payload=value)


@pytest.mark.parametrize('mode,expected', [
    ('full_v1', '7e042560150ab4ef3bbdab980debf61d4602af1128ff5ae25af4819bfa5cce57'),
    ('compact_v1', '3f9313405f6ab97738c10212d0ed00b60019070500c2b5e5558f186fb1a0a6c4')])
def test_existing_wire_bytes_match_the_preimplementation_baseline(mode, expected):
    assert digest_value(region_wire_payload(payload(wire=mode))) == expected


def test_action_configuration_requires_catalog_and_has_distinct_algorithm_identity(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = config()
    cfg['llm']['region_wire_format'] = MODE
    report, new = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert new is not None, report['errors']
    cfg['llm']['region_wire_format'] = 'compact_v1'
    _, old = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert new.signatures.algorithm != old.signatures.algorithm
    assert new.signatures.comparison_protocol == old.signatures.comparison_protocol
    assert new.signatures.initialization_compatibility == old.signatures.initialization_compatibility
    cfg['llm']['region_wire_format'] = MODE
    cfg['optimization']['region_proposal'] = 'bounds_v1'
    report, invalid = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert invalid is None and report['errors']


def test_action_wire_refuses_direct_use_without_a_catalog():
    value = action_payload()
    value['region_proposal'] = 'bounds_v1'
    with pytest.raises(ValueError): region_wire_payload(value)


def test_region_action_mode_does_not_change_warmstart_payload(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    cfg = config()
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    old = build_electrothermal_payload('warm_start_electrothermal', prepared=prepared, history=[])
    cfg = deepcopy(prepared.config)
    cfg['llm']['region_wire_format'] = MODE
    p = SimpleNamespace(config=cfg, space=prepared.space, dataset=prepared.dataset, signatures=prepared.signatures)
    new = build_electrothermal_payload('warm_start_electrothermal', prepared=p, history=[])
    assert canonical_json(new) == canonical_json(old)
    assert region_wire_payload(new) == new


def test_action_chat_request_keeps_compact_input_encoding():
    from llmbo_para.llm import ChatCompletionsTransport
    class Capture(ChatCompletionsTransport):
        def _post_json(self, body, *, task):
            self.body = body
            return {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    value = action_payload()
    sent = region_wire_payload(value)
    client = Capture('https://provider.invalid/v1/chat/completions', 'UNUSED', model='test', max_tokens=8192, json_mode=True)
    client.post(sent)
    assert client.body['messages'][1]['content'] == json.dumps(
        {k:v for k,v in sent.items() if k != 'instructions'}, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def test_real_payload_selects_action_prompt_and_binds_the_mode(tmp_path_factory):
    from test_region_signed_residuals import make_context
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    p, opt = make_context(tmp_path_factory.mktemp('ap'), 'dynamic_decision_v3')
    cfg = deepcopy(p.config)
    cfg['optimization']['region_proposal'] = 'catalog_v1'
    cfg['llm']['region_wire_format'] = MODE
    prepared = SimpleNamespace(config=cfg, space=p.space, dataset=p.dataset, signatures=p.signatures)
    past = [r for r in opt.history if r.evaluation_id in opt.last_context.scalarization.observation_ids]
    value = build_electrothermal_payload('region_preference_electrothermal', prepared=prepared, history=past, context=opt.last_context)
    assert value['region_wire_format'] == MODE
    assert value['proposal_binding'] == catalog_proposal_binding(value)
    assert 200 <= len(value['instructions'].split()) <= 300
    assert 'Do not provide explanations' in value['instructions']
    assert 'reason' not in region_wire_payload(value)['response_contract']['properties']['region']['oneOf'][0]['required']
