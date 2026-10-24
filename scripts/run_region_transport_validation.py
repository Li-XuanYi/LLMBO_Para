"""Gated, bounded Region transport validation; importing or dry-running sends nothing."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time

from run_lgbo_real_gain import (
    OwnedWindowsJob, check_payload, fingerprint, keep_awake, read_credential,
    sha, supervise, write,
)

WT = Path('C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para')
MAIN = Path('D:/Users/aa133/Desktop/LLMBO_Para')
BASE = MAIN / 'bo-repair-work/20261017_et_implementation'
EVIDENCE = BASE / 'api-transport-repair-20261024'
OUTPUT = MAIN / 'runs/t24r'
CAPS = {'API': 66, 'DFN': 256, 'wall_clock_s': 10800}
PHASES = {'diagnostic': {'API': 6, 'DFN': 0},
          'initialization': {'API': 0, 'DFN': 16},
          'main': {'API': 60, 'DFN': 240}}


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def gate_passed(proofs):
    if type(proofs) is not list or len(proofs) != 3:
        return False
    try:
        ids = [p['context_id'] for p in proofs]
        if len(set(ids)) != 3 or any(type(i) is not str or len(i) != 64 for i in ids):
            return False
        for proof in proofs:
            effect = proof['effect']
            if not (proof['complete'] is True and effect['action_valid'] is True
                    and effect['state_preserved'] is True and effect['EI_matches'] is True):
                return False
            shift = effect['max_abs_shift']
            if type(shift) not in (int, float) or not math.isfinite(shift) or shift < 0:
                return False
        return any(p['effect']['tilt_applied'] is True and p['effect']['max_abs_shift'] > 1e-12
                   for p in proofs)
    except (KeyError, TypeError):
        return False


class ValidationBudget:
    """One durable parent journal, phase caps, absolute clocks and no renewal."""

    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def start(cls, path, *, protocol_sha):
        if type(protocol_sha) is not str or len(protocol_sha) != 64:
            raise ValueError('protocol digest required')
        obj = cls(path)
        value = {'type': 'start', 'limits': CAPS, 'protocol_sha': protocol_sha,
                 'mono': time.monotonic(), 'unix': time.time(), 'previous': None}
        value['hash'] = digest(value)
        with obj.path.open('x', encoding='utf8') as stream:
            stream.write(json.dumps(value, separators=(',', ':')) + '\n')
            stream.flush()
            import os
            os.fsync(stream.fileno())
        return obj

    @classmethod
    def load(cls, path):
        obj = cls(path)
        obj.state()
        return obj

    def state(self):
        content = self.path.read_text(encoding='utf8')
        if not content.endswith('\n'):
            raise ValueError('incomplete budget journal')
        events = [json.loads(line) for line in content.splitlines()]
        if not events or events[0].get('type') != 'start' or events[0].get('limits') != CAPS:
            raise ValueError('invalid budget origin')
        state = {'counts': {'API': 0, 'DFN': 0}, 'phase': None, 'finished': [],
                 'closed': False, 'ids': set(), 'phase_counts': {k: {'API': 0, 'DFN': 0} for k in PHASES}}
        previous = None
        for i, event in enumerate(events):
            if event.get('previous') != previous or event.get('hash') != digest({k: v for k, v in event.items() if k != 'hash'}):
                raise ValueError('budget hash chain differs')
            previous = event['hash']
            if i == 0:
                continue
            if state['closed']:
                raise ValueError('event after closure')
            if event['type'] == 'begin':
                expected = list(PHASES)[len(state['finished'])]
                if state['phase'] is not None or event['phase'] != expected:
                    raise ValueError('budget phase order differs')
                if expected == 'initialization' and not gate_passed(event.get('gate')):
                    raise ValueError('DFN phase lacks complete Region gate')
                state['phase'] = expected
            elif event['type'] == 'charge':
                phase, kind, ident = state['phase'], event['kind'], event['event_id']
                if phase is None or kind not in ('API', 'DFN') or ident in state['ids']:
                    raise ValueError('invalid or duplicate budget charge')
                state['ids'].add(ident)
                state['counts'][kind] += 1
                state['phase_counts'][phase][kind] += 1
                if state['counts'][kind] > CAPS[kind] or state['phase_counts'][phase][kind] > PHASES[phase][kind]:
                    raise ValueError('persisted budget exceeds scope')
            elif event['type'] == 'finish':
                if state['phase'] is None or type(event['success']) is not bool:
                    raise ValueError('invalid phase completion')
                state['finished'].append(state['phase'])
                state['phase'] = None
                state['closed'] = not event['success'] or len(state['finished']) == len(PHASES)
            else:
                raise ValueError('unknown budget event')
        state.update(origin=events[0], hash=previous)
        return state

    def _append(self, value):
        import os
        value = {**value, 'previous': self.state()['hash']}
        value['hash'] = digest(value)
        with self.path.open('a', encoding='utf8') as stream:
            stream.write(json.dumps(value, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    @property
    def deadline(self):
        origin = self.state()['origin']
        return min(origin['mono'] + CAPS['wall_clock_s'],
                   time.monotonic() + max(0., origin['unix'] + CAPS['wall_clock_s'] - time.time()))

    def _open(self):
        state = self.state()
        stage_end = state['origin']['mono'] + 900 if state['phase'] == 'diagnostic' else self.deadline
        if state['closed'] or time.monotonic() >= min(self.deadline, stage_end):
            raise RuntimeError('experiment closed or deadline exhausted')
        return state

    def begin(self, phase, *, gate=None):
        state = self._open()
        expected = list(PHASES)[len(state['finished'])] if len(state['finished']) < len(PHASES) else None
        if state['phase'] is not None or phase != expected:
            raise RuntimeError('overlapping, repeated or unordered phase')
        if phase == 'initialization' and not gate_passed(gate):
            raise RuntimeError('Region gate not passed')
        self._append({'type': 'begin', 'phase': phase, **({'gate': gate} if gate is not None else {})})

    def finish(self, success):
        if self.state()['phase'] is None or type(success) is not bool:
            raise RuntimeError('active phase required')
        self._append({'type': 'finish', 'success': success})

    def counts(self):
        return self.state()['counts'].copy()

    def require(self, calls):
        if type(calls) is not int or calls < 0:
            raise ValueError('integer reservation required')
        state = self._open()
        phase = state['phase']
        if phase is None or state['counts']['DFN'] + calls > CAPS['DFN'] or state['phase_counts'][phase]['DFN'] + calls > PHASES[phase]['DFN']:
            raise RuntimeError('insufficient solver reservation')

    def charge(self, kind, ident):
        state = self._open()
        phase = state['phase']
        if (phase is None or kind not in ('API', 'DFN') or type(ident) is not str or not ident
                or ident in state['ids'] or state['counts'][kind] >= CAPS[kind]
                or state['phase_counts'][phase][kind] >= PHASES[phase][kind]):
            raise RuntimeError('invalid or exhausted scoped charge')
        self._append({'type': 'charge', 'kind': kind, 'event_id': ident})


class RequestFailureStreak:
    def __init__(self, initial=0):
        if type(initial) is not int or not 0 <= initial < 3:
            raise ValueError('initial failure streak must be in [0,2]')
        self.count = initial

    def observe(self, outcome):
        status = outcome.get('status')
        if status == 'received':
            self.count = 0
        elif status == 'failed':
            self.count += 1
        else:
            raise RuntimeError('formal request was skipped or unavailable')
        if self.count >= 3:
            raise RuntimeError('three consecutive Region request failures')


def validate_region_effect(payload: dict, formal: dict, round_file: Path) -> dict:
    """Historical frozen-GP replay, never a newly evaluated BO observation."""
    import numpy as np
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.mo_optimizer import MORoundContext
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.electrothermal_lgbo import apply_lgbo_region, validate_lgbo_region
    from llmbo_para.runstore import canonical_json
    saved = read(round_file)
    c = saved['context']
    if digest({k: v for k, v in c.items() if k != 'context_id'}) != c['context_id']:
        raise ValueError('frozen round identity differs')
    s = c['scalarization']
    scalar = build_scalarization_context(s['x'], s['y'], s['observation_ids'], weights=s['weights'],
        objective_scales=s['objective_scales'], rho_aug=s['rho_aug'], protocol_signature=s['protocol_signature'])
    if digest(scalar.to_dict()) != digest(s):
        raise ValueError('frozen scalar labels differ')
    if (payload['context_id'] != c['context_id'] or payload['signatures'] != c['signatures']
            or payload['fit_rates'] != c['fit_rates']):
        raise ValueError('frozen payload identity differs')
    gp = Matern52GP.from_state(c['gp_state'])
    if not np.array_equal(gp.x, scalar.x) or not np.array_equal(gp.y, scalar.labels):
        raise ValueError('frozen GP labels differ')
    mean, std = gp.predict(c['pool'])
    if not np.allclose(mean, saved['mean'], atol=1e-10, rtol=1e-10) or not np.allclose(std, saved['std'], atol=1e-10, rtol=1e-10):
        raise ValueError('frozen posterior differs')
    method = payload['region_method']
    validate_lgbo_region(formal, expected_context_id=c['context_id'],
        expected_signatures=c['signatures'], expected_region_method=method)
    before = digest(gp.state_dict())
    config = read(Path(round_file).parent.parent / 'manifest.json')['config']
    space = parameter_space_from_config(config)
    context = MORoundContext(scalar, tuple(c['fit_rates']), canonical_json(c['signatures']).decode(),
        canonical_json(c['gp_state']).decode(), tuple(map(tuple, c['pool'])), c['ordinal'], c['context_id'])
    result = apply_lgbo_region(gp, context, c['pool'], formal, space=space, region_method=method)
    ei = []
    for m, sigma in zip(result['adjusted_mean'], std):
        improvement = scalar.best - m
        if sigma <= 0:
            ei.append(max(improvement, 0.))
        else:
            z = improvement / sigma
            ei.append(max(0., improvement * .5 * math.erfc(-z/math.sqrt(2.))
                          + sigma * math.exp(-.5*z*z)/math.sqrt(2.*math.pi)))
    preserved = before == digest(gp.state_dict()) and np.array_equal(result['std'], std)
    matches = bool(np.allclose(ei, result['effective_ei'], atol=1e-10, rtol=1e-10))
    if not preserved or not matches:
        raise ValueError('frozen state/variance/EI changed inconsistently')
    return {'action_valid': result['action_valid'], 'tilt_applied': result['tilt_applied'],
        'max_abs_shift': max(abs(v) for v in result['signed_delta']),
        'selection_changed': result['selection_changed'], 'fallback_reason': result['fallback_reason'],
        'state_preserved': preserved, 'EI_matches': matches, 'replay': result,
        'DFN': 0, 'API': 0, 'new_objective_pairs': 0, 'GP_state_restores': 1, 'hyperparameter_searches': 0}


def execute_sequence(protocol, budget, *, run_phase, integrity_check=None):
    """Actual phase order and stop rules, independently testable without providers."""
    cases, attempts, proofs = [], [], []
    initialization = None
    inputs_sha = digest(protocol)
    stage = 'diagnostic'

    def invoke(spec):
        budget._open()
        if digest(protocol) != inputs_sha:
            raise ValueError('scientific protocol mutated')
        if integrity_check is not None:
            integrity_check()
        result = run_phase(spec)
        budget._open()  # A late result cannot release the next stage.
        if integrity_check is not None:
            integrity_check()
        return result

    def historical(index, timeout, label):
        result = invoke({'kind': 'historical', 'context_index': index,
                         'timeout_s': timeout, 'label': label})
        attempts.append(result)
        if result.get('passed') and result.get('context_id') != protocol['contexts'][index]['context_id']:
            raise ValueError('historical reply belongs to a different approved context')
        return result

    try:
        budget.begin('diagnostic')
        minimal = invoke({'kind': 'minimal', 'timeout_s': 60., 'label': 'd0'})
        attempts.append(minimal)
        if not minimal.get('passed'):
            raise RuntimeError('minimal transport contract failed')
        first = historical(0, 60., 'd1')
        next_label = 2
        if not first.get('passed'):
            diagnostic = first.get('diagnostic') or {}
            transient = (diagnostic.get('network_diagnostic') or {}).get('category') in (
                'connection_reset', 'connection_aborted', 'timeout', 'tls_eof', 'remote_disconnected')
            if diagnostic.get('reason') not in ('timeout', 'deadline_exceeded') and not transient:
                raise RuntimeError('complete Region failed without an approved recovery condition')
            first = historical(0, 120., 'd2')
            next_label = 3
        if not first.get('passed'):
            raise RuntimeError('controlled Region replay failed')
        proofs.append(first)
        for index in (1, 2):
            result = historical(index, 120., 'd' + str(next_label))
            next_label += 1
            if not result.get('passed'):
                raise RuntimeError('distinct complete Region contract failed')
            proofs.append(result)
        if not gate_passed(proofs):
            raise RuntimeError('complete Region replies lack authentic nonzero influence')
        budget.finish(True)
        stage = 'initialization'
        budget.begin(stage, gate=proofs)
        initialization = invoke({'kind': 'initialization', 'label': 'i0'})
        if (initialization.get('status') != 'completed' or not initialization.get('audit_passed')
                or initialization.get('candidate_count') != 8):
            raise RuntimeError('fresh initialization is incomplete')
        plan = Path(initialization['plan_path'])
        initial_sha = initialization['plan_file_sha256']
        if sha(plan) != initial_sha:
            raise ValueError('fresh initialization differs from the child receipt')
        budget.finish(True)
        stage = 'main'
        budget.begin(stage)
        streak = 0
        for seed, order in zip(protocol['comparison']['seeds'], [('plain', 'full'), ('full', 'plain'), ('plain', 'full')]):
            for arm in order:
                if sha(plan) != initial_sha:
                    raise ValueError('frozen shared initialization changed')
                result = invoke({'kind': 'arm', 'seed': seed, 'arm': arm,
                    'label': 'c' + str(len(cases)).zfill(2), 'initial_failure_streak': streak,
                    'initial': {'path': str(plan), 'sha256': initial_sha}})
                if (result.get('status') != 'completed' or not result.get('audit_passed')
                        or result.get('BO_rounds') != 20 or result.get('seed') != seed
                        or result.get('arm') != arm or result.get('initial_file_sha') != initial_sha):
                    raise RuntimeError('paired arm is incomplete')
                numerical = result.get('first_numerical_context_sha')
                if type(numerical) is not str or len(numerical) != 64:
                    raise ValueError('first numerical context receipt missing')
                previous = next((c for c in cases if c['seed'] == seed), None)
                if previous is not None and previous['first_numerical_context_sha'] != numerical:
                    raise ValueError('paired arms have different starting numerical contexts')
                cases.append(result)
                if arm == 'full':
                    streak = result['request_failure_streak']
                    if type(streak) is not int or not 0 <= streak < 3:
                        raise RuntimeError('invalid continuing Region failure streak')
        if sha(plan) != initial_sha:
            raise ValueError('shared initialization changed at final result')
        if integrity_check is not None:
            integrity_check()
        if len(cases) != 6:
            raise RuntimeError('paired experiment is incomplete')
        budget.finish(True)
        return {'status': 'completed', 'cases': cases, 'initialization': initialization,
                'diagnostic_attempts': attempts, 'gate_proofs': proofs, 'costs': budget.counts()}
    except Exception as exc:
        if budget.state()['phase'] is not None:
            budget.finish(False)
        return {'status': 'failed', 'failure_stage': stage, 'error_type': type(exc).__name__,
                'cases': cases, 'initialization': initialization, 'diagnostic_attempts': attempts,
                'gate_proofs': proofs, 'costs': budget.counts(), 'gain_status': 'inconclusive'}


def make_api_transport(spec, store):
    from llmbo_para.electrothermal_responses import BoundedResponsesTransport
    return BoundedResponsesTransport('https://sidrune.ai/v1/responses', 'SUB2API_API_KEY',
        model='deepseek-v4-pro', max_tokens=8192, json_mode=True,
        timeout_s=spec['timeout_s'], run_store=store)


def validation_worker(spec, connection):
    """Cold source namespace; native request/DFN children remain in the owned job."""
    import os
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    if any(n == 'llmbo_para' or n.startswith('llmbo_para.') for n in sys.modules):
        raise RuntimeError('owned validation worker source namespace was already populated')
    root = Path(spec['source_root']).resolve()
    sys.path.insert(0, str(root / 'src'))
    if spec['kind'] in ('initialization', 'arm'):
        import lgbo_real_gain_worker as worker
        original = worker._controller
        streak = RequestFailureStreak(spec.get('initial_failure_streak', 0))

        def controller(*args, **kwargs):
            client = original(*args, **kwargs)
            request = client.request

            def checked(payload, **options):
                response = request(payload, **options)
                streak.observe(client.last_request_outcome)
                return response

            client.request = checked
            return client

        worker._controller = controller

        class ReceiptConnection:
            def send(self, message):
                kind, value = message
                if kind == 'result':
                    value = {**value, 'request_failure_streak': streak.count}
                    if spec['kind'] == 'initialization':
                        value['plan_file_sha256'] = sha(value['plan_path'])
                    write(Path(spec['output']) / 'validation-receipt.json', value)
                connection.send((kind, value))

            def recv(self):
                return connection.recv()

            def close(self):
                connection.close()

        worker.run_worker(spec, ReceiptConnection())
        return
    from llmbo_para import electrothermal_provenance as provenance
    from llmbo_para.electrothermal_region_wire import region_wire_payload, decode_region_wire
    from llmbo_para.electrothermal_responses import responses_request_body, decode_responses_json
    from llmbo_para.runstore import RunStore
    from lgbo_real_gain_worker import RPCBudget
    if Path(provenance.__file__).resolve() != root/'src/llmbo_para/electrothermal_provenance.py' or provenance.source_fingerprint(root) != spec['source']:
        raise ValueError('actual validation worker source differs')
    budget = RPCBudget(connection, deadline=spec['deadline'], maximum=0, prefix=spec['label'])
    store = RunStore(spec['output'], {'kind': 'transport_probe' if spec['kind'] == 'minimal' else 'honest_historical_Region_replay',
        'actual_transport_source': spec['source'], 'protocol_sha256': spec['protocol_sha']},
        command='bounded API contract and frozen GP influence validation')
    result = None
    transport = None
    try:
        payload = ({'task': 'warm_start_electrothermal', 'artifact_task': 'api_transport_minimal',
                    'instructions': 'This is only a transport probe. Return exactly the JSON object {"ok":true}.',
                    'response_contract': {'type': 'object', 'properties': {'ok': {'const': True}},
                                          'required': ['ok'], 'additionalProperties': False}}
                   if spec['kind'] == 'minimal' else deepcopy(spec['payload']))
        check_payload(payload)
        if spec['kind'] == 'historical' and sha(spec['round_path']) != spec['round_sha256']:
            raise ValueError('approved historical round changed')
        store.write_json('historical-provenance.json', {
            'historical_payload': spec['kind'] == 'historical', 'never_resigned': True,
            'not_new_BO_data': True, 'actual_source_root': str(root),
            'actual_transport_source': spec['source'], 'source_commit': spec.get('source_commit')})
        store.write_json('frozen-payload.json', payload)
        expected = responses_request_body(region_wire_payload(payload), model='deepseek-v4-pro',
                                           max_tokens=8192, json_mode=True)
        transport = make_api_transport(spec, store)
        budget.charge_api(spec['label'])
        formal = transport.post(payload, deadline=budget.deadline)
        task = payload['artifact_task']
        sent = read(store.path / 'http' / (task + '.request.json'))
        raw = read(store.path / 'http' / (task + '.response.json'))
        decoded, issue = decode_responses_json(raw)
        restored = decode_region_wire(decoded, payload) if issue is None else None
        diagnostic = transport.last_request_diagnostic
        if (issue is not None or digest(restored) != digest(formal) or digest(sent['body']) != digest(expected)
                or sent['endpoint'] != 'https://sidrune.ai/v1/responses'
                or diagnostic.get('http_status') != 200 or not diagnostic.get('http_request_started')):
            raise ValueError('raw wire, formal JSON or supervision differs')
        result = {'passed': True, 'complete': True, 'kind': spec['kind'],
                  'diagnostic': diagnostic, 'run_directory': str(store.path)}
        if spec['kind'] == 'minimal':
            if formal != {'ok': True}:
                raise ValueError('minimal JSON contract differs')
        else:
            result.update(context_id=payload['context_id'],
                effect=validate_region_effect(payload, formal, Path(spec['round_path'])))
        store.write_json('validation-proof.json', result)
        store.finish('completed', result)
    except Exception as exc:
        result = {'passed': False, 'complete': False, 'kind': spec['kind'],
                  'error_type': type(exc).__name__, 'run_directory': str(store.path),
                  'diagnostic': transport.last_request_diagnostic if transport is not None else None}
        store.finish('failed', result)
    finally:
        write(Path(spec['output']) / 'worker-result.json', result)
        connection.send(('result', result))
        connection.close()


def _validate_release(protocol, evidence_root, approval, release):
    protocol_file = evidence_root / 'proposed-protocol.json'
    protocol_sha = sha(protocol_file)
    plan = Path(protocol['plan_path'])
    if (approval.get('approved_commit') != 'b204050bced0328fd743eb50fe3c7f35b1657aca'
            or approval.get('plan_sha256') != sha(plan)
            or approval.get('proposed_protocol_sha256') != protocol_sha
            or digest(read(protocol_file)) != digest(protocol)
            or release.get('protocol_sha256') != protocol_sha
            or release.get('source_fingerprint') != fingerprint(WT)
            or approval.get('limits') != {'DFN': 256, 'API': 66, 'wall_clock_s': 10800,
                                         'diagnostic_API': 6, 'diagnostic_wall_clock_s': 900}
            or approval.get('controlled_frozen_replay') != 1 or approval.get('automatic_retries') != 0):
        raise ValueError('approval, reviewed inputs or tested source differs')
    runtime = release['runtime_files']
    if (sha(release['runtime_manifest']) != release['runtime_manifest_sha256']
            or read(release['runtime_manifest']).get('files') != runtime):
        raise ValueError('runtime freeze does not match the pre-test manifest')
    if set(runtime) != {'run_region_transport_validation.py', 'run_lgbo_real_gain.py', 'lgbo_real_gain_worker.py'}:
        raise ValueError('complete frozen runtime required')
    for name, expected in runtime.items():
        if sha(Path(__file__).parent / name) != expected or sha(WT / 'scripts' / name) != expected:
            raise ValueError('tested runtime differs')
    full = read(release['full_result'])
    expected_observation = {'runtime_manifest_sha256': release['runtime_manifest_sha256'],
        'runtime_files': runtime, 'head': release['head'], 'protocol_sha256': protocol_sha}
    if (full.get('runtime_observation') != expected_observation
            or full.get('runtime_unchanged_during_run') is not True
            or full.get('head_after') != release['head']
            or read(release['runtime_manifest']).get('head') != release['head']):
        raise ValueError('full regression did not observe this frozen runtime')
    counts = full.get('junit_counts') or {}
    if (sha(release['full_result']) != release['full_result_sha256'] or full.get('exit_code') != 0
            or counts.get('passed', 0) < 1205 or any(counts.get(k) != 0 for k in ('failures', 'errors', 'skipped'))
            or full.get('source_unchanged_during_run') is not True
            or full.get('protected_unchanged_during_run') is not True
            or full.get('boundary', {}).get('network_attempts') != 0
            or full.get('boundary', {}).get('battery_solve_attempts') != 0):
        raise ValueError('fresh full software regression required')
    actual_source = {p.relative_to(WT).as_posix(): sha(p) for p in sorted((WT/'src').rglob('*'))
                     if p.is_file() and '__pycache__' not in p.parts}
    if full.get('source_after') != actual_source:
        raise ValueError('source was not the source tested by the full regression')


def _execute(protocol, evidence_root, approval, release):
    """Prepare immutable inputs first; only then acquire the dedicated key and clock."""
    import os
    snapshots = {}

    def pin(path, expected=None):
        path = Path(path)
        value = sha(path)
        if expected is not None and value != expected:
            raise ValueError('approved scientific input changed')
        snapshots[str(path)] = value
        return path

    def copy_file(source, destination, expected=None):
        source = pin(source, expected)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if destination.read_bytes() != source.read_bytes():
                raise ValueError('owned frozen input differs')
        else:
            with destination.open('xb') as out:
                out.write(source.read_bytes())
        pin(destination, snapshots[str(source)])
        return destination

    source_root = evidence_root / 's'
    source_files = [*sorted((WT/'src/llmbo_para').rglob('*.py')),
                    *sorted((WT/'src/llmbo_para/prompts').glob('*.txt'))]
    source_files += [WT/n for n in ('requirements-py312.lock', 'requirements-research.lock',
                                    'requirements-test.lock', 'pyproject.toml')]
    for path in source_files:
        copy_file(path, source_root / path.relative_to(WT))
    if fingerprint(source_root) != release['source_fingerprint']:
        raise ValueError('owned scientific source differs')
    for name, expected in release['runtime_files'].items():
        pin(Path(__file__).parent/name, expected)
        pin(WT/'scripts'/name, expected)
    pin(evidence_root/'approval.json')
    pin(evidence_root/'software-release.json')
    pin(evidence_root/'proposed-protocol.json', approval['proposed_protocol_sha256'])
    pin(protocol['plan_path'], approval['plan_sha256'])
    old_seal_path = BASE/'lgbo-real-gain-20261023/delivery-seal.json'
    pin(old_seal_path, protocol['previous_trial_seal_sha256'])
    old_files = read(old_seal_path)['files']
    proposal = BASE/'lgbo-real-gain-proposal-20261023'
    template_file = pin(proposal/'new_full.disabled-config.json', old_files[(proposal/'new_full.disabled-config.json').as_posix()])
    coordinate_file = pin(proposal/'fixed-eight-coordinates.json', old_files[(proposal/'fixed-eight-coordinates.json').as_posix()])
    template = read(template_file)
    template['llm']['timeout_s'] = 120.
    template['llm']['max_tokens'] = 8192
    template['llm'].setdefault('task_options', {})['region_preference_electrothermal'] = {'timeout_s': 120., 'max_tokens': 8192}
    coordinates = read(coordinate_file)['parameters']
    contexts = []
    original_runs = set()
    for i, item in enumerate(protocol['contexts']):
        original_payload = pin(item['payload_path'], item['payload_sha256'])
        original_round = pin(item['round_path'], item['round_sha256'])
        original_run = original_round.parent.parent
        original_runs.add(original_run)
        manifest = pin(original_run/'manifest.json', old_files[(original_run/'manifest.json').as_posix()])
        frozen = evidence_root/'historical'/str(i)
        copy_file(manifest, frozen/'manifest.json')
        payload_file = copy_file(original_payload, frozen/'llm'/original_payload.name)
        round_file = copy_file(original_round, frozen/'mo-rounds'/original_round.name)
        contexts.append({'payload': read(payload_file), 'round_path': str(round_file),
                         'round_sha256': sha(round_file)})
    # Old sources remain old; audit their archived context before any live clock.
    sys.path.insert(0, str(source_root/'src'))
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    for i, root in enumerate(sorted(original_runs)):
        proof = audit_electrothermal_run(root, deep=True)
        if not proof['passed']:
            raise ValueError('historical source/data/GP audit failed')
        write(evidence_root/('historical-audit-'+str(i)+'.json'), proof)

    def integrity():
        if fingerprint(WT) != release['source_fingerprint'] or fingerprint(source_root) != release['source_fingerprint']:
            raise ValueError('scientific source changed')
        if any(sha(path) != expected for path, expected in snapshots.items()):
            raise ValueError('frozen source/runtime/scientific input changed')

    integrity()
    read_credential()
    write(evidence_root/'execution-claim.json', {'protocol_sha256': sha(evidence_root/'proposed-protocol.json'),
        'recorded_utc': datetime.now(timezone.utc).isoformat(), 'one_shot': True})
    write(evidence_root/'input-pins.json', snapshots)
    budget = ValidationBudget.start(evidence_root/'budget-journal.jsonl',
                                    protocol_sha=sha(evidence_root/'proposed-protocol.json'))
    write(evidence_root/'live-launch.json', {'started_utc': datetime.now(timezone.utc).isoformat(),
        'limits': CAPS, 'diagnostic_limits': PHASES['diagnostic'], 'credential_present': True,
        'source_fingerprint': release['source_fingerprint'], 'output_root': str(OUTPUT),
        'runtime_files': release['runtime_files']})
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    results_dir = evidence_root/'phase-results'
    initial_pin = None

    def run_phase(intent):
        nonlocal initial_pin
        integrity()
        spec = {**deepcopy(intent), 'source_root': str(source_root), 'source': release['source_fingerprint'],
            'source_commit': release.get('head'), 'deadline': budget.deadline,
            'protocol_sha': sha(evidence_root/'proposed-protocol.json'),
            'output': str(OUTPUT/intent['label'])}
        deadline = budget.deadline
        if intent['kind'] in ('minimal', 'historical'):
            deadline = min(deadline, budget.state()['origin']['mono']+900)
            spec['deadline'] = deadline
            if intent['kind'] == 'historical':
                spec.update(deepcopy(contexts[intent['context_index']]))
        else:
            spec.update(base_config=deepcopy(template), coordinates=deepcopy(coordinates),
                        solve_cap=16 if intent['kind'] == 'initialization' else 40,
                        seed=intent.get('seed', 1709), arm=intent.get('arm', 'plain'))
            if intent['kind'] == 'arm':
                if initial_pin is None:
                    initial_pin = deepcopy(intent['initial'])
                if intent['initial'] != initial_pin or sha(initial_pin['path']) != initial_pin['sha256']:
                    raise ValueError('shared initialization changed')

        def checked():
            integrity()
            if initial_pin is not None and sha(initial_pin['path']) != initial_pin['sha256']:
                raise ValueError('initialization changed during an arm')

        result = supervise(validation_worker, spec, budget, deadline=deadline,
            metadata=evidence_root/'supervision'/(intent['label']+'.json'), integrity_check=checked)
        checked()
        if intent['kind'] == 'arm' and result.get('source') != release['source_fingerprint']:
            raise ValueError('paired result is from a different source')
        write(results_dir/(intent['label']+'.json'), result)
        print(json.dumps({'phase': intent['label'], 'status': result.get('status'),
            'passed': result.get('passed'), 'costs': budget.counts(),
            'diagnostic': result.get('diagnostic'),
            'metrics': {k: result.get(k) for k in ('HV', 'F_U', 'F_T')},
            'effect': {k: result.get('effect', {}).get(k) for k in ('action_valid', 'tilt_applied', 'max_abs_shift', 'selection_changed')}}), flush=True)
        return result

    with keep_awake(evidence_root/'live-idle-lease.json'):
        result = execute_sequence(protocol, budget, run_phase=run_phase, integrity_check=integrity)
        try:
            integrity()
        except Exception as exc:
            result.update(status='failed', failure_stage='final_integrity', error_type=type(exc).__name__, gain_status='inconclusive')
        result.update(finished_utc=datetime.now(timezone.utc).isoformat(),
                      protocol_sha256=sha(evidence_root/'proposed-protocol.json'),
                      source_fingerprint=release['source_fingerprint'])
        write(evidence_root/'summary.json', result)
        write(evidence_root/'execution-exit.json', {'exit_code': 0 if result['status'] == 'completed' else 1})
        return result


def run_validation(protocol: dict, evidence_root: Path, *, execute=False) -> dict:
    if not execute:
        return {'dry_run': True, 'actual_API': 0, 'actual_DFN': 0, 'limits': CAPS,
                'gate': 'three complete historical contexts and one authentic nonzero tilt'}
    approval = read(Path(evidence_root) / 'approval.json')
    release = read(Path(evidence_root) / 'software-release.json')
    if not release.get('passed') or approval.get('limits', {}).get('API') != CAPS['API']:
        raise ValueError('verified software and human authority required')
    _validate_release(protocol, Path(evidence_root), approval, release)
    return _execute(protocol, Path(evidence_root), approval, release)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    protocol = read(EVIDENCE / 'proposed-protocol.json')
    result = run_validation(protocol, EVIDENCE, execute=args.execute)
    public = result if result.get('dry_run') else {
        **{k: result.get(k) for k in ('status', 'costs', 'failure_stage', 'error_type')},
        'complete_cases': len(result.get('cases', [])), 'evidence': str(EVIDENCE)}
    print(json.dumps(public, ensure_ascii=False))
    return 0 if result.get('dry_run') or result.get('status') == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
