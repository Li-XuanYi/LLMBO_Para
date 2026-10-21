"""Task limits and an owned-process deadline for electrothermal chat requests.

Only the credential environment-variable name crosses the process boundary.
The existing chat transport owns wire validation, HTTPS and secret redaction.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import time

from .electrothermal_execution import run_with_deadline
from .llm import ChatCompletionsTransport
from .runstore import RunStore, reject_inline_secrets


TASKS = ("warm_start_electrothermal", "region_preference_electrothermal")


def _timeout(value, name):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError(name + " must be a finite positive number")
    return float(value)


def _tokens(value, name):
    if type(value) is not int or not 1 <= value <= 8192:
        raise ValueError(name + " must be an integer in [1, 8192]")
    return value


def _thinking(value):
    if type(value) is not str or value not in ('enabled', 'disabled'):
        raise ValueError('thinking must be explicitly enabled or disabled')
    return value


def request_controls(config, task):
    """Return validated task limits, inheriting but never exceeding globals."""
    if not isinstance(config, dict) or type(config.get("schema_version")) is not int or config["schema_version"] != 2:
        raise ValueError("electrothermal request controls require schema_version=2")
    if task not in TASKS:
        raise ValueError("unknown electrothermal LLM request task")
    llm = config.get("llm")
    if not isinstance(llm, dict):
        raise ValueError("llm must be an object")
    global_limits = {"timeout_s": _timeout(llm.get("timeout_s"), "llm.timeout_s"),
                     "max_tokens": _tokens(llm.get("max_tokens"), "llm.max_tokens")}
    if 'thinking' in llm:
        global_limits['thinking'] = _thinking(llm['thinking'])
    options = llm.get("task_options", {})
    if not isinstance(options, dict) or any(name not in TASKS for name in options):
        raise ValueError("llm.task_options supports only the two electrothermal tasks")
    validated = {}
    for name, item in options.items():
        if not isinstance(item, dict) or set(item) - {"timeout_s", "max_tokens", "thinking"}:
            raise ValueError("llm.task_options entries accept only timeout_s, max_tokens and thinking")
        limits = dict(global_limits)
        for field, value in item.items():
            if field == 'thinking':
                limits[field] = _thinking(value)
                continue
            limits[field] = (_timeout(value, "llm.task_options." + name + "." + field)
                             if field == "timeout_s" else
                             _tokens(value, "llm.task_options." + name + "." + field))
            if limits[field] > global_limits[field]:
                raise ValueError("llm.task_options." + name + "." + field + " exceeds its global ceiling")
        validated[name] = limits
    return dict(validated.get(task, global_limits))


def completion_summary(response, token_limit, *, transport='openai_chat_completions'):
    """Public machine evidence only; never read or interpret reasoning text."""
    if transport == 'openai_responses':
        from .electrothermal_responses import responses_completion_summary
        return responses_completion_summary(response, token_limit)
    if transport != 'openai_chat_completions':
        raise ValueError('unknown completion transport')
    response = response if isinstance(response, dict) else {}
    choices = response.get('choices')
    choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else {}
    finish = choice.get('finish_reason')
    finish = finish if finish in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call') else 'other'
    message = choice.get('message'); message = message if isinstance(message, dict) else {}
    content = message.get('content')
    answer = len(content) if isinstance(content, str) else 0 if content is None else None
    result = {'finish_reason': finish, 'answer_characters': answer}
    usage = response.get('usage'); usage = usage if isinstance(usage, dict) else {}
    details = usage.get('completion_tokens_details'); details = details if isinstance(details, dict) else {}
    valid = lambda v: type(v) is int and v >= 0
    tokens = usage.get('completion_tokens')
    if valid(tokens): result['completion_tokens'] = tokens
    counts = [v for v in (details.get('reasoning_tokens'), usage.get('completion_thinking_tokens')) if valid(v)]
    if counts and len(set(counts)) == 1: result['reasoning_tokens'] = counts[0]
    result['state'] = ('complete_answer' if finish == 'stop' and answer else
                       'empty_answer' if finish == 'stop' and answer == 0 else
                       'truncated_answer' if finish == 'length' and answer else 'unclassified')
    if (finish == 'length' and answer == 0 and type(token_limit) is int and token_limit > 0
            and valid(tokens) and tokens == token_limit and result.get('reasoning_tokens') == tokens):
        result['state'] = 'reasoning_budget_exhausted'
    return result


class LLMRequestFailure(RuntimeError):
    """A classified failure with public diagnostics and no exception text."""
    def __init__(self, kind, diagnostic):
        self.kind = kind
        self.diagnostic = dict(diagnostic)
        super().__init__("electrothermal LLM request failed (" + kind + ")")


class HTTPArchive:
    """Use an existing run's immutable files/events without creating a new run."""
    _create_json = staticmethod(RunStore._create_json)

    def __init__(self, run_path, connection=None, max_tokens=None, *, transport='openai_chat_completions'):
        self.enabled = run_path is not None
        self.path = Path(run_path).resolve() if self.enabled else Path("unarchived")
        self.events_path = self.path / "events.jsonl"
        self.connection = connection
        self.http_request_started = False
        self.last_http_status = None
        self.last_error = None
        self.max_tokens = max_tokens
        self.completion = None
        self.transport = transport

    def write_json(self, relative_path, value):
        if relative_path.endswith('.response.json'):
            self.completion = completion_summary(value, self.max_tokens, transport=self.transport)
        if relative_path.endswith((".error.json", ".parse-error.json")):
            value = {**value, "http_request_started": self.http_request_started}
            if relative_path.endswith(".parse-error.json"):
                value["http_status"] = self.last_http_status
            self.last_error = value
            value = _public_diagnostic(value)
        if self.enabled:
            return RunStore.write_json(self, relative_path, value)
        return None

    def append_event(self, event):
        if event.get("type") in ("llm_http_finished","llm_http_headers_received"):
            self.last_http_status = event.get("http_status")
        if event.get("type") == "llm_http_finished" and event.get("error_type"):
            event = {"type": "llm_http_finished", "task": event.get("task"),
                     **_public_diagnostic({**event, "http_request_started": self.http_request_started})}
        if self.enabled:
            RunStore.append_event(self, event)
        if event.get("type") == "llm_http_started":
            self.http_request_started = True
            if self.connection is not None:
                # The generic owned-worker supervisor acknowledges this start
                # before allowing the existing transport to open the socket.
                self.connection.send(("solve_started", None))
                if self.connection.recv() != "continue":
                    raise RuntimeError("invalid owned-request start acknowledgement")


def _public_diagnostic(value):
    """Allowlist machine fields; never transfer raw exception/provider text."""
    value = value if isinstance(value, dict) else {}
    result = {}
    error_type = value.get("error_type")
    if isinstance(error_type, str) and re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]{0,79}", error_type):
        result["error_type"] = error_type
    status = value.get("http_status")
    result["http_status"] = status if type(status) is int and 100 <= status <= 599 else None
    elapsed = value.get("elapsed_s")
    if type(elapsed) in (int, float) and math.isfinite(elapsed) and elapsed >= 0:
        result["elapsed_s"] = float(elapsed)
    result["http_request_started"] = value.get("http_request_started") is True
    if value.get('protocol_issue') in ('invalid_completion','unfinished_completion','empty_content','invalid_content_type',
            'invalid_json','non_object_content','invalid_binding'):
        result['protocol_issue']=value['protocol_issue']
    completion = value.get('completion')
    if isinstance(completion, dict):
        public = {key: completion[key] for key in ('answer_characters', 'completion_tokens', 'reasoning_tokens', 'input_tokens', 'total_tokens')
                  if type(completion.get(key)) is int and completion[key] >= 0}
        if 'answer_characters' in completion and completion['answer_characters'] is None:
            public['answer_characters'] = None
        if completion.get('finish_reason') in ('stop', 'length', 'content_filter', 'tool_calls', 'function_call', 'other'):
            public['finish_reason'] = completion['finish_reason']
        if completion.get('state') in ('complete_answer', 'empty_answer', 'truncated_answer', 'unclassified', 'reasoning_budget_exhausted'):
            public['state'] = completion['state']
        if completion.get('response_status') in ('completed', 'failed', 'in_progress', 'cancelled', 'queued', 'incomplete', 'other'):
            public['response_status'] = completion['response_status']
        result['completion'] = public
    return result


def _failure_kind(diagnostic):
    if diagnostic.get("http_status") is not None and diagnostic["http_status"] >= 400:
        return "http_error"
    error_type = diagnostic.get("error_type")
    if error_type in ("TimeoutError", "timeout"):
        return "timeout"
    if error_type in ("ValueError", "JSONDecodeError", "KeyError", "IndexError", "TypeError"):
        return "protocol_error"
    if error_type in ("URLError", "RemoteDisconnected", "SSLError", "ConnectionError",
                      "ConnectionResetError", "ConnectionAbortedError", "BrokenPipeError", "OSError"):
        return "transport_error"
    return "worker_error"


def _chat_request_worker(spec, payload, run_path, connection):
    """Spawn entry point: one real transport invocation and no retries."""
    archive = HTTPArchive(run_path, connection, max_tokens=spec.get('max_tokens'))
    try:
        from .electrothermal_region_wire import region_wire_payload,decode_region_wire
        transport = ChatCompletionsTransport(**spec, run_store=archive)
        response = transport.post(region_wire_payload(payload))
        try:response=decode_region_wire(response,payload)
        except ValueError:
            task=payload.get('artifact_task',payload['task'])
            archive.write_json('http/'+task+'.parse-error.json',{'error_type':'ValueError','protocol_issue':'invalid_binding'})
            raise
        connection.send(("result", {"ok": True, "response": response,
            "diagnostic": {"http_status": 200, "http_request_started": archive.http_request_started,
                           **({'completion': archive.completion} if archive.completion is not None else {})}}))
    except Exception as exc:
        diagnostic = _public_diagnostic(archive.last_error)
        if diagnostic['http_status'] is None:diagnostic['http_status']=archive.last_http_status
        diagnostic.setdefault("error_type", type(exc).__name__)
        if archive.completion is not None: diagnostic['completion'] = archive.completion
        diagnostic["http_request_started"] = archive.http_request_started
        connection.send(("result", {"ok": False, "diagnostic": diagnostic}))
    finally:
        connection.close()


class BoundedChatCompletionsTransport(ChatCompletionsTransport):
    """Preserve chat semantics while enforcing a whole-request hard deadline."""
    def __init__(self, endpoint, api_key_env, *, model, max_tokens, json_mode,
                 timeout_s=60., run_store=None, thinking=None):
        timeout_s = _timeout(timeout_s, "request timeout_s")
        super().__init__(endpoint, api_key_env, model=model, max_tokens=max_tokens,
            json_mode=json_mode, timeout_s=timeout_s, run_store=run_store, thinking=thinking)
        self.last_request_diagnostic = None

    def _request_worker(self):
        # Resolve at call time so injected offline workers retain their old API.
        return _chat_request_worker

    def _publish(self, task, diagnostic):
        self.last_request_diagnostic = dict(diagnostic)
        if self.store is not None:
            self.store.write_json("http/" + task + ".supervision.json", diagnostic)

    def post(self, payload, *, deadline=None):
        started = time.monotonic()
        task = payload.get("artifact_task", payload.get("task", "request")) if isinstance(payload, dict) else "request"
        wire_format=payload.get('region_wire_format','full_v1') if isinstance(payload,dict) else 'full_v1'
        base = {"configured_timeout_s": self.timeout_s, "max_tokens": self.max_tokens,
                "http_request_started": False, "http_status": None,
                'wire_format':wire_format if wire_format in ('full_v1','compact_v1') else 'invalid'}
        if self.thinking is not None: base['thinking'] = self.thinking
        if getattr(self, 'response_protocol', None) == 'openai_responses':
            base['response_protocol'] = 'openai_responses'
        request_started=False;request_start_elapsed=None

        def fail(kind, diagnostic=None):
            progress=self._archived_progress(self.store.path if self.store is not None else None,task)
            detail=_public_diagnostic(diagnostic)
            if detail['http_status'] is None:detail['http_status']=progress.get('http_status')
            stage='decoding_content' if kind=='protocol_error' else progress.get('failure_stage',
                'awaiting_headers' if request_started else 'worker_startup')
            public = {**base, **detail, "status": "failed", "reason": kind,'failure_stage':stage,
                      'request_start_elapsed_s':request_start_elapsed,
                      "elapsed_s": time.monotonic() - started}
            self._publish(task, public)
            raise LLMRequestFailure(kind, public)

        try:
            reject_inline_secrets(payload)
            if not isinstance(payload, dict) or payload.get("task") not in TASKS:
                raise ValueError("unknown electrothermal LLM request task")
            if base['wire_format']=='invalid':raise ValueError('invalid Region wire format')
            if not isinstance(task, str) or not re.fullmatch(r"[a-z_]+", task):
                raise ValueError("artifact task must be a fixed safe label")
            instructions = payload.get("instructions")
            if not isinstance(instructions, str) or not instructions.strip():
                raise ValueError("versioned request instructions required")
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
            if deadline is not None and (type(deadline) not in (int, float) or not math.isfinite(deadline)):
                raise ValueError("finite monotonic run deadline required")
            if not os.environ.get(self.api_key_env):
                raise ValueError("credential environment variable is not set")
        except (TypeError, ValueError):
            # Invalid artifact labels must not reach filesystem path creation.
            if not isinstance(task, str) or not re.fullmatch(r"[a-z_]+", task):
                task = "invalid_request"
            fail("configuration_error", {"error_type": "ValueError"})

        hard_deadline = min(started + self.timeout_s, deadline) if deadline is not None else started + self.timeout_s
        base["effective_timeout_s"] = max(0., hard_deadline - started)
        if time.monotonic() >= hard_deadline:
            fail("deadline_exceeded", {"error_type": "TimeoutError"})
        request_started = False

        def on_request_start():
            nonlocal request_started,request_start_elapsed
            request_started = True
            request_start_elapsed=time.monotonic()-started

        spec = {"endpoint": self.endpoint, "api_key_env": self.api_key_env, "model": self.model,
                "max_tokens": self.max_tokens, "json_mode": self.json_mode,
                "timeout_s": max(.001, hard_deadline - time.monotonic()), "thinking": self.thinking}
        run_path = str(self.store.path) if self.store is not None else None
        try:
            result = run_with_deadline(self._request_worker(), (spec, payload, run_path),
                deadline=hard_deadline, on_solve_start=on_request_start)
        except TimeoutError:
            request_started = request_started or self._archived_start(run_path, task)
            fail("deadline_exceeded", {"error_type": "TimeoutError", "http_request_started": request_started})
        except Exception as exc:
            request_started = request_started or self._archived_start(run_path, task)
            fail("worker_error", {"error_type": type(exc).__name__, "http_request_started": request_started})
        if not isinstance(result, dict):
            fail("worker_error", {"error_type": "InvalidWorkerResult", "http_request_started": request_started})
        diagnostic = _public_diagnostic(result.get("diagnostic"))
        diagnostic["http_request_started"] = diagnostic["http_request_started"] or request_started or self._archived_start(run_path, task)
        if not result.get("ok"):
            fail(_failure_kind(diagnostic), diagnostic)
        response = result.get("response")
        if not isinstance(response, dict):
            fail("protocol_error", {**diagnostic, "error_type": "InvalidResponseObject"})
        self._publish(task, {**base, **diagnostic, "status": "completed", "reason": None,
                             'failure_stage':None,'request_start_elapsed_s':request_start_elapsed,
                             "elapsed_s": time.monotonic() - started})
        return response

    @staticmethod
    def _archived_start(run_path, task):
        return run_path is not None and (Path(run_path) / "http" / (task + ".request.json")).is_file()

    @staticmethod
    def _archived_progress(run_path,task):
        if run_path is None:return {}
        try:
            headers=[json.loads(line) for line in (Path(run_path)/'events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
            headers=[e for e in headers if e.get('type')=='llm_http_headers_received' and e.get('task')==task]
            if headers:return {'failure_stage':'reading_body','http_status':_public_diagnostic(headers[-1])['http_status']}
        except (OSError,ValueError,TypeError):pass
        return {}


def electrothermal_transport_class(config: dict) -> type:
    """Select a configured class without reading a key or constructing a client."""
    selected = config['llm'].get('transport', 'openai_chat_completions')
    if selected == 'openai_chat_completions':
        return BoundedChatCompletionsTransport
    if selected == 'openai_responses':
        from .electrothermal_responses import BoundedResponsesTransport
        return BoundedResponsesTransport
    raise ValueError('unknown electrothermal LLM transport')
