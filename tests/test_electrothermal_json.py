"""Shared JSON behavior pinned independently of compatibility wrappers."""
from copy import deepcopy
import importlib
import importlib.util
import json

import numpy as np
import pytest


def feature():
    name = 'llmbo_para.electrothermal_json'
    assert importlib.util.find_spec(name) is not None, 'common electrothermal JSON tools are missing'
    return importlib.import_module(name)


@pytest.mark.parametrize('value, expected', [
    ({'x': [None, True, 1, 1., 's', {'y': []}]}, True),
    (float('nan'), True), (float('inf'), True),
    (np.array([1.]), False), (np.float64(1.), False), (np.int64(1), False),
    ((1, 2), False), ({1: 'x'}, False), ({'x': [np.bool_(True)]}, False)])
def test_native_type_boundary_is_structural(value, expected):
    assert feature().is_json_native(value) is expected


def test_archival_json_preserves_diagnostic_and_redaction():
    module = feature()
    assert module.archival_json({'secret': 'fixture-only'}) == '{"secret": "[REDACTED]"}'
    assert module.archival_json({'x': float('nan')}) == '{"x": NaN}'
    assert module.archival_json({'x': float('inf')}) == '{"x": Infinity}'
    assert module.archival_json({'x': (1, 2)}) == '{"x": {"__rejected_python_type__": "tuple"}}'
    assert module.archival_json({1: 'x'}) == '{"__rejected_python_type__": "non_string_object_key"}'
    assert not module.is_json_native(np.array([1.]))


def test_redacted_keys_retain_length_values_and_uniqueness():
    module = feature()
    first, second = 'sk-' + 'x' * 8, 'sk-' + 'y' * 8
    data = {first: 'a', second: 'b', '*' * 11: 'reserved', 'nested': [first]}
    actual = json.loads(module.archival_json(data))
    assert actual == {'*' * 11: 'reserved', '*' * 9 + '~1': 'a',
                      '*' * 9 + '~2': 'b', 'nested': ['*' * 11]}
    assert len(actual) == 4
    assert data[first] == 'a'


def test_compatibility_wrappers_preserve_bytes_and_native_rules():
    module = feature()
    from llmbo_para.electrothermal_region_catalog import catalog_archival_json, catalog_reply_is_json_native
    from llmbo_para.electrothermal_lgbo import _native
    for value in ({'x': [1, None]}, {'x': float('nan')}, {'secret': 'fixture'}, {'x': (1, 2)}):
        assert catalog_archival_json(value) == module.archival_json(value)
        assert catalog_reply_is_json_native(value) is module.is_json_native(value)
        assert _native(value) is module.is_json_native(value)


def request_and_action():
    from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id
    payload = {'task': 'region_preference_electrothermal', 'schema_version': 2,
        'parameter_profile': 'electrothermal_4e2t', 'fit_rates': ['0.5C', '1C'],
        'signatures': {'source': 'fixture', 'fit_rates': ['0.5C', '1C']},
        'context_id': 'frozen-round', 'region_method': 'lgbo_v1'}
    return payload, {'request_id': lgbo_request_id(payload), 'region': {'kind': 'none'}}


def archived(protocol, text):
    if protocol == 'openai_chat_completions':
        return {'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]}
    return {'status': 'completed', 'error': None, 'incomplete_details': None,
        'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                    'content': [{'type': 'output_text', 'text': text}]}]}


@pytest.mark.parametrize('protocol', ['openai_chat_completions', 'openai_responses'])
@pytest.mark.parametrize('kind, issue', [('valid', None), ('truncated', 'unfinished_completion'),
    ('empty', 'empty_content'), ('bad_json', 'invalid_json'), ('binding', 'invalid_binding'),
    ('non_object', 'non_object_content')])
def test_archived_completion_and_wire_boundaries(protocol, kind, issue):
    module = feature()
    payload, action = request_and_action()
    original = deepcopy(payload)
    if kind == 'binding':
        action['request_id'] = 'wrong-binding'
    text = '' if kind == 'empty' else '{' if kind == 'bad_json' else '[]' if kind == 'non_object' else json.dumps(action)
    value = archived(protocol, text)
    if kind == 'truncated':
        if protocol == 'openai_responses':
            value['status'] = 'incomplete'
        else:
            value['choices'][0]['finish_reason'] = 'length'
    decoded, actual_issue = module.decode_archived_http_response(value, payload=payload, transport=protocol)
    assert actual_issue == issue
    if issue is None:
        assert decoded == {**{k: v for k, v in payload.items() if k != 'task'}, 'region': {'kind': 'none'}}
    else:
        assert decoded is None
    assert payload == original
    from llmbo_para.electrothermal_region_catalog import decode_catalog_http_response
    assert decode_catalog_http_response(value, payload=payload, transport=protocol) == (decoded, actual_issue)


def test_unknown_transport_preserves_exception():
    with pytest.raises(ValueError, match='^unknown catalog HTTP protocol$'):
        feature().decode_archived_http_response({}, payload={}, transport='unknown')


def test_archived_nan_is_not_a_valid_lgbo_action():
    module = feature()
    payload, action = request_and_action()
    action['region'] = {'kind': 'region', 'lb': [float('nan')] * 6, 'ub': [.8] * 6, 'confidence': .5}
    diagnostic = module.archival_json(action)
    assert 'NaN' in diagnostic
    assert module.decode_archived_http_response(archived('openai_chat_completions', diagnostic),
        payload=payload) == (None, 'invalid_binding')
