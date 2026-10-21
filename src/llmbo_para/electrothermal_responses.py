"""Explicit Responses wire format; no protocol guessing or provider fallback."""
from __future__ import annotations

import json
import math

from .llm import HttpJsonTransport
from .runstore import reject_inline_secrets


JSON_INSTRUCTIONS = '\nReturn exactly one JSON object matching the supplied response contract.'
RESPONSE_STATUSES = ('completed', 'failed', 'in_progress', 'cancelled', 'queued', 'incomplete')


def _settings(model, max_tokens, json_mode):
    if not isinstance(model, str) or not model.strip():
        raise ValueError('Responses requires an explicit model ID')
    if type(max_tokens) is not int or not 1 <= max_tokens <= 8192:
        raise ValueError('Responses max_tokens must be an integer in [1, 8192]')
    if type(json_mode) is not bool:
        raise ValueError('Responses json_mode must be boolean')


def responses_request_body(payload: dict, *, model: str, max_tokens: int, json_mode: bool) -> dict:
    _settings(model, max_tokens, json_mode)
    reject_inline_secrets(payload)
    if not isinstance(payload, dict) or not isinstance(payload.get('instructions'), str) or not payload['instructions'].strip():
        raise ValueError('Responses requires versioned instructions')
    body = {'model': model, 'instructions': payload['instructions'] + (JSON_INSTRUCTIONS if json_mode else ''),
            'input': json.dumps({k: v for k, v in payload.items() if k != 'instructions'},
                               ensure_ascii=False, allow_nan=False, separators=(',', ':')),
            'max_output_tokens': max_tokens, 'stream': False, 'store': False}
    if json_mode:
        body['text'] = {'format': {'type': 'json_object'}}
    return body


def _formal_text(value):
    if not isinstance(value, dict) or value.get('status') not in RESPONSE_STATUSES:
        return None, 'invalid_completion'
    if value['status'] != 'completed':
        return None, 'unfinished_completion'
    if value.get('error') is not None or value.get('incomplete_details') is not None:
        return None, 'invalid_completion'
    output = value.get('output')
    if not isinstance(output, list) or any(not isinstance(item, dict) or item.get('type') not in ('message', 'reasoning') for item in output):
        return None, 'invalid_completion'
    messages = [item for item in output if item.get('type') == 'message']
    if len(messages) != 1:
        return None, 'invalid_completion'
    message = messages[0]
    content = message.get('content')
    if (message.get('role') != 'assistant' or message.get('status') != 'completed'
            or not isinstance(content, list) or len(content) != 1
            or not isinstance(content[0], dict) or content[0].get('type') != 'output_text'):
        return None, 'invalid_completion'
    text = content[0].get('text')
    if not isinstance(text, str):
        return None, 'invalid_content_type'
    if not text.strip():
        return text, 'empty_content'
    return text, None


def _invalid_constant(value):
    raise ValueError('nonfinite JSON constant')


def decode_responses_json(value: dict) -> tuple[dict | None, str | None]:
    text, issue = _formal_text(value)
    if issue is not None:
        return None, issue
    try:
        result = json.loads(text, parse_constant=_invalid_constant)
        # Also reject numeric overflow such as 1e999, not only named constants.
        json.dumps(result, allow_nan=False)
    except (ValueError, TypeError, OverflowError):
        return None, 'invalid_json'
    if not isinstance(result, dict):
        return None, 'non_object_content'
    return result, None


def responses_completion_summary(value: dict, token_limit: int) -> dict:
    value = value if isinstance(value, dict) else {}
    text, issue = _formal_text(value)
    status = value.get('status')
    result = {'response_status': status if status in RESPONSE_STATUSES else 'other',
              'answer_characters': len(text) if isinstance(text, str) else None,
              'state': 'complete_answer' if issue is None else 'empty_answer' if issue == 'empty_content' else 'unclassified'}
    usage = value.get('usage')
    usage = usage if isinstance(usage, dict) else {}
    for source, target in (('input_tokens', 'input_tokens'), ('output_tokens', 'completion_tokens'), ('total_tokens', 'total_tokens')):
        count = usage.get(source)
        if type(count) is int and count >= 0:
            result[target] = count
    details = usage.get('output_tokens_details')
    count = details.get('reasoning_tokens') if isinstance(details, dict) else None
    if type(count) is int and count >= 0:
        result['reasoning_tokens'] = count
    return result


class ResponsesTransport(HttpJsonTransport):
    """One nonstreaming, stateless Responses POST with the existing HTTP guard."""

    response_protocol = 'openai_responses'

    def __init__(self, endpoint, api_key_env, *, model, max_tokens, json_mode,
                 timeout_s=60., run_store=None, thinking=None):
        _settings(model, max_tokens, json_mode)
        if thinking is not None:
            raise ValueError('Responses thinking mapping has not been confirmed')
        if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError('Responses timeout must be finite and positive')
        super().__init__(endpoint, api_key_env, timeout_s=timeout_s, run_store=run_store)
        if not endpoint.rstrip('/').endswith('/responses'):
            raise ValueError('Responses transport requires the full /responses HTTPS endpoint')
        self.model, self.max_tokens, self.json_mode = model, max_tokens, json_mode
        self.thinking = None

    def post(self, payload):
        body = responses_request_body(payload, model=self.model, max_tokens=self.max_tokens, json_mode=self.json_mode)
        task = payload.get('artifact_task', payload.get('task', 'request'))
        raw = self._post_json(body, task=task)
        formal, issue = decode_responses_json(raw)
        if issue is not None:
            if self.store is not None:
                self.store.write_json('http/' + task + '.parse-error.json',
                                      {'error_type': 'ValueError', 'protocol_issue': issue})
            raise ValueError('Responses output must be complete formal JSON (' + issue + ')')
        return formal


def _responses_request_worker(spec, payload, run_path, connection):
    """Owned child: exactly one Responses invocation, then local wire binding."""
    from .electrothermal_requests import HTTPArchive, _public_diagnostic
    from .electrothermal_region_wire import region_wire_payload, decode_region_wire
    archive = HTTPArchive(run_path, connection, max_tokens=spec.get('max_tokens'), transport='openai_responses')
    try:
        transport = ResponsesTransport(**spec, run_store=archive)
        formal = transport.post(region_wire_payload(payload))
        try:
            formal = decode_region_wire(formal, payload)
        except ValueError:
            task = payload.get('artifact_task', payload['task'])
            archive.write_json('http/' + task + '.parse-error.json',
                               {'error_type': 'ValueError', 'protocol_issue': 'invalid_binding'})
            raise
        connection.send(('result', {'ok': True, 'response': formal,
            'diagnostic': {'http_status': 200, 'http_request_started': archive.http_request_started,
                           **({'completion': archive.completion} if archive.completion is not None else {})}}))
    except Exception as exc:
        diagnostic = _public_diagnostic(archive.last_error)
        if diagnostic['http_status'] is None:
            diagnostic['http_status'] = archive.last_http_status
        diagnostic.setdefault('error_type', type(exc).__name__)
        if archive.completion is not None:
            diagnostic['completion'] = archive.completion
        diagnostic['http_request_started'] = archive.http_request_started
        connection.send(('result', {'ok': False, 'diagnostic': diagnostic}))
    finally:
        connection.close()


from .electrothermal_requests import BoundedChatCompletionsTransport


class BoundedResponsesTransport(BoundedChatCompletionsTransport, ResponsesTransport):
    """Keep the proven deadline implementation; change initialization and worker."""

    def __init__(self, endpoint, api_key_env, *, model, max_tokens, json_mode,
                 timeout_s=60., run_store=None, thinking=None):
        # Deliberately use Responses validation rather than Chat's endpoint check.
        ResponsesTransport.__init__(self, endpoint, api_key_env, model=model, max_tokens=max_tokens,
            json_mode=json_mode, timeout_s=timeout_s, run_store=run_store, thinking=thinking)
        self.last_request_diagnostic = None

    def _request_worker(self):
        return _responses_request_worker
