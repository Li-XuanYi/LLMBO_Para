"""Responses protocol tests; mock only the socket-opening boundary."""
from copy import deepcopy
import importlib
import importlib.util
import json
from types import SimpleNamespace

import pytest


def feature():
    name = 'llmbo_para.electrothermal_responses'
    assert importlib.util.find_spec(name) is not None, 'Responses adapter not implemented'
    return importlib.import_module(name)


def response(value=None, **updates):
    content = json.dumps({'answer': 'formal JSON'} if value is None else value)
    return {'status': 'completed', 'error': None, 'incomplete_details': None,
            'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                        'content': [{'type': 'output_text', 'text': content}]}], **updates}


def payload(task='warm_start_electrothermal'):
    return {'task': task, 'instructions': 'Return one formal JSON object.',
            'schema_version': 2, 'parameter_profile': 'electrothermal_4e2t',
            'fit_rates': ['0.5C', '1C'], 'signatures': {'source': 'unit-software-only'},
            'context_id': 'frozen-context', 'response_contract': {'properties': {'region': {'type': 'object'}}}}


@pytest.mark.parametrize('kind', ['warm', 'full', 'compact'])
def test_responses_wire_keeps_binding_and_store_false(kind):
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    from llmbo_para.runstore import digest_value
    p = payload('warm_start_electrothermal' if kind == 'warm' else 'region_preference_electrothermal')
    if kind == 'compact':
        p['region_wire_format'] = 'compact_v1'
    wire = region_wire_payload(p)
    before = digest_value(wire)
    sent = feature().responses_request_body(wire, model='deepseek-v4-pro', max_tokens=1536, json_mode=True)
    assert set(sent) == {'model', 'instructions', 'input', 'max_output_tokens', 'text', 'stream', 'store'}
    assert sent['model'] == 'deepseek-v4-pro' and sent['max_output_tokens'] == 1536
    assert sent['text'] == {'format': {'type': 'json_object'}}
    assert sent['store'] is sent['stream'] is False
    assert sent['instructions'] == wire['instructions'] + '\nReturn exactly one JSON object matching the supplied response contract.'
    assert json.loads(sent['input']) == {k: v for k, v in wire.items() if k != 'instructions'}
    assert digest_value(wire) == before


def test_json_mode_false_does_not_send_a_format_or_change_instructions():
    p = payload()
    sent = feature().responses_request_body(p, model='deepseek-v4-pro', max_tokens=32, json_mode=False)
    assert 'text' not in sent and sent['instructions'] == p['instructions']
    assert sent['store'] is False


def test_completed_final_json_only():
    assert feature().decode_responses_json(response({'answer': 42})) == ({'answer': 42}, None)


def test_reasoning_is_never_formal_answer():
    raw = response({'answer': 42})
    raw['output'].insert(0, {'type': 'reasoning', 'summary': [{'text': '{"wrong":true}'}]})
    assert feature().decode_responses_json(raw) == ({'answer': 42}, None)
    raw['output'].pop()
    assert feature().decode_responses_json(raw)[1] == 'invalid_completion'


@pytest.mark.parametrize('status', ['incomplete', 'failed', 'queued', 'in_progress', 'cancelled'])
def test_noncompleted_response_is_rejected_even_with_valid_json(status):
    assert feature().decode_responses_json(response(status=status))[1] == 'unfinished_completion'


@pytest.mark.parametrize('damage', ['error', 'incomplete_details', 'missing_status', 'unknown_status',
    'refusal', 'extra_message', 'extra_text', 'tool', 'unknown_item', 'wrong_role',
    'message_incomplete', 'missing_output', 'choices_only', 'top_level_text_only', 'non_list_content'])
def test_ambiguous_or_nonformal_output_cannot_be_repaired(damage):
    raw = response()
    message = raw['output'][0]
    if damage in ('error', 'incomplete_details'):
        raw[damage] = {'reason': 'not complete'}
    elif damage == 'missing_status':
        del raw['status']
    elif damage == 'unknown_status':
        raw['status'] = True
    elif damage == 'refusal':
        message['content'] = [{'type': 'refusal', 'refusal': 'refused'}]
    elif damage == 'extra_message':
        raw['output'].append(deepcopy(message))
    elif damage == 'extra_text':
        message['content'].append(deepcopy(message['content'][0]))
    elif damage in ('tool', 'unknown_item'):
        raw['output'].append({'type': 'function_call' if damage == 'tool' else 'future_item'})
    elif damage == 'wrong_role':
        message['role'] = 'user'
    elif damage == 'message_incomplete':
        message['status'] = 'incomplete'
    elif damage == 'non_list_content':
        message['content'] = {'type': 'output_text', 'text': '{}'}
    else:
        del raw['output']
        if damage == 'choices_only':
            raw['choices'] = [{'finish_reason': 'stop', 'message': {'content': '{}'}}]
        elif damage == 'top_level_text_only':
            raw['output_text'] = '{}'
    assert feature().decode_responses_json(raw) == (None, 'invalid_completion')


@pytest.mark.parametrize('text,issue', [(None, 'invalid_content_type'), ([], 'invalid_content_type'),
    (' ', 'empty_content'), ('bad JSON', 'invalid_json'), ('[]', 'non_object_content'),
    ('null', 'non_object_content'), ('{"x":NaN}', 'invalid_json'), ('{"x":Infinity}', 'invalid_json')])
def test_invalid_formal_text_is_rejected(text, issue):
    raw = response()
    raw['output'][0]['content'][0]['text'] = text
    assert feature().decode_responses_json(raw) == (None, issue)


def test_unknown_usage_is_not_zero():
    summary = feature().responses_completion_summary(response(), 1536)
    assert summary['response_status'] == 'completed' and summary['state'] == 'complete_answer'
    assert 'finish_reason' not in summary
    for key in ('input_tokens', 'completion_tokens', 'total_tokens', 'reasoning_tokens'):
        assert key not in summary
    raw = response(usage={'input_tokens': 20, 'output_tokens': 7, 'total_tokens': 27,
                          'output_tokens_details': {'reasoning_tokens': 2}})
    summary = feature().responses_completion_summary(raw, 1536)
    assert [summary[k] for k in ('input_tokens', 'completion_tokens', 'total_tokens', 'reasoning_tokens')] == [20, 7, 27, 2]
    raw['usage'] = {'input_tokens': True, 'output_tokens': -1, 'total_tokens': '27',
                    'output_tokens_details': {'reasoning_tokens': False}}
    assert not any(k in feature().responses_completion_summary(raw, 1536)
                   for k in ('input_tokens', 'completion_tokens', 'total_tokens', 'reasoning_tokens'))


class MemoryArchive:
    def __init__(self, path):
        self.path = path
        self.files, self.events = {}, []
    def write_json(self, name, value):
        self.files[name] = deepcopy(value)
    def append_event(self, value):
        self.events.append(deepcopy(value))


def test_responses_reuses_no_redirect_and_secret_redaction(monkeypatch, tmp_path):
    from llmbo_para.llm import NoRedirect
    raw = response({'reason': 'unit-responses-private-credential'})
    sent, handlers = [], []
    class HTTPResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, count): return json.dumps(raw).encode()[:count]
    class Provider:
        def open(self, request, **kwargs):
            sent.append(request)
            return HTTPResponse()
    def opener(handler):
        handlers.append(handler)
        return Provider()
    monkeypatch.setattr('llmbo_para.llm.build_opener', opener)
    monkeypatch.setenv('RESPONSES_UNIT_KEY', 'unit-responses-private-credential')
    archive = MemoryArchive(tmp_path)
    transport = feature().ResponsesTransport('https://example.invalid/v1/responses', 'RESPONSES_UNIT_KEY',
        model='deepseek-v4-pro', max_tokens=1536, json_mode=True, run_store=archive)
    result = transport.post(payload())
    assert result == {'reason': '[REDACTED]'}
    assert len(sent) == 1 and isinstance(handlers[0], NoRedirect)
    assert handlers[0].redirect_request(None, None, 302, '', {}, 'https://other.invalid') is None
    assert sent[0].get_header('Authorization') == 'Bearer unit-responses-private-credential'
    assert 'unit-responses-private-credential' not in json.dumps(archive.files)
    assert json.loads(sent[0].data)['store'] is False
    assert any(name.endswith('.response.json') for name in archive.files)


@pytest.mark.parametrize('change', [{'model': ''}, {'max_tokens': True}, {'max_tokens': 0},
    {'max_tokens': 8193}, {'json_mode': 1}, {'thinking': 'disabled'},
    {'endpoint': 'https://example.invalid/v1/chat/completions'}, {'endpoint': 'http://example.invalid/v1/responses'}])
def test_invalid_settings_fail_before_network(change):
    settings = {'endpoint': 'https://example.invalid/v1/responses', 'api_key_env': 'RESPONSES_UNIT_KEY',
                'model': 'deepseek-v4-pro', 'max_tokens': 1536, 'json_mode': True, **change}
    with pytest.raises(ValueError):
        feature().ResponsesTransport(**settings)


def test_http_body_limit_is_inherited_without_a_retry(monkeypatch):
    calls = []
    class HTTPResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, count): return b'x' * count
    class Provider:
        def open(self, request, **kwargs):
            calls.append(request)
            return HTTPResponse()
    monkeypatch.setattr('llmbo_para.llm.build_opener', lambda *args: Provider())
    monkeypatch.setenv('RESPONSES_UNIT_KEY', 'unit-responses-private-credential')
    with pytest.raises(RuntimeError):
        feature().ResponsesTransport('https://example.invalid/v1/responses', 'RESPONSES_UNIT_KEY',
            model='deepseek-v4-pro', max_tokens=1536, json_mode=True).post(payload())
    assert len(calls) == 1
