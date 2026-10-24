"""Configured stream controls, including actual owned offline HTTP workers."""
from copy import deepcopy
import io
import json
import time
from types import SimpleNamespace

import pytest

from test_electrothermal_responses import payload, feature, response
from test_electrothermal_responses_requests import config, store, ENV


def stream_worker(mode, spec, sent, run_path, connection, *, entry=None):
    from unittest.mock import patch
    from llmbo_para.electrothermal_responses import _responses_request_worker

    class HTTPResponse:
        status = 200
        def __init__(self, body):
            wire = json.loads(body['input'])
            formal = ({k: wire[k] for k in ('schema_version','parameter_profile','fit_rates','signatures')}
                      if 'request_id' not in wire else {})
            if 'request_id' in wire:
                formal = {'request_id':wire['request_id'], 'region':{'kind':'region',
                    'lb':[.3]*6,'ub':[.8]*6,'confidence':.65}}
            elif wire['task'] == 'warm_start_electrothermal':
                formal['candidates'] = []
            else:
                formal['context_id'] = wire['context_id']
                formal['region'] = {'kind':'none','coordinate_space':'normalized','confidence':0.,'reason':'unit'}
            raw = response(formal)
            self.streaming = body['stream']
            if mode == 'partial':
                self.data = io.BytesIO(b'data: {"type":"response.created","sequence_number":0}\n\n')
                return
            self.data = io.BytesIO((
                'event: response.completed\ndata: '+json.dumps({'type':'response.completed',
                    'sequence_number':2,'response':raw})+'\n\n'
                if self.streaming else json.dumps(raw)).encode())

        def getheader(self, name, default=None):
            return ('text/event-stream; charset=utf-8' if self.streaming else 'application/json') if name.lower() == 'content-type' else default
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, count): return self.data.read(count)
        def read1(self, count):
            if mode == 'stall': time.sleep(10)
            return self.data.read(min(count,7))

    class Provider:
        def open(self, request, **kwargs):
            body = json.loads(request.data)
            assert body['stream'] is (spec.get('responses_stream') is True)
            return HTTPResponse(body)

    with patch('llmbo_para.llm.build_opener', return_value=Provider()):
        (entry or _responses_request_worker)(spec, sent, run_path, connection)


def successful_stream_worker(*args): stream_worker('success', *args)
def stalled_stream_worker(*args): stream_worker('stall', *args)


@pytest.mark.parametrize('configured', [False, True])
def test_global_stream_control_is_boolean_and_shared(configured):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    cfg = config(); cfg['llm'].update(responses_stream=configured, reasoning_effort='none')
    before = deepcopy(cfg)
    assert electrothermal_configuration_errors(cfg) == []
    for task in ('warm_start_electrothermal','region_preference_electrothermal'):
        assert request_controls(cfg, task)['responses_stream'] is configured
    assert cfg == before


@pytest.mark.parametrize('invalid', [None, 0, 1, 'true', [], {}])
def test_invalid_stream_config_is_rejected_while_disabled(invalid):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    cfg = config(); cfg['llm'].update(enabled=False, responses_stream=invalid)
    assert electrothermal_configuration_errors(cfg)
    with pytest.raises(ValueError): request_controls(cfg, 'warm_start_electrothermal')


def test_stream_cannot_leak_into_chat_schema1_or_task_options():
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    from llmbo_para.config import configuration_errors
    from llmbo_para.synthetic import synthetic_config
    cfg = config(); cfg['llm'].update(transport='openai_chat_completions', responses_stream=False)
    assert electrothermal_configuration_errors(cfg)
    with pytest.raises(ValueError): request_controls(cfg, 'warm_start_electrothermal')
    for task in ('warm_start_electrothermal','region_preference_electrothermal'):
        cfg = config(); cfg['llm']['task_options'] = {task:{'responses_stream':True}}
        assert electrothermal_configuration_errors(cfg)
        with pytest.raises(ValueError): request_controls(cfg, task)
    cfg = synthetic_config(); cfg['llm']['responses_stream'] = False
    assert configuration_errors(cfg)


@pytest.mark.parametrize('configured', [None, False, True])
def test_stream_is_the_only_wire_difference(configured):
    module = feature()
    kwargs = dict(model='deepseek-v4-pro', max_tokens=8192, json_mode=True, reasoning_effort='none')
    p = payload(); before = deepcopy(p)
    old = module.responses_request_body(p, **kwargs)
    actual = module.responses_request_body(p, **kwargs, responses_stream=configured)
    assert actual == {**old, 'stream':configured is True}
    assert actual['store'] is False and p == before


@pytest.mark.parametrize('invalid', [0, 1, 'true', [], {}])
def test_constructor_and_serializer_reject_non_boolean_stream(invalid):
    with pytest.raises(ValueError):
        feature().ResponsesTransport('https://provider.invalid/v1/responses', ENV,
            model='deepseek-v4-pro', max_tokens=8192, json_mode=True, responses_stream=invalid)
    with pytest.raises(ValueError):
        feature().responses_request_body(payload(), model='deepseek-v4-pro', max_tokens=8192,
            json_mode=True, responses_stream=invalid)


@pytest.mark.parametrize('task', ['warm_start_electrothermal','region_preference_electrothermal'])
@pytest.mark.parametrize('configured', [None, False, True])
def test_clone_and_spawn_use_config_not_injected_hidden_stream(monkeypatch,tmp_path,task,configured):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    module = feature(); cfg = config()
    if configured is not None: cfg['llm']['responses_stream'] = configured
    monkeypatch.setenv(ENV,'offline-stream-unit-placeholder')
    monkeypatch.setattr(module,'_responses_request_worker',successful_stream_worker)
    archive = store(tmp_path,cfg)
    injected = module.ResponsesTransport(cfg['llm']['endpoint'],ENV,
        model=cfg['llm']['model'],max_tokens=1536,json_mode=True,responses_stream=configured is not True)
    controller = ElectrothermalLLMController(transport=injected)
    assert controller.request(payload(task),prepared=SimpleNamespace(config=cfg),store=archive,
        budgets=cfg['budgets'],request_cap=1) is not None, controller.last_request_outcome
    outcome = controller.last_request_outcome
    body = json.loads(next((archive.path/'http').glob('*.request.json')).read_text())['body']
    supervision = json.loads(next((archive.path/'http').glob('*.supervision.json')).read_text())
    assert body['stream'] is (configured is True)
    for item in (outcome,supervision):
        assert ('responses_stream' in item) == (configured is not None)
        if configured is not None: assert item['responses_stream'] is configured
    assert injected.responses_stream is (configured is not True)
    assert controller.requests == 1 and outcome['hard_deadline_enforced']


@pytest.mark.parametrize('reason',['disabled','global_budget','missing_credential'])
def test_inactive_stream_calls_do_not_construct_transport(monkeypatch,tmp_path,reason):
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    cfg = config(); cfg['llm']['responses_stream'] = True
    monkeypatch.delenv(ENV,raising=False)
    if reason == 'disabled': cfg['llm']['enabled'] = False
    if reason == 'global_budget': cfg['budgets']['max_llm_requests'] = 0
    monkeypatch.setattr(requests,'electrothermal_transport_class',lambda *a:pytest.fail('inactive constructed'))
    controller = ElectrothermalLLMController(); archive = store(tmp_path,cfg)
    assert controller.request(payload(),prepared=SimpleNamespace(config=cfg),store=archive,
        budgets=cfg['budgets'],request_cap=1) is None
    assert controller.last_request_outcome['reason'] == reason
    assert controller.last_request_outcome['responses_stream'] is True and controller.requests == 0


def test_stream_retains_whole_request_hard_deadline(monkeypatch,tmp_path):
    from llmbo_para.electrothermal_requests import LLMRequestFailure
    module = feature()
    monkeypatch.setenv(ENV,'offline-stream-unit-placeholder')
    monkeypatch.setattr(module,'_responses_request_worker',stalled_stream_worker)
    archive = store(tmp_path,config())
    client = module.BoundedResponsesTransport('https://provider.invalid/v1/responses',ENV,
        model='deepseek-v4-pro',max_tokens=1536,json_mode=True,responses_stream=True,
        timeout_s=3.,run_store=archive)
    started = time.monotonic()
    with pytest.raises(LLMRequestFailure) as exc: client.post(payload())
    assert time.monotonic()-started < 6. and exc.value.kind == 'deadline_exceeded'
    assert exc.value.diagnostic['responses_stream'] is True
    assert len(list((archive.path/'http').glob('*.request.json'))) == 1
