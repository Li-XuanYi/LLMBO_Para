"""Responses routing and real spawn supervision with an offline HTTP provider."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import multiprocessing
import time

import pytest

from electrothermal_fixtures import et_config
from test_electrothermal_responses import payload, response, feature


ENV = 'RESPONSES_OFFLINE_TEST_CREDENTIAL'


def config():
    cfg = et_config()
    cfg['llm'].update(transport='openai_responses', enabled=True,
        endpoint='https://provider.invalid/v1/responses', api_key_env=ENV,
        model='deepseek-v4-pro', max_tokens=1536, timeout_s=30.)
    cfg['budgets']['max_llm_requests'] = 2
    return cfg


def offline_worker(mode, spec, sent, run_path, connection):
    """Patches only the spawned child's HTTP boundary, never the parent parser."""
    import os
    from unittest.mock import patch
    from llmbo_para.electrothermal_responses import _responses_request_worker
    if mode == 'startup':
        time.sleep(10)
    class HTTPResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, count):
            if mode == 'body': time.sleep(10)
            wire = self.wire
            if wire['task'] == 'warm_start_electrothermal':
                formal = {k: wire[k] for k in ('schema_version', 'parameter_profile', 'fit_rates', 'signatures')}
                formal['candidates'] = []
            else:
                region = {'kind': 'none', 'coordinate_space': 'normalized', 'confidence': .7,
                          'reason': os.environ[spec['api_key_env']]}
                if wire.get('region_proposal') == 'catalog_v1':
                    region['proposal_binding'] = wire['proposal_binding']
                formal = ({'request_id': wire['request_id'], 'region': region} if 'request_id' in wire else
                    {**{k: wire[k] for k in ('schema_version', 'parameter_profile', 'fit_rates', 'signatures', 'context_id')}, 'region': region})
            raw = response(formal, usage={'input_tokens': 50, 'output_tokens': 20, 'total_tokens': 70})
            if mode == 'incomplete': raw['status'] = 'incomplete'
            return json.dumps(raw).encode()[:count]
    class Provider:
        def open(self, request, **kwargs):
            if mode == 'headers': time.sleep(10)
            wire = json.loads(request.data)
            assert wire['store'] is wire['stream'] is False
            assert 'thinking' not in wire and 'messages' not in wire
            result = HTTPResponse()
            result.wire = json.loads(wire['input'])
            return result
    with patch('llmbo_para.llm.build_opener', return_value=Provider()):
        _responses_request_worker(spec, sent, run_path, connection)


def successful_responses_worker(*args): offline_worker('success', *args)
def startup_stall_worker(*args): offline_worker('startup', *args)
def headers_stall_worker(*args): offline_worker('headers', *args)
def body_stall_worker(*args): offline_worker('body', *args)
def incomplete_responses_worker(*args): offline_worker('incomplete', *args)


def store(tmp_path, cfg):
    from llmbo_para.runstore import RunStore
    from llmbo_para.electrothermal_store import CostLedger
    result = RunStore(tmp_path, cfg, command='offline Responses supervision test')
    result.ledger = CostLedger(result)
    return result


def bounded(*, archive=None, timeout=30.):
    module = feature()
    assert hasattr(module, 'BoundedResponsesTransport'), 'Responses owned-process supervision missing'
    return module.BoundedResponsesTransport('https://provider.invalid/v1/responses', ENV,
        model='deepseek-v4-pro', max_tokens=1536, json_mode=True, timeout_s=timeout, run_store=archive)


def test_v2_default_chat_and_explicit_responses():
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = config()
    assert electrothermal_configuration_errors(cfg) == []
    assert hasattr(requests, 'electrothermal_transport_class')
    assert requests.electrothermal_transport_class(cfg).__name__ == 'BoundedResponsesTransport'
    old = et_config(); before = deepcopy(old)
    assert requests.electrothermal_transport_class(old) is requests.BoundedChatCompletionsTransport
    assert old == before


@pytest.mark.parametrize('change', [{'transport': 'unknown'}, {'transport': None}, {'transport': []},
    {'endpoint': 'https://provider.invalid/v1/chat/completions'},
    {'transport': 'openai_chat_completions'}, {'endpoint': 'http://provider.invalid/v1/responses'}])
def test_transport_endpoint_mismatch_and_unknown_rejected(change):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = config(); cfg['llm'].update(change)
    assert electrothermal_configuration_errors(cfg)


@pytest.mark.parametrize('task', [None, 'warm_start_electrothermal', 'region_preference_electrothermal'])
def test_responses_thinking_requires_confirmed_mapping(task):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = config()
    if task is None: cfg['llm']['thinking'] = 'disabled'
    else: cfg['llm']['task_options'] = {task: {'thinking': 'disabled'}}
    assert any('thinking' in e.lower() for e in electrothermal_configuration_errors(cfg))


def test_v1_does_not_inherit_responses_transport():
    from llmbo_para.synthetic import synthetic_config
    from llmbo_para.config import configuration_errors
    cfg = synthetic_config(); cfg['optimization']['llm_enabled'] = True
    cfg['llm'].update(transport='openai_responses', endpoint='https://provider.invalid/v1/responses',
                      model='deepseek-v4-pro', api_key_env=ENV, max_tokens=1536, json_mode=True)
    assert configuration_errors(cfg)


@pytest.mark.parametrize('reason', ['disabled', 'global_budget', 'missing_credential'])
def test_disabled_zero_budget_and_missing_key_never_open_http(monkeypatch, tmp_path, reason):
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    assert hasattr(requests, 'electrothermal_transport_class'), 'transport selector missing'
    cfg = config()
    monkeypatch.delenv(ENV, raising=False)
    if reason == 'disabled': cfg['llm']['enabled'] = False
    if reason == 'global_budget': cfg['budgets']['max_llm_requests'] = 0
    def forbidden(*args, **kwargs): pytest.fail('inactive request must not select or instantiate any transport')
    monkeypatch.setattr(requests, 'electrothermal_transport_class', forbidden)
    controller = ElectrothermalLLMController()
    archive = store(tmp_path, cfg)
    assert controller.request(payload(), prepared=SimpleNamespace(config=cfg), store=archive,
                              budgets=cfg['budgets'], request_cap=1) is None
    assert controller.last_request_outcome['reason'] == reason
    assert controller.requests == archive.ledger.summary()['llm_requests'] == 0


@pytest.mark.parametrize('mode,worker', [('startup', startup_stall_worker), ('headers', headers_stall_worker), ('body', body_stall_worker)])
def test_response_worker_deadline_no_retry(monkeypatch, tmp_path, mode, worker):
    from llmbo_para.electrothermal_requests import LLMRequestFailure
    module = feature()
    assert hasattr(module, '_responses_request_worker'), 'Responses worker missing'
    monkeypatch.setattr(module, '_responses_request_worker', worker)
    monkeypatch.setenv(ENV, 'offline-responses-unit-credential')
    archive = store(tmp_path, config())
    before = {p.pid for p in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(LLMRequestFailure) as failure:
        bounded(archive=archive, timeout=3.).post(payload())
    assert time.monotonic() - started < 6.
    assert failure.value.kind == 'deadline_exceeded'
    assert failure.value.diagnostic['http_request_started'] == (mode != 'startup')
    assert failure.value.diagnostic['response_protocol'] == 'openai_responses'
    if mode == 'body': assert failure.value.diagnostic['failure_stage'] == 'reading_body'
    assert {p.pid for p in multiprocessing.active_children()} <= before
    events = [json.loads(s) for s in archive.events_path.read_text().splitlines()]
    assert sum(e['type'] == 'llm_http_started' for e in events) == int(mode != 'startup')


@pytest.mark.parametrize('task', ['warm_start_electrothermal', 'region_preference_electrothermal'])
def test_controller_selects_responses_worker_and_archives_real_status(monkeypatch, tmp_path, task):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    module = feature()
    assert hasattr(module, '_responses_request_worker'), 'Responses worker missing'
    monkeypatch.setattr(module, '_responses_request_worker', successful_responses_worker)
    monkeypatch.setenv(ENV, 'offline-responses-unit-credential')
    cfg = config(); archive = store(tmp_path, cfg)
    controller = ElectrothermalLLMController()
    result = controller.request(payload(task), prepared=SimpleNamespace(config=cfg), store=archive,
                                budgets=cfg['budgets'], request_cap=1)
    assert result is not None, controller.last_request_outcome
    outcome = controller.last_request_outcome
    assert outcome['hard_deadline_enforced'] and outcome['http_request_started']
    assert outcome['response_protocol'] == 'openai_responses'
    assert outcome['completion']['response_status'] == 'completed'
    assert outcome['completion']['input_tokens'] == 50 and 'finish_reason' not in outcome['completion']
    assert controller.requests == archive.ledger.summary()['llm_requests'] == 1
    assert len(list((archive.path / 'http').glob('*.request.json'))) == 1
    for path in (archive.path / 'http').glob('*.json'):
        assert 'offline-responses-unit-credential' not in path.read_text()


def test_response_completion_dispatch_is_explicit_and_preserves_chat_shape():
    from llmbo_para.electrothermal_requests import completion_summary
    raw = response({'answer': 42})
    new = completion_summary(raw, 1536, transport='openai_responses')
    assert new == feature().responses_completion_summary(raw, 1536)
    chat = {'choices': [{'finish_reason': 'stop', 'message': {'content': '{}'}}]}
    assert completion_summary(chat, 1536) == {'finish_reason': 'stop', 'answer_characters': 2, 'state': 'complete_answer'}
    assert completion_summary(chat, 1536, transport='openai_responses')['state'] != 'complete_answer'
