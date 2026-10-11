"""One bounded chat-compatible API request; credentials stay in memory."""

from __future__ import annotations

import argparse
import getpass
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener
from urllib.parse import urlsplit

for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ.setdefault(name, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from llmbo_para.runstore import RunStore


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="glm-5.3-flash")
    parser.add_argument("--base-url", default="https://opencode.ai/zen/v1")
    parser.add_argument("--api-key-env", default="LLMBO_OPENCODE_API_KEY")
    parser.add_argument("--output", type=Path, default=Path("runs/api-probes"))
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--max-tokens", type=int, default=32)
    parser.add_argument("--json-mode", action="store_true")
    parser.add_argument("--list-models", action="store_true")
    args = parser.parse_args()
    parsed = urlsplit(args.base_url)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        parser.error("base URL must be HTTPS without embedded credentials, query or fragment")
    endpoint = args.base_url.rstrip("/") + ("/models" if args.list_models else "/chat/completions")
    if not 0 < args.timeout <= 60:
        parser.error("timeout must be in (0, 60]")
    if not 1 <= args.max_tokens <= 1024:
        parser.error("probe max-tokens must be in [1, 1024]")
    config = {"run_kind": "live_api_connectivity_probe", "endpoint": endpoint,
              "operation": "list_models" if args.list_models else "generation",
              "model": args.model, "api_key_env": args.api_key_env, "timeout_s": args.timeout,
              "maximum_completion_tokens": args.max_tokens, "maximum_requests": 1,
              "json_mode": args.json_mode,
              "credential_storage": "process memory only; no request authentication headers archived",
              "experiment_data_sent": False}
    store = RunStore(args.output, config, command="python " + str(Path(__file__).resolve()) + " " + " ".join(sys.argv[1:]))
    print(json.dumps({"run_directory": str(store.path), "state": "awaiting_transient_credential"}), flush=True)
    key = os.environ.get(args.api_key_env) or getpass.getpass("Temporary API credential (hidden): ")
    if not key or any(char.isspace() for char in key):
        store.finish("preflight_failed", {"reason": "missing or malformed transient credential", "http_requests": 0})
        return 2

    def redact(value):
        if isinstance(value, str):
            return re.sub(r"sk-[A-Za-z0-9_-]{8,}", "[REDACTED]", value.replace(key, "[REDACTED]"))
        if isinstance(value, dict):
            return {name: redact(child) for name, child in value.items()
                    if str(name).lower() not in {"authorization", "api_key", "access_token", "token", "secret"}}
        if isinstance(value, list):
            return [redact(child) for child in value]
        return value

    payload = {"model": args.model, "messages": [
        {"role": "user", "content": 'Connectivity test only. Reply exactly with the JSON object {"ok":true}.'}
    ], "max_tokens": args.max_tokens, "stream": False}
    if args.json_mode:
        payload["response_format"] = {"type": "json_object"}
    store.write_json("request.json", {"method": "GET", "url": endpoint} if args.list_models else payload)
    request = Request(endpoint, data=None if args.list_models else json.dumps(payload).encode("utf-8"),
                      headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                               "User-Agent": "LLMBO-Para-connectivity-probe/1"}, method="GET" if args.list_models else "POST")
    started = time.perf_counter()
    result = {"http_requests": 1, "model": args.model, "endpoint": endpoint,
              "success": False, "experiment_data_sent": False, "credential_archived": False}
    try:
        with build_opener(NoRedirect()).open(request, timeout=args.timeout) as response:
            body = response.read(1024 * 1024 + 1)
            result["http_status"] = response.status
            if len(body) > 1024 * 1024:
                raise ValueError("response exceeds 1 MiB")
            value = json.loads(body)
            store.write_json("response.json", redact(value))
            if args.list_models:
                result.update(success=isinstance(value.get("data"), list),
                              model_ids=[item["id"] for item in value.get("data", [])],
                              model_count=len(value.get("data", [])))
            else:
                content = value["choices"][0]["message"]["content"]
                result.update(success=json.loads(content).get("ok") is True,
                              response_model=value.get("model"), usage=value.get("usage"))
            if not result["success"]:
                result["diagnosis"] = "HTTP succeeded but the requested JSON acknowledgement was not returned"
    except HTTPError as exc:
        body = exc.read(64 * 1024)
        try:
            error = json.loads(body)
        except (ValueError, UnicodeError):
            error = {"text": body.decode("utf-8", errors="replace")}
        store.write_json("http-error.json", redact(error))
        result.update(http_status=exc.code, error_type="HTTPError")
        details = error.get("error", {}) if isinstance(error, dict) else {}
        provider_type = details.get("type") if isinstance(details, dict) else None
        result["provider_error_type"] = provider_type
        if provider_type == "FreeTierError":
            result["diagnosis"] = "the provider restricts this free model to the OpenCode application; this response alone does not prove credential validity"
        elif exc.code == 401:
            result["diagnosis"] = "provider returned an authentication error; inspect the sanitized response"
        elif exc.code == 403:
            result["diagnosis"] = "provider forbids this request; the sanitized error specifies whether model, account or credential policy applies"
        else:
            result["diagnosis"] = "provider request failed; inspect the sanitized HTTP response before retrying"
    except Exception as exc:
        result.update(error_type=type(exc).__name__, diagnosis=redact(str(exc)))
    result["elapsed_s"] = time.perf_counter() - started
    store.write_json("probe-summary.json", redact(result))
    store.finish("completed" if result["success"] else "failed", redact(result))
    print(json.dumps({"run_directory": str(store.path), **redact(result)}, indent=2), flush=True)
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
