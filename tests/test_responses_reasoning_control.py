"""Explicit requested effort, including real spawned workers with offline HTTP."""
from copy import deepcopy
from types import SimpleNamespace
import json
import time

import pytest

from test_electrothermal_responses import payload, feature
from test_electrothermal_responses_requests import (
    config, store, ENV, successful_responses_worker, headers_stall_worker,
)


@pytest.mark.parametrize('effort', ['none', 'low', 'high', 'max'])
def test_optional_global_effort_is_inherited_by_both_tasks(effort):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    cfg = config()
    cfg['llm']['reasoning_effort'] = effort
    before = deepcopy(cfg)
    assert electrothermal_configuration_errors(cfg) == []
    for task in ('warm_start_electrothermal', 'region_preference_electrothermal'):
        assert request_controls(cfg, task)['reasoning_effort'] == effort
    assert cfg == before


@pytest.mark.parametrize('effort', [None, True, 1, '', 'NONE', 'medium', [], {}])
def test_invalid_config_effort_is_rejected_even_when_disabled(effort):
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    cfg = config()
    cfg['llm'].update(enabled=False, reasoning_effort=effort)
    assert electrothermal_configuration_errors(cfg)
    with pytest.raises(ValueError): request_controls(cfg, 'warm_start_electrothermal')


def test_missing_effort_preserves_legacy_request_and_configuration():
    from llmbo_para.electrothermal_requests import request_controls
    cfg = config()
    before = deepcopy(cfg)
    body = feature().responses_request_body(payload(), model='deepseek-v4-pro', max_tokens=1536, json_mode=True)
    omitted = feature().responses_request_body(payload(), model='deepseek-v4-pro', max_tokens=1536,
                                               json_mode=True, reasoning_effort=None)
    assert omitted == body and 'reasoning' not in body
    assert 'reasoning_effort' not in request_controls(cfg, 'warm_start_electrothermal')
    assert cfg == before


@pytest.mark.parametrize('effort', ['none', 'low', 'high', 'max'])
def test_wire_adds_only_the_native_reasoning_field(effort):
    p = payload()
    original = deepcopy(p)
    settings = dict(model='deepseek-v4-pro', max_tokens=8192, json_mode=True)
    old = feature().responses_request_body(p, **settings)
    actual = feature().responses_request_body(p, **settings, reasoning_effort=effort)
    assert actual == {**old, 'reasoning': {'effort': effort}}
    assert actual['stream'] is actual['store'] is False and p == original


def test_effort_is_responses_v2_only_and_not_a_task_override():
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    from llmbo_para.synthetic import synthetic_config
    from llmbo_para.config import configuration_errors
    for task in ('warm_start_electrothermal', 'region_preference_electrothermal'):
        cfg = config()
        cfg['llm']['task_options'] = {task: {'reasoning_effort': 'none'}}
        assert electrothermal_configuration_errors(cfg)
        with pytest.raises(ValueError): request_controls(cfg, task)
    cfg = config()
    cfg['llm'].update(transport='openai_chat_completions', enabled=False, reasoning_effort='none')
    assert electrothermal_configuration_errors(cfg)
    with pytest.raises(ValueError): request_controls(cfg, 'warm_start_electrothermal')
    old = synthetic_config()
    old['llm']['reasoning_effort'] = 'none'
    assert configuration_errors(old)


def test_effort_does_not_translate_chat_thinking_or_raise_other_limits():
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.electrothermal_requests import request_controls
    cfg = config()
    cfg['llm']['reasoning_effort'] = 'none'
    cfg['llm']['task_options'] = {'region_preference_electrothermal': {'timeout_s': 3., 'max_tokens': 256}}
    assert request_controls(cfg, 'region_preference_electrothermal') == {
        'timeout_s': 3., 'max_tokens': 256, 'reasoning_effort': 'none'}
    cfg['llm']['thinking'] = 'disabled'
    assert electrothermal_configuration_errors(cfg)
    with pytest.raises(ValueError):
        feature().ResponsesTransport('https://provider.invalid/v1/responses', ENV,
            model='deepseek-v4-pro', max_tokens=1536, json_mode=True,
            reasoning_effort='none', thinking='disabled')


@pytest.mark.parametrize('bad', [True, 'medium', [], {}])
def test_constructor_and_serializer_reject_invalid_effort_before_http(bad):
    with pytest.raises(ValueError):
        feature().ResponsesTransport('https://provider.invalid/v1/responses', ENV,
            model='deepseek-v4-pro', max_tokens=1536, json_mode=True, reasoning_effort=bad)
    with pytest.raises(ValueError):
        feature().responses_request_body(payload(), model='deepseek-v4-pro',
            max_tokens=1536, json_mode=True, reasoning_effort=bad)


@pytest.mark.parametrize('task', ['warm_start_electrothermal', 'region_preference_electrothermal'])
@pytest.mark.parametrize('configured', [None, 'none'])
def test_typed_client_clone_spawn_and_outcome_use_only_configured_effort(monkeypatch, tmp_path, task, configured):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    module = feature()
    cfg = config()
    if configured is not None: cfg['llm']['reasoning_effort'] = configured
    monkeypatch.setenv(ENV, 'offline-reasoning-control-placeholder')
    monkeypatch.setattr(module, '_responses_request_worker', successful_responses_worker)
    archive = store(tmp_path, cfg)
    # The injected client's value must never override or supply configuration.
    injected = module.ResponsesTransport(cfg['llm']['endpoint'], ENV,
        model=cfg['llm']['model'], max_tokens=1536, json_mode=True,
        reasoning_effort='high' if configured == 'none' else 'none')
    controller = ElectrothermalLLMController(transport=injected)
    assert controller.request(payload(task), prepared=SimpleNamespace(config=cfg), store=archive,
                              budgets=cfg['budgets'], request_cap=1) is not None
    outcome = controller.last_request_outcome
    body = json.loads(next((archive.path/'http').glob('*.request.json')).read_text())['body']
    supervised = json.loads(next((archive.path/'http').glob('*.supervision.json')).read_text())
    if configured is None:
        assert 'reasoning' not in body
        assert 'reasoning_effort' not in outcome and 'reasoning_effort' not in supervised
    else:
        assert body['reasoning'] == {'effort': configured}
        assert outcome['reasoning_effort'] == supervised['reasoning_effort'] == configured
    assert controller.requests == 1 and outcome['hard_deadline_enforced']
    assert injected.reasoning_effort == ('high' if configured == 'none' else 'none')


@pytest.mark.parametrize('reason', ['disabled', 'global_budget', 'missing_credential'])
def test_inactive_controlled_requests_do_not_construct_transport(monkeypatch, tmp_path, reason):
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    cfg = config()
    cfg['llm']['reasoning_effort'] = 'none'
    monkeypatch.delenv(ENV, raising=False)
    if reason == 'disabled': cfg['llm']['enabled'] = False
    elif reason == 'global_budget': cfg['budgets']['max_llm_requests'] = 0
    monkeypatch.setattr(requests, 'electrothermal_transport_class', lambda *a: pytest.fail('inactive transport constructed'))
    archive = store(tmp_path, cfg)
    controller = ElectrothermalLLMController()
    assert controller.request(payload(), prepared=SimpleNamespace(config=cfg), store=archive,
                              budgets=cfg['budgets'], request_cap=1) is None
    assert controller.last_request_outcome['reason'] == reason
    assert controller.last_request_outcome['reasoning_effort'] == 'none'
    assert controller.requests == 0


def test_effort_does_not_extend_hard_deadline_or_trigger_retry(monkeypatch, tmp_path):
    from llmbo_para.electrothermal_requests import LLMRequestFailure
    module = feature()
    monkeypatch.setenv(ENV, 'offline-reasoning-control-placeholder')
    monkeypatch.setattr(module, '_responses_request_worker', headers_stall_worker)
    archive = store(tmp_path, config())
    client = module.BoundedResponsesTransport('https://provider.invalid/v1/responses', ENV,
        model='deepseek-v4-pro', max_tokens=1536, json_mode=True, timeout_s=3.,
        reasoning_effort='none', run_store=archive)
    started = time.monotonic()
    with pytest.raises(LLMRequestFailure) as exc: client.post(payload())
    assert time.monotonic()-started < 6.
    assert exc.value.kind == 'deadline_exceeded'
    assert exc.value.diagnostic['reasoning_effort'] == 'none'
    assert len(list((archive.path/'http').glob('*.request.json'))) == 1
