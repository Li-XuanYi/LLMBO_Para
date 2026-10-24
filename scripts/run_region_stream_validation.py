"""Fixed SSE diagnostic, then gated paired DFN validation. Dry by default."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from run_lgbo_real_gain import fingerprint, keep_awake, read_credential, sha, supervise, write
from run_region_transport_validation import ValidationBudget, gate_passed, validate_region_effect

WT = Path(__file__).resolve().parents[1]
MAIN = Path('D:/Users/aa133/Desktop/LLMBO_Para')
BASE = MAIN/'bo-repair-work/20261017_et_implementation'
EVIDENCE = BASE/'region-transport-stages-20261024'
OUTPUT = MAIN/'runs/s24r'
APPROVED_COMMIT = 'cc5e3d620c0fc3744ab7830f537dbf1ba84bb7b9'
PLAN = WT/'docs/superpowers/plans/2026-10-24-region-stream-transport-plan.md'
SPEC = WT/'docs/superpowers/specs/2026-10-24-region-stream-transport-design.md'
CAPS = {'API': 66, 'DFN': 256, 'wall_clock_s': 10800}
PROVIDER = {'endpoint': 'https://sidrune.ai/v1/responses', 'model': 'deepseek-v4-pro',
    'api_key_env': 'SUB2API_API_KEY', 'max_tokens': 8192, 'reasoning_effort': 'none'}
PROBES = [dict(label='p0', kind='minimal', context_index=None, timeout_s=60., responses_stream=False),
    *[dict(label='p'+str(n), kind='historical', context_index=i, timeout_s=120., responses_stream=s)
      for n, i, s in ((1,0,False),(2,0,True),(3,1,True),(4,2,True),(5,0,True))]]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf8'))


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, allow_nan=False,
        sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def environment():
    return {'python': sys.version, 'executable': sys.executable,
        'dependencies': {name: importlib.metadata.version(name) for name in
            ('pytest','numpy','scipy','pybamm','casadi','pybammsolvers','openpyxl')}}


def check_request_status(outcome):
    status = outcome.get('http_status')
    if type(status) is int and status >= 400:
        raise RuntimeError('HTTP failure stops the approved validation')


def classify_wait_stacks(text):
    """Classify only the last complete sampled stack, never manufacture timings."""
    pieces = text.split('Timeout (')[1:]
    sample = pieces[-1] if pieces else ''
    names = set(re.findall(r'\bin ([A-Za-z_][A-Za-z_0-9]*)', sample))
    if '_tunnel' in names:
        stage = 'proxy'
    elif 'do_handshake' in names:
        stage = 'tls'
    elif 'send' in names or 'sendall' in names:
        stage = 'send'
    elif '_read_status' in names and 'getresponse' in names:
        stage = 'origin_response'
    elif names & {'read_responses_sse', '_read_response'} and names & {'read', 'read1', 'readinto'}:
        stage = 'origin_body'
    elif names & {'getaddrinfo', 'create_connection'}:
        stage = 'dns_tcp'
    else:
        stage = 'unknown'
    return {'stage': stage, 'samples': len(pieces)}


def observed_responses_worker(spec, payload, run_path, connection):
    """Scope sampling to the actual HTTP child, without changing the request."""
    import faulthandler
    from llmbo_para import electrothermal_requests as requests
    from llmbo_para.electrothermal_responses import _responses_request_worker
    original, handle = requests.HTTPArchive, None

    class ObservedArchive(original):
        def append_event(self, event):
            nonlocal handle
            super().append_event(event)
            if event.get('type') == 'llm_http_started':
                handle = (self.path/'http'/(event['task']+'.wait-stacks.log')).open('x', encoding='utf8')
                faulthandler.dump_traceback_later(30, repeat=True, file=handle)

    requests.HTTPArchive = ObservedArchive
    try:
        _responses_request_worker(spec, payload, run_path, connection)
    finally:
        requests.HTTPArchive = original
        if handle is not None:
            faulthandler.cancel_dump_traceback_later()
            handle.close()


def stream_gate_passed(proofs):
    if type(proofs) is not list or len(proofs) != 4:
        return False
    try:
        if not all(p['wire_verified'] is True for p in proofs):
            return False
        if proofs[0]['context_id'] != proofs[3]['context_id']:
            return False
        for proof in proofs:
            effect = proof['effect']
            shift = effect['max_abs_shift']
            if not (proof['complete'] is True and effect['action_valid'] is True
                    and effect['state_preserved'] is True and effect['EI_matches'] is True
                    and type(shift) in (int,float) and math.isfinite(shift) and shift >= 0):
                return False
        return gate_passed(proofs[:3]) or gate_passed([proofs[3], *proofs[1:3]])
    except (KeyError, TypeError, ValueError):
        return False


def _registered_cutoff(result):
    d = result.get('diagnostic') or {}
    wait = result.get('wait_observation') or {}
    return (result.get('owned_tree_stopped') is True and result.get('wire_verified') is True
        and d.get('reason') == 'deadline_exceeded' and d.get('http_request_started') is True
        and d.get('http_status') in (None,200) and d.get('configured_timeout_s') == 120.
        and type(d.get('effective_timeout_s')) in (int,float) and math.isfinite(d['effective_timeout_s']) and d['effective_timeout_s'] >= 119.5
        and type(d.get('elapsed_s')) in (int,float) and math.isfinite(d['elapsed_s']) and d['elapsed_s'] >= 119.5
        and wait.get('stage') in ('origin_response','origin_body')
        and type(wait.get('samples')) is int and wait['samples'] > 0)


def execute_sequence(protocol, budget, *, run_phase, integrity_check=None):
    attempts, proofs, cases, initialization = [], [], [], None
    fixed = digest(protocol)

    def invoke(intent):
        budget._open()
        if digest(protocol) != fixed:
            raise ValueError('protocol mutated')
        if integrity_check: integrity_check()
        result = run_phase(deepcopy(intent))
        budget._open()
        if integrity_check: integrity_check()
        return result

    try:
        budget.begin('diagnostic')
        for spec in PROBES:
            result = invoke(spec)
            attempts.append(result)
            check_request_status(result.get('diagnostic') or {})
            if result.get('wire_verified') is not True:
                raise ValueError('unverified wire')
            if not result.get('passed'):
                if spec['label'] != 'p1' or not _registered_cutoff(result):
                    raise RuntimeError('fixed diagnostic failed')
            elif spec['kind'] == 'historical':
                if result.get('context_id') != protocol['contexts'][spec['context_index']]['context_id']:
                    raise ValueError('different historical context')
            if spec['label'] == 'p2' and (not result.get('body_without_stream_sha256')
                    or result['body_without_stream_sha256'] != attempts[1].get('body_without_stream_sha256')):
                raise ValueError('comparison changed fields beyond stream')
            if spec['responses_stream']:
                proofs.append(result)
        if not stream_gate_passed(proofs):
            raise RuntimeError('four complete streams lack authentic influence')
        budget.finish(True)
        chosen = proofs[:3] if gate_passed(proofs[:3]) else [proofs[3], *proofs[1:3]]
        budget.begin('initialization', gate=chosen)
        initialization = invoke({'kind':'initialization','label':'i0'})
        if (initialization.get('status') != 'completed' or initialization.get('audit_passed') is not True
                or initialization.get('candidate_count') != 8):
            raise RuntimeError('initialization incomplete')
        plan, initial_sha = Path(initialization['plan_path']), initialization['plan_file_sha256']
        if sha(plan) != initial_sha:
            raise ValueError('initialization receipt differs')
        budget.finish(True)
        budget.begin('main')
        streak = 0
        for seed, order in zip(protocol['comparison']['seeds'], [('plain','full'),('full','plain'),('plain','full')]):
            for arm in order:
                if sha(plan) != initial_sha:
                    raise ValueError('shared initialization changed')
                result = invoke({'kind':'arm','seed':seed,'arm':arm,'label':'c'+str(len(cases)).zfill(2),
                    'initial_failure_streak':streak,'initial':{'path':str(plan),'sha256':initial_sha}})
                if (result.get('status') != 'completed' or result.get('audit_passed') is not True
                        or result.get('BO_rounds') != 20 or result.get('seed') != seed
                        or result.get('arm') != arm or result.get('initial_file_sha') != initial_sha):
                    raise RuntimeError('paired arm incomplete')
                first = result.get('first_numerical_context_sha')
                if type(first) is not str or len(first) != 64:
                    raise ValueError('missing first numerical context')
                previous = next((c for c in cases if c['seed'] == seed), None)
                if previous and previous['first_numerical_context_sha'] != first:
                    raise ValueError('paired numerical contexts differ')
                cases.append(result)
                if arm == 'full':
                    streak = result['request_failure_streak']
                    if type(streak) is not int or not 0 <= streak < 3:
                        raise RuntimeError('invalid failure streak')
        if sha(plan) != initial_sha:
            raise ValueError('initialization changed at final gate')
        budget.finish(True)
        return {'status':'completed','transport_ready':True,'attempts':attempts,'gate_proofs':proofs,
            'initialization':initialization,'cases':cases,'costs':budget.counts(),'gain_status':'paired_results_available'}
    except Exception as exc:
        failure_stage = budget.state()['phase']
        if failure_stage is not None:
            budget.finish(False)
        return {'status':'failed','error_type':type(exc).__name__,'transport_ready':stream_gate_passed(proofs),
            'failure_stage':failure_stage,
            'attempts':attempts,'gate_proofs':proofs,'initialization':initialization,
            'cases':cases,'costs':budget.counts(),'gain_status':'inconclusive'}


def validation_worker(spec, connection):
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    if any(n == 'llmbo_para' or n.startswith('llmbo_para.') for n in sys.modules):
        raise RuntimeError('owned worker namespace is not cold')
    if spec['kind'] in ('initialization','arm'):
        import run_region_transport_validation as old
        original = old.RequestFailureStreak
        class StrictStreak(original):
            def observe(self, outcome):
                check_request_status(outcome)
                super().observe(outcome)
        old.RequestFailureStreak = StrictStreak
        try:
            return old.validation_worker(spec, connection)
        finally:
            old.RequestFailureStreak = original
    root = Path(spec['source_root']).resolve()
    sys.path.insert(0, str(root/'src'))
    from llmbo_para.electrothermal_provenance import source_fingerprint
    from llmbo_para.electrothermal_responses import BoundedResponsesTransport, responses_request_body
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    from llmbo_para.runstore import RunStore
    if source_fingerprint(root) != spec['source'] or environment() != spec['environment']:
        raise ValueError('worker runtime differs')
    class ObservedTransport(BoundedResponsesTransport):
        def _request_worker(self): return observed_responses_worker
    payload = deepcopy(spec['payload'])
    expected = responses_request_body(region_wire_payload(payload), model=PROVIDER['model'],
        max_tokens=8192, json_mode=True, reasoning_effort='none', responses_stream=spec['responses_stream'])
    store = RunStore(spec['output'], {'kind':'region_stream_probe_v1','historical_identity_unchanged':True,
        'not_new_BO_data':True,'actual_source':spec['source'],'protocol_sha256':spec['protocol_sha']},
        command='bounded full Region stream and wait diagnostic')
    store.write_json('frozen-payload.json',payload)
    client = ObservedTransport(PROVIDER['endpoint'],PROVIDER['api_key_env'],model=PROVIDER['model'],
        max_tokens=8192,json_mode=True,timeout_s=spec['timeout_s'],reasoning_effort='none',
        responses_stream=spec['responses_stream'],run_store=store)
    result = {'passed':False,'complete':False}
    try:
        connection.send(('charge',('API',spec['label'])))
        if connection.recv()[0] != 'ok': raise RuntimeError('API charge denied')
        formal = client.post(payload,deadline=spec['deadline'])
        result.update(passed=True,complete=True)
        if spec['kind'] == 'minimal':
            if set(formal) != {'ok'} or formal['ok'] is not True:
                raise ValueError('minimal formal result differs')
        else:
            result.update(context_id=payload['context_id'],
                effect=validate_region_effect(payload,formal,Path(spec['round_path'])))
    except Exception as exc:
        result.update(passed=False,complete=False,error_type=type(exc).__name__)
    finally:
        result['diagnostic'] = client.last_request_diagnostic or {}
        task = payload.get('artifact_task',payload['task'])
        try:
            sent = read(store.path/'http'/(task+'.request.json'))
            if sent['body'] != expected or sent['endpoint'] != PROVIDER['endpoint']:
                raise ValueError('actual wire differs')
            without = deepcopy(sent['body']); without.pop('stream')
            result.update(wire_verified=True,body_sha256=digest(sent['body']),
                body_without_stream_sha256=digest(without))
        except (OSError,ValueError,KeyError,TypeError):
            result.update(passed=False,complete=False,wire_verified=False)
        stack = store.path/'http'/(task+'.wait-stacks.log')
        result['wait_observation'] = classify_wait_stacks(stack.read_text(encoding='utf8')) if stack.exists() else {'stage':'unknown','samples':0}
        result.update(run_directory=str(store.path),label=spec['label'])
        store.write_json('validation-proof.json',result)
        store.finish('completed' if result['passed'] else 'failed',result)
        write(Path(spec['output'])/'worker-result.json',result)
        connection.send(('result',result))
        connection.close()


def _pins(evidence):
    path = evidence/'run_tests.py'
    spec = importlib.util.spec_from_file_location('stream_runtime_pin_observer',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.runtime_pins()


def replay_round_path(context):
    path = Path(context['round_path'])
    if sha(path) != context['round_sha256'] or not (path.parent.parent/'manifest.json').is_file():
        raise ValueError('bound historical round or manifest layout differs')
    return path


def _fixed_inputs():
    """Authority is the sealed historical inputs, never a caller's new hashes."""
    gain_path = BASE/'lgbo-real-gain-20261023/delivery-seal.json'
    reasoning_path = BASE/'region-timeout-root-cause-20261024/delivery-seal.json'
    if (sha(gain_path) != '11caf15ae045ea26d95c4afbc39f68c0b2f7d1865b8183c512a82ee94db1c45c'
            or sha(reasoning_path) != 'fabb8613cca25fcd5498e18baf72186185ba0a5784d312ad5e15ed4f6fcd7b37'):
        raise ValueError('historical authority seal changed')
    gain = {str(Path(p).resolve()):s for p,s in read(gain_path)['files'].items()}
    reasoning = {str(Path(p).resolve()):s for p,s in read(reasoning_path)['files'].items()}
    descriptor = BASE/'region-timeout-root-cause-20261024/diagnostic-protocol.json'
    if sha(descriptor) != reasoning[str(descriptor.resolve())]:
        raise ValueError('historical descriptor changed')
    contexts = read(descriptor)['contexts']
    original_run = MAIN/'runs/g23r/c01/20261023T170200Z_1b49df6886b8_6a4b06a2'
    pins = {str(gain_path):sha(gain_path), str(reasoning_path):sha(reasoning_path),
            str(descriptor):sha(descriptor)}
    for item in contexts:
        for key in ('frozen_payload','frozen_round','frozen_manifest'):
            path = str(Path(item[key]).resolve()); pins[path] = reasoning[path]
        for key in ('payload_path','round_path'):
            path = str(Path(item[key]).resolve()); pins[path] = gain[path]
    proposal = BASE/'lgbo-real-gain-proposal-20261023'
    for path in (original_run/'manifest.json', proposal/'new_full.disabled-config.json',
                 proposal/'fixed-eight-coordinates.json'):
        key = str(path.resolve()); pins[key] = gain[key]
    return {'contexts':contexts,'input_pins':pins,'original_run':str(original_run)}


def _validate_release(protocol, evidence):
    required = ('approval.json','validation-protocol.json','software-release.json')
    if not all((evidence/name).is_file() for name in required):
        raise ValueError('bound approval, protocol and full software release required')
    approval, release = read(evidence/'approval.json'), read(evidence/'software-release.json')
    if (approval.get('approved') is not True or approval.get('approved_commit') != APPROVED_COMMIT
            or approval.get('limits') != CAPS or approval.get('plan_sha256') != sha(PLAN)
            or approval.get('spec_sha256') != sha(SPEC)):
        raise ValueError('approved scope differs')
    if (protocol != read(evidence/'validation-protocol.json') or protocol.get('version') != 'region_stream_validation_v1'
            or protocol.get('limits') != CAPS or protocol.get('provider') != PROVIDER
            or protocol.get('probes') != PROBES or protocol.get('comparison') != {'seeds':[1709,3253,5501]}):
        raise ValueError('fixed protocol differs')
    fixed = _fixed_inputs()
    if any(protocol.get(key) != value for key,value in fixed.items()):
        raise ValueError('frozen historical inputs differ')
    for item in fixed['contexts']:
        for name in ('frozen_payload','frozen_round','frozen_manifest'):
            if sha(item[name]) != protocol['input_pins'][item[name]]:
                raise ValueError('historical input changed')
    if any(sha(path) != expected for path,expected in protocol['input_pins'].items()):
        raise ValueError('approved input bytes changed')
    head = subprocess.check_output(['git','-C',str(WT),'rev-parse','HEAD'],text=True).strip()
    label = release.get('full_label')
    if label not in ('ge-st-final-full','ge-st-final-full-r2','ge-st-final-full-r3'):
        raise ValueError('registered complete regression required')
    result_path = evidence/'tests'/label/'result.json'
    result = read(result_path); manifest = read(result_path.parent/'manifest-before.json')
    counts = result.get('junit_counts') or {}
    import xml.etree.ElementTree as ET
    xml = ET.parse(result_path.parent/'junit.xml').getroot()
    suites = [xml] if xml.tag == 'testsuite' else list(xml.findall('testsuite'))
    xml_counts = {k:sum(int(s.attrib.get(k,'0')) for s in suites) for k in ('tests','failures','errors','skipped')}
    xml_counts['passed'] = xml_counts['tests']-sum(xml_counts[k] for k in ('failures','errors','skipped'))
    if (release.get('head') != head or release.get('source_fingerprint') != fingerprint(WT)
            or release.get('runtime_pins') != _pins(evidence)
            or release.get('result_sha256') != sha(result_path)
            or release.get('protocol_sha256') != sha(evidence/'validation-protocol.json')
            or release.get('environment') != environment()
            or result.get('exit_code') != 0 or counts.get('tests',0) < 1441
            or any(counts.get(k) != 0 for k in ('failures','errors','skipped'))
            or result.get('runtime_unchanged_during_run') is not True
            or result.get('runtime_pins') != release['runtime_pins']
            or result.get('source_unchanged_during_run') is not True
            or result.get('protected_unchanged_during_run') is not True
            or result.get('head_after') != head or counts != xml_counts
            or (result_path.parent/'exit-code.txt').read_text(encoding='utf8').strip() != '0'
            or not result.get('command_args') or result['command_args'][0] != 'tests'
            or '--collect-only' in result['command_args']
            or manifest.get('command') != [str(evidence/'run_tests.py'),'test',label,'tests']
            or manifest.get('head') != head
            or manifest.get('python') != sys.version
            or manifest.get('executable') != sys.executable or manifest.get('dependencies') != environment()['dependencies']
            or result.get('boundary',{}).get('network_attempts') != 0
            or result.get('boundary',{}).get('battery_solve_attempts') != 0):
        raise ValueError('actual runtime differs from the complete tested release')


def _execute(protocol, evidence):
    _validate_release(protocol,evidence)
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    if (evidence/'execution-claim.json').exists() or (evidence/'budget-journal.jsonl').exists() or OUTPUT.exists():
        raise ValueError('one-shot execution already claimed')
    release = read(evidence/'software-release.json')
    source_root = evidence/'s'
    for relative in [p.relative_to(WT) for p in (WT/'src').rglob('*')
            if p.is_file() and p.suffix in ('.py','.txt') and '__pycache__' not in p.parts] + [
            Path(n) for n in ('requirements-py312.lock','requirements-research.lock','requirements-test.lock','pyproject.toml')]:
        target = source_root/relative
        target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists() and target.read_bytes() != (WT/relative).read_bytes():
            raise ValueError('owned source snapshot differs')
        if not target.exists():
            with target.open('xb') as stream: stream.write((WT/relative).read_bytes())
    if fingerprint(source_root) != release['source_fingerprint']:
        raise ValueError('snapshot differs')
    proposal = BASE/'lgbo-real-gain-proposal-20261023'
    template = read(proposal/'new_full.disabled-config.json')
    template['llm'].update(transport='openai_responses',endpoint=PROVIDER['endpoint'],model=PROVIDER['model'],
        api_key_env=PROVIDER['api_key_env'],timeout_s=120.,max_tokens=8192,reasoning_effort='none',responses_stream=True)
    template['llm'].setdefault('task_options',{})['region_preference_electrothermal'] = {'timeout_s':120.,'max_tokens':8192}
    if template['fit_rates'] != ['0.5C','1C']:
        raise ValueError('approved rate set differs')
    coordinates = read(proposal/'fixed-eight-coordinates.json')['parameters']
    # Historical scientific audit is outside the live clock; meter GP fits honestly.
    sys.path.insert(0,str(source_root/'src'))
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.surrogate import Matern52GP
    original, counter = Matern52GP.fit, [0]
    def counted(self,*args,**kwargs):
        counter[0] += 1
        return original(self,*args,**kwargs)
    Matern52GP.fit = counted
    try:
        historical_root = Path(protocol['original_run'])
        audit = audit_electrothermal_run(historical_root,deep=True)
    finally:
        Matern52GP.fit = original
    write(evidence/'historical-deep-audit.json',{'audit':audit,'GP_fit_calls':counter[0],
        'GP_sweeps':'not separately metered','API':0,'DFN':0})
    if not audit['passed']:
        raise ValueError('historical audit failed')
    _validate_release(protocol,evidence)
    read_credential()
    OUTPUT.mkdir(parents=True,exist_ok=False)
    write(evidence/'execution-claim.json',{'one_shot':True,'protocol_sha256':sha(evidence/'validation-protocol.json'),
        'utc':datetime.now(timezone.utc).isoformat()})
    budget = ValidationBudget.start(evidence/'budget-journal.jsonl',protocol_sha=sha(evidence/'validation-protocol.json'))

    def integrity():
        _validate_release(protocol,evidence)
        if fingerprint(source_root) != release['source_fingerprint']:
            raise ValueError('snapshot changed')

    def run_phase(intent):
        integrity()
        deadline = budget.deadline-30.
        spec = {**intent,'source_root':str(source_root),'source':release['source_fingerprint'],
            'source_commit':release['head'],'protocol_sha':sha(evidence/'validation-protocol.json'),
            'output':str(OUTPUT/intent['label']),'deadline':deadline,'environment':environment()}
        if intent['kind'] in ('minimal','historical'):
            deadline = min(deadline,budget.state()['origin']['mono']+870.,
                           time.monotonic()+intent['timeout_s']+10.)
            spec['deadline'] = deadline
            if intent['kind'] == 'minimal':
                spec['payload'] = {'task':'warm_start_electrothermal','artifact_task':'api_stream_minimal',
                    'instructions':'This is only a transport probe. Return exactly the JSON object {"ok":true}.',
                    'response_contract':{'type':'object','properties':{'ok':{'const':True}},'required':['ok'],'additionalProperties':False}}
            else:
                item = protocol['contexts'][intent['context_index']]
                spec.update(payload=read(item['frozen_payload']),round_path=str(replay_round_path(item)))
        else:
            spec.update(base_config=deepcopy(template),coordinates=coordinates,
                solve_cap=16 if intent['kind']=='initialization' else 40,
                seed=intent.get('seed',1709),arm=intent.get('arm','plain'))
        metadata = OUTPUT/(intent['label']+'-owned.json')
        value = supervise(validation_worker,spec,budget,deadline=deadline,metadata=metadata,integrity_check=integrity)
        value = {**value,'owned_tree_stopped':read(metadata).get('owned_tree_stopped')}
        if value['owned_tree_stopped'] is not True:
            raise RuntimeError('owned tree did not stop')
        if intent['kind'] == 'arm' and value.get('source') != release['source_fingerprint']:
            raise ValueError('paired source differs')
        write(evidence/('phase-'+intent['label']+'.json'),value)
        print(json.dumps({'phase':intent['label'],'passed':value.get('passed'),'status':value.get('status'),
            'diagnostic':value.get('diagnostic'),'wait':value.get('wait_observation'),'costs':budget.counts()},ensure_ascii=False),flush=True)
        return value

    with keep_awake(OUTPUT/'wake.json'):
        result = execute_sequence(protocol,budget,run_phase=run_phase,integrity_check=integrity)
    result.update(finished_utc=datetime.now(timezone.utc).isoformat(),source=release['source_fingerprint'])
    write(evidence/'validation-result.json',result)
    return result


def run_validation(protocol, evidence_root, *, execute=False):
    if not execute:
        return {'dry_run':True,'actual_API':0,'actual_DFN':0,'actual_BO':0,
                'limits':CAPS,'probes':PROBES,'gain_status':'not_tested'}
    return _execute(protocol,Path(evidence_root))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    args = parser.parse_args()
    path = EVIDENCE/'validation-protocol.json'
    result = run_validation(read(path) if path.exists() else {},EVIDENCE,execute=args.execute)
    print(json.dumps({k:v for k,v in result.items() if k not in ('attempts','gate_proofs','cases')},ensure_ascii=False))
    return 0 if result.get('dry_run') or result.get('status')=='completed' else 1


if __name__ == '__main__': raise SystemExit(main())
