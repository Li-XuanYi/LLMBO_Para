"""Machine-only HTTP failure diagnostics, with the real worker and no sockets."""
from importlib import import_module
import json
import socket
import ssl
from urllib.error import URLError
from http.client import RemoteDisconnected

import pytest


def feature():
    return import_module('llmbo_para.http_diagnostics')


@pytest.mark.parametrize('error,category,cause,number', [
    (socket.gaierror(11001, 'private'), 'dns', 'gaierror', 11001),
    (socket.gaierror(-2, 'private'), 'dns', 'gaierror', -2),
    (ConnectionRefusedError(10061, 'private'), 'connection_refused', 'ConnectionRefusedError', 10061),
    (ConnectionResetError(10054, 'private'), 'connection_reset', 'ConnectionResetError', 10054),
    (ConnectionAbortedError(10053, 'private'), 'connection_aborted', 'ConnectionAbortedError', 10053),
    (BrokenPipeError(32, 'private'), 'broken_pipe', 'BrokenPipeError', 32),
    (TimeoutError(10060, 'private'), 'timeout', 'TimeoutError', 10060),
    (ssl.SSLCertVerificationError(1, 'private'), 'tls_certificate', 'SSLCertVerificationError', 1),
    (ssl.SSLEOFError(8, 'private'), 'tls_eof', 'SSLEOFError', 8),
    (ssl.SSLError(1, 'private'), 'tls_other', 'SSLError', 1),
    (RemoteDisconnected('private'), 'remote_disconnected', 'RemoteDisconnected', None),
    # Python on Windows specializes these WSA errors at construction.
    (OSError(10061, 'private'), 'connection_refused', type(OSError(10061, '')).__name__, 10061),
    (OSError(10054, 'private'), 'connection_reset', type(OSError(10054, '')).__name__, 10054),
    (OSError(10060, 'private'), 'timeout', type(OSError(10060, '')).__name__, 10060),
    (OSError(11001, 'private'), 'dns', 'OSError', 11001),
    (OSError(9876, 'private'), 'other_os', 'OSError', 9876),
])
@pytest.mark.parametrize('wrapped', [False, True])
def test_safe_network_categories(error, category, cause, number, wrapped):
    actual = feature().transport_error_fields(URLError(error) if wrapped else error)['network_diagnostic']
    assert actual['category'] == category and actual['cause_type'] == cause
    if number is None:
        assert 'os_errno' not in actual
    else:
        assert actual['os_errno'] == number
    assert 'private' not in json.dumps(actual)


def test_certificate_code_and_windows_code_are_numeric_only():
    exc = ssl.SSLCertVerificationError(1, 'private')
    exc.verify_code = 20
    exc.winerror = 10054
    actual = feature().transport_error_fields(URLError(exc))['network_diagnostic']
    assert actual['tls_verify_code'] == 20 and actual['winerror'] == 10054


@pytest.mark.parametrize('kind', ['string_reason', 'cyclic', 'too_deep'])
def test_unusable_reason_is_bounded_and_unknown(kind):
    exc = URLError('https://private:credential@proxy.invalid/private')
    if kind == 'cyclic':
        exc.reason = exc
    if kind == 'too_deep':
        exc = ConnectionRefusedError(10061, 'private')
        for _ in range(8):
            exc = URLError(exc)
    actual = feature().transport_error_fields(exc)['network_diagnostic']
    assert actual == {'category': 'unknown', 'cause_type': 'other'}


def test_explicit_exception_cause_is_unwrapped_without_message():
    outer = RuntimeError('private')
    outer.__cause__ = URLError(socket.gaierror(11001, 'private'))
    assert feature().transport_error_fields(outer)['network_diagnostic']['category'] == 'dns'
    assert feature().transport_error_fields(ValueError('not a network failure')) == {}


@pytest.mark.parametrize('error', [RuntimeError('private'), ValueError('private')])
def test_unknown_typed_url_reason_retains_unknown_without_private_text(error):
    assert feature().transport_error_fields(URLError(error)) == {
        'network_diagnostic': {'category': 'unknown', 'cause_type': 'other'}}
    assert feature().transport_error_fields(error) == {}


@pytest.mark.parametrize('value', [[], True, 2**40])
def test_invalid_os_attributes_do_not_escape_or_break_classification(value):
    exc = OSError(9876, 'private')
    exc.errno = value
    exc.winerror = value
    actual = feature().transport_error_fields(exc)['network_diagnostic']
    assert actual == {'category': 'other_os', 'cause_type': 'OSError'}


VALID = {'category': 'dns', 'cause_type': 'gaierror', 'os_errno': 11001}


@pytest.mark.parametrize('damage', [
    {'category': 'private'}, {'cause_type': 'private'}, {'os_errno': True},
    {'os_errno': 2**40}, {'os_errno': 'private'}, {'winerror': False},
    {'tls_verify_code': -1}, {'message': 'private'}, {'category': None},
])
def test_public_network_fields_reject_malformed_or_extra_values(damage):
    value = {**VALID, **damage}
    assert feature().public_network_diagnostic(value) is None


def test_public_copy_and_existing_allowlist_keep_only_machine_fields():
    from llmbo_para.electrothermal_requests import _public_diagnostic
    safe = feature().public_network_diagnostic(VALID)
    assert safe == VALID and safe is not VALID
    public = _public_diagnostic({'error_type': 'URLError', 'message': 'private',
                                'provider_response': 'private', 'network_diagnostic': VALID})
    assert public['network_diagnostic'] == VALID
    assert 'private' not in json.dumps(public)
    assert 'network_diagnostic' not in _public_diagnostic({'error_type': 'TimeoutError'})


@pytest.mark.parametrize('protocol', ['chat', 'responses'])
@pytest.mark.parametrize('unknown', [False, True])
def test_real_worker_preserves_machine_cause_without_free_text(monkeypatch, tmp_path, protocol, unknown):
    from test_region_transport_repairs import payload, Connection
    from llmbo_para.electrothermal_requests import _chat_request_worker
    from llmbo_para.electrothermal_responses import _responses_request_worker
    canary = 'unrelated-private-proxy-password-canary'
    env = 'NETWORK_DIAGNOSTIC_OFFLINE_ONLY'
    monkeypatch.setenv(env, 'not-a-provider-credential')

    class Provider:
        def open(self, *args, **kwargs):
            raise URLError(RuntimeError(canary) if unknown else ConnectionRefusedError(10061, canary))

    monkeypatch.setattr('llmbo_para.llm.build_opener', lambda *args: Provider())
    run = tmp_path / 'archive'
    run.mkdir()
    spec = {'endpoint': 'https://provider.invalid/v1/' + ('responses' if protocol == 'responses' else 'chat/completions'),
            'api_key_env': env, 'model': 'offline', 'max_tokens': 512, 'json_mode': True, 'timeout_s': 1.}
    connection = Connection()
    worker = _responses_request_worker if protocol == 'responses' else _chat_request_worker
    worker(spec, payload(), str(run), connection)
    actual = connection.messages[-1][1]
    assert not actual['ok']
    expected = ({'category': 'unknown', 'cause_type': 'other'} if unknown else
                {'category': 'connection_refused', 'cause_type': 'ConnectionRefusedError', 'os_errno': 10061})
    assert actual['diagnostic']['network_diagnostic'] == expected
    for p in (run / 'http').glob('*.error.json'):
        assert json.loads(p.read_text())['network_diagnostic'] == expected
    assert all(canary not in p.read_text(encoding='utf8') for p in run.rglob('*') if p.is_file())
    assert canary not in json.dumps(connection.messages)
    from llmbo_para.electrothermal_audit import _audit_network_diagnostics
    diagnostic = actual['diagnostic']
    _audit_network_diagnostics({'network_diagnostic': expected}, diagnostic,
                              {'network_diagnostic': expected}, supported_source=True)


def test_parent_and_controller_keep_network_fields_without_a_real_request(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from test_region_transport_repairs import payload
    from test_electrothermal_responses_requests import config, store, ENV
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    expected = dict(VALID)
    monkeypatch.setenv(ENV, 'offline-not-a-provider-key')

    def failed(*args, **kwargs):
        kwargs['on_solve_start']()
        return {'ok': False, 'diagnostic': {'error_type': 'URLError', 'http_request_started': True,
                                          'network_diagnostic': expected}}

    monkeypatch.setattr(requests, 'run_with_deadline', failed)
    cfg = config()
    archive = store(tmp_path, cfg)
    controller = ElectrothermalLLMController()
    assert controller.request(payload(), prepared=SimpleNamespace(config=cfg), store=archive,
                              budgets=cfg['budgets'], request_cap=1) is None
    outcome = controller.last_request_outcome
    assert outcome['network_diagnostic'] == expected
    assert outcome['reason'] == 'transport_error'
    assert json.loads(next((archive.path / 'http').glob('*.supervision.json')).read_text())['network_diagnostic'] == expected


def test_hard_deadline_retains_already_archived_machine_error(monkeypatch, tmp_path):
    from test_region_transport_repairs import payload, spec, ENV
    from llmbo_para.electrothermal_requests import BoundedChatCompletionsTransport, LLMRequestFailure
    from llmbo_para.runstore import RunStore
    archive = RunStore(tmp_path, {'kind': 'offline-deadline-race'}, command='offline diagnostic')
    monkeypatch.setenv(ENV, 'offline-only')
    expected = {'category': 'connection_reset', 'cause_type': 'ConnectionResetError', 'os_errno': 10054}

    def race(*args, **kwargs):
        kwargs['on_solve_start']()
        archive.write_json('http/' + payload()['artifact_task'] + '.error.json',
                           {'error_type': 'URLError', 'network_diagnostic': expected})
        raise TimeoutError('parent deadline after child recorded its error')

    monkeypatch.setattr('llmbo_para.electrothermal_requests.run_with_deadline', race)
    with pytest.raises(LLMRequestFailure) as exc:
        BoundedChatCompletionsTransport(**spec(), run_store=archive).post(payload())
    assert exc.value.kind == 'deadline_exceeded'
    assert exc.value.diagnostic['network_diagnostic'] == expected


def test_configuration_failure_does_not_inherit_an_unrelated_archived_cause(monkeypatch, tmp_path):
    from test_region_transport_repairs import payload, spec, ENV
    from llmbo_para.electrothermal_requests import BoundedChatCompletionsTransport, LLMRequestFailure
    from llmbo_para.runstore import RunStore
    archive = RunStore(tmp_path, {'kind': 'offline-stale-diagnostic'}, command='offline diagnostic')
    archive.write_json('http/' + payload()['artifact_task'] + '.error.json',
                       {'error_type': 'URLError', 'network_diagnostic': VALID})
    monkeypatch.delenv(ENV, raising=False)
    with pytest.raises(LLMRequestFailure) as exc:
        BoundedChatCompletionsTransport(**spec(), run_store=archive).post(payload())
    assert exc.value.kind == 'configuration_error'
    assert 'network_diagnostic' not in exc.value.diagnostic
