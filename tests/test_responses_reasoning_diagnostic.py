"""Bounded reasoning diagnostic: deterministic sequence, no network in tests."""
from copy import deepcopy
from contextlib import nullcontext
from importlib import import_module, util
import json
from pathlib import Path
import sys

import pytest


def feature():
    scripts = str(Path(__file__).resolve().parents[1]/'scripts')
    if scripts not in sys.path: sys.path.insert(0, scripts)
    assert util.find_spec('run_responses_reasoning_diagnostic') is not None, 'diagnostic not implemented'
    return import_module('run_responses_reasoning_diagnostic')


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf8')


def protocol_fixture(module, root):
    contexts = []
    for i in range(3):
        p, r, m = (root/str(i)/name for name in ('payload.json', 'round.json', 'manifest.json'))
        put(p, {'context_id': str(i)*64, 'task': 'region_preference_electrothermal'})
        put(r, {'original': i}); put(m, {'config': {}})
        contexts.append({'context_id': str(i)*64, 'frozen_payload': str(p), 'payload_sha256': module.sha(p),
                         'frozen_round': str(r), 'round_sha256': module.sha(r), 'frozen_manifest': str(m)})
    value = {'version': 'responses_reasoning_probe_v1', 'approved_plan_commit': module.APPROVED_COMMIT,
             'limits': deepcopy(module.LIMITS), 'provider': deepcopy(module.PROVIDER),
             'phases': deepcopy(module.PHASES), 'contexts': contexts}
    put(root/'diagnostic-protocol.json', value)
    return value


def arrange(module, tmp_path, monkeypatch, *, failure=None):
    protocol = protocol_fixture(module, tmp_path/'e')
    calls = []
    monkeypatch.setattr(module, '_validate_release', lambda *a: None)
    monkeypatch.setattr(module, 'read_credential', lambda: calls.append('key'))
    monkeypatch.setattr(module, 'keep_awake', lambda *a: nullcontext())
    monkeypatch.setattr(module, 'OUTPUT', tmp_path/'output')
    def invoke(worker, spec, budget, *, deadline, metadata, integrity_check):
        assert deadline <= budget.deadline-30
        integrity_check()
        budget.charge('API', spec['label'])
        calls.append(deepcopy(spec))
        result = {'passed': True, 'complete': True, 'context_id': spec.get('context_id'),
            'wire_verified': True,
            'effect': {'action_valid': True, 'tilt_applied': True, 'max_abs_shift': .1,
                       'state_preserved': True, 'EI_matches': True},
            'diagnostic': {'status': 'completed', 'http_status': 200, 'http_request_started': True}}
        if failure and spec['label'] == failure[0]: result.update(deepcopy(failure[1]))
        put(metadata, {'owned_tree_stopped': True})
        # Actual worker validates the full raw body; parent checks comparator hashes.
        result['body_without_reasoning_sha256'] = 'b'*64
        result['body_sha256'] = ('c' if spec.get('reasoning_effort') else 'd')*64
        return result
    monkeypatch.setattr(module, 'supervise', invoke)
    return protocol, calls


def test_dry_run_never_loads_key_or_starts_clock(tmp_path, monkeypatch):
    m = feature(); protocol = protocol_fixture(m, tmp_path)
    monkeypatch.setattr(m, 'read_credential', lambda: pytest.fail('dry key read'))
    result = m.run_diagnostic(protocol, tmp_path)
    assert result['actual_API'] == result['actual_DFN'] == result['actual_BO'] == 0
    assert result['dry_run'] and not (tmp_path/'budget.jsonl').exists()


@pytest.mark.parametrize('damage', ['cap', 'DFN', 'phase', 'provider', 'payload', 'context'])
def test_protocol_drift_rejected_without_key(tmp_path, monkeypatch, damage):
    m = feature(); p = protocol_fixture(m, tmp_path)
    monkeypatch.setattr(m, 'read_credential', lambda: pytest.fail('key read'))
    if damage == 'cap': p['limits']['API'] = 6
    elif damage == 'DFN': p['limits']['DFN'] = 1
    elif damage == 'phase': p['phases'][2]['reasoning_effort'] = 'none'
    elif damage == 'provider': p['provider']['model'] = 'other'
    elif damage == 'context': p['contexts'][2]['context_id'] = p['contexts'][0]['context_id']
    else: Path(p['contexts'][0]['frozen_payload']).write_text('{}')
    with pytest.raises((ValueError, RuntimeError)): m.run_diagnostic(p, tmp_path, execute=True)


@pytest.mark.parametrize('missing', ['approval', 'release', 'key'])
def test_authority_failures_precede_any_budget_start(tmp_path, monkeypatch, missing):
    m = feature(); p = protocol_fixture(m, tmp_path)
    monkeypatch.setattr(m, 'OUTPUT', tmp_path/'output')
    if missing != 'approval':
        monkeypatch.setattr(m, '_validate_release', lambda *a: None if missing == 'key' else (_ for _ in ()).throw(ValueError('release missing')))
    monkeypatch.setattr(m, 'read_credential', lambda: (_ for _ in ()).throw(ValueError('key missing')))
    with pytest.raises((ValueError, FileNotFoundError)): m.run_diagnostic(p, tmp_path, execute=True)
    assert not (tmp_path/'budget.jsonl').exists()


def test_fixed_sequence_and_shared_comparator(tmp_path, monkeypatch):
    m = feature(); p, calls = arrange(m, tmp_path, monkeypatch)
    result = m.run_diagnostic(p, tmp_path/'e', execute=True)
    assert result['status'] == 'completed' and result['transport_ready']
    sent = calls[1:]
    assert [s['label'] for s in sent] == ['p0','p1','p2','p3','p4']
    assert [s.get('reasoning_effort') for s in sent] == ['none','none',None,'none','none']
    assert [s['timeout_s'] for s in sent] == [60.,120.,120.,120.,120.]
    assert sent[1]['payload'] == sent[2]['payload']
    assert result['actual_API'] == 5 and result['actual_DFN'] == result['actual_BO'] == 0
    assert result['comparator_equal_except_reasoning']
    with pytest.raises((FileExistsError, RuntimeError)): m.run_diagnostic(p, tmp_path/'e', execute=True)


@pytest.mark.parametrize('label', ['p0','p1','p3','p4'])
def test_none_failure_stops_without_retry(tmp_path, monkeypatch, label):
    m = feature(); p, calls = arrange(m, tmp_path, monkeypatch,
        failure=(label, {'passed': False, 'diagnostic': {'reason': 'deadline_exceeded', 'http_request_started': True}}))
    result = m.run_diagnostic(p, tmp_path/'e', execute=True)
    assert result['status'] == 'failed' and not result['transport_ready']
    assert [s['label'] for s in calls[1:]][-1] == label
    assert result['actual_API'] == int(label[1:])+1


@pytest.mark.parametrize('reason,status,started,elapsed,expected', [
    ('deadline_exceeded',None,True,120.,5), ('deadline_exceeded',200,True,120.,5), ('timeout',None,True,120.,3),
    ('worker_error',None,True,120.,3), ('deadline_exceeded',None,False,120.,3),
    ('deadline_exceeded',None,True,30.,3), ('deadline_exceeded',503,True,120.,3),
    ('http_error',401,True,1.,3), ('http_error',403,True,1.,3),
    ('http_error',404,True,1.,3), ('http_error',429,True,1.,3)])
def test_only_pre_registered_omitted_parent_cutoff_can_continue(tmp_path, monkeypatch, reason,status,started,elapsed,expected):
    m = feature()
    diag = {'reason': reason, 'http_status': status, 'http_request_started': started,
            'configured_timeout_s': 120., 'effective_timeout_s': 120., 'elapsed_s': elapsed}
    p, calls = arrange(m, tmp_path, monkeypatch, failure=('p2', {'passed': False, 'diagnostic': diag}))
    result = m.run_diagnostic(p, tmp_path/'e', execute=True)
    assert result['actual_API'] == expected
    assert result['transport_ready'] == (expected == 5)


def test_persistent_budget_rejects_dfns_duplicates_expiry_and_tamper(tmp_path, monkeypatch):
    m = feature(); clock = [10.]
    monkeypatch.setattr(m.time, 'monotonic', lambda: clock[0])
    budget = m.ProbeBudget.start(tmp_path/'b.jsonl', protocol_sha='a'*64)
    budget.charge('API', 'p0')
    with pytest.raises(RuntimeError): budget.charge('API', 'p0')
    with pytest.raises(RuntimeError): budget.charge('DFN', 'x')
    assert budget.state()['API'] == 1 and budget.deadline == 730.
    clock[0] = 701.
    with pytest.raises((RuntimeError, TimeoutError)): budget.charge('API', 'p1')
    assert budget.state()['API'] == 1
    budget.close('failed')
    with pytest.raises(RuntimeError): budget.charge('API', 'p1')
    value = budget.path.read_text().replace('"API":5', '"API":6')
    budget.path.write_text(value)
    with pytest.raises(ValueError): budget.state()


@pytest.mark.parametrize('damage', ['wire', 'owned', 'pair', 'tilt', 'source', 'crash'])
def test_false_evidence_or_runtime_failure_closes_sequence(tmp_path, monkeypatch, damage):
    m = feature(); p, calls = arrange(m, tmp_path, monkeypatch)
    original = m.supervise
    def damaged(worker, spec, budget, **kwargs):
        if damage == 'crash': raise RuntimeError('worker exited')
        result = original(worker, spec, budget, **kwargs)
        if damage == 'wire': result['wire_verified'] = False
        elif damage == 'owned': put(kwargs['metadata'], {'owned_tree_stopped': False})
        elif damage == 'pair' and spec['label'] == 'p2': result['body_without_reasoning_sha256'] = 'z'*64
        elif damage == 'tilt': result['effect'].update(tilt_applied=False, max_abs_shift=0.)
        elif damage == 'source':
            monkeypatch.setattr(m, '_validate_release', lambda *a: (_ for _ in ()).throw(ValueError('source drift')))
        return result
    monkeypatch.setattr(m, 'supervise', damaged)
    result = m.run_diagnostic(p, tmp_path/'e', execute=True)
    assert result['status'] == 'failed' and not result['transport_ready']


def release_fixture(m, root):
    import importlib.metadata
    environment = {'executable': sys.executable, 'python': sys.version,
        'dependencies': {name: importlib.metadata.version(name) for name in
                         ('pytest','numpy','scipy','pybamm','casadi','pybammsolvers','openpyxl')}}
    p = protocol_fixture(m, root)
    put(root/'approval.json', {'approved': True, 'approved_commit': m.APPROVED_COMMIT,
        'limits': {k:v for k,v in m.LIMITS.items() if k != 'cleanup_reserve_s'},
        'plan_sha256': m.sha(m.PLAN), 'spec_sha256': m.sha(m.SPEC)})
    (root/'run_tests.py').write_text('# offline release fixture')
    pins = m.required_pins(p, root)
    manifest = {'head': m._head(), 'source_fingerprint': m.fingerprint(m.WT), 'pins': pins,
                'environment': environment}
    put(root/'runtime-before-final.json', manifest)
    observation = {'head': manifest['head'], 'source_fingerprint': manifest['source_fingerprint'],
        'pins_digest': m.digest(pins), 'runtime_manifest_sha256': m.sha(root/'runtime-before-final.json'),
        'protocol_sha256': m.sha(root/'diagnostic-protocol.json')}
    before = {'head': manifest['head'], 'runtime_observation': observation, **environment}
    full = {'exit_code': 0, 'head_after': manifest['head'], 'command_args': ['tests'],
        'junit_counts': {'tests': 1, 'passed': 1, 'failures': 0, 'errors': 0, 'skipped': 0},
        'boundary': {'network_attempts': 0, 'battery_solve_attempts': 0},
        'source_unchanged_during_run': True, 'protected_unchanged_during_run': True,
        'runtime_unchanged_during_run': True, 'runtime_observation': observation}
    fullpath = root/'tests/ge-re-final-full/result.json'
    put(fullpath.parent/'manifest-before.json', before); put(fullpath, full)
    release = {**manifest, 'runtime_manifest_sha256': m.sha(root/'runtime-before-final.json'),
        'protocol_sha256': observation['protocol_sha256'], 'full_result_sha256': m.sha(fullpath)}
    put(root/'software-release.json', release)
    return p


@pytest.mark.parametrize('damage', ['none', 'plan', 'caps', 'runtime', 'full', 'observer', 'source', 'head'])
def test_software_release_requires_actual_full_runtime_binding(tmp_path, monkeypatch, damage):
    m = feature(); p = release_fixture(m, tmp_path)
    m._validate_release(p, tmp_path)
    if damage == 'none': return
    if damage in ('plan', 'caps'):
        path = tmp_path/'approval.json'; value = m.read(path)
        if damage == 'plan': value['plan_sha256'] = 'a'*64
        else: value['limits']['API'] = 6
        put(path, value)
    elif damage == 'runtime': (tmp_path/'run_tests.py').write_text('# altered')
    elif damage in ('full', 'observer'):
        path = tmp_path/'tests/ge-re-final-full/result.json'; value = m.read(path)
        if damage == 'full': value['exit_code'] = 1
        else: value['runtime_observation']['pins_digest'] = 'a'*64
        put(path, value)
        release = m.read(tmp_path/'software-release.json'); release['full_result_sha256'] = m.sha(path)
        put(tmp_path/'software-release.json', release)
    elif damage == 'source': monkeypatch.setattr(m, 'fingerprint', lambda *a: 'b'*64)
    else: monkeypatch.setattr(m, '_head', lambda: 'b'*40)
    with pytest.raises(ValueError): m._validate_release(p, tmp_path)


def minimal_http_worker(spec, payload, run_path, connection):
    from unittest.mock import patch
    from test_electrothermal_responses import response
    from llmbo_para.electrothermal_responses import _responses_request_worker
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return json.dumps(response({'ok': True})).encode()[:limit]
    class Provider:
        def open(self, request, **kwargs):
            assert json.loads(request.data)['reasoning'] == {'effort': 'none'}
            return Reply()
    with patch('llmbo_para.llm.build_opener', return_value=Provider()):
        _responses_request_worker(spec, payload, run_path, connection)


def offline_transport(spec, store):
    import llmbo_para.electrothermal_responses as responses
    responses._responses_request_worker = minimal_http_worker
    return responses.BoundedResponsesTransport('https://sidrune.ai/v1/responses', 'SUB2API_API_KEY',
        model='deepseek-v4-pro', max_tokens=8192, json_mode=True, timeout_s=20.,
        reasoning_effort='none', run_store=store)


def offline_diagnostic_worker(spec, connection):
    m = feature(); m.make_transport = offline_transport
    m.reasoning_diagnostic_worker(spec, connection)


def test_actual_owned_worker_charges_parent_before_offline_http(tmp_path, monkeypatch):
    m = feature()
    monkeypatch.setenv('SUB2API_API_KEY', 'offline-diagnostic-placeholder')
    budget = m.ProbeBudget.start(tmp_path/'budget.jsonl', protocol_sha='a'*64)
    spec = {**m.PHASES[0], 'source_root': str(m.WT), 'source': m.fingerprint(m.WT),
        'source_commit': m._head(), 'output': str(tmp_path/'child'), 'protocol_sha': 'a'*64,
        'environment': release_fixture_environment(),
        'deadline': m.time.monotonic()+30., 'payload': {'task': 'warm_start_electrothermal',
            'artifact_task': 'offline_minimal', 'instructions': 'Return JSON {"ok":true}.'}}
    result = m.supervise(offline_diagnostic_worker, spec, budget, deadline=spec['deadline'],
        metadata=tmp_path/'owned.json', integrity_check=lambda: None)
    assert result['passed'] and result['wire_verified'], result
    assert budget.state()['API'] == 1 and m.read(tmp_path/'owned.json')['owned_tree_stopped']


def test_full_runtime_observer_captures_pretest_bytes_and_detects_drift(tmp_path):
    m = feature(); p = release_fixture(m, tmp_path)
    assert hasattr(m, 'RuntimeObservation'), 'pre-test observer missing'
    observer = m.RuntimeObservation(p, tmp_path)
    assert observer.unchanged()
    assert observer.observation['runtime_manifest_sha256'] == m.sha(tmp_path/'runtime-before-final.json')
    (tmp_path/'run_tests.py').write_text('# modified after observed start')
    assert not observer.unchanged()


def release_fixture_environment():
    import importlib.metadata
    return {'executable': sys.executable, 'python': sys.version,
        'dependencies': {n: importlib.metadata.version(n) for n in
                         ('pytest','numpy','scipy','pybamm','casadi','pybammsolvers','openpyxl')}}


@pytest.mark.parametrize('field', ['executable', 'python', 'dependencies'])
def test_release_rejects_testing_environment_drift(tmp_path, field):
    m = feature(); p = release_fixture(m, tmp_path)
    path = tmp_path/'tests/ge-re-final-full/manifest-before.json'
    value = m.read(path)
    value[field] = {'numpy': 'untested'} if field == 'dependencies' else 'untested-environment'
    put(path, value)
    with pytest.raises(ValueError): m._validate_release(p, tmp_path)


def test_observer_pins_loaded_protection_helper(tmp_path, monkeypatch):
    m = feature(); p = release_fixture(m, tmp_path)
    observer = m.RuntimeObservation(p, tmp_path)
    helper = (m.BASE/'sub2api-responses-20261021/protect_workspace.py').resolve()
    original = m.sha
    monkeypatch.setattr(m, 'sha', lambda path: 'a'*64 if Path(path).resolve() == helper else original(path))
    assert not observer.unchanged()


def test_actual_worker_rejects_environment_drift_before_http(tmp_path, monkeypatch):
    m = feature(); monkeypatch.setenv('SUB2API_API_KEY', 'offline-placeholder')
    budget = m.ProbeBudget.start(tmp_path/'b.jsonl', protocol_sha='a'*64)
    spec = {**m.PHASES[0], 'source_root': str(m.WT), 'source': m.fingerprint(m.WT),
        'source_commit': m._head(), 'output': str(tmp_path/'child'), 'protocol_sha': 'a'*64,
        'environment': {'python': 'wrong'}, 'deadline': m.time.monotonic()+30.,
        'payload': {'task': 'warm_start_electrothermal', 'artifact_task': 'offline_minimal', 'instructions': 'JSON'}}
    with pytest.raises(RuntimeError):
        m.supervise(offline_diagnostic_worker, spec, budget, deadline=spec['deadline'],
            metadata=tmp_path/'owned.json', integrity_check=lambda: None)
    assert budget.state()['API'] == 0 and not (tmp_path/'child').exists()


def headers_stall_http_worker(spec, payload, run_path, connection):
    from unittest.mock import patch
    import time
    from llmbo_para.electrothermal_responses import _responses_request_worker
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): time.sleep(20.)
    class Provider:
        def open(self, *args, **kwargs): return Reply()
    with patch('llmbo_para.llm.build_opener', return_value=Provider()):
        _responses_request_worker(spec, payload, run_path, connection)


def test_actual_bounded_headers_then_parent_cutoff_preserves_200(tmp_path, monkeypatch):
    from llmbo_para import electrothermal_responses as responses
    from llmbo_para.electrothermal_requests import LLMRequestFailure
    from llmbo_para.runstore import RunStore
    monkeypatch.setenv('SUB2API_API_KEY', 'offline-placeholder')
    monkeypatch.setattr(responses, '_responses_request_worker', headers_stall_http_worker)
    store = RunStore(tmp_path/'run', {'kind': 'offline headers hard cutoff'}, command='offline cutoff fixture')
    client = responses.BoundedResponsesTransport('https://provider.invalid/v1/responses', 'SUB2API_API_KEY',
        model='offline', max_tokens=8192, json_mode=True, timeout_s=4., run_store=store)
    with pytest.raises(LLMRequestFailure):
        client.post({'task': 'warm_start_electrothermal', 'artifact_task': 'headers_stall', 'instructions': 'JSON'})
    diagnostic = client.last_request_diagnostic
    assert diagnostic['reason'] == 'deadline_exceeded' and diagnostic['http_request_started']
    assert diagnostic['http_status'] == 200 and diagnostic['failure_stage'] == 'reading_body'


def test_observer_wrapper_does_not_preload_spawn_modules(tmp_path):
    m = feature(); p = release_fixture(m, tmp_path)
    spec = util.spec_from_file_location('own_reasoning_guard', m.EVIDENCE/'run_tests.py')
    wrapper = util.module_from_spec(spec); spec.loader.exec_module(wrapper)
    assert hasattr(wrapper, 'make_observer'), 'observer import isolation missing'
    names = ('run_responses_reasoning_diagnostic','run_region_transport_validation','run_lgbo_real_gain')
    saved = {n:sys.modules.pop(n, None) for n in names}
    try:
        observed = wrapper.make_observer(p, tmp_path)
        assert not any(n in sys.modules for n in names)
        from test_lgbo_real_gain import load
        live = load()
        transport = import_module('run_region_transport_validation')
        import pickle
        assert pickle.loads(pickle.dumps(transport.supervise.__globals__['_owned_bootstrap'])) is live._owned_bootstrap
        assert observed.unchanged()
    finally:
        for n in names:
            sys.modules.pop(n, None)
            if saved[n] is not None: sys.modules[n] = saved[n]


@pytest.mark.parametrize('attempt', ['r2','r3'])
def test_versioned_full_release_preserves_failed_original(tmp_path, attempt):
    m = feature(); p = release_fixture(m, tmp_path)
    release = m.read(tmp_path/'software-release.json')
    old_manifest = tmp_path/'runtime-before-final.json'
    manifest_path = tmp_path/f'runtime-before-final-{attempt}.json'
    manifest_path.write_bytes(old_manifest.read_bytes())
    old_result = tmp_path/'tests/ge-re-final-full/result.json'
    destination = tmp_path/f'tests/ge-re-final-full-{attempt}/result.json'
    before = m.read(old_result.parent/'manifest-before.json')
    full = m.read(old_result)
    for value in (before, full):
        value['runtime_observation']['runtime_manifest_sha256'] = m.sha(manifest_path)
    put(destination.parent/'manifest-before.json', before); put(destination, full)
    old_full = m.read(old_result); old_full['exit_code'] = 1; put(old_result, old_full)
    release.update(full_attempt=attempt, full_result_sha256=m.sha(destination),
                   runtime_manifest_sha256=m.sha(manifest_path))
    put(tmp_path/'software-release.json', release)
    m._validate_release(p, tmp_path)
    assert m.read(old_result)['exit_code'] == 1
    observer = m.RuntimeObservation(p, tmp_path, attempt=attempt)
    assert observer.unchanged()


@pytest.mark.parametrize('attempt', ['../r2','r1','r9',None,True])
def test_full_attempt_cannot_select_arbitrary_evidence(tmp_path, attempt):
    m = feature(); p = release_fixture(m, tmp_path)
    value = m.read(tmp_path/'software-release.json'); value['full_attempt'] = attempt
    put(tmp_path/'software-release.json', value)
    with pytest.raises(ValueError): m._validate_release(p, tmp_path)
