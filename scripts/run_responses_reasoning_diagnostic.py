"""Five-call API-only reasoning probe. Dry by default; never starts BO/DFN."""
from __future__ import annotations

import argparse
from copy import deepcopy
import importlib.metadata
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

from run_lgbo_real_gain import fingerprint, keep_awake, read_credential, sha, supervise, write
from run_region_transport_validation import digest, gate_passed, validate_region_effect

WT = Path(__file__).resolve().parents[1]
BASE = Path('D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/20261017_et_implementation')
EVIDENCE = BASE/'region-timeout-root-cause-20261024'
OUTPUT = Path('D:/Users/aa133/Desktop/LLMBO_Para/runs/r24eff')
APPROVED_COMMIT = '4138597cf334e6f719d0f3c9f05a145b0b298cb2'
PLAN = WT/'docs/superpowers/plans/2026-10-24-responses-reasoning-control-plan.md'
SPEC = WT/'docs/superpowers/specs/2026-10-24-responses-reasoning-control-design.md'
LIMITS = {'API': 5, 'DFN': 0, 'BO': 0, 'wall_clock_s': 720, 'cleanup_reserve_s': 30}
PROVIDER = {'endpoint': 'https://sidrune.ai/v1/responses', 'model': 'deepseek-v4-pro',
            'api_key_env': 'SUB2API_API_KEY', 'max_tokens': 8192, 'stream': False, 'store': False}
PHASES = [dict(label='p0', kind='minimal', context_index=None, timeout_s=60., reasoning_effort='none'),
          dict(label='p1', kind='historical', context_index=0, timeout_s=120., reasoning_effort='none'),
          dict(label='p2', kind='historical', context_index=0, timeout_s=120., reasoning_effort=None),
          dict(label='p3', kind='historical', context_index=1, timeout_s=120., reasoning_effort='none'),
          dict(label='p4', kind='historical', context_index=2, timeout_s=120., reasoning_effort='none')]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def _head():
    return subprocess.check_output(['git', '-C', str(WT), 'rev-parse', 'HEAD'], text=True).strip()


def runtime_environment():
    """Actual interpreter and installed versions, not inferred from lock files."""
    return {'executable': sys.executable, 'python': sys.version,
        'dependencies': {n: importlib.metadata.version(n) for n in
                         ('pytest','numpy','scipy','pybamm','casadi','pybammsolvers','openpyxl')}}


def _validate_protocol(protocol, evidence):
    if (protocol.get('version') != 'responses_reasoning_probe_v1'
            or protocol.get('approved_plan_commit') != APPROVED_COMMIT
            or protocol.get('limits') != LIMITS or protocol.get('provider') != PROVIDER
            or protocol.get('phases') != PHASES
            or digest(read(evidence/'diagnostic-protocol.json')) != digest(protocol)):
        raise ValueError('fixed approved diagnostic protocol differs')
    contexts = protocol['contexts']
    if len(contexts) != 3 or len({c['context_id'] for c in contexts}) != 3:
        raise ValueError('three distinct historical contexts required')
    for c in contexts:
        if (sha(c['frozen_payload']) != c['payload_sha256']
                or sha(c['frozen_round']) != c['round_sha256']
                or read(c['frozen_payload'])['context_id'] != c['context_id']):
            raise ValueError('frozen historical input differs')
        read(c['frozen_manifest'])


def required_pins(protocol, evidence):
    paths = [WT/'scripts'/name for name in ('run_responses_reasoning_diagnostic.py',
        'run_region_transport_validation.py', 'run_lgbo_real_gain.py', 'lgbo_real_gain_worker.py')]
    paths += [evidence/'run_tests.py', evidence/'diagnostic-protocol.json', evidence/'approval.json', PLAN, SPEC,
              BASE/'lgbo-engineering-20261023/run_tests.py', BASE/'baseline.py',
              BASE/'sub2api-responses-20261021/run_tests.py',
              BASE/'sub2api-responses-20261021/protect_workspace.py']
    paths += [Path(c[key]) for c in protocol['contexts']
              for key in ('frozen_payload', 'frozen_round', 'frozen_manifest')]
    paths += sorted((WT/'tests').rglob('*.py'))
    return {str(p.resolve()): sha(p) for p in paths}


def _full_paths(evidence, attempt=''):
    if type(attempt) is not str or attempt not in ('', 'r2', 'r3'):
        raise ValueError('unapproved full regression attempt selector')
    suffix = '-'+attempt if attempt else ''
    return evidence/('runtime-before-final'+suffix+'.json'), evidence/('tests/ge-re-final-full'+suffix+'/result.json')


class RuntimeObservation:
    """Observe the runtime before pytest, including the wrapper doing the observing."""
    def __init__(self, protocol, evidence, *, attempt=''):
        self.protocol, self.evidence = protocol, Path(evidence)
        path, _ = _full_paths(self.evidence, attempt)
        self.manifest_path = path
        manifest = read(path)
        self.pins = manifest['pins']
        if (self.pins != required_pins(protocol, self.evidence) or manifest['head'] != _head()
                or manifest['source_fingerprint'] != fingerprint(WT)
                or manifest.get('environment') != runtime_environment()):
            raise ValueError('pre-test runtime bytes differ')
        self.observation = {'runtime_manifest_sha256': sha(path), 'head': manifest['head'],
            'source_fingerprint': manifest['source_fingerprint'],
            'protocol_sha256': sha(self.evidence/'diagnostic-protocol.json'), 'pins_digest': digest(self.pins)}
        self.environment = manifest['environment']

    def unchanged(self):
        try:
            return (self.pins == required_pins(self.protocol, self.evidence)
                    and self.observation['head'] == _head()
                    and self.observation['source_fingerprint'] == fingerprint(WT)
                    and self.environment == runtime_environment()
                    and self.observation['runtime_manifest_sha256'] == sha(self.manifest_path))
        except (OSError, ValueError, KeyError): return False


def _validate_release(protocol, evidence):
    approval = read(evidence/'approval.json')
    release = read(evidence/'software-release.json')
    caps = {k: v for k, v in LIMITS.items() if k != 'cleanup_reserve_s'}
    if (approval.get('approved') is not True or approval.get('approved_commit') != APPROVED_COMMIT
            or approval.get('limits') != caps or approval.get('plan_sha256') != sha(PLAN)
            or approval.get('spec_sha256') != sha(SPEC)):
        raise ValueError('software and five-call diagnostic approval required')
    manifest_path, full_path = _full_paths(evidence, release.get('full_attempt', ''))
    manifest = read(manifest_path)
    if (release.get('head') != _head() or release.get('source_fingerprint') != fingerprint(WT)
            or release.get('protocol_sha256') != sha(evidence/'diagnostic-protocol.json')
            or release.get('runtime_manifest_sha256') != sha(manifest_path)
            or manifest.get('head') != release['head']
            or manifest.get('source_fingerprint') != release['source_fingerprint']
            or manifest.get('environment') != runtime_environment()):
        raise ValueError('tested source/runtime release differs')
    pins = manifest['pins']
    if any(pins.get(p) != value for p, value in required_pins(protocol, evidence).items()):
        raise ValueError('required runtime/input pins missing or changed')
    if any(sha(p) != value for p, value in pins.items()):
        raise ValueError('tested runtime/input changed')
    expected = {'runtime_manifest_sha256': sha(manifest_path), 'head': release['head'],
                'source_fingerprint': release['source_fingerprint'],
                'protocol_sha256': release['protocol_sha256'], 'pins_digest': digest(pins)}
    full, before = read(full_path), read(full_path.parent/'manifest-before.json')
    if {k:before.get(k) for k in ('executable','python','dependencies')} != runtime_environment():
        raise ValueError('tested interpreter or installed dependencies differ')
    counts = full['junit_counts']
    if (release.get('full_result_sha256') != sha(full_path) or full.get('exit_code') != 0
            or full.get('command_args', [None])[0] != 'tests' or counts['tests'] <= 0
            or counts['passed'] != counts['tests'] or any(counts[k] for k in ('failures','errors','skipped'))
            or any(full['boundary'][k] for k in ('network_attempts','battery_solve_attempts'))
            or full.get('source_unchanged_during_run') is not True
            or full.get('protected_unchanged_during_run') is not True
            or full.get('runtime_unchanged_during_run') is not True
            or full.get('head_after') != release['head'] or before.get('head') != release['head']
            or any(d.get('runtime_observation') != expected for d in (full, before))):
        raise ValueError('fresh full regression did not observe this runtime')


class ProbeBudget:
    """One fsynced hash journal; no resume, retry, DFN or budget renewal."""
    def __init__(self, path): self.path = Path(path)

    @classmethod
    def start(cls, path, *, protocol_sha):
        obj = cls(path)
        obj._write({'type': 'start', 'limits': LIMITS, 'protocol_sha': protocol_sha,
                    'mono': time.monotonic(), 'unix': time.time(), 'previous': None}, exclusive=True)
        return obj

    def _write(self, value, *, exclusive=False):
        value = {**value, 'hash': digest(value)}
        with self.path.open('x' if exclusive else 'a', encoding='utf8') as stream:
            stream.write(json.dumps(value, separators=(',', ':'))+'\n')
            stream.flush(); os.fsync(stream.fileno())

    def state(self):
        text = self.path.read_text(encoding='utf8')
        if not text.endswith('\n'): raise ValueError('incomplete probe journal')
        events = [json.loads(line) for line in text.splitlines()]
        if not events or events[0].get('type') != 'start' or events[0].get('limits') != LIMITS:
            raise ValueError('probe budget origin differs')
        previous, count, closed = None, 0, False
        for i, e in enumerate(events):
            if closed or e.get('previous') != previous or e.get('hash') != digest({k:v for k,v in e.items() if k != 'hash'}):
                raise ValueError('probe journal chain differs')
            previous = e['hash']
            if i == 0: continue
            if e['type'] == 'charge' and count < 5 and e.get('kind') == 'API' and e.get('event_id') == PHASES[count]['label']:
                count += 1
            elif e['type'] == 'close' and e.get('status') in ('completed', 'failed'): closed = True
            else: raise ValueError('invalid probe budget event')
        return {'API': count, 'DFN': 0, 'closed': closed, 'hash': previous, 'origin': events[0]}

    @property
    def deadline(self): return self.state()['origin']['mono']+720.

    def require(self, calls):
        if type(calls) is not int or calls != 0: raise RuntimeError('DFN budget is zero')
        if self.state()['closed']: raise RuntimeError('probe already closed')
        if time.monotonic() >= self.deadline-30:
            raise TimeoutError('probe execution window closed')

    def charge(self, kind, ident):
        self.require(0); state = self.state()
        if kind != 'API' or state['API'] >= 5 or ident != PHASES[state['API']]['label']:
            raise RuntimeError('invalid, duplicate or exhausted API charge')
        self._write({'type': 'charge', 'kind': kind, 'event_id': ident, 'previous': state['hash']})

    def close(self, status):
        state = self.state()
        if state['closed']: raise RuntimeError('probe already closed')
        self._write({'type': 'close', 'status': status, 'previous': state['hash']})


def make_transport(spec, store):
    from llmbo_para.electrothermal_responses import BoundedResponsesTransport
    return BoundedResponsesTransport(PROVIDER['endpoint'], PROVIDER['api_key_env'],
        model=PROVIDER['model'], max_tokens=8192, json_mode=True, timeout_s=spec['timeout_s'],
        reasoning_effort=spec.get('reasoning_effort'), run_store=store)


def reasoning_diagnostic_worker(spec, connection):
    """Cold actual source; native HTTP children belong to the parent's owned job."""
    sys.dont_write_bytecode = True
    for k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'): os.environ[k] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    if spec.get('environment') != runtime_environment():
        raise ValueError('actual worker interpreter or installed dependencies differ')
    if any(n == 'llmbo_para' or n.startswith('llmbo_para.') for n in sys.modules):
        raise RuntimeError('probe worker namespace already populated')
    root = Path(spec['source_root']).resolve(); sys.path.insert(0, str(root/'src'))
    from llmbo_para import electrothermal_provenance as provenance
    from llmbo_para.electrothermal_responses import responses_request_body, decode_responses_json
    from llmbo_para.electrothermal_region_wire import region_wire_payload, decode_region_wire
    from llmbo_para.runstore import RunStore
    if Path(provenance.__file__).resolve() != root/'src/llmbo_para/electrothermal_provenance.py' or provenance.source_fingerprint(root) != spec['source']:
        raise ValueError('actual probe source differs')
    store = RunStore(spec['output'], {'kind': 'responses_reasoning_probe_v1',
        'actual_transport_source': spec['source'], 'protocol_sha256': spec['protocol_sha']},
        command='API-only historical reasoning diagnostic')
    client, result = None, None
    payload = deepcopy(spec['payload'])
    task = payload['artifact_task']
    expected = responses_request_body(region_wire_payload(payload), model=PROVIDER['model'],
        max_tokens=8192, json_mode=True, reasoning_effort=spec.get('reasoning_effort'))
    try:
        store.write_json('probe-provenance.json', {'version': 'responses_reasoning_probe_v1',
            'original_historical_identity_unchanged': True, 'not_new_BO_data': True,
            'actual_source': spec['source'], 'actual_source_commit': spec['source_commit'],
            'approval_plan_commit': APPROVED_COMMIT, 'protocol_sha256': spec['protocol_sha'],
            'requested_reasoning_effort': spec.get('reasoning_effort'), 'kind': spec['kind']})
        store.write_json('frozen-payload.json', payload)
        client = make_transport(spec, store)
        # This API-only journal uses the five fixed phase labels. Charge and
        # receive the parent's durable acknowledgement before opening HTTP.
        connection.send(('charge', ('API', spec['label'])))
        if connection.recv()[0] != 'ok': raise RuntimeError('parent denied API authorization')
        formal = client.post(payload, deadline=spec['deadline'])
        raw = read(store.path/'http'/(task+'.response.json'))
        decoded, issue = decode_responses_json(raw)
        restored = decode_region_wire(decoded, payload) if issue is None else None
        diagnostic = client.last_request_diagnostic
        if issue is not None or digest(restored) != digest(formal) or diagnostic.get('http_status') != 200:
            raise ValueError('formal completion or raw response differs')
        result = {'passed': True, 'complete': True, 'diagnostic': diagnostic}
        if spec['kind'] == 'minimal':
            if formal != {'ok': True}: raise ValueError('minimal JSON contract differs')
        else:
            # The replay helper expects the original run's manifest/mo-rounds layout.
            replay = Path(spec['output'])/'frozen-gp'
            (replay/'mo-rounds').mkdir(parents=True)
            import shutil
            shutil.copyfile(spec['round_path'], replay/'mo-rounds/round.json')
            shutil.copyfile(spec['manifest_path'], replay/'manifest.json')
            result.update(context_id=payload['context_id'],
                effect=validate_region_effect(payload, formal, replay/'mo-rounds/round.json'))
    except Exception as exc:
        result = {'passed': False, 'complete': False, 'error_type': type(exc).__name__,
                  'diagnostic': client.last_request_diagnostic if client is not None else None}
    finally:
        try:
            sent = read(store.path/'http'/(task+'.request.json'))
            if sent['body'] != expected or sent['endpoint'] != PROVIDER['endpoint']:
                raise ValueError('sent controls or scientific request differs')
            body = deepcopy(sent['body']); body.pop('reasoning', None)
            result.update(wire_verified=True, body_sha256=digest(sent['body']),
                          body_without_reasoning_sha256=digest(body))
        except (OSError, ValueError, KeyError, TypeError):
            result.update(passed=False, complete=False, wire_verified=False)
        result['run_directory'] = str(store.path)
        store.write_json('validation-proof.json', result)
        store.finish('completed' if result['passed'] else 'failed', result)
        write(Path(spec['output'])/'worker-result.json', result)
        connection.send(('result', result)); connection.close()


def _omitted_cutoff(result, *, label):
    d = result.get('diagnostic') or {}
    return (label == 'p2' and d.get('reason') == 'deadline_exceeded'
            and d.get('http_status') in (None, 200) and d.get('http_request_started') is True
            and d.get('configured_timeout_s') == 120. and d.get('effective_timeout_s', 0.) >= 119.5
            and type(d.get('elapsed_s')) in (int,float) and math.isfinite(d['elapsed_s']) and d['elapsed_s'] >= 119.5)


def run_diagnostic(protocol, evidence_root, *, execute=False):
    evidence = Path(evidence_root); _validate_protocol(protocol, evidence)
    if not execute:
        return {'dry_run': True, 'actual_API': 0, 'actual_DFN': 0, 'actual_BO': 0, 'limits': LIMITS}
    _validate_release(protocol, evidence)
    read_credential()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    budget = ProbeBudget.start(evidence/'budget.jsonl', protocol_sha=sha(evidence/'diagnostic-protocol.json'))
    attempts, proofs, status, error_type, equal_pair = [], [], 'failed', None, False
    try:
        with keep_awake(OUTPUT/'wake.json'):
            for phase in PHASES:
                budget.require(0); _validate_release(protocol, evidence)
                spec = {**phase, 'source_root': str(WT), 'source': fingerprint(WT), 'source_commit': _head(),
                    'environment': runtime_environment(),
                    'output': str(OUTPUT/phase['label']), 'protocol_sha': sha(evidence/'diagnostic-protocol.json'),
                    'deadline': min(time.monotonic()+phase['timeout_s']+10., budget.deadline-30.)}
                if phase['kind'] == 'minimal':
                    spec['payload'] = {'task': 'warm_start_electrothermal', 'artifact_task': 'api_reasoning_minimal',
                        'instructions': 'This is only a transport probe. Return exactly the JSON object {"ok":true}.',
                        'response_contract': {'type': 'object', 'properties': {'ok': {'const': True}},
                                              'required': ['ok'], 'additionalProperties': False}}
                else:
                    c = protocol['contexts'][phase['context_index']]
                    spec.update(payload=read(c['frozen_payload']), context_id=c['context_id'],
                        round_path=c['frozen_round'], manifest_path=c['frozen_manifest'])
                metadata = OUTPUT/(phase['label']+'-owned.json')
                result = supervise(reasoning_diagnostic_worker, spec, budget, deadline=spec['deadline'],
                    metadata=metadata, integrity_check=lambda: _validate_release(protocol, evidence))
                if read(metadata).get('owned_tree_stopped') is not True:
                    raise RuntimeError('owned probe tree did not stop')
                budget.require(0); _validate_release(protocol, evidence)
                result = {**result, 'label': phase['label']}; attempts.append(result)
                if result.get('wire_verified') is not True:
                    raise ValueError('actual sent request was not verified')
                if phase['label'] == 'p2':
                    equal_pair = result.get('body_without_reasoning_sha256') == attempts[1].get('body_without_reasoning_sha256')
                    if not equal_pair or not result.get('body_without_reasoning_sha256'):
                        raise ValueError('comparator changed fields beyond reasoning')
                if not result.get('passed'):
                    if not _omitted_cutoff(result, label=phase['label']):
                        raise RuntimeError('fixed diagnostic phase failed')
                elif phase['kind'] == 'historical' and phase['label'] != 'p2':
                    if result.get('context_id') != spec['context_id']:
                        raise ValueError('historical response binding differs')
                    proofs.append(result)
            if not gate_passed(proofs): raise RuntimeError('three complete actions lack authentic nonzero tilt')
            status = 'completed'
    except Exception as exc:
        error_type = type(exc).__name__
    finally:
        budget.close(status)
    result = {'status': status, 'error_type': error_type, 'transport_ready': status == 'completed',
        'actual_API': budget.state()['API'], 'actual_DFN': 0, 'actual_BO': 0,
        'attempts': attempts, 'comparator_equal_except_reasoning': equal_pair,
        'gain_status': 'not_tested', 'latency_interpretation': 'descriptive, single ordered comparison; not causal proof'}
    write(evidence/'diagnostic-result.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    result = run_diagnostic(read(EVIDENCE/'diagnostic-protocol.json'), EVIDENCE, execute=args.execute)
    print(json.dumps({k:v for k,v in result.items() if k != 'attempts'}, ensure_ascii=False))
    return 0 if result.get('dry_run') or result['status'] == 'completed' else 1


if __name__ == '__main__': raise SystemExit(main())
