"""Native JSON boundaries and diagnostic archives, independent of Region policy."""
from __future__ import annotations

import json
import re


def is_json_native(value: object) -> bool:
    """Check structural types only; action validators separately reject NaN/Inf."""
    if type(value) is dict:
        return all(type(key) is str and is_json_native(child) for key, child in value.items())
    if type(value) is list:
        return all(is_json_native(child) for child in value)
    return value is None or type(value) in (str, int, float, bool)


def archival_json(value: object) -> str:
    """Redact diagnostic JSON without legitimizing rejected Python/nonfinite values.

    Token-shaped strings retain their lengths, including distinct redacted keys.
    This serializer never reads credentials and is not an action validator.
    """
    def redact(item: object) -> object:
        if type(item) not in (dict, list, str, int, float, bool, type(None)):
            return {'__rejected_python_type__': type(item).__name__}
        if type(item) is str:
            return re.sub(r'sk-[A-Za-z0-9_-]{8,}', lambda match: '*' * len(match[0]), item)
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                return {'__rejected_python_type__': 'non_string_object_key'}
            result = {}
            reserved = set(item)
            for name, child in sorted(item.items(), key=lambda pair: str(pair[0])):
                public = redact(name)
                if public != name:
                    suffix = 0
                    while public in reserved or public in result:
                        suffix += 1
                        ending = '~' + str(suffix)
                        public = '*' * max(0, len(name) - len(ending)) + ending
                result[public] = ('[REDACTED]' if name.lower() in
                    {'authorization', 'api_key', 'access_token', 'secret'} else redact(child))
            return result
        if type(item) is list:
            return [redact(child) for child in item]
        return item

    return json.dumps(redact(value), ensure_ascii=False, sort_keys=True, allow_nan=True)


def decode_archived_http_response(
    value: object, *, payload: dict, transport: str = 'openai_chat_completions',
) -> tuple[dict | None, str | None]:
    """Replay protocol completion, JSON and binding failures from archived HTTP.

    Imports are local: protocol decoders depend on policy contracts, while this
    common module must remain importable without a controller or catalog.
    """
    if transport == 'openai_responses':
        from .electrothermal_responses import decode_responses_json
        decoded, issue = decode_responses_json(value)
        if issue is not None:
            return None, issue
        from .electrothermal_region_wire import decode_region_wire
        try:
            return decode_region_wire(decoded, payload), None
        except ValueError:
            return None, 'invalid_binding'
    if transport != 'openai_chat_completions':
        raise ValueError('unknown catalog HTTP protocol')
    issue = 'invalid_completion'
    try:
        choice = value['choices'][0]
        if choice.get('finish_reason') != 'stop':
            return None, 'unfinished_completion'
        content = choice['message']['content']
        if content is None or isinstance(content, str) and not content.strip():
            return None, 'empty_content'
        if not isinstance(content, str):
            return None, 'invalid_content_type'
        issue = 'invalid_json'
        decoded = json.loads(content)
        if not isinstance(decoded, dict):
            return None, 'non_object_content'
        issue = 'invalid_binding'
        from .electrothermal_region_wire import decode_region_wire
        return decode_region_wire(decoded, payload), None
    except (KeyError, IndexError, TypeError, ValueError, AttributeError):
        return None, issue
