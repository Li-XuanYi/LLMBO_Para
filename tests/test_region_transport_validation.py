"""No-network release gates and bounded experiment accounting."""
from copy import deepcopy
from importlib import import_module
import json
from pathlib import Path
import sys

import pytest


def feature():
    scripts = str(Path(__file__).resolve().parents[1] / 'scripts')
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    return import_module('run_region_transport_validation')


def proofs():
    return [{'context_id': str(i)*64, 'complete': True,
             'effect': {'action_valid': True, 'tilt_applied': i == 1,
                        'max_abs_shift': .01 if i == 1 else 0.,
                        'state_preserved': True, 'EI_matches': True}}
            for i in (1, 2, 3)]


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'incomplete', 'none_only',
                                   'no_shift', 'variance', 'EI'])
def test_region_gate_does_not_release_false_success(damage):
    module = feature()
    values = proofs()
    assert module.gate_passed(values)
    if damage == 'missing': values.pop()
    elif damage == 'duplicate': values[1]['context_id'] = values[0]['context_id']
    elif damage == 'incomplete': values[1]['complete'] = False
    elif damage == 'none_only': values[0]['effect'].update(tilt_applied=False, max_abs_shift=0.)
    elif damage == 'no_shift': values[0]['effect']['max_abs_shift'] = 0.
    elif damage == 'variance': values[1]['effect']['state_preserved'] = False
    else: values[1]['effect']['EI_matches'] = False
    assert not module.gate_passed(values)


def test_budget_is_persistent_bounded_and_duplicate_charges_fail(tmp_path):
    module = feature()
    budget = module.ValidationBudget.start(tmp_path / 'journal.jsonl', protocol_sha='a'*64)
    budget.begin('diagnostic')
    for i in range(6): budget.charge('API', str(i))
    with pytest.raises(RuntimeError): budget.charge('API', 'extra')
    with pytest.raises(RuntimeError): budget.charge('API', '0')
    with pytest.raises(RuntimeError): budget.require(1)
    restored = module.ValidationBudget.load(budget.path)
    assert restored.counts() == {'API': 6, 'DFN': 0}
    restored.finish(True)
    with pytest.raises(RuntimeError): restored.begin('initialization', gate=[])
    restored.begin('initialization', gate=proofs())
    for i in range(16): restored.charge('DFN', 'd'+str(i))
    with pytest.raises(RuntimeError): restored.charge('DFN', 'd16')
    assert restored.counts() == {'API': 6, 'DFN': 16}


def test_budget_deadline_and_failure_do_not_reset(tmp_path, monkeypatch):
    module = feature()
    clock = [100.]
    monkeypatch.setattr(module.time, 'monotonic', lambda: clock[0])
    budget = module.ValidationBudget.start(tmp_path / 'j.jsonl', protocol_sha='a'*64)
    budget.begin('diagnostic')
    clock[0] += 901
    with pytest.raises((RuntimeError, TimeoutError)): budget.charge('API', 'late')
    budget.finish(False)
    with pytest.raises(RuntimeError): module.ValidationBudget.load(budget.path).begin('diagnostic')


def test_authentication_and_zero_authority_never_load_a_credential(tmp_path, monkeypatch):
    module = feature()
    calls = []
    monkeypatch.setattr(module, 'read_credential', lambda: calls.append(1))
    result = module.run_validation({}, tmp_path)
    assert result['dry_run'] and result['actual_API'] == result['actual_DFN'] == 0
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        module.run_validation({}, tmp_path, execute=True)
    assert not calls and not (tmp_path / 'budget-journal.jsonl').exists()


def test_consecutive_failure_stop_and_legal_abstention():
    streak = feature().RequestFailureStreak()
    streak.observe({'status': 'failed'})
    streak.observe({'status': 'failed'})
    streak.observe({'status': 'received'})  # Includes a legitimate kind=none.
    assert streak.count == 0
    streak.observe({'status': 'failed'})
    streak.observe({'status': 'failed'})
    with pytest.raises(RuntimeError): streak.observe({'status': 'failed'})


def test_failure_streak_can_continue_across_full_arms():
    streak = feature().RequestFailureStreak(initial=2)
    with pytest.raises(RuntimeError): streak.observe({'status': 'failed'})


def scenario(tmp_path, mode):
    """Logical phase charges only; never use a model, credential or HTTP client."""
    module = feature()
    protocol = {'contexts': [{'context_id': str(i)*64} for i in (1, 2, 3)],
                'comparison': {'seeds': [1709, 3253, 5501]}}
    budget = module.ValidationBudget.start(tmp_path / 'budget.jsonl', protocol_sha='a'*64)
    calls = []
    plan = tmp_path / 'initial.json'
    first_failed = False

    def run(spec):
        nonlocal first_failed
        calls.append(deepcopy(spec))
        kind = spec['kind']
        if kind in ('minimal', 'historical'):
            budget.charge('API', spec['label'])
            if kind == 'minimal':
                return {'passed': mode != 'minimal_failure', 'diagnostic': {'reason': 'protocol_error'}}
            i = spec['context_index']
            if i == 0 and not first_failed and mode in ('timeout_once', 'bad_protocol', 'unknown_network'):
                first_failed = True
                reason = {'timeout_once': 'deadline_exceeded', 'bad_protocol': 'protocol_error',
                          'unknown_network': 'transport_error'}[mode]
                return {'passed': False, 'diagnostic': {'reason': reason,
                        'network_diagnostic': {'category': 'unknown', 'cause_type': 'other'}}}
            proof = deepcopy(proofs()[i])
            if mode == 'none_only': proof['effect'].update(tilt_applied=False, max_abs_shift=0.)
            if mode == 'wrong_context': proof['context_id'] = 'f'*64
            return {'passed': True, **proof}
        if kind == 'initialization':
            for i in range(16): budget.charge('DFN', 'initial'+str(i))
            plan.write_text('{}')
            return {'status': 'completed', 'audit_passed': True, 'candidate_count': 8,
                    'plan_path': str(plan), 'plan_file_sha256': module.sha(plan)}
        assert kind == 'arm'
        if mode == 'carry_failure' and spec['arm'] == 'full' and spec['seed'] == 3253:
            assert spec['initial_failure_streak'] == 2
            raise RuntimeError('third consecutive failure in next Full arm')
        for i in range(40): budget.charge('DFN', spec['label']+str(i))
        if spec['arm'] == 'full':
            for i in range(20): budget.charge('API', spec['label']+'a'+str(i))
        if mode == 'initial_tamper': plan.write_text('{"changed":true}')
        return {'status': 'completed', 'audit_passed': True, 'BO_rounds': 20,
                'seed': spec['seed'], 'arm': 'wrong' if mode == 'wrong_arm' else spec['arm'],
                'initial_file_sha': 'f'*64 if mode == 'wrong_initial_receipt' else module.sha(plan),
                'first_numerical_context_sha': 'b'*64 if mode == 'wrong_first_context' and spec['arm'] == 'full' else 'a'*64,
                'HV': 95., 'F_U': .01, 'F_T': .1,
                'request_failure_streak': 2 if mode == 'carry_failure' and spec['arm'] == 'full' else 0}

    result = module.execute_sequence(protocol, budget, run_phase=run)
    return result, calls, budget


@pytest.mark.parametrize('mode', ['minimal_failure', 'bad_protocol', 'unknown_network', 'none_only', 'wrong_context'])
def test_api_gate_failure_never_dispatches_initialization_or_bo(tmp_path, mode):
    result, calls, budget = scenario(tmp_path, mode)
    assert result['status'] == 'failed'
    assert not any(c['kind'] in ('initialization', 'arm') for c in calls)
    assert budget.counts()['DFN'] == 0
    assert budget.state()['closed']


@pytest.mark.parametrize('mode,api_count', [('success', 64), ('timeout_once', 65)])
def test_gated_six_arm_sequence_and_controlled_replay(tmp_path, mode, api_count):
    result, calls, budget = scenario(tmp_path, mode)
    assert result['status'] == 'completed'
    assert budget.counts() == {'API': api_count, 'DFN': 256}
    historical = [c for c in calls if c['kind'] == 'historical']
    assert [c['timeout_s'] for c in historical] == ([60., 120., 120.] if mode == 'success' else [60., 120., 120., 120.])
    arms = [c for c in calls if c['kind'] == 'arm']
    assert [(c['seed'], c['arm']) for c in arms] == [(1709, 'plain'), (1709, 'full'),
        (3253, 'full'), (3253, 'plain'), (5501, 'plain'), (5501, 'full')]


@pytest.mark.parametrize('mode', ['carry_failure', 'initial_tamper'])
def test_failure_streak_and_frozen_initialization_stop_sequence(tmp_path, mode):
    result, calls, budget = scenario(tmp_path, mode)
    assert result['status'] == 'failed'
    assert budget.counts()['DFN'] < 256
    assert budget.state()['closed']


@pytest.mark.parametrize('mode', ['wrong_arm', 'wrong_initial_receipt', 'wrong_first_context'])
def test_misaligned_pair_cannot_be_reported_as_completed(tmp_path, mode):
    result, calls, budget = scenario(tmp_path, mode)
    assert result['status'] == 'failed'
    assert budget.state()['closed']


def test_fake_release_cannot_reach_execution_or_load_a_key(tmp_path, monkeypatch):
    module = feature()
    (tmp_path / 'approval.json').write_text(json.dumps({'limits': {'API': 66}}))
    (tmp_path / 'software-release.json').write_text(json.dumps({'passed': True}))
    calls = []
    monkeypatch.setattr(module, 'read_credential', lambda: calls.append('key'))
    monkeypatch.setattr(module, '_execute', lambda *a: calls.append('execution') or {}, raising=False)
    with pytest.raises((ValueError, RuntimeError, KeyError, FileNotFoundError)):
        module.run_validation({}, tmp_path, execute=True)
    assert not calls and not (tmp_path / 'budget-journal.jsonl').exists()


@pytest.mark.parametrize('damage', [None, 'protocol', 'plan', 'runtime_manifest', 'result', 'source',
                                   'untested_runtime', 'stale_runtime', 'runtime_drift'])
def test_release_binds_plan_inputs_runtime_and_actual_tested_source(tmp_path, damage, monkeypatch):
    module = feature()
    # The runtime and the source under test must be the same checkout.
    monkeypatch.setattr(module, 'WT', Path(__file__).resolve().parents[1])
    from datetime import datetime, timezone
    plan = tmp_path / 'plan.md'
    plan.write_text('software-only release unit fixture')
    protocol = {'version': 'region_transport_validation_v1', 'plan_path': str(plan)}
    protocol_path = tmp_path / 'proposed-protocol.json'
    protocol_path.write_text(json.dumps(protocol))
    names = ['run_region_transport_validation.py', 'run_lgbo_real_gain.py', 'lgbo_real_gain_worker.py']
    runtime = {n: module.sha(module.WT / 'scripts' / n) for n in names}
    runtime_path = tmp_path / 'runtime.json'
    head = 'software-fixture-head'
    runtime_path.write_text(json.dumps({'files': runtime, 'head': head}))
    observation = {'runtime_manifest_sha256': module.sha(runtime_path), 'runtime_files': runtime,
                   'head': head, 'protocol_sha256': module.sha(protocol_path)}
    full = tmp_path / 'result.json'
    full_data = {'exit_code': 0, 'head_after': head, 'runtime_observation': observation,
        'runtime_unchanged_during_run': True,
        'junit_counts': {'passed': 1205, 'failures': 0, 'errors': 0, 'skipped': 0},
        'boundary': {'network_attempts': 0, 'battery_solve_attempts': 0},
        'source_unchanged_during_run': True, 'protected_unchanged_during_run': True,
        'source_after': {p.relative_to(module.WT).as_posix(): module.sha(p)
                         for p in sorted((module.WT/'src').rglob('*'))
                         if p.is_file() and '__pycache__' not in p.parts}}
    if damage == 'untested_runtime': full_data.pop('runtime_observation')
    elif damage == 'stale_runtime':
        full_data['runtime_observation'] = {**observation, 'runtime_manifest_sha256': 'f'*64}
    elif damage == 'runtime_drift': full_data['runtime_unchanged_during_run'] = False
    full.write_text(json.dumps(full_data))
    approval = {'approved_commit': 'b204050bced0328fd743eb50fe3c7f35b1657aca',
        'plan_sha256': module.sha(plan), 'proposed_protocol_sha256': module.sha(protocol_path),
        'limits': {'DFN': 256, 'API': 66, 'wall_clock_s': 10800, 'diagnostic_API': 6, 'diagnostic_wall_clock_s': 900},
        'controlled_frozen_replay': 1, 'automatic_retries': 0}
    release = {'head': head, 'protocol_sha256': module.sha(protocol_path), 'source_fingerprint': module.fingerprint(module.WT),
        'runtime_files': runtime, 'runtime_manifest': str(runtime_path),
        'runtime_manifest_sha256': module.sha(runtime_path),
        'full_result': str(full), 'full_result_sha256': module.sha(full)}
    if damage == 'protocol': protocol_path.write_text('{}')
    elif damage == 'plan': plan.write_text('changed')
    elif damage == 'runtime_manifest': runtime_path.write_text('{}')
    elif damage == 'result': full.write_text('{}')
    elif damage == 'source': release['source_fingerprint'] = 'f'*64
    if damage is None:
        module._validate_release(protocol, tmp_path, approval, release)
    else:
        with pytest.raises(ValueError): module._validate_release(protocol, tmp_path, approval, release)


@pytest.mark.parametrize('damage', [None, 'script', 'test', 'added_test', 'protocol', 'manifest', 'head'])
def test_guarded_full_observation_captures_before_testing_and_detects_drift(tmp_path, damage):
    from importlib.util import spec_from_file_location, module_from_spec
    spec = spec_from_file_location('transport_plan_test_guard', feature().EVIDENCE/'run_tests.py')
    guard = module_from_spec(spec)
    spec.loader.exec_module(guard)
    wt = tmp_path/'worktree'
    (wt/'scripts').mkdir(parents=True)
    (wt/'tests').mkdir()
    test_file = wt/'tests/test_example.py'
    test_file.write_text('assert True')
    names = ('run_region_transport_validation.py', 'run_lgbo_real_gain.py', 'lgbo_real_gain_worker.py')
    for name in names: (wt/'scripts'/name).write_text('fixture runtime '+name)
    runtime = {n: guard.RuntimeObservation.sha(wt/'scripts'/n) for n in names}
    manifest = tmp_path/'runtime.json'
    manifest.write_text(json.dumps({'files': runtime, 'head': 'fixture',
                                   'frozen_entry': str(wt/'scripts'/names[0])}))
    protocol = tmp_path/'protocol.json'
    protocol.write_text('{}')
    head = ['fixture']
    observed = guard.RuntimeObservation(manifest, protocol, wt, head_reader=lambda: head[0])
    initial = deepcopy(observed.observation)
    if damage == 'script': (wt/'scripts'/names[0]).write_text('changed')
    elif damage == 'test': test_file.write_text('changed')
    elif damage == 'added_test': (wt/'tests/test_new.py').write_text('assert True')
    elif damage == 'protocol': protocol.write_text('{"changed":true}')
    elif damage == 'manifest': manifest.write_text('{}')
    elif damage == 'head': head[0] = 'changed'
    assert observed.observation == initial  # Never recapture a later runtime as the tested one.
    assert observed.unchanged() is (damage is None)


def offline_api_worker(spec, payload, run_path, connection):
    """Real owned HTTP worker, with only its socket boundary replaced in memory."""
    from unittest.mock import patch
    from llmbo_para.electrothermal_responses import _responses_request_worker
    from test_electrothermal_responses import response

    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return self.body[:limit]

    class Provider:
        def open(self, request, **kwargs):
            wire = json.loads(json.loads(request.data)['input'])
            formal = ({'ok': True} if 'request_id' not in wire else
                      {'request_id': wire['request_id'], 'region': {'kind': 'region',
                       'lb': [.3]*6, 'ub': [.8]*6, 'confidence': .65}})
            reply = Reply()
            reply.body = json.dumps(response(formal)).encode()
            return reply

    with patch('llmbo_para.llm.build_opener', return_value=Provider()):
        _responses_request_worker(spec, payload, run_path, connection)


def offline_native_validation_worker(spec, connection):
    module = feature()

    def factory(options, store):
        from llmbo_para.electrothermal_responses import BoundedResponsesTransport
        client = BoundedResponsesTransport('https://sidrune.ai/v1/responses', 'SUB2API_API_KEY',
            model='deepseek-v4-pro', max_tokens=8192, json_mode=True,
            timeout_s=options['timeout_s'], run_store=store)
        client._request_worker = lambda: offline_api_worker
        return client

    module.make_api_transport = factory
    module.validation_worker(spec, connection)


@pytest.mark.parametrize('kind', ['minimal', 'historical'])
def test_real_spawned_validation_path_with_offline_http(archived_round, monkeypatch, tmp_path_factory, tmp_path, kind):
    module = feature()
    payload, formal, path = frozen_round(archived_round, monkeypatch, tmp_path_factory)
    monkeypatch.setenv('SUB2API_API_KEY', 'offline-not-a-provider-key')
    budget = module.ValidationBudget.start(tmp_path / 'j.jsonl', protocol_sha='a'*64)
    budget.begin('diagnostic')
    spec = {'kind': kind, 'label': 'd0', 'timeout_s': 30., 'source_root': str(module.WT),
        'source': module.fingerprint(module.WT), 'source_commit': 'offline-software-test',
        'deadline': budget.deadline, 'output': str(tmp_path / 'out'), 'protocol_sha': 'a'*64,
        'payload': payload, 'round_path': str(path), 'round_sha256': module.sha(path)}
    result = module.supervise(offline_native_validation_worker, spec, budget,
        deadline=module.time.monotonic()+45., metadata=tmp_path / 'supervision.json')
    assert result['passed'], result
    assert budget.counts() == {'API': 1, 'DFN': 0}  # Logical fixture charge, real API0.
    assert json.loads((tmp_path / 'supervision.json').read_text())['owned_tree_stopped']
    if kind == 'historical':
        assert result['effect']['tilt_applied'] and result['effect']['state_preserved']


def failing_software_validation_worker(spec, connection):
    module = feature()
    import lgbo_real_gain_worker as worker
    original = worker._controller

    def factory(*args, **kwargs):
        client = original(*args, **kwargs)

        class Failing:
            def post(self, payload):
                raise TimeoutError('offline failure; no API')

        client.transport = Failing()
        return client

    worker._controller = factory
    module.validation_worker(spec, connection)


def test_new_worker_shared_initialization_twenty_rounds_and_global_streak(monkeypatch):
    """Actual optimizer/stores/audit; algebraic model and mock none, not real DFN/API."""
    import tempfile
    module = feature()
    monkeypatch.setattr(module, 'WT', Path(__file__).resolve().parents[1])
    root = Path(tempfile.mkdtemp(prefix='nt24-', dir=module.MAIN/'runs'))
    proposal = module.BASE/'lgbo-real-gain-proposal-20261023'
    base = module.read(proposal/'new_full.disabled-config.json')
    base['optimization'].update(gp_sweeps=0, global_pool_size=16, local_pool_size=8)
    budget = module.ValidationBudget.start(root/'j.jsonl', protocol_sha='a'*64)
    budget.begin('diagnostic')
    budget.finish(True)
    budget.begin('initialization', gate=proofs())  # Explicit software gate fixture.
    spec = {'kind': 'initialization', 'arm': 'plain', 'label': 'i0', 'seed': 1709,
        'base_config': base, 'software_fixture': True, 'solve_cap': 0,
        'source_root': str(module.WT), 'source': module.fingerprint(module.WT),
        'source_commit': 'software-fixture-only', 'deadline': budget.deadline,
        'output': str(root/'i'), 'coordinates': module.read(proposal/'fixed-eight-coordinates.json')['parameters']}
    first = module.supervise(module.validation_worker, spec, budget,
        deadline=module.time.monotonic()+120, metadata=root/'mi.json')
    assert first['audit_passed'] and first['candidate_count'] == 8
    assert first['plan_file_sha256'] == module.sha(first['plan_path'])
    budget.finish(True)
    budget.begin('main')
    results = []
    for arm in ('plain', 'full'):
        current = {**deepcopy(spec), 'kind': 'arm', 'arm': arm, 'label': arm,
            'initial_failure_streak': 2, 'output': str(root/arm[0]),
            'initial': {'path': first['plan_path'], 'sha256': first['plan_file_sha256']}}
        results.append(module.supervise(module.validation_worker, current, budget,
            deadline=module.time.monotonic()+120, metadata=root/(arm+'.json')))
    assert all(r['audit_passed'] and r['BO_rounds'] == 20 for r in results)
    assert results[0]['HV'] == results[1]['HV']
    assert results[0]['first_numerical_context_sha'] == results[1]['first_numerical_context_sha']
    assert results[1]['request_failure_streak'] == 0
    current.update(label='stop', output=str(root/'stop'))
    with pytest.raises(RuntimeError):
        module.supervise(failing_software_validation_worker, current, budget,
            deadline=module.time.monotonic()+60, metadata=root/'stop.json')
    run = next((root/'stop').glob('2026*'))
    assert not list((run/'mo-rounds').glob('*.json'))
    assert module.read(root/'stop.json')['owned_tree_stopped']
    assert budget.counts() == {'API': 0, 'DFN': 0}


def test_actual_source_and_historical_preparation_stops_before_key_and_clock(monkeypatch):
    """Exercise real immutable input preparation, stopping before any authorization use."""
    import tempfile
    import shutil
    module = feature()
    monkeypatch.setattr(module, 'WT', Path(__file__).resolve().parents[1])
    root = Path(tempfile.mkdtemp(prefix='nprep-', dir=module.MAIN/'runs'))
    original = module.EVIDENCE
    for name in ('approval.json', 'proposed-protocol.json'):
        shutil.copyfile(original/name, root/name)
    (root/'software-release.json').write_text('{"fixture":"no live authority"}')
    release = {'source_fingerprint': module.fingerprint(module.WT),
        'runtime_files': {n: module.sha(module.WT/'scripts'/n) for n in
            ('run_region_transport_validation.py', 'run_lgbo_real_gain.py', 'lgbo_real_gain_worker.py')}}
    reached = []

    def forbidden():
        reached.append(True)
        raise RuntimeError('software stop before reading any key')

    monkeypatch.setattr(module, 'read_credential', forbidden)
    with pytest.raises(RuntimeError, match='software stop'):
        module._execute(module.read(root/'proposed-protocol.json'), root,
                        module.read(root/'approval.json'), release)
    assert reached and module.fingerprint(root/'s') == release['source_fingerprint']
    assert module.read(root/'historical-audit-0.json')['passed']
    assert not (root/'budget-journal.jsonl').exists()
    assert not (root/'execution-claim.json').exists()


@pytest.fixture(scope='module')
def archived_round():
    return {}


def frozen_round(archived_round, monkeypatch, tmp_path_factory):
    from test_lgbo_region_audit import run_fixture
    from test_region_failure_audit import _shared_initialization
    if 'shared' not in archived_round:
        archived_round['shared'] = _shared_initialization(tmp_path_factory.mktemp('gateinit'))
        archived_round['shared']['budgets']['wall_clock_s'] = 300.
    run, _ = run_fixture(archived_round, monkeypatch, tmp_path_factory, kind='region')
    payload = json.loads(next((run / 'llm').glob('*.payload.json')).read_text())
    ordinal = 0
    formal = json.loads(json.loads((run / 'llm' / f'{ordinal:06d}.responses-formal.json').read_text())['response_json'])
    path = next(p for p in (run / 'mo-rounds').glob('*.json')
                if json.loads(p.read_text())['context']['context_id'] == payload['context_id'])
    return payload, formal, path


def test_frozen_region_effect_restores_real_gp_without_new_targets(archived_round, monkeypatch, tmp_path_factory):
    payload, formal, path = frozen_round(archived_round, monkeypatch, tmp_path_factory)
    result = feature().validate_region_effect(payload, formal, path)
    assert result['action_valid'] and result['tilt_applied']
    assert result['max_abs_shift'] > 0
    assert result['state_preserved'] and result['EI_matches']
    assert result['DFN'] == result['API'] == result['new_objective_pairs'] == 0


@pytest.mark.parametrize('damage', ['binding', 'weight', 'scale', 'variance'])
def test_frozen_effect_rejects_mismatched_input(archived_round, monkeypatch, tmp_path_factory, tmp_path, damage):
    payload, formal, path = frozen_round(archived_round, monkeypatch, tmp_path_factory)
    payload, formal = deepcopy(payload), deepcopy(formal)
    # Copy the archived run so parent manifest and source paths remain available.
    import shutil
    run = tmp_path / 'r'
    shutil.copytree(path.parent.parent, run)
    target = run / 'mo-rounds' / path.name
    data = json.loads(target.read_text())
    if damage == 'binding': formal['context_id'] = 'wrong'
    elif damage == 'weight': data['context']['scalarization']['weights'] = [.1, .9]
    elif damage == 'scale': data['context']['scalarization']['objective_scales'] = [100., 1.]
    else: data['std'][0] += .1
    target.write_text(json.dumps(data), encoding='utf8')
    with pytest.raises(ValueError): feature().validate_region_effect(payload, formal, target)
