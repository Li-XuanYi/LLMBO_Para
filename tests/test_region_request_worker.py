"""Spawn the real request worker against a network-free provider boundary."""
import json
import multiprocessing
import time

import pytest


ENVIRONMENT_NAME = 'REGION_WORKER_TEST_CREDENTIAL'
SENTINEL = 'unit-only-wire-credential-never-to-be-archived'
TASK = 'region_preference_electrothermal'
ARTIFACT = TASK + '_request_a'


def payload(task=TASK, artifact=ARTIFACT):
    return {'task': task, 'artifact_task': artifact, 'instructions': 'Return one JSON object.',
            'context_id': 'offline-frozen-context'}


def make_store(tmp_path_factory):
    from llmbo_para.runstore import RunStore
    return RunStore(tmp_path_factory.mktemp('wr'), {'run_kind': 'offline_request_worker'},
                    command='offline worker integration regression')


def make_transport(requests, store):
    return requests.BoundedChatCompletionsTransport(
        'https://provider.example.test/v1/chat/completions', ENVIRONMENT_NAME,
        model='offline-test-model', max_tokens=512, json_mode=True,
        timeout_s=15., run_store=store)


def assert_private_and_single_request(store, original_manifest):
    assert (store.path / 'manifest.json').read_bytes() == original_manifest
    assert len(list(store.path.parent.glob('*/manifest.json'))) == 1
    events = [json.loads(line) for line in store.events_path.read_text(encoding='utf8').splitlines()]
    assert sum(row['type'] == 'llm_http_started' for row in events) == 1
    assert sum(row['type'] == 'llm_http_finished' for row in events) == 1
    for path in (store.path / 'http').glob('*.json'):
        assert SENTINEL not in path.read_text(encoding='utf8')


def test_real_spawn_worker_decodes_redacts_and_archives_in_existing_run(monkeypatch, tmp_path_factory):
    from llmbo_para import electrothermal_requests as requests
    from region_request_process_fixtures import successful_request_worker
    monkeypatch.setenv(ENVIRONMENT_NAME, SENTINEL)
    monkeypatch.setattr(requests, '_chat_request_worker', successful_request_worker)
    store = make_store(tmp_path_factory)
    manifest = (store.path / 'manifest.json').read_bytes()
    transport = make_transport(requests, store)
    previous_children = {process.pid for process in multiprocessing.active_children()}

    result = transport.post(payload())

    assert result['region']['kind'] == 'none'
    assert result['region']['reason'] == '[REDACTED]'
    assert {process.pid for process in multiprocessing.active_children()} <= previous_children
    supervision = json.loads((store.path / 'http' / (ARTIFACT + '.supervision.json')).read_text())
    assert supervision['status'] == 'completed'
    assert supervision['http_status'] == 200 and supervision['http_request_started']
    assert supervision['configured_timeout_s'] == 15. and supervision['max_tokens'] == 512
    assert 0 < supervision['effective_timeout_s'] <= 15.
    assert (store.path / 'http' / (ARTIFACT + '.request.json')).is_file()
    assert (store.path / 'http' / (ARTIFACT + '.response.json')).is_file()
    assert_private_and_single_request(store, manifest)


def test_real_spawn_worker_classifies_http400_without_transferring_provider_text(monkeypatch, tmp_path_factory):
    from llmbo_para import electrothermal_requests as requests
    from region_request_process_fixtures import http_error_request_worker
    monkeypatch.setenv(ENVIRONMENT_NAME, SENTINEL)
    monkeypatch.setattr(requests, '_chat_request_worker', http_error_request_worker)
    store = make_store(tmp_path_factory)
    manifest = (store.path / 'manifest.json').read_bytes()

    with pytest.raises(requests.LLMRequestFailure) as caught:
        make_transport(requests, store).post(payload())

    assert caught.value.kind == 'http_error'
    assert caught.value.diagnostic['http_status'] == 400
    assert caught.value.diagnostic['http_request_started']
    error = json.loads((store.path / 'http' / (ARTIFACT + '.error.json')).read_text())
    assert error['error_type'] == 'HTTPError' and error['http_status'] == 400
    assert error['http_request_started']
    assert 'message' not in error and 'provider_response' not in error
    assert_private_and_single_request(store, manifest)


@pytest.mark.parametrize('layer', ['inner', 'outer'])
def test_real_spawn_worker_classifies_malformed_http200_as_protocol_error(monkeypatch, tmp_path_factory, layer):
    from llmbo_para import electrothermal_requests as requests
    from region_request_process_fixtures import malformed_inner_request_worker, malformed_outer_request_worker
    monkeypatch.setenv(ENVIRONMENT_NAME, SENTINEL)
    worker = malformed_inner_request_worker if layer == 'inner' else malformed_outer_request_worker
    monkeypatch.setattr(requests, '_chat_request_worker', worker)
    store = make_store(tmp_path_factory)
    manifest = (store.path / 'manifest.json').read_bytes()

    with pytest.raises(requests.LLMRequestFailure) as caught:
        make_transport(requests, store).post(payload())

    assert caught.value.kind == 'protocol_error'
    assert caught.value.diagnostic['http_status'] == 200
    assert caught.value.diagnostic['http_request_started']
    suffix = '.parse-error.json' if layer == 'inner' else '.error.json'
    error = json.loads((store.path / 'http' / (ARTIFACT + suffix)).read_text())
    assert error['http_status'] == 200 and error['http_request_started']
    assert 'message' not in error and 'reason' not in error
    assert not (store.path / 'http' / (TASK + '.parse-error.json')).exists()
    assert_private_and_single_request(store, manifest)


def test_missing_credential_fails_before_spawning_worker(monkeypatch, tmp_path_factory):
    from llmbo_para import electrothermal_requests as requests
    monkeypatch.delenv(ENVIRONMENT_NAME, raising=False)
    def forbidden(*args, **kwargs):
        pytest.fail('missing credential must not spawn a request worker')
    monkeypatch.setattr(requests, 'run_with_deadline', forbidden)
    store = make_store(tmp_path_factory)

    with pytest.raises(requests.LLMRequestFailure) as caught:
        make_transport(requests, store).post(payload())

    assert caught.value.kind == 'configuration_error'
    assert not caught.value.diagnostic['http_request_started']
    assert not list((store.path / 'http').glob('*.request.json'))


def test_deadline_during_http_read_records_start_and_leaves_no_worker(monkeypatch, tmp_path_factory):
    from llmbo_para import electrothermal_requests as requests
    from region_request_process_fixtures import blocked_http_request_worker
    monkeypatch.setenv(ENVIRONMENT_NAME, SENTINEL)
    monkeypatch.setattr(requests, '_chat_request_worker', blocked_http_request_worker)
    store = make_store(tmp_path_factory)
    transport = make_transport(requests, store)
    # Windows process startup can exceed a few seconds under the full suite.
    # Leave startup headroom while the offline read stays blocked past the deadline.
    transport.timeout_s = 20.
    previous_children = {process.pid for process in multiprocessing.active_children()}
    started = time.monotonic()

    with pytest.raises(requests.LLMRequestFailure) as caught:
        transport.post(payload())

    assert time.monotonic() - started < 24.
    assert caught.value.kind == 'deadline_exceeded'
    assert caught.value.diagnostic['http_request_started']
    assert {process.pid for process in multiprocessing.active_children()} <= previous_children
    events = [json.loads(line) for line in store.events_path.read_text(encoding='utf8').splitlines()]
    assert sum(row['type'] == 'llm_http_started' for row in events) == 1
    assert sum(row['type'] == 'llm_http_finished' for row in events) == 0
    supervision = json.loads((store.path / 'http' / (ARTIFACT + '.supervision.json')).read_text())
    assert supervision['status'] == 'failed' and supervision['reason'] == 'deadline_exceeded'
    assert supervision['http_request_started']


def test_injected_bounded_transport_uses_current_task_limits_without_mutation(monkeypatch, tmp_path_factory):
    from electrothermal_fixtures import et_config
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from region_request_process_fixtures import successful_request_worker
    monkeypatch.setenv(ENVIRONMENT_NAME, SENTINEL)
    monkeypatch.setattr(requests, '_chat_request_worker', successful_request_worker)
    root = tmp_path_factory.mktemp('wi')
    cfg = et_config()
    cfg['llm'].update(enabled=True, endpoint='https://provider.example.test/v1/chat/completions',
        api_key_env=ENVIRONMENT_NAME, model='offline-test-model', timeout_s=120., max_tokens=4096,
        task_options={'warm_start_electrothermal': {'timeout_s': 120., 'max_tokens': 4096},
                      TASK: {'timeout_s': 30., 'max_tokens': 1536}})
    cfg['budgets']['max_llm_requests'] = 2
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=root)
    assert prepared is not None, report['errors']
    store = ElectrothermalRunStore(root, cfg, dataset=prepared.dataset,
        signatures=prepared.signatures, command='injected task controls regression')
    original_transport = requests.BoundedChatCompletionsTransport(
        cfg['llm']['endpoint'], ENVIRONMENT_NAME, model='offline-test-model', max_tokens=4096,
        json_mode=True, timeout_s=120., run_store=None)
    controller = ElectrothermalLLMController(transport=original_transport)

    for task, expected_timeout, expected_tokens in (
        (TASK, 30., 1536), ('warm_start_electrothermal', 120., 4096)):
        assert controller.request({'task': task, 'instructions': 'Return one JSON object.'},
            prepared=prepared, store=store, budgets=cfg['budgets'], request_cap=2)['region']['kind'] == 'none'
        outcome = controller.last_request_outcome
        assert outcome['hard_deadline_enforced'] is True
        assert outcome['requested_timeout_s'] == expected_timeout
        artifact = task + '_request_' + 'a' * controller.requests
        wire = json.loads((store.path / 'http' / (artifact + '.request.json')).read_text())['body']
        assert wire['max_tokens'] == expected_tokens
        supervision = json.loads((store.path / 'http' / (artifact + '.supervision.json')).read_text())
        assert supervision['configured_timeout_s'] == expected_timeout
        assert supervision['max_tokens'] == expected_tokens
    assert controller.transport is original_transport
    assert original_transport.timeout_s == 120. and original_transport.max_tokens == 4096
    assert original_transport.store is None
    assert store.ledger.summary()['llm_requests'] == 2
