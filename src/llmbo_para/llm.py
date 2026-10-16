"""Strict JSON contracts and injectable two-call LLM client."""

from __future__ import annotations

import json
import math
import os
import hashlib
import re
import time
from copy import copy
from importlib import resources
from typing import Mapping, Protocol, Sequence
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.error import HTTPError
from urllib.parse import urlsplit

from .metrics import RATE_ORDER
from .parameters import ParameterSpace
from .runstore import reject_inline_secrets


class JsonTransport(Protocol):
    def post(self, payload: Mapping) -> Mapping: ...


class NoRedirect(HTTPRedirectHandler):
    """Never forward a bearer credential to a redirected endpoint."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class HttpJsonTransport:
    """Bearer-token transport; no request occurs until post is explicitly called."""

    def __init__(self, endpoint: str, api_key_env: str, *, timeout_s: float = 30.0, run_store=None):
        if not isinstance(endpoint, str) or not isinstance(api_key_env, str):
            raise ValueError("HTTPS endpoint and credential environment-variable name are required")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment or not api_key_env or not isinstance(timeout_s, (int, float)) or not math.isfinite(timeout_s) or timeout_s <= 0:
            raise ValueError("HTTPS endpoint, API-key environment variable and positive timeout are required")
        self.endpoint, self.api_key_env, self.timeout_s = endpoint, api_key_env, timeout_s
        self.store = run_store

    def post(self, payload: Mapping) -> Mapping:
        return self._post_json(payload, task=payload.get("task", "request"))

    def _post_json(self, payload: Mapping, *, task: str) -> Mapping:
        reject_inline_secrets(payload)
        if not isinstance(task, str) or not re.fullmatch(r"[a-z_]+", task):
            raise ValueError("transport task name must be a fixed artifact-safe label")
        key = os.environ.get(self.api_key_env)
        if not key:
            raise RuntimeError(f"missing required environment variable: {self.api_key_env}")

        def redact(value):
            if isinstance(value, str):
                return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value.replace(key, "[REDACTED]"))
            if isinstance(value, dict):
                return {name: ("[REDACTED]" if str(name).lower() in {"authorization", "api_key", "access_token", "secret"} else redact(child))
                        for name, child in value.items()}
            if isinstance(value, (tuple, list)):
                return [redact(child) for child in value]
            return value

        public_headers = {"User-Agent": "LLMBO-Para/1"}
        if urlsplit(self.endpoint).hostname == "opencode.ai" and urlsplit(self.endpoint).path.startswith("/zen/go/"):
            public_headers["x-opencode-session"] = "llmbo-para-" + (self.store.path.name if self.store else "unarchived")
        if self.store:
            self.store.write_json(f"http/{task}.request.json", {"endpoint": self.endpoint, "headers": public_headers,
                                                               "body": redact(dict(payload))})
            self.store.append_event({"type": "llm_http_started", "task": task, "endpoint": self.endpoint})
        request = Request(
            self.endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json", **public_headers},
            method="POST",
        )
        started = time.perf_counter()
        status = None
        try:
            with build_opener(NoRedirect()).open(request, timeout=self.timeout_s) as response:
                status = response.status
                body = response.read(1024 * 1024 + 1)
                if len(body) > 1024 * 1024:
                    raise ValueError("structured LLM response exceeds the 1 MiB limit")
                result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError("LLM endpoint did not return a JSON object")
            result = redact(result)
            if self.store:
                self.store.write_json(f"http/{task}.response.json", result)
                self.store.append_event({"type": "llm_http_finished", "task": task, "http_status": status,
                                         "elapsed_s": time.perf_counter()-started, "usage": result.get("usage"),
                                         "response_model": result.get("model")})
            return result
        except Exception as exc:
            diagnostic = {"error_type": type(exc).__name__, "http_status": status,
                          "elapsed_s": time.perf_counter()-started}
            if isinstance(exc, HTTPError):
                diagnostic["http_status"] = exc.code
                raw = exc.read(64 * 1024).decode("utf-8", errors="replace")
                try:
                    diagnostic["provider_response"] = json.loads(raw)
                except ValueError:
                    diagnostic["provider_response"] = raw
            else:
                diagnostic["message"] = str(exc)
            diagnostic = redact(diagnostic)
            if self.store:
                self.store.write_json(f"http/{task}.error.json", diagnostic)
                self.store.append_event({"type": "llm_http_finished", "task": task, **diagnostic})
            raise RuntimeError(f"LLM HTTP request failed ({type(exc).__name__}, status={diagnostic['http_status']}); see sanitized HTTP diagnostics") from None


class ChatCompletionsTransport(HttpJsonTransport):
    """Adapt the existing two-task JSON contract to messages/choices."""

    def __init__(self, endpoint: str, api_key_env: str, *, model: str, max_tokens: int,
                 json_mode: bool, timeout_s: float = 60, run_store=None, thinking: str | None = None):
        super().__init__(endpoint, api_key_env, timeout_s=timeout_s, run_store=run_store)
        if not endpoint.rstrip("/").endswith("/chat/completions"):
            raise ValueError("chat transport requires the full /chat/completions HTTPS endpoint")
        if not isinstance(model, str) or not model.strip():
            raise ValueError("chat transport needs an explicit model ID")
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or not 1 <= max_tokens <= 8192:
            raise ValueError("chat max_tokens must be an integer in [1, 8192]")
        if not isinstance(json_mode, bool):
            raise ValueError("json_mode must be an explicit boolean")
        if thinking is not None and thinking not in ("enabled", "disabled"):
            raise ValueError("thinking must be enabled, disabled or omitted")
        self.model, self.max_tokens, self.json_mode = model, max_tokens, json_mode
        self.thinking = thinking

    def post(self, payload: Mapping) -> Mapping:
        reject_inline_secrets(payload)
        instructions = payload.get("instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            raise ValueError("chat transport needs the versioned task instructions")
        wire = {"model": self.model, "messages": [
                    {"role": "system", "content": instructions},
                    {"role": "user", "content": json.dumps({k: v for k, v in payload.items() if k != "instructions"}, ensure_ascii=False, allow_nan=False)}
                ], "max_tokens": self.max_tokens, "stream": False}
        if self.json_mode:
            wire["response_format"] = {"type": "json_object"}
        if self.thinking is not None:
            wire["thinking"] = {"type": self.thinking}
        result = self._post_json(wire, task=payload["task"])
        try:
            choice = result["choices"][0]
            if choice.get("finish_reason") != "stop":
                raise ValueError("chat completion did not stop normally; truncated/refused output cannot be accepted")
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("chat completion did not contain text")
            decoded = json.loads(content)
            if not isinstance(decoded, dict):
                raise ValueError("chat completion content must be a JSON object")
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            if self.store:
                self.store.write_json(f"http/{payload['task']}.parse-error.json", {"error_type": type(exc).__name__, "reason": str(exc)})
            raise ValueError("chat response failed the strict JSON completion contract; see archived response") from None
        return decoded


class LLMClient:
    def __init__(self, transport: JsonTransport, *, context: Mapping | None = None, run_store=None, min_diversity_distance: float = 1e-3):
        self.transport = transport
        self.context = dict(context or {})
        reject_inline_secrets(self.context)
        self.store = run_store
        if not math.isfinite(min_diversity_distance) or min_diversity_distance < 0:
            raise ValueError("min_diversity_distance must be finite and non-negative")
        self.min_diversity_distance = min_diversity_distance
        self.used_tasks = set()

    def _request(self, payload: dict, *, archive_prefix: str = "") -> Mapping:
        task = payload["task"]
        request_key = archive_prefix + task
        if request_key in self.used_tasks:
            raise ValueError("each LLM task may be requested only once per run")
        self.used_tasks.add(request_key)
        store = self.store
        transport = self.transport
        if archive_prefix and store:
            parent_store = store
            class ScopedStore:
                path = parent_store.path / archive_prefix
                def write_json(inner, relative_path, value):
                    return parent_store.write_json(archive_prefix + relative_path, value)
                def append_event(inner, event):
                    parent_store.append_event({**event, "request_archive_prefix": archive_prefix})
            store = ScopedStore()
            if isinstance(transport, HttpJsonTransport):
                transport = copy(transport)
                transport.store = store
        prompt_name = {"warm_start": "warm_start", "warm_start_select": "warm_start_select",
                       "rate_parameter_groups": "parameter_groups", "region_preference": "region_preference",
                       "lengthscale_prior": "lengthscale_prior"}[task]
        if task in {'warm_start','warm_start_select'} and self.context.get('initialization_policy') == 'quality_feedback':
            prompt_name += '_quality'
            if self.context.get('staged_screening',{}).get('policy') == 'two_complete_then_quality':
                prompt_name = prompt_name.removesuffix('_quality') + '_staged'
        instructions = resources.files("llmbo_para").joinpath(f"prompts/{prompt_name}.txt").read_text(encoding="utf-8")
        payload = {**payload, "context": self.context, "instructions": instructions,
                   "prompt_sha256": hashlib.sha256(instructions.encode("utf-8")).hexdigest()}
        if store:
            store.write_json(f"llm/{task}.request.json", payload)
        try:
            response = dict(transport.post(payload))
            reject_inline_secrets(response, "response")
        except Exception as exc:
            if store:
                store.write_json(f"llm/{task}.error.json", {"error_type": type(exc).__name__})
            raise RuntimeError(f"LLM {task} failed ({type(exc).__name__}); transport error text omitted to protect credentials") from None
        if store:
            store.write_json(f"llm/{task}.response.json", response)
        try:
            return self._content(response)
        except (ValueError, TypeError) as exc:
            if store:
                store.write_json(f"llm/{task}.error.json", {"error_type":type(exc).__name__, "stage":"content_decoding"})
            raise ValueError("LLM content decoding failed; see archived response") from None

    @staticmethod
    def _content(response: Mapping) -> Mapping:
        content = response.get("content", response)
        if isinstance(content, str):
            content = json.loads(content)
        if not isinstance(content, Mapping):
            raise ValueError("structured LLM response must be a JSON object")
        return content

    def region_preference(self, space: ParameterSpace, records, *, iteration: int, settings):
        """Bounded, per-iteration JSON requests; the same transport and archives.

        A schema repair can repeat once. Transport failures are visible to the
        optimizer, which falls back for that iteration rather than inventing a
        region. A later iteration can try again with new observations.
        """
        from .informed import observation_summary, validate_region_response
        if type(iteration) is not int or iteration < 0:
            raise ValueError("region request iteration must be a nonnegative integer")
        payload = {"task":"region_preference", "iteration":iteration,
            "parameter_order":[s.name for s in space.specs], "units":[s.unit for s in space.specs],
            "bounds":[[s.lower,s.upper] for s in space.specs], "transforms":[s.transform for s in space.specs],
            "physical_constraints":{"negative_porosity":space.negative_porosity,"positive_porosity":space.positive_porosity},
            "objective":"minimize the arithmetic mean of four complete measured-grid RMSEs (V)",
            "observations":observation_summary(space, records),
            "region_policy":{"min_width":settings.min_width,"max_width":settings.max_width},
            "response_schema":{"kind":"region or none", "coordinate_space":"normalized", "lb":"six normalized numbers, region only",
                "ub":"six normalized numbers, region only", "confidence":"number in [0,1]", "reason":"short rationale"}}
        for attempt in range(1, 3):
            prefix = f"informed-requests/iteration-{iteration:06d}/attempt-{attempt:03d}/"
            self.last_region_request = {"iteration":iteration,"attempts":attempt,"archive_prefix":prefix,"valid_response":False}
            response = self._request(payload, archive_prefix=prefix)
            try:
                validated = validate_region_response(response)
                reason = None
            except ValueError as exc:
                reason = str(exc)
            validation = {"valid_response":reason is None, "reason":reason}
            if self.store:
                self.store.write_json(prefix+"validation.json", validation)
            if reason is None:
                self.last_region_request["valid_response"] = True
                return validated
            payload = {**payload, "contract_repair":{"previous_response":response,"error":reason,
                "instruction":"Correct the JSON schema only, or explicitly abstain using kind=none. Never invent missing parameter values."}}
        raise ValueError("region JSON contract failed after two archived attempts")

    def warm_start(self, space: ParameterSpace, count: int = 10) -> tuple[tuple[float, ...], ...]:
        if count < 1:
            raise ValueError("warm-start count must be positive")
        response = self._request({
            "task": "warm_start",
            "rates": list(RATE_ORDER),
            "physical_constraints": {"negative_porosity": space.negative_porosity, "positive_porosity": space.positive_porosity},
            "parameter_order": [s.name for s in space.specs],
            "units": [s.unit for s in space.specs],
            "bounds": [[s.lower, s.upper] for s in space.specs],
            "transforms": [s.transform for s in space.specs],
            "requested_count": count,
            "response_schema": {"candidates": [{"parameters": "six finite numbers"}]},
        })
        candidates = response.get("candidates")
        if not isinstance(candidates, list):
            raise ValueError("warm-start response requires a candidates list")
        valid, seen, rejected, original_indices = [], set(), [], {}
        for original_index, row in enumerate(candidates):
            if not isinstance(row, Mapping) or not isinstance(row.get("parameters"), list):
                rejected.append({"index": original_index, "reason": "invalid_candidate_shape"})
                continue
            try:
                values = space.validate(row["parameters"])
            except (TypeError, ValueError) as exc:
                rejected.append({"index": original_index, "reason": str(exc)})
                continue
            key = tuple(round(v, 12) for v in space.normalize(values))
            if key not in seen:
                seen.add(key)
                valid.append(values)
                original_indices[values] = original_index
            else:
                rejected.append({"index": original_index, "reason": "duplicate_normalized_vector"})
        chosen = []
        while valid and len(chosen) < count:
            if not chosen:
                chosen.append(valid.pop(0))
                continue
            def separation(point):
                normalized = space.normalize(point)
                return min(math.sqrt(sum((a-b)**2 for a, b in zip(normalized, space.normalize(other)))) for other in chosen)
            index = max(range(len(valid)), key=lambda i: separation(valid[i]))
            if separation(valid[index]) < self.min_diversity_distance:
                break
            chosen.append(valid.pop(index))
        self.last_warm_statistics = {"received": len(candidates), "accepted_for_selection": len(chosen),
            "rejected_invalid_or_duplicate": len(rejected), "unused_diversity_or_limit": len(candidates)-len(rejected)-len(chosen)}
        # Keep rejected numeric proposals available to bounded Agent feedback;
        # older callers and the immutable accepted-file schema stay unchanged.
        self.last_warm_rejections = [{**row, "parameters": candidates[row["index"]].get("parameters")
            if isinstance(candidates[row["index"]], Mapping) else None} for row in rejected]
        self.last_warm_rejections.extend({"parameters":list(point), "reason":"minimum_diversity_or_response_limit"}
            for point in valid)
        if self.store:
            self.store.write_json("llm/warm_start.accepted.json", {"parameters": chosen, "original_indices": [original_indices[point] for point in chosen],
                "rejections": rejected, "statistics": self.last_warm_statistics, "min_diversity_distance": self.min_diversity_distance})
        return tuple(chosen)

    def select_warm_start(self, space: ParameterSpace, candidates: Sequence[Sequence[float]], count: int):
        """Ask the LLM to select existing proposals; never accept invented points."""
        pool = [space.validate(point) for point in candidates]
        if type(count) is not int or count < 1 or len(pool) < count:
            raise ValueError("warm-start selection requires enough legal proposals for the requested initial set")
        payload = {"task": "warm_start_select", "rates": list(RATE_ORDER),
            "parameter_order": [spec.name for spec in space.specs],
            "units": [spec.unit for spec in space.specs],
            "bounds": [[spec.lower, spec.upper] for spec in space.specs],
            "transforms": [spec.transform for spec in space.specs],
            "physical_constraints": {"negative_porosity": space.negative_porosity, "positive_porosity": space.positive_porosity},
            "candidates": [{"index": index, "parameters": point} for index, point in enumerate(pool)],
            "requested_count": count, "response_schema": {"selected_indices": "exactly requested_count unique zero-based integers"}}
        if "warm_start_select" in self.used_tasks:
            raise ValueError("each LLM task may be requested only once per run")
        self.used_tasks.add("warm_start_select")
        self.last_selection_request_attempts = 0
        for attempt in range(1, 4):
            prefix = f"llm-attempts/warm_start_select/attempt-{attempt:03d}/"
            self.last_selection_request_attempts = attempt
            response = self._request(payload, archive_prefix=prefix)
            indices = response.get("selected_indices")
            reason = None
            if not isinstance(indices, list):
                reason = "selected_indices_must_be_a_list"
            elif len(indices) != count:
                reason = "wrong_selected_count"
            elif any(isinstance(index, bool) or not isinstance(index, int) or index < 0 or index >= len(pool) for index in indices):
                reason = "index_out_of_range_or_not_integer"
            elif len(set(indices)) != count:
                reason = "duplicate_index"
            self.last_selection_validation = {"valid_response": reason is None, "reason": reason,
                "requested_count": count, "pool_size": len(pool), "received_count": len(indices) if isinstance(indices, list) else None,
                "attempt": attempt}
            if self.store:
                self.store.write_json(prefix + "validation.json", self.last_selection_validation)
                self.store.append_event({"type": "llm_selection_attempt_validation", **self.last_selection_validation})
            if reason is None:
                break
            payload = {**payload, "contract_repair": {"previous_response": response,
                "validation": self.last_selection_validation,
                "instruction": "Correct only the index contract. Return exactly requested_count distinct integer indices from the unchanged candidates list. Do not invent or alter candidate parameters."}}
        if self.store:
            for kind in ("llm", "http"):
                for suffix in ("request.json", "response.json"):
                    source = self.store.path / prefix / kind / ("warm_start_select." + suffix)
                    if source.exists():
                        self.store.write_json(kind + "/warm_start_select." + suffix, json.loads(source.read_text(encoding="utf-8")))
            self.store.write_json("llm/warm_start_select.validation.json", self.last_selection_validation)
        if reason is not None:
            raise ValueError("LLM must select the requested number of distinct existing candidate indices")
        selected = tuple(pool[index] for index in indices)
        if self.store:
            self.store.write_json("llm/warm_start_select.accepted.json", {"selected_indices": indices, "parameters": selected})
        return selected

    def parameter_groups(self, space: ParameterSpace, observations: Sequence[Mapping]) -> dict[str, tuple[str, ...]]:
        allowed_observation_keys = {"parameters", "rmse_v", "residual_summary"}
        safe_observations = []
        for observation in observations:
            if not isinstance(observation, Mapping) or set(observation) - allowed_observation_keys:
                raise ValueError("LLM observations may contain only parameters, RMSE and derived residual summaries")
            if "parameters" not in observation or "rmse_v" not in observation:
                raise ValueError("each LLM observation needs parameters and rmse_v")
            parameters = space.validate(observation["parameters"])
            errors = observation["rmse_v"]
            if not isinstance(errors, Mapping) or set(errors) != set(RATE_ORDER):
                raise ValueError("rmse_v must contain exactly four scalar rate errors")
            if any(isinstance(v, (bool, list, dict)) or not math.isfinite(float(v)) or float(v) < 0 for v in errors.values()):
                raise ValueError("RMSE must contain only finite non-negative scalars")
            safe = {"parameters": parameters, "rmse_v": {r: float(errors[r]) for r in RATE_ORDER}}
            if "residual_summary" in observation:
                summaries = observation["residual_summary"]
                permitted = {"n_points", "mean_v", "rmse_v", "max_abs_v", "early_mean_v", "late_mean_v"}
                if not isinstance(summaries, Mapping) or set(summaries) != set(RATE_ORDER):
                    raise ValueError("residual summaries need exactly the four rates")
                for summary in summaries.values():
                    if not isinstance(summary, Mapping) or set(summary) - permitted:
                        raise ValueError("residual summaries may contain only approved scalar statistics")
                    if any(isinstance(v, (bool, list, dict, tuple)) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in summary.values()):
                        raise ValueError("residual summaries may contain only finite scalar statistics")
                safe["residual_summary"] = {r: dict(summaries[r]) for r in RATE_ORDER}
            safe_observations.append(safe)
        payload = {
            "task": "rate_parameter_groups",
            "parameter_order": [s.name for s in space.specs],
            "units": [s.unit for s in space.specs],
            "bounds": [[s.lower, s.upper] for s in space.specs],
            "rates": list(RATE_ORDER),
            "observations": safe_observations,
            "group_constraints": {"maximum_nonempty_group_size": len(space.specs) - 1,
                                  "allow_empty_abstention": True, "all_six_parameters_is_invalid": True},
            "response_schema": {"groups": {rate: ["parameter names"] for rate in RATE_ORDER}},
        }
        if "rate_parameter_groups" in self.used_tasks:
            raise ValueError("each LLM task may be requested only once per run")
        self.used_tasks.add("rate_parameter_groups")
        for attempt in range(1, 4):
            prefix = f"llm-attempts/rate_parameter_groups/attempt-{attempt:03d}/"
            response = self._request(payload, archive_prefix=prefix)
            output = self._validate_parameter_groups(space, response)
            if self.store:
                self.store.write_json(prefix + "validation.json", self.last_group_validation)
                self.store.append_event({"type": "llm_group_attempt_validation", "attempt": attempt, **self.last_group_validation})
            if self.last_group_validation["valid_response"]:
                break
            payload = {**payload, "contract_repair": {"previous_response": response,
                "validation": self.last_group_validation,
                "instruction": "Correct only contract errors. Copy names verbatim from parameter_order; do not invent or silently replace names. Return all four groups again, or explicit [] if evidence is insufficient."}}
        self.last_group_validation["request_attempts"] = attempt
        if self.store:
            # Canonical paths identify the final response; every rejected attempt stays immutable.
            for kind in ("llm", "http"):
                for suffix in ("request.json", "response.json"):
                    source = self.store.path / prefix / kind / ("rate_parameter_groups." + suffix)
                    if source.exists():
                        self.store.write_json(kind + "/rate_parameter_groups." + suffix, json.loads(source.read_text(encoding="utf-8")))
            self.store.write_json("llm/rate_parameter_groups.validation.json", self.last_group_validation)
            self.store.write_json("llm/rate_parameter_groups.accepted.json", output)
            self.store.append_event({"type": "llm_group_validation", **self.last_group_validation})
        return output

    def _validate_parameter_groups(self, space: ParameterSpace, response: Mapping):
        groups = response.get("groups")
        if not isinstance(groups, Mapping):
            raise ValueError("group response requires a groups object")
        allowed = {s.name for s in space.specs}
        output, diagnostics = {}, {}
        for rate in RATE_ORDER:
            names = groups.get(rate, [])
            reason = None
            if rate not in groups:
                reason = "missing_rate"
            elif not isinstance(names, list):
                reason = "group_must_be_a_list"
            elif any(not isinstance(name, str) or name not in allowed for name in names):
                reason = "unknown_parameter_name"
            elif len(set(names)) >= len(space.specs):
                reason = "all_six_parameters_not_a_subset"
            if reason:
                output[rate], status = (), "rejected"
            else:
                unique = tuple(dict.fromkeys(names))
                output[rate] = unique
                status = "accepted" if unique else "abstained"
                reason = "valid_subset" if unique else "explicit_empty_group"
            diagnostics[rate] = {"status": status, "reason": reason,
                                 "requested_count": len(names) if isinstance(names, list) else None,
                                 "accepted_count": len(output[rate])}
        invalid_rates = [rate for rate, item in diagnostics.items() if item["status"] == "rejected"]
        unexpected_rates = sorted(str(rate) for rate in set(groups) - set(RATE_ORDER))
        self.last_group_validation = {"valid_response": not invalid_rates and not unexpected_rates,
                                      "invalid_rates": invalid_rates, "unexpected_rates": unexpected_rates,
                                      "maximum_nonempty_group_size": len(space.specs) - 1, "rates": diagnostics}
        return output
