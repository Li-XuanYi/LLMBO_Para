"""HTTP deadline/diagnostic behavior at the real supervision boundary."""
import multiprocessing
import time
import pytest


def transport(module, *, timeout=30., store=None):
    return module.BoundedChatCompletionsTransport('https://example.invalid/v1/chat/completions',
        'REGION_TEST_CREDENTIAL', model='unit-test-model', max_tokens=512, json_mode=True,
        timeout_s=timeout, run_store=store)


def test_blocked_request_is_stopped_at_hard_deadline_without_orphan_worker(monkeypatch):
    from llmbo_para import electrothermal_requests as requests
    from region_request_process_fixtures import stalled_request_worker
    monkeypatch.setenv('REGION_TEST_CREDENTIAL','unit-test-credential')
    monkeypatch.setattr(requests,'_chat_request_worker',stalled_request_worker)
    before={p.pid for p in multiprocessing.active_children()}; started=time.monotonic()
    with pytest.raises(requests.LLMRequestFailure) as failure:
        transport(requests,timeout=.4).post({'task':'region_preference_electrothermal','instructions':'Return JSON'})
    assert failure.value.kind=='deadline_exceeded'
    assert time.monotonic()-started<3.
    assert {p.pid for p in multiprocessing.active_children()} <= before


def test_remaining_run_deadline_caps_request_even_when_configured_timeout_is_larger(monkeypatch):
    from llmbo_para import electrothermal_requests as requests
    captured={}; deadline=time.monotonic()+.2
    def execute(worker,args,**kwargs):
        captured.update(kwargs)
        return {'ok':True,'response':{'region':{'kind':'none'}}}
    monkeypatch.setattr(requests,'run_with_deadline',execute)
    monkeypatch.setenv('REGION_TEST_CREDENTIAL','unit-test-credential')
    result=transport(requests,timeout=120).post({'task':'region_preference_electrothermal','instructions':'Return JSON'},deadline=deadline)
    assert result=={'region':{'kind':'none'}}
    assert captured['deadline']<=deadline


def test_http_error_retains_http_status_and_transport_category(monkeypatch):
    from llmbo_para import electrothermal_requests as requests
    def execute(*args,**kwargs):
        return {'ok':False,'diagnostic':{'error_type':'HTTPError','http_status':400,'http_request_started':True}}
    monkeypatch.setattr(requests,'run_with_deadline',execute)
    monkeypatch.setenv('REGION_TEST_CREDENTIAL','unit-test-credential')
    with pytest.raises(requests.LLMRequestFailure) as failure:
        transport(requests).post({'task':'region_preference_electrothermal','instructions':'Return JSON'})
    assert failure.value.kind=='http_error' and failure.value.diagnostic['http_status']==400
