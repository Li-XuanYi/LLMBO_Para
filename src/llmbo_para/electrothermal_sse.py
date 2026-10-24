"""Bounded Responses SSE framing and replay; deltas never substitute for a reply."""
from __future__ import annotations

import codecs
from copy import deepcopy
import json
import re
import time

MAX_BYTES = 1024 * 1024
MAX_EVENTS = 4096
TERMINALS = {'response.completed': 'completed', 'response.failed': 'failed',
             'response.incomplete': 'incomplete'}
EVENT_TYPES = frozenset((*TERMINALS, 'response.created', 'response.in_progress',
    'response.output_item.added', 'response.output_item.done',
    'response.content_part.added', 'response.content_part.done',
    'response.reasoning_text.delta', 'response.reasoning_text.done',
    'response.reasoning_summary_part.added', 'response.reasoning_summary_part.done',
    'response.reasoning_summary_text.delta', 'response.reasoning_summary_text.done',
    'response.output_text.delta', 'response.output_text.done'))


def _invalid_constant(value):
    raise ValueError('nonfinite SSE JSON')


def _json(text):
    try:
        value = json.loads(text, parse_constant=_invalid_constant)
        json.dumps(value, allow_nan=False)
        return value
    except (ValueError, TypeError, OverflowError):
        raise ValueError('invalid finite SSE JSON') from None


class _Completion:
    def __init__(self):
        self.sequence = -1
        self.count = 0
        self.response_id = None
        self.terminal = None

    def accept(self, entry):
        self.count += 1
        if self.count > MAX_EVENTS or self.terminal is not None or type(entry) is not dict:
            raise ValueError('invalid or excessive SSE events')
        data = entry.get('data')
        if type(data) is not dict:
            raise ValueError('SSE event requires a JSON object')
        json.dumps(data, allow_nan=False)
        kind, sequence = data.get('type'), data.get('sequence_number')
        if (type(kind) is not str or kind not in EVENT_TYPES
                or entry.get('event') not in (None, '', kind)
                or type(sequence) is not int or sequence < 0 or sequence <= self.sequence):
            raise ValueError('invalid Responses SSE type or sequence')
        self.sequence = sequence
        item = data.get('item')
        if kind.startswith('response.output_item.') and (
                type(item) is not dict or item.get('type') not in ('message', 'reasoning')):
            raise ValueError('tools and unknown SSE output items are unsupported')
        response = data.get('response')
        if type(response) is dict and response.get('id') is not None:
            ident = response['id']
            if type(ident) is not str or not ident or self.response_id not in (None, ident):
                raise ValueError('SSE response identity changed')
            self.response_id = ident
        if kind in TERMINALS:
            if type(response) is not dict or response.get('status') != TERMINALS[kind]:
                raise ValueError('SSE terminal status differs')
            self.terminal = response


def decode_sse_events(events):
    """Replay sanitized event envelopes; formal/business validation follows this."""
    state = _Completion()
    for entry in events:
        state.accept(entry)
    if state.terminal is None:
        raise ValueError('SSE ended without a terminal response')
    return state.terminal


def _archive_entry(entry, redact):
    value = redact(deepcopy(entry))
    # Project intermediate events onto replay metadata: an open-ended denylist
    # misses refusal, annotations and future free-text fields that can split a
    # credential across events. Only the terminal retains the redacted response.
    data = value.get('data')
    if type(data) is dict and not (type(data.get('type')) is str and data['type'] in TERMINALS):
        kind, event = data.get('type'), value.get('event')
        metadata = {'type': kind if type(kind) is str and kind in EVENT_TYPES else None,
                    'sequence_number': data.get('sequence_number')
                        if type(data.get('sequence_number')) is int else None}
        response = data.get('response')
        if type(response) is dict:
            metadata['response'] = {'id': response['id']} if type(response.get('id')) is str else {}
        item = data.get('item')
        if type(item) is dict:
            metadata['item'] = {'type': item.get('type')
                                if item.get('type') in ('message', 'reasoning') else None}
        value = {'event': event if event in (None, '') or type(event) is str and event in EVENT_TYPES
                         else '[INVALID_SSE_EVENT]',
                 'data': metadata}
    return value


def read_responses_sse(response, *, archive, task, redact):
    """Read available chunks up to a terminal event; absolute time is owned by caller."""
    if type(task) is not str or re.fullmatch(r'[a-z_]+', task) is None:
        raise ValueError('fixed safe SSE task required')
    if archive is not None:
        archive.start_stream(task)
    mime = response.getheader('Content-Type', '')
    if type(mime) is not str or mime.partition(';')[0].strip().lower() != 'text/event-stream':
        raise ValueError('Responses streaming requires text/event-stream')
    decoder = codecs.getincrementaldecoder('utf8')('strict')
    state = _Completion()
    line, data_lines = [], []
    event = None
    after_cr, initial = False, True
    received, first_event = 0, None
    started = time.perf_counter()

    def dispatch():
        nonlocal event, first_event
        if not data_lines:
            event = None
            return
        text = '\n'.join(data_lines)
        data_lines.clear()
        try:
            entry = {'event': event, 'data': _json(text)}
        except ValueError:
            if archive is not None:
                archive.append_stream(task, {'event': event, 'data_text': redact(text)})
            raise
        event = None
        if archive is not None:
            archive.append_stream(task, _archive_entry(entry, redact))
        state.accept(entry)
        if first_event is None:
            first_event = time.perf_counter() - started
        if archive is not None:
            archive.append_event({'type': 'llm_http_stream_progress', 'task': task,
                'semantic_events': state.count, 'last_event': entry['data']['type'],
                'received_bytes': received, 'first_event_read_elapsed_s': first_event})

    def consume_line():
        nonlocal event
        text = ''.join(line)
        line.clear()
        if not text:
            dispatch()
        elif not text.startswith(':'):
            name, sep, value = text.partition(':')
            if value.startswith(' '):
                value = value[1:]
            if name == 'data':
                data_lines.append(value)
            elif name == 'event':
                event = value

    while True:
        chunk = response.read1(min(8192, MAX_BYTES - received + 1))
        if type(chunk) is not bytes:
            raise ValueError('SSE reader requires bytes')
        received += len(chunk)
        if received > MAX_BYTES:
            raise ValueError('Responses SSE exceeds the 1 MiB limit')
        try:
            text = decoder.decode(chunk, final=not chunk)
        except UnicodeError:
            raise ValueError('invalid SSE UTF8') from None
        for char in text:
            if initial:
                initial = False
                if char == '\ufeff':
                    continue
            if after_cr:
                after_cr = False
                if char == '\n':
                    continue
            if char in ('\r', '\n'):
                consume_line()
                after_cr = char == '\r'
                if state.terminal is not None:
                    return state.terminal
            else:
                line.append(char)
        if not chunk:
            # EOF does not dispatch an unfinished SSE frame.
            raise ValueError('SSE ended without a terminal response')
