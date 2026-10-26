"""Request-bound candidate replies for electrothermal WarmStart."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re

from .runstore import canonical_json, digest_value, sha256_file


@dataclass(frozen=True)
class WarmStartRequest:
    run_id: str
    ordinal: int
    task: str
    artifact_task: str
    payload_json: bytes
    payload_sha256: str
    identity_sha256: str


@dataclass(frozen=True)
class BoundWarmStartReply:
    response: dict
    receipt: dict
    request: WarmStartRequest


def freeze_warmstart_request(payload: dict, *, run_id: str, ordinal: int) -> WarmStartRequest:
    if (type(payload) is not dict or payload.get('task') != 'warm_start_electrothermal'
            or payload.get('warmstart_wire_format') != 'candidate_only_v1'
            or type(run_id) is not str or not run_id
            or type(ordinal) is not int or ordinal < 0
            or type(payload.get('artifact_task')) is not str
            or not re.fullmatch(r'warm_start_electrothermal_request_[a-z]+', payload['artifact_task'])
            or any(k not in payload for k in ('schema_version', 'parameter_profile', 'fit_rates', 'signatures'))):
        raise ValueError('complete candidate-only WarmStart request required')
    frozen = canonical_json(payload)
    identity = {k: payload[k] for k in ('schema_version', 'parameter_profile', 'fit_rates', 'signatures')}
    return WarmStartRequest(run_id, ordinal, payload['task'], payload['artifact_task'],
                            frozen, digest_value(payload), digest_value(identity))


def bind_warmstart_response(request: WarmStartRequest, decoded_reply: dict, *, store,
                            transport_status: str) -> BoundWarmStartReply:
    if store.run_id != request.run_id or transport_status not in ('completed', 'mock'):
        raise ValueError('WarmStart reply has no matching fresh transport')
    if type(decoded_reply) is not dict:
        raise ValueError('candidate reply must be a JSON object')
    envelope_path = Path(store.path) / 'http' / (request.artifact_task + '.response.json')
    envelope_sha = None
    if transport_status == 'completed':
        if not envelope_path.is_file():
            raise ValueError('fresh WarmStart HTTP envelope missing')
        envelope = json.loads(envelope_path.read_text(encoding='utf8'))
        try:
            content = envelope['choices'][0]['message']['content']
            from_http = json.loads(content) if type(content) is str else content
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError('invalid WarmStart HTTP envelope') from exc
        if digest_value(from_http) != digest_value(decoded_reply):
            raise ValueError('WarmStart reply differs from HTTP envelope')
        envelope_sha = sha256_file(envelope_path)
    receipt = {'version': 'warmstart_candidate_binding_v1', 'run_id': request.run_id,
               'ordinal': request.ordinal, 'task': request.task,
               'artifact_task': request.artifact_task,
               'payload_sha256': request.payload_sha256,
               'identity_sha256': request.identity_sha256,
               'response_sha256': digest_value(decoded_reply),
               'http_envelope_sha256': envelope_sha,
               'transport_status': transport_status}
    store.write_json(f'llm/{request.ordinal:06d}.warmstart-response.json', decoded_reply)
    store.write_json(f'llm/{request.ordinal:06d}.warmstart-binding.json', receipt)
    return BoundWarmStartReply(decoded_reply, receipt, request)


def decode_candidate_only_reply(reply: BoundWarmStartReply, *, prepared,
                                expected_request: WarmStartRequest) -> list[dict]:
    if (type(reply) is not BoundWarmStartReply or type(reply.receipt) is not dict
            or reply.request != expected_request):
        raise ValueError('bound WarmStart reply required')
    request = expected_request
    current_identity = {'schema_version': 2, 'parameter_profile': prepared.space.profile,
                        'fit_rates': list(prepared.dataset.fit_rates),
                        'signatures': asdict(prepared.signatures)}
    receipt = reply.receipt
    if (request.identity_sha256 != digest_value(current_identity)
            or request.payload_sha256 != digest_value(json.loads(request.payload_json))
            or set(receipt) != {'version', 'run_id', 'ordinal', 'task', 'artifact_task',
                                'payload_sha256', 'identity_sha256', 'response_sha256',
                                'http_envelope_sha256', 'transport_status'}
            or receipt['version'] != 'warmstart_candidate_binding_v1'
            or any(receipt[k] != getattr(request, k) for k in ('run_id', 'ordinal', 'task',
                                                                'artifact_task', 'payload_sha256',
                                                                'identity_sha256'))
            or receipt['transport_status'] not in ('completed', 'mock')
            or (receipt['transport_status'] == 'completed') != (type(receipt['http_envelope_sha256']) is str)
            or type(reply.response) is not dict or set(reply.response) != {'candidates'}
            or type(reply.response['candidates']) is not list
            or not reply.response['candidates']
            or len(reply.response['candidates']) > prepared.config['optimization']['warmstart']['max_candidates']
            or receipt['response_sha256'] != digest_value(reply.response)):
        raise ValueError('stale or invalid request-bound WarmStart candidate reply')
    return reply.response['candidates']
