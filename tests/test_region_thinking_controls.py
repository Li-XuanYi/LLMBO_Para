"""Reasoning output controls must reach v2 HTTP without changing BO semantics."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from electrothermal_fixtures import et_config

REGION = 'region_preference_electrothermal'
WARM = 'warm_start_electrothermal'
ENV = 'REGION_THINKING_UNIT_CREDENTIAL'


def config():
    cfg = et_config()
    cfg['llm'].update(enabled=True, endpoint='https://offline.example.test/v1/chat/completions',
        api_key_env=ENV, model='offline-model', timeout_s=30., max_tokens=1536)
    cfg['budgets']['max_llm_requests'] = 2
    return cfg


def test_thinking_inheritance_task_override_and_old_omission(tmp_path):
    from llmbo_para.electrothermal_requests import request_controls
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = config(); original = deepcopy(cfg)
    assert request_controls(cfg, REGION) == {'timeout_s': 30., 'max_tokens': 1536}
    cfg['llm']['thinking'] = 'enabled'
    cfg['llm']['task_options'] = {REGION: {'thinking': 'disabled', 'max_tokens': 1024}}
    before = deepcopy(cfg)
    report, p = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert p is not None, report['errors']
    assert request_controls(cfg, WARM) == {'timeout_s': 30., 'max_tokens': 1536, 'thinking': 'enabled'}
    assert request_controls(cfg, REGION) == {'timeout_s': 30., 'max_tokens': 1024, 'thinking': 'disabled'}
    assert cfg == before and original['llm'].get('thinking') is None


@pytest.mark.parametrize('value', [None, False, 0, 'off', 'none', {'type': 'disabled'}, []])
@pytest.mark.parametrize('scope', ['global', 'task'])
def test_malformed_thinking_rejected_even_when_disabled(tmp_path, scope, value):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    cfg = et_config()
    if scope == 'global':
        cfg['llm']['thinking'] = value
    else:
        cfg['llm']['task_options'] = {REGION: {'thinking': value}}
    report, p = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert p is None and report['errors']
    assert report['paid_api_calls_made'] == report['battery_simulations_made'] == 0


def fake_completion(*, finish='length', content='', completion=1536, reasoning=1536):
    return {'choices': [{'finish_reason': finish, 'message': {'content': content,
        'reasoning_content': 'untrusted provider text must not enter diagnostics'}}],
        'usage': {'completion_tokens': completion, 'completion_tokens_details': {'reasoning_tokens': reasoning}}}


def test_reasoning_exhaustion_machine_summary_contains_no_provider_text():
    from llmbo_para.electrothermal_requests import completion_summary
    summary = completion_summary(fake_completion(), 1536)
    assert summary == {'finish_reason': 'length', 'answer_characters': 0, 'completion_tokens': 1536,
        'reasoning_tokens': 1536, 'state': 'reasoning_budget_exhausted'}
    assert 'untrusted' not in json.dumps(summary)


@pytest.mark.parametrize('response', [
    fake_completion(reasoning=None), fake_completion(reasoning=True),
    fake_completion(reasoning=-1), fake_completion(reasoning='1536'),
    fake_completion(completion=1535), fake_completion(reasoning=100),
    fake_completion(content='{'), fake_completion(finish='stop')])
def test_nonmatching_or_missing_usage_is_never_declared_reasoning_exhaustion(response):
    from llmbo_para.electrothermal_requests import completion_summary
    assert completion_summary(response, 1536).get('state') != 'reasoning_budget_exhausted'


def test_controller_passes_task_thinking_to_bounded_worker_without_mutating_injected_client(tmp_path, monkeypatch):
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.llm import ChatCompletionsTransport
    cfg = config(); cfg['llm']['thinking'] = 'enabled'
    cfg['llm']['task_options'] = {REGION: {'thinking': 'disabled'}}
    report, p = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert p is not None, report['errors']
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=p.dataset, signatures=p.signatures, command='thinking config test')
    injected = ChatCompletionsTransport(cfg['llm']['endpoint'], ENV, model='offline-model', max_tokens=4096,
        json_mode=True, thinking='enabled')
    controller = ElectrothermalLLMController(transport=injected)
    monkeypatch.setenv(ENV, 'unit-only-credential')
    seen = []
    def boundary(worker, args, **kwargs):
        seen.append(args[0]); kwargs['on_solve_start']()
        return {'ok': True, 'response': {}, 'diagnostic': {'http_status': 200, 'http_request_started': True}}
    monkeypatch.setattr(requests, 'run_with_deadline', boundary)
    for task, mode in [(REGION, 'disabled'), (WARM, 'enabled')]:
        controller.request({'task': task, 'instructions': 'Return JSON.'}, prepared=p, store=store,
            budgets=cfg['budgets'], request_cap=1)
        assert seen[-1]['thinking'] == controller.last_request_outcome['thinking'] == mode
        assert controller.last_request_outcome['max_tokens'] == 1536
    assert injected.thinking == 'enabled' and injected.max_tokens == 4096 and injected.store is None
    assert store.ledger.summary()['llm_requests'] == len(seen) == 2


@pytest.mark.parametrize('mode', ['complete', 'reasoning_exhausted'])
def test_real_worker_sends_explicit_thinking_and_classifies_without_retry(monkeypatch, tmp_path_factory, mode):
    from llmbo_para.electrothermal_requests import _chat_request_worker, BoundedChatCompletionsTransport
    from llmbo_para.runstore import RunStore
    from test_region_transport_repairs import payload, spec, Connection
    sent = []
    class Response:
        status = 200
        def read(self, count):
            value = fake_completion() if mode == 'reasoning_exhausted' else fake_completion(
                finish='stop', content='{}', completion=2, reasoning=0)
            return json.dumps(value).encode()[:count]
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
    class Provider:
        def open(self, request, **kwargs):
            sent.append(json.loads(request.data))
            assert sent[-1]['thinking'] == {'type': 'disabled'}
            return Response()
    monkeypatch.setenv(ENV, 'unit-only-credential')
    monkeypatch.setattr('llmbo_para.llm.build_opener', lambda *args: Provider())
    store = RunStore(tmp_path_factory.mktemp('rthink'), {'kind': 'offline-worker'}, command='thinking worker')
    worker_spec = {**spec(), 'api_key_env': ENV, 'max_tokens': 1536, 'thinking': 'disabled'}
    connection = Connection()
    _chat_request_worker(worker_spec, payload(), str(store.path), connection)
    returned = connection.messages[-1][1]
    assert len(sent) == 1 and returned['ok'] == (mode == 'complete')
    summary = returned['diagnostic']['completion']
    assert summary['reasoning_tokens'] == (0 if mode == 'complete' else 1536)
    if mode == 'reasoning_exhausted':
        assert returned['diagnostic']['protocol_issue'] == 'unfinished_completion'
        assert summary['state'] == 'reasoning_budget_exhausted'
    assert 'untrusted provider text' not in json.dumps(returned)


def test_public_completion_summary_does_not_transfer_provider_fields():
    from llmbo_para.electrothermal_requests import _public_diagnostic
    public = _public_diagnostic({'completion': {'finish_reason': 'provider-secret', 'answer_characters': False,
        'completion_tokens': -1, 'reasoning_tokens': 'secret', 'reasoning_content': 'secret',
        'state': 'reasoning_budget_exhausted', 'extra': 'secret'}})
    assert 'secret' not in json.dumps(public) and 'extra' not in public.get('completion', {})


@pytest.mark.parametrize('damage', ['none', 'wire_thinking', 'completion', 'response_usage', 'flag_bypass', 'invalid_content'])
def test_full_archive_audit_checks_sent_controls_and_raw_completion(tmp_path_factory, monkeypatch, damage):
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from region_control_process_fixtures import successful_compact_worker, invalid_content_worker
    from test_region_failure_audit import _shared_initialization
    root = tmp_path_factory.mktemp('rac')
    cfg = _shared_initialization(root)
    cfg['llm'].update(config()['llm'], thinking='disabled', region_wire_format='compact_v1')
    cfg['budgets']['max_llm_requests'] = 2
    cfg['optimization'].update(mode='full_llmbo_mo', total_candidate_budget=3,
        region_advice='candidate_aware_v1', region_selection='fair_region_v1')
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100., min_sigma_ratio=0.)
    monkeypatch.setenv(ENV, 'unit-only-credential')
    monkeypatch.setattr(requests, '_chat_request_worker', invalid_content_worker if damage == 'invalid_content' else successful_compact_worker)
    result = run_electrothermal_experiment(cfg, root, base_dir=root)
    folder = Path(result['run_directory'])
    assert audit_electrothermal_run(folder, deep=True)['passed']
    if damage == 'none': return
    if damage == 'invalid_content':
        outcome = json.loads(next((folder/'llm').glob('*.outcome.json')).read_text())
        assert outcome['protocol_issue'] == 'invalid_content_type' and outcome['completion']['answer_characters'] is None
        return
    if damage in ('wire_thinking', 'flag_bypass'):
        path = next((folder/'http').glob('*.request.json')); row = json.loads(path.read_text())
        row['body']['thinking']['type'] = 'enabled'; path.write_text(json.dumps(row))
        if damage == 'flag_bypass':
            path = next((folder/'llm').glob('*.outcome.json')); row = json.loads(path.read_text())
            row['hard_deadline_enforced'] = False; path.write_text(json.dumps(row))
            path = folder/'mo-rounds/000001.json'; row = json.loads(path.read_text())
            row['region']['request_outcome']['hard_deadline_enforced'] = False; path.write_text(json.dumps(row))
    elif damage == 'response_usage':
        path = next((folder/'http').glob('*.response.json')); row = json.loads(path.read_text())
        row['usage']['completion_tokens_details']['reasoning_tokens'] = 1; path.write_text(json.dumps(row))
    else:
        for path in [*list((folder/'llm').glob('*.outcome.json')), *list((folder/'http').glob('*.supervision.json'))]:
            row = json.loads(path.read_text()); row['completion']['reasoning_tokens'] = 1; path.write_text(json.dumps(row))
        path = folder/'mo-rounds/000001.json'; row = json.loads(path.read_text())
        row['region']['request_outcome']['completion']['reasoning_tokens'] = 1; path.write_text(json.dumps(row))
    assert not audit_electrothermal_run(folder, deep=True)['passed']
