"""Bounded, source-isolated real LGBO comparison; dry-run by default.

No optimization mathematics lives here. The worker uses each pinned source's
evaluator, optimizer, transport and independent audit unchanged.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time
from io import BytesIO

WT = Path('C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para')
MAIN = Path('D:/Users/aa133/Desktop/LLMBO_Para')
BASE = MAIN / 'bo-repair-work/20261017_et_implementation'
PROPOSAL = BASE / 'lgbo-real-gain-proposal-20261023'
EVIDENCE = BASE / 'lgbo-real-gain-20261023'
OUTPUT = MAIN / 'runs/g23r'
CAPS = {'DFN': 472, 'API': 161, 'wall_clock_s': 10800}
PHASES = {'preflight': {'DFN': 0, 'API': 1},
          'initialization': {'DFN': 32, 'API': 0},
          'main': {'DFN': 360, 'API': 120},
          'confirmation': {'DFN': 80, 'API': 40}}
SEEDS = (1709, 3253, 5501)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class ExperimentBudget:
    """Single parent writer; durable authorization precedes child side effects."""
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def start(cls, path, *, protocol_sha):
        if not isinstance(protocol_sha, str) or len(protocol_sha) != 64:
            raise ValueError('fixed protocol hash required')
        obj = cls(path)
        event = {'type': 'start', 'protocol_sha': protocol_sha, 'limits': CAPS,
                 'unix': time.time(), 'mono': time.monotonic(), 'previous': None}
        event['hash'] = digest(event)
        with obj.path.open('x', encoding='utf-8') as stream:
            stream.write(json.dumps(event, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())
        return obj

    @classmethod
    def load(cls, path):
        obj = cls(path)
        obj.state()
        return obj

    def state(self):
        text = self.path.read_text(encoding='utf-8')
        if not text.endswith('\n'):
            raise ValueError('incomplete budget journal')
        events = [json.loads(line) for line in text.splitlines()]
        if not events or events[0].get('type') != 'start' or events[0].get('limits') != CAPS:
            raise ValueError('invalid budget origin')
        state = {'counts': {'DFN': 0, 'API': 0}, 'phase': None, 'closed': False,
                 'finished': [], 'ids': set(), 'phase_counts': {p: {'DFN': 0, 'API': 0} for p in PHASES}}
        previous = None
        for i, event in enumerate(events):
            if event.get('previous') != previous or event.get('hash') != digest({k: v for k, v in event.items() if k != 'hash'}):
                raise ValueError('budget hash chain differs')
            previous = event['hash']
            if not i:
                continue
            if state['closed']:
                raise ValueError('event after closure')
            kind = event['type']
            if kind == 'begin':
                phase = event['phase']
                expected = list(PHASES)[len(state['finished'])] if len(state['finished']) < 4 else None
                if state['phase'] is not None or phase != expected:
                    raise ValueError('overlapping or out-of-order phase')
                state['phase'] = phase
            elif kind == 'charge':
                phase, item, ident = state['phase'], event['kind'], event['event_id']
                if phase is None or item not in ('DFN', 'API') or ident in state['ids']:
                    raise ValueError('unscoped/duplicate charge')
                state['ids'].add(ident)
                state['counts'][item] += 1
                state['phase_counts'][phase][item] += 1
                if state['counts'][item] > CAPS[item] or state['phase_counts'][phase][item] > PHASES[phase][item]:
                    raise ValueError('persisted budget exceeds cap')
            elif kind == 'finish':
                if state['phase'] is None or type(event['success']) is not bool:
                    raise ValueError('invalid phase completion')
                state['finished'].append(state['phase'])
                state['phase'] = None
                state['closed'] = not event['success']
            else:
                raise ValueError('unknown budget event')
        state.update(origin=events[0], hash=previous)
        return state

    def _append(self, event):
        event = {**event, 'previous': self.state()['hash']}
        event['hash'] = digest(event)
        with self.path.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(event, separators=(',', ':')) + '\n')
            stream.flush()
            os.fsync(stream.fileno())

    @property
    def deadline(self):
        start = self.state()['origin']
        return min(start['mono'] + CAPS['wall_clock_s'],
                   time.monotonic() + max(0., start['unix'] + CAPS['wall_clock_s'] - time.time()))

    def counts(self):
        return self.state()['counts'].copy()

    def _open(self):
        state = self.state()
        if state['closed'] or time.monotonic() >= self.deadline:
            raise RuntimeError('experiment closed or absolute deadline exhausted')
        return state

    def begin(self, phase, *, confirmation_released=False):
        state = self._open()
        expected = list(PHASES)[len(state['finished'])] if len(state['finished']) < 4 else None
        if state['phase'] is not None or phase != expected:
            raise RuntimeError('repeated, overlapping or out-of-order phase')
        if phase == 'confirmation' and confirmation_released is not True:
            raise RuntimeError('conditional confirmation not released')
        self._append({'type': 'begin', 'phase': phase})

    def finish(self, success):
        if self.state()['phase'] is None or type(success) is not bool:
            raise RuntimeError('active phase required')
        self._append({'type': 'finish', 'success': success})

    def require(self, calls):
        if type(calls) is not int or calls < 0:
            raise ValueError('nonnegative integer reservation required')
        state = self._open()
        phase = state['phase']
        if phase is None or state['counts']['DFN'] + calls > CAPS['DFN'] or state['phase_counts'][phase]['DFN'] + calls > PHASES[phase]['DFN']:
            raise RuntimeError('insufficient active solve reservation')

    def charge(self, kind, ident):
        state = self._open()
        phase = state['phase']
        if (phase is None or kind not in ('DFN', 'API') or not isinstance(ident, str)
                or not ident or ident in state['ids'] or state['counts'][kind] >= CAPS[kind]
                or state['phase_counts'][phase][kind] >= PHASES[phase][kind]):
            raise RuntimeError('duplicate, unscoped or exhausted charge')
        self._append({'type': 'charge', 'kind': kind, 'event_id': ident})


def _complete(row):
    return (row.get('completed') is True and row.get('audit_passed') is True
            and row.get('BO_rounds') == 20
            and all(type(row.get(k)) in (int, float) and math.isfinite(row[k]) and row[k] >= 0 for k in ('HV', 'F_U', 'F_T')))


def _regressed(old, new):
    delta = new['HV'] - old['HV']
    return (delta < -1e-6 or abs(delta) <= 1e-6
            and new['F_U'] - old['F_U'] > 1e-6 and new['F_T'] - old['F_T'] > 1e-4)


def decide(rows, confirmation=None):
    bad = {'status': 'inconclusive', 'needs_confirmation': False, 'revert': False}
    if (len(rows) != 3 or {r.get('seed') for r in rows} != set(SEEDS)
            or any(not _complete(r.get(a, {})) for r in rows for a in ('old_full', 'new_full'))):
        return bad
    means = {a: {k: math.fsum(r[a][k] for r in rows)/3 for k in ('HV', 'F_U', 'F_T')}
             for a in ('old_full', 'new_full')}
    negative = sum(_regressed(r['old_full'], r['new_full']) for r in rows)
    needs = negative >= 2 and _regressed(means['old_full'], means['new_full'])
    result = {'status': 'completed', 'needs_confirmation': needs, 'revert': False,
              'negative_seeds': negative, 'mean': means,
              'delta_HV': [r['new_full']['HV']-r['old_full']['HV'] for r in rows]}
    if confirmation is not None:
        if (not needs or confirmation.get('seed') != 7919
                or any(not _complete(confirmation.get(a, {})) for a in ('old_full', 'new_full'))):
            return bad
        result['revert'] = _regressed(confirmation['old_full'], confirmation['new_full'])
    return result


def check_initialization(old, new):
    if len(old) != len(new) or not old:
        raise ValueError('initialization sizes differ')
    for a, b in zip(old, new):
        for record in (a, b):
            values = record.get('objectives')
            if (not isinstance(values, (list, tuple)) or len(values) != 2
                    or any(type(v) not in (float, int) or not math.isfinite(v) or v < 0 for v in values)):
                raise ValueError('initialization needs two finite nonnegative errors')
        if tuple(a['parameters']) != tuple(b['parameters']) or any(
                abs(x-y) > tol for x, y, tol in zip(a['objectives'], b['objectives'], (1e-9, 1e-8))):
            raise ValueError('initialization coordinates/order or objectives differ')
    return True


@contextmanager
def keep_awake(path, *, kernel=None):
    """Prevent system idle sleep only while this owner runs; restore its state."""
    if kernel is None and os.name != 'nt':
        yield
        return
    if kernel is None:
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.SetThreadExecutionState.argtypes = [ctypes.c_ulong]
        kernel.SetThreadExecutionState.restype = ctypes.c_ulong
    previous = kernel.SetThreadExecutionState(0x80000001)
    if not previous:
        raise RuntimeError('could not acquire experiment wake lease')
    state = {'owner_pid': os.getpid(), 'active': True, 'released': False}
    try:
        write(path, state)
        yield
    finally:
        state.update(active=False, released=bool(kernel.SetThreadExecutionState(previous)))
        Path(path).write_text(json.dumps(state), encoding='utf-8')


def check_payload(value):
    if isinstance(value, dict):
        if 'known_parameters' in value:
            raise ValueError('synthetic truth must not reach the request')
        for item in value.values():
            check_payload(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            check_payload(item)


def stop_owned(process):
    if process.is_alive():
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=subprocess.CREATE_NO_WINDOW, timeout=10, check=False)
        else:
            process.terminate()
        process.join(1)
        if process.is_alive():
            process.kill()
            process.join(1)
    return not process.is_alive()


class OwnedWindowsJob:
    """A kill-on-close job owns descendants even after their root exits."""
    def __init__(self, process):
        import ctypes as c
        if os.name != 'nt':
            raise RuntimeError('this approved launcher requires Windows Job Objects')
        class Basic(c.Structure):
            _fields_ = [('process_time', c.c_longlong), ('job_time', c.c_longlong),
                ('flags', c.c_ulong), ('min_ws', c.c_size_t), ('max_ws', c.c_size_t),
                ('active_limit', c.c_ulong), ('affinity', c.c_size_t),
                ('priority', c.c_ulong), ('scheduling', c.c_ulong)]
        class IO(c.Structure):
            _fields_ = [(name, c.c_ulonglong) for name in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
        class Extended(c.Structure):
            _fields_ = [('basic', Basic), ('io', IO), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process_memory', c.c_size_t), ('peak_job_memory', c.c_size_t)]
        class Accounting(c.Structure):
            _fields_ = [(name,c.c_longlong) for name in ('user','kernel','period_user','period_kernel')] + [
                (name,c.c_ulong) for name in ('faults','total','active','terminated')]
        self.c, self.Accounting = c, Accounting
        self.k = c.WinDLL('kernel32', use_last_error=True)
        self.k.CreateJobObjectW.argtypes = [c.c_void_p, c.c_wchar_p]
        self.k.CreateJobObjectW.restype = c.c_void_p
        self.k.SetInformationJobObject.argtypes = [c.c_void_p,c.c_int,c.c_void_p,c.c_ulong]
        self.k.OpenProcess.argtypes = [c.c_ulong,c.c_int,c.c_ulong]
        self.k.OpenProcess.restype = c.c_void_p
        self.k.AssignProcessToJobObject.argtypes = [c.c_void_p,c.c_void_p]
        self.k.TerminateJobObject.argtypes = [c.c_void_p,c.c_uint]
        self.k.QueryInformationJobObject.argtypes = [c.c_void_p,c.c_int,c.c_void_p,c.c_ulong,c.c_void_p]
        self.k.CloseHandle.argtypes = [c.c_void_p]
        self.handle = self.k.CreateJobObjectW(None,None)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        process_handle = None
        try:
            limits = Extended()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not self.k.SetInformationJobObject(self.handle,9,c.byref(limits),c.sizeof(limits)):
                raise c.WinError(c.get_last_error())
            process_handle = self.k.OpenProcess(0x100 | 0x1,False,process.pid)
            if not process_handle or not self.k.AssignProcessToJobObject(self.handle,process_handle):
                raise c.WinError(c.get_last_error())
        except BaseException:
            self.k.CloseHandle(self.handle)
            self.handle = None
            raise
        finally:
            if process_handle:
                self.k.CloseHandle(process_handle)

    def active(self):
        value = self.Accounting()
        if not self.k.QueryInformationJobObject(self.handle,1,self.c.byref(value),self.c.sizeof(value),None):
            raise self.c.WinError(self.c.get_last_error())
        return value.active

    def close(self):
        stopped = False
        try:
            if self.active():
                if not self.k.TerminateJobObject(self.handle,1):
                    raise self.c.WinError(self.c.get_last_error())
            until = time.monotonic()+2
            while self.active() and time.monotonic()<until:
                time.sleep(.01)
            stopped = self.active() == 0
        finally:
            self.k.CloseHandle(self.handle)
            self.handle = None
        return stopped


def _owned_bootstrap(worker, spec, connection):
    # No source import, HTTP or solve is possible before job membership.
    if connection.recv() != ('go', None):
        raise RuntimeError('owned worker start was not authorized')
    worker(spec, connection)


def supervise(worker, spec, budget, *, deadline, metadata, integrity_check=None):
    """Non-daemon worker can own bounded solver/HTTP descendants."""
    deadline = min(deadline, budget.deadline)
    if time.monotonic() >= deadline:
        raise TimeoutError('deadline exhausted before worker')
    if integrity_check is not None:
        integrity_check()
    parent, child = multiprocessing.get_context('spawn').Pipe()
    process = multiprocessing.get_context('spawn').Process(target=_owned_bootstrap, args=(worker, spec, child), daemon=False)
    process.start()
    child.close()
    status = 'failed'
    job = None
    try:
        job = OwnedWindowsJob(process)
        parent.send(('go', None))
        while time.monotonic() < deadline:
            if parent.poll(min(.05, max(0., deadline-time.monotonic()))):
                try:
                    kind, value = parent.recv()
                except EOFError:
                    raise RuntimeError('owned worker closed without result') from None
                if time.monotonic() >= deadline:
                    raise TimeoutError('late owned result')
                if integrity_check is not None:
                    integrity_check()
                if kind in ('charge', 'require'):
                    try:
                        budget.charge(*value) if kind == 'charge' else budget.require(value)
                        parent.send(('ok', None))
                    except Exception as exc:
                        parent.send(('denied', type(exc).__name__))
                        raise
                elif kind == 'result':
                    status = 'returned'
                    return value
                elif kind == 'error':
                    raise RuntimeError('owned phase failed: ' + value)
                else:
                    raise RuntimeError('invalid worker protocol')
            if not process.is_alive() and not parent.poll():
                raise RuntimeError('owned worker exited without result')
        raise TimeoutError('absolute owned worker deadline exhausted')
    finally:
        if status == 'returned':
            process.join(timeout=1)
        cleanup_error = None
        try:
            stopped = job.close() if job is not None else stop_owned(process)
        except Exception as exc:
            stopped = False
            cleanup_error = type(exc).__name__
        process.join(timeout=1)
        if process.is_alive():
            process.kill()
            process.join(timeout=1)
            stopped = False
        parent.close()
        write(metadata, {'owned_pid': process.pid, 'owned_tree_stopped': stopped,
                         'status': status, 'exit_code': process.exitcode, 'deadline_monotonic': deadline,
                         'cleanup_error_type': cleanup_error})
        if not stopped:
            raise RuntimeError('owned job cleanup could not be verified')


def cases():
    orders = [('plain', 'old_full', 'new_full'), ('old_full', 'new_full', 'plain'),
              ('new_full', 'plain', 'old_full')]
    return [{'seed': seed, 'arm': arm, 'case_id': f'{seed}_{arm}'}
            for seed, order in zip(SEEDS, orders) for arm in order]


def validate_proposal():
    protocol = read(PROPOSAL/'protocol.json')
    seal = read(PROPOSAL/'proposal-seal.json')
    for name, value in seal['files_sha256'].items():
        if sha(PROPOSAL/name) != value:
            raise ValueError('proposal file changed: ' + name)
    if sha(protocol['plan']['path']) != protocol['plan']['sha256']:
        raise ValueError('reviewed plan bytes changed')
    for cfg in protocol['configs'].values():
        value = read(PROPOSAL/cfg['path'])
        if value['llm']['enabled'] or value['budgets']['max_solver_calls'] or value['budgets']['max_llm_requests']:
            raise ValueError('proposal must remain disabled')
    return protocol


def dry_run(*, output=OUTPUT):
    protocol = validate_proposal()
    return {'dry_run': True, 'cases': cases(), 'limits': CAPS, 'actual_API': 0,
            'actual_DFN': 0, 'output': str(output), 'protocol_sha256': sha(PROPOSAL/'protocol.json'),
            'region_method': 'lgbo_v2', 'conditional_confirmation_seed': 7919}


def read_credential():
    """Only the dedicated endpoint's variable; never serialize its value."""
    key = os.environ.get('SUB2API_API_KEY')
    if not key and os.name == 'nt':
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, 'Environment') as handle:
            try:
                key, _ = winreg.QueryValueEx(handle, 'SUB2API_API_KEY')
            except FileNotFoundError:
                key = None
    if not isinstance(key, str) or not key.strip() or any(c.isspace() for c in key):
        raise ValueError('dedicated credential unavailable')
    os.environ['SUB2API_API_KEY'] = key


def worker_entry(spec, connection):
    # Lazy import prevents source pollution and makes __mp_main__ inert.
    from lgbo_real_gain_worker import run_worker
    run_worker(spec, connection)


def fingerprint(root):
    root = Path(root)
    files = [*sorted((root/'src/llmbo_para').rglob('*.py')),
             *sorted((root/'src/llmbo_para/prompts').glob('*.txt'))]
    files += [root/n for n in ('requirements-py312.lock', 'requirements-research.lock',
                               'requirements-test.lock', 'pyproject.toml')]
    return digest({p.relative_to(root).as_posix(): sha(p) for p in files if p.is_file()})


def materialize_old(protocol):
    root = EVIDENCE/'s0'
    expected = protocol['sources']['old_full']
    if not root.exists():
        root.mkdir()
        archive = subprocess.check_output(['git', '-C', str(WT), 'archive', expected['commit'], '--',
            'src/llmbo_para', 'requirements-py312.lock', 'requirements-research.lock',
            'requirements-test.lock', 'pyproject.toml'])
        with tarfile.open(fileobj=BytesIO(archive)) as stream:
            for item in stream.getmembers():
                if not item.isfile():
                    continue
                target = (root/item.name).resolve()
                if not target.is_relative_to(root.resolve()):
                    raise ValueError('archive path leaves owned snapshot')
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as destination:
                    destination.write(stream.extractfile(item).read())
    if fingerprint(root) != expected['fingerprint']:
        raise ValueError('old source snapshot differs')
    for path in (root/'src/llmbo_para/prompts').glob('*.txt'):
        if path.read_text(encoding='utf-8') != (WT/'src/llmbo_para/prompts'/path.name).read_text(encoding='utf-8'):
            raise ValueError('old/current runtime Prompt text differs')
    return root


def materialize_new(protocol):
    """Copy actual tested checkout bytes, preserving their source fingerprint."""
    root = EVIDENCE/'s1'
    if not root.exists():
        root.mkdir()
        files = [*sorted((WT/'src/llmbo_para').rglob('*.py')),
                 *sorted((WT/'src/llmbo_para/prompts').glob('*.txt'))]
        files += [WT/n for n in ('requirements-py312.lock', 'requirements-research.lock',
            'requirements-test.lock', 'pyproject.toml', 'configs/electrothermal-lgbo-numerical-ablation-software.json')]
        for source in files:
            destination = root/source.relative_to(WT)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open('xb') as stream:
                stream.write(source.read_bytes())
    if fingerprint(root) != protocol['sources']['new_full_and_plain']['fingerprint']:
        raise ValueError('current owned source snapshot differs')
    return root


def freeze_runtime():
    current = Path(__file__).resolve().parent
    names = ('run_lgbo_real_gain.py', 'lgbo_real_gain_worker.py')
    root = EVIDENCE/'runtime'/digest({n: sha(current/n) for n in names})[:16]
    root.mkdir(parents=True, exist_ok=True)
    for name in names:
        destination = root/name
        if destination.exists():
            if destination.read_bytes() != (current/name).read_bytes():
                raise ValueError('owned runtime snapshot differs')
        else:
            with destination.open('xb') as stream:
                stream.write((current/name).read_bytes())
    return root


def final_integrity_gate(result, *, expected, actual):
    value = deepcopy(result)
    value['integrity_expected'], value['integrity_actual'] = expected, actual
    if expected != actual:
        value.update(status='inconclusive', failure_stage='final_integrity',
                     decision={'status': 'inconclusive', 'revert': False, 'needs_confirmation': False})
    return value


def archive_path_check(output, source_roots):
    paths = []
    for root in source_roots:
        relative = [p.relative_to(root) for folder in ('src', 'configs', 'scripts', 'tests', 'docs')
                    for p in (root/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
        paths.extend(Path(output)/'c00'/('0'*38)/'source'/p for p in relative)
    paths.append(Path(output)/'c00'/('0'*38)/'http'/('region_preference_electrothermal_request_'+'a'*20+'.response.json'))
    maximum = max(len(str(p.resolve())) for p in paths)
    if os.name == 'nt' and maximum >= 260:
        raise ValueError('unsafe Windows archive root')
    return maximum


def _release():
    path = EVIDENCE/'software-release.json'
    if not path.is_file():
        raise ValueError('offline software release is missing')
    release = read(path)
    if (release.get('passed') is not True or release.get('protocol_sha256') != sha(PROPOSAL/'protocol.json')
            or release.get('script_sha256') != sha(__file__)
            or release.get('worker_sha256') != sha(Path(__file__).with_name('lgbo_real_gain_worker.py'))):
        raise ValueError('tested runtime freeze differs')
    for name in ('baseline', 'related', 'full'):
        result = read(release[name]['path'])
        if sha(release[name]['path']) != release[name]['sha256']:
            raise ValueError('software evidence changed')
        counts = result.get('junit_counts') or {}
        if (result.get('exit_code') != 0 or counts.get('tests', 0) < 1
                or counts.get('failures') or counts.get('errors') or counts.get('skipped')
                or result['boundary']['network_attempts'] or result['boundary']['battery_solve_attempts']
                or not result.get('source_unchanged_during_run') or not result.get('protected_unchanged_during_run')):
            raise ValueError('software verification failed')
    return release


def _configuration(arm):
    protocol = validate_proposal()
    entry = protocol['configs'][arm]
    raw = (PROPOSAL/entry['path']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != entry['sha256']:
        raise ValueError('sealed configuration changed')
    return json.loads(raw)


def checked_initial(reference):
    if sha(reference['path']) != reference['sha256']:
        raise ValueError('fresh initialization changed after its first pin')
    return deepcopy(reference)


def _pairs(results, seeds):
    by_key = {(r['seed'], r['arm']): r for r in results}
    return [{'seed': seed, **{a: by_key.get((seed, a), {}) for a in ('old_full', 'new_full')}} for seed in seeds]


def execute():
    _release()  # Before credential reads, creating a live clock or any worker.
    protocol = validate_proposal()
    approval = read(EVIDENCE/'approval.json')
    if (approval.get('approved_by_user') is not True or approval.get('limits') != CAPS
            or approval.get('protocol_sha256') != sha(PROPOSAL/'protocol.json')
            or approval.get('automatic_retries') != 0 or approval.get('parallel_workers') != 1):
        raise ValueError('exact independent approval is required')
    if OUTPUT.exists() or (EVIDENCE/'budget-journal.jsonl').exists():
        raise ValueError('experiment already claimed; automatic resume forbidden')
    if fingerprint(WT) != protocol['sources']['new_full_and_plain']['fingerprint']:
        raise ValueError('current product source changed')
    templates = {arm: _configuration(arm) for arm in ('plain','old_full','new_full')}
    coordinates_raw = (PROPOSAL/protocol['coordinates']['path']).read_bytes()
    if hashlib.sha256(coordinates_raw).hexdigest() != protocol['coordinates']['sha256']:
        raise ValueError('fixed coordinate input changed')
    points = json.loads(coordinates_raw)['parameters']
    old_root = materialize_old(protocol)
    current_root = materialize_new(protocol)
    runtime = Path(__file__).resolve().parent
    if runtime.resolve() != freeze_runtime().resolve():
        raise ValueError('execute only the frozen tested runtime copy')
    expected = {'old': protocol['sources']['old_full']['fingerprint'],
        'current': protocol['sources']['new_full_and_plain']['fingerprint'],
        'workspace': protocol['sources']['new_full_and_plain']['fingerprint'],
        'script': sha(runtime/'run_lgbo_real_gain.py'), 'worker': sha(runtime/'lgbo_real_gain_worker.py'),
        'preflight_config': sha(current_root/'configs/electrothermal-lgbo-numerical-ablation-software.json')}
    def actual_integrity():
        def observed(function, path):
            try:
                return function(path)
            except OSError:
                return None
        return {'old': observed(fingerprint, old_root), 'current': observed(fingerprint, current_root),
            'workspace': observed(fingerprint, WT), 'script': observed(sha, runtime/'run_lgbo_real_gain.py'),
            'worker': observed(sha, runtime/'lgbo_real_gain_worker.py'),
            'preflight_config': observed(sha, current_root/'configs/electrothermal-lgbo-numerical-ablation-software.json')}
    def verify_integrity():
        if expected != actual_integrity():
            raise ValueError('source/runtime integrity differs during experiment')
    verify_integrity()
    maximum_path = archive_path_check(OUTPUT, (current_root, old_root))
    read_credential()
    OUTPUT.mkdir(parents=True, exist_ok=False)
    write(EVIDENCE/'live-launch.json', {'protocol_sha256': sha(PROPOSAL/'protocol.json'),
        'started_utc': datetime.now(timezone.utc).isoformat(), 'limits': CAPS,
        'archive_maximum_path': maximum_path, 'credential_present': True,
        'old_source_root': str(old_root), 'current_source_root': str(current_root),
        'runtime_root': str(runtime), 'integrity_expected': expected, 'output_root': str(OUTPUT),
        'runtime_sha256': sha(__file__), 'worker_sha256': sha(Path(__file__).with_name('lgbo_real_gain_worker.py'))})
    budget = ExperimentBudget.start(EVIDENCE/'budget-journal.jsonl', protocol_sha=sha(PROPOSAL/'protocol.json'))
    results, initializations, initial_references = [], {}, {}
    outcome = {'status': 'inconclusive', 'revert': False, 'needs_confirmation': False}
    stage = 'preflight'
    def run(spec):
        spec.update(deadline=budget.deadline, protocol_sha=sha(PROPOSAL/'protocol.json'))
        source_key = 'old_full' if spec.get('arm') == 'old_full' else 'new_full_and_plain'
        spec['source_root'] = str(old_root if source_key == 'old_full' else current_root)
        spec['source'] = protocol['sources'][source_key]['fingerprint']
        spec['source_commit'] = protocol['sources'][source_key]['commit']
        return supervise(worker_entry, spec, budget, deadline=budget.deadline,
            metadata=EVIDENCE/'supervision'/(spec['label']+'.json'), integrity_check=verify_integrity)
    try:
        budget.begin('preflight')
        proof = run({'kind': 'preflight', 'arm': 'new_full', 'solve_cap': 0,
                     'output': str(OUTPUT/'p'), 'label': 'preflight'})
        if proof.get('passed') is not True:
            raise RuntimeError('real contract preflight did not pass')
        budget.finish(True)
        stage = 'initialization'
        budget.begin(stage)
        for i, source_arm in enumerate(('old_full', 'new_full')):
            result = run({'kind': 'initialization', 'arm': source_arm, 'seed': 1709,
                'solve_cap': 16, 'coordinates': points, 'base_config': deepcopy(templates[source_arm]),
                'output': str(OUTPUT/f'i{i}'), 'label': f'i{i}'})
            initializations[source_arm] = result
            initial_references[source_arm] = {'path': result['plan_path'], 'sha256': sha(result['plan_path'])}
        check_initialization(initializations['old_full']['ordered_records'], initializations['new_full']['ordered_records'])
        budget.finish(True)
        stage = 'main'
        budget.begin(stage)
        for index, case in enumerate(cases()):
            source_arm = 'old_full' if case['arm'] == 'old_full' else 'new_full'
            spec = {**case, 'kind': 'arm', 'solve_cap': 40,
                'base_config': deepcopy(templates[case['arm']]), 'initial': checked_initial(initial_references[source_arm]),
                'label': f'c{index:02d}', 'output': str(OUTPUT/f'c{index:02d}')}
            result = run(spec)
            if not _complete(result):
                raise RuntimeError('arm incomplete; no replacement permitted')
            results.append(result)
            write(EVIDENCE/'case-results'/(spec['label']+'.json'), result)
            print(json.dumps({'case': case['case_id'], 'HV': result['HV'],
                'F_U_mV': 1000*result['F_U'], 'F_T_K': result['F_T'], 'costs': budget.counts()}), flush=True)
        # Same-source Plain/Full must start from exactly the same numerical state.
        by_key = {(r['seed'], r['arm']): r for r in results}
        for seed in SEEDS:
            a, b = by_key[seed, 'plain'], by_key[seed, 'new_full']
            if a['initial_file_sha'] != b['initial_file_sha'] or a['first_numerical_context_sha'] != b['first_numerical_context_sha']:
                raise ValueError('shared initialization/first numerical context differs')
        verify_integrity()
        outcome = decide(_pairs(results, SEEDS))
        budget.finish(True)
        write(EVIDENCE/'main-decision.json', outcome)
        if outcome['needs_confirmation']:
            verify_integrity()
            stage = 'confirmation'
            budget.begin(stage, confirmation_released=True)
            confirmation = []
            for index, source_arm in enumerate(('new_full', 'old_full'), start=9):
                result = run({'kind': 'arm', 'seed': 7919, 'arm': source_arm, 'solve_cap': 40,
                    'base_config': deepcopy(templates[source_arm]), 'initial': checked_initial(initial_references[source_arm]),
                    'label': f'c{index:02d}', 'output': str(OUTPUT/f'c{index:02d}')})
                if not _complete(result):
                    raise RuntimeError('confirmation incomplete')
                results.append(result)
                confirmation.append(result)
                write(EVIDENCE/'case-results'/f'c{index:02d}.json', result)
            outcome = decide(_pairs(results, SEEDS), _pairs(confirmation, (7919,))[0])
            budget.finish(True)
        result = {'status': 'completed', 'decision': outcome, 'cases': results,
                  'costs': budget.counts(), 'initializations': initializations}
    except Exception as exc:
        if budget.state()['phase'] is not None:
            budget.finish(False)
        result = {'status': 'inconclusive', 'failure_stage': stage,
                  'error_type': type(exc).__name__, 'error': str(exc),
                  'cases': results, 'initializations': initializations,
                  'costs': budget.counts(), 'decision': {'revert': False, 'status': 'inconclusive'}}
    result = final_integrity_gate(result, expected=expected, actual=actual_integrity())
    result.update(finished_utc=datetime.now(timezone.utc).isoformat(),
        source_after=fingerprint(WT), protocol_sha256=sha(PROPOSAL/'protocol.json'))
    write(EVIDENCE/'summary.json', result)
    write(EVIDENCE/'execution-exit.json', {'exit_code': 0 if result['status'] == 'completed' else 1})
    print(json.dumps({k: result[k] for k in ('status', 'costs', 'decision')}, ensure_ascii=False), flush=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps(dry_run(), ensure_ascii=False))
        return 0
    _release()
    with keep_awake(EVIDENCE/'live-idle-lease.json'):
        return 0 if execute()['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
