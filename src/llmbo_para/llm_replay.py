"""Strict replay of an archived group reply for paired numerical experiments.

No network access, no synthetic replacement, and no claim of a fresh LLM call.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from .runstore import digest_value, reject_inline_secrets, sha256_file

SIGNATURE_FIELDS = ("task", "parameter_order", "units", "bounds", "rates", "observations", "context", "prompt_sha256")


def group_request_signature(payload):
    return digest_value({key: payload.get(key) for key in SIGNATURE_FIELDS})


class ArchivedGroupTransport:
    def __init__(self, evidence, *, expected_model, run_store=None):
        if not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}:
            raise ValueError("archived reply evidence requires path and sha256")
        path = Path(evidence["path"])
        if not path.is_absolute() or not path.is_file() or sha256_file(path) != evidence["sha256"]:
            raise ValueError("archived reply path or hash mismatch")
        self.raw_bytes = path.read_bytes()
        self.packet = json.loads(self.raw_bytes.decode("utf-8"))
        reject_inline_secrets(self.packet, "archived_reply")
        packet = self.packet
        if packet.get("schema_version") != 1 or packet.get("task") != "rate_parameter_groups":
            raise ValueError("unsupported archived reply task/schema")
        if packet.get("source_kind") not in {"archived_real_llm_response", "synthetic_software_fixture"}:
            raise ValueError("archived reply must declare its real or synthetic provenance")
        if packet.get("model") != expected_model:
            raise ValueError("archived reply model differs from the configured model")
        if not isinstance(packet.get("source_request"), dict) or not isinstance(packet.get("source_response"), dict):
            raise ValueError("archived reply requires its original request and response")
        if packet["source_request"].get("task") != "rate_parameter_groups":
            raise ValueError("archived source request is not a group task")
        sources = packet.get("source_files")
        if not isinstance(sources, list) or len(sources) < 2:
            raise ValueError("archived reply requires source-file fingerprints")
        verified_contents = []
        for source in sources:
            source_path = Path(source["path"])
            if not source_path.is_file() or sha256_file(source_path) != source["sha256"]:
                raise ValueError("archived reply source-file hash mismatch")
            verified_contents.append(json.loads(source_path.read_text(encoding="utf-8")))
        if packet["source_request"] not in verified_contents or packet["source_response"] not in verified_contents:
            raise ValueError("archived reply content differs from verified original request/response")
        self.evidence = dict(evidence)
        self.store = run_store
        self.signature = group_request_signature(packet["source_request"])
        if self.store:
            target = self.store.path / "inputs/parameter-groups-replay.json"
            target.parent.mkdir(exist_ok=True)
            with target.open("xb") as output:
                output.write(self.raw_bytes)
            if sha256_file(target) != evidence["sha256"]:
                raise ValueError("archived replay copy hash mismatch")

    def post(self, payload):
        if payload.get("task") != "rate_parameter_groups":
            raise ValueError("archived reply cannot execute a different LLM task")
        if group_request_signature(payload) != self.signature:
            raise ValueError("archived reply request signature differs: initial observations, context or prompt changed")
        if self.store:
            self.store.append_event({"type": "llm_archived_reply_replayed", "task": "rate_parameter_groups",
                "evidence_sha256": self.evidence["sha256"], "source_kind": self.packet["source_kind"],
                "source_model": self.packet["model"], "live_api_request": False})
        return copy.deepcopy(self.packet["source_response"])


def audit_group_replay(path, config):
    """Self-contained audit: never needs to reopen old external source paths."""
    path = Path(path)
    expected = config["llm"]["parameter_groups_replay"]
    packet_path = path/"inputs/parameter-groups-replay.json"
    issues = []
    if not packet_path.is_file() or sha256_file(packet_path) != expected["sha256"]:
        return ["archived group replay copy or hash mismatch"]
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    request = json.loads((path/"llm/rate_parameter_groups.request.json").read_text(encoding="utf-8"))
    response = json.loads((path/"llm/rate_parameter_groups.response.json").read_text(encoding="utf-8"))
    if group_request_signature(request) != group_request_signature(packet["source_request"]):
        issues.append("archived group replay used a different initial-observation or prompt signature")
    if response != packet["source_response"]:
        issues.append("archived group reply changed during replay")
    events = [json.loads(line) for line in (path/"events.jsonl").read_text(encoding="utf-8").splitlines()]
    replay_events = [e for e in events if e["type"] == "llm_archived_reply_replayed"]
    if len(replay_events) != 1 or replay_events[0].get("live_api_request") is not False:
        issues.append("archived group replay was not explicitly recorded exactly once")
    if any(e["type"] == "llm_http_started" and e.get("task") == "rate_parameter_groups" for e in events):
        issues.append("archived group replay unexpectedly sent a live API request")
    return issues
