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
    options = llm.get("task_options", {})
    if not isinstance(options, dict) or any(name not in TASKS for name in options):
        raise ValueError("llm.task_options supports only the two electrothermal tasks")
    validated = {}
    for name, item in options.items():
        if not isinstance(item, dict) or set(item) - {"timeout_s", "max_tokens"}:
            raise ValueError("llm.task_options entries accept only timeout_s and max_tokens")
        limits = dict(global_limits)
        for field, value in item.items():
            limits[field] = (_timeout(value, "llm.task_options." + name + "." + field)
                             if field == "timeout_s" else
                             _tokens(value, "llm.task_options." + name + "." + field))
            if limits[field] > global_limits[field]:
                raise ValueError("llm.task_options." + name + "." + field + " exceeds its global ceiling")
        validated[name] = limits
    return dict(validated.get(task, global_limits))


class LLMRequestFailure(RuntimeError):
    """A classified failure with public diagnostics and no exception text."""
    def __init__(self, kind, diagnostic):
        self.kind = kind
        self.diagnostic = dict(diagnostic)
        super().__init__("electrothermal LLM request failed (" + kind + ")")


class HTTPArchive:
    """Use an existing run's immutable files/events without creating a new run."""
    _create_json = staticmethod(RunStore._create_json)

    def __init__(self, run_path, connection=None):
        self.enabled = run_path is not None
        self.path = Path(run_path).resolve() if self.enabled else Path("unarchived")
        self.events_path = self.path / "events.jsonl"
        self.connection = connection
        self.http_request_started = False
        self.last_http_status = None
        self.last_error = None

    def write_json(self, relative_path, value):
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
        if event.get("type") == "llm_http_finished":
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
    archive = HTTPArchive(run_path, connection)
    try:
        transport = ChatCompletionsTransport(**spec, run_store=archive)
        response = transport.post(payload)
        connection.send(("result", {"ok": True, "response": response,
            "diagnostic": {"http_status": 200, "http_request_started": archive.http_request_started}}))
    except Exception as exc:
        diagnostic = _public_diagnostic(archive.last_error)
        diagnostic.setdefault("error_type", type(exc).__name__)
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

    def _publish(self, task, diagnostic):
        self.last_request_diagnostic = dict(diagnostic)
        if self.store is not None:
            self.store.write_json("http/" + task + ".supervision.json", diagnostic)

    def post(self, payload, *, deadline=None):
        started = time.monotonic()
        task = payload.get("artifact_task", payload.get("task", "request")) if isinstance(payload, dict) else "request"
        base = {"configured_timeout_s": self.timeout_s, "max_tokens": self.max_tokens,
                "http_request_started": False, "http_status": None}

        def fail(kind, diagnostic=None):
            public = {**base, **_public_diagnostic(diagnostic), "status": "failed", "reason": kind,
                      "elapsed_s": time.monotonic() - started}
            self._publish(task, public)
            raise LLMRequestFailure(kind, public)

        try:
            reject_inline_secrets(payload)
            if not isinstance(payload, dict) or payload.get("task") not in TASKS:
                raise ValueError("unknown electrothermal LLM request task")
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
            nonlocal request_started
            request_started = True

        spec = {"endpoint": self.endpoint, "api_key_env": self.api_key_env, "model": self.model,
                "max_tokens": self.max_tokens, "json_mode": self.json_mode,
                "timeout_s": max(.001, hard_deadline - time.monotonic()), "thinking": self.thinking}
        run_path = str(self.store.path) if self.store is not None else None
        try:
            result = run_with_deadline(_chat_request_worker, (spec, payload, run_path),
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
                             "elapsed_s": time.monotonic() - started})
        return response

    @staticmethod
    def _archived_start(run_path, task):
        return run_path is not None and (Path(run_path) / "http" / (task + ".request.json")).is_file()
