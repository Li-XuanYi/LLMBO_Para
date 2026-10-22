"""Approved 2x2 software controls; CLI is dry-run unless --execute is given.

Uses the ordinary evaluator, immutable initialization, optimizer and deep audit.
Instrumentation delegates every scientific call unchanged. No real LLM or DFN.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from copy import deepcopy
import csv
from dataclasses import asdict
import hashlib
import json
import math
import multiprocessing
import os
from pathlib import Path
import socket
import sys
import time

WT = Path(__file__).resolve().parents[1]
STAGE_WALL_CLOCK_S = 3600
PER_RUN_WALL_CLOCK_S = 120
MATRIX = [('G016_S0', 16, 0), ('G512_S0', 512, 0),
          ('G016_S4', 16, 4), ('G512_S4', 512, 4)]
SEEDS = (17, 41, 59)
MODES = ('warmstart_only', 'full_llmbo_mo')


def _environment():
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    for name in ('SUB2API_API_KEY', 'OPENAI_API_KEY'):
        os.environ.pop(name, None)
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    if str(WT/'src') not in sys.path:
        sys.path.insert(0, str(WT/'src'))


def _write(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _append(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, allow_nan=False)+'\n')


def _cases():
    return [dict(cell=cell, global_pool_size=size, gp_sweeps=sweeps, seed=seed,
                 mode=mode, case_id=f'{cell}_{seed}_{mode}')
            for cell, size, sweeps in MATRIX for seed in SEEDS
            for mode in (MODES[::-1] if seed == 41 else MODES)]


def case_output_root(output: Path, case: dict) -> Path:
    """Keep the scientific case ID in the index, with a short disk directory."""
    ids = [c['case_id'] for c in _cases()]
    try:
        index = ids.index(case['case_id'])
    except (KeyError, ValueError):
        raise ValueError('unknown archive case') from None
    return Path(output)/f'r{index:02d}'


def validate_archive_paths(output: Path) -> dict:
    """Check all snapshot/long Region filenames before spending any budget."""
    output = Path(output).resolve()
    relative = [p.relative_to(WT) for folder in ('src', 'configs', 'scripts', 'tests', 'docs')
                for p in (WT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    run_bases = [output/'init', *[case_output_root(output, c) for c in _cases()]]
    paths = [base/('0'*38)/'source'/p for base in run_bases for p in relative]
    paths += [base/('0'*38)/'http'/('region_preference_electrothermal_request_'+'a'*20+'.response.json')
              for base in run_bases]
    longest = max(paths, key=lambda p:len(str(p)))
    maximum = len(str(longest))
    if os.name == 'nt' and maximum >= 260:
        raise ValueError(f'archive path exceeds Windows limit ({maximum}); use a shorter output root')
    return dict(maximum_path_length=maximum, longest_path=str(longest), case_layout='r00-r23', initialization_layout='init')


def ablation_protocol(base_config: dict) -> dict:
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    cfg = deepcopy(base_config)
    errors = electrothermal_configuration_errors(cfg)
    opt = cfg.get('optimization', {}); budget = cfg.get('budgets', {})
    expected = dict(initial_count=8, total_candidate_budget=28, local_pool_size=8,
        local_radius=.2, max_rate_attempts=1, parallel_workers=1, region_method='lgbo_v1',
        objective_scales=[.1, 1.], rho_aug=.05,
        weights=[[.8, .2], [.2, .8], [.5, .5]], hv_reference=[10., 10.])
    if any(opt.get(k) != v for k, v in expected.items()):
        errors.append('settings differ from the frozen numerical protocol')
    if (cfg.get('run_kind') != 'synthetic_software' or cfg.get('model', {}).get('provider') != 'software'
            or cfg.get('fit_rates') != ['0.5C', '1C'] or cfg.get('data', {}).get('kind') != 'builtin_synthetic'
            or cfg.get('llm', {}).get('enabled') is not False
            or budget.get('max_llm_requests') != 0 or budget.get('max_solver_calls') != 0
            or opt.get('initial_plan') is not None):
        errors.append('only fresh R2 builtin software data with zero API/DFN is permitted')
    if opt.get('warmstart') != dict(count=8, pool_size=16, max_requests=1, max_candidates=16, max_evaluations=16):
        errors.append('initialization must be the approved fresh 16-select-8 protocol')
    if errors:
        raise ValueError('; '.join(errors))
    return dict(version='lgbo_numerical_software_v1', base_config=cfg,
        matrix=[dict(cell=c, global_pool_size=n, gp_sweeps=s) for c, n, s in MATRIX],
        seeds=list(SEEDS), cases=_cases(), max_software_candidates=496, max_software_calls=992,
        wall_clock_s=STAGE_WALL_CLOCK_S, per_run_wall_clock_s=PER_RUN_WALL_CLOCK_S,
        fixed_mock_region=dict(kind='region', lb=[.3]*6, ub=[.8]*6, confidence=.65),
        API_requests=0, DFN_solves=0, new_objective_evaluations=0, dry_run=True)


def make_case_config(base_config: dict, *, global_pool_size: int, gp_sweeps: int,
                     seed: int, mode: str, initial_plan: dict) -> dict:
    cfg = ablation_protocol(base_config)['base_config']
    if (type(global_pool_size) is not int or global_pool_size not in (16, 512)
            or type(gp_sweeps) is not int or gp_sweeps not in (0, 4)
            or type(seed) is not int or seed not in SEEDS or mode not in MODES):
        raise ValueError('case outside the approved matrix')
    if (type(initial_plan) is not dict or set(initial_plan) != {'path', 'sha256'}
            or not isinstance(initial_plan['path'], str) or not initial_plan['path']
            or not isinstance(initial_plan['sha256'], str) or len(initial_plan['sha256']) != 64):
        raise ValueError('immutable initialization path/hash required')
    cfg['optimization'].update(global_pool_size=global_pool_size, gp_sweeps=gp_sweeps,
        seed=seed, mode=mode, initial_plan=deepcopy(initial_plan))
    cfg['budgets']['wall_clock_s'] = 120.
    return cfg


def recovery_protocol(base_config: dict, recovery: dict) -> dict:
    """The human-approved single recovery: preserve the actual 16/32 history."""
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    protocol = ablation_protocol(base_config)
    if (type(recovery) is not dict or set(recovery) != {'initial_plan','prior_costs'}
            or recovery['prior_costs'] != {'new_objective_evaluations':16,'software_calls':32}):
        raise ValueError('controlled recovery requires the original 16/32 cost attribution')
    cfg = make_case_config(base_config, global_pool_size=16, gp_sweeps=0, seed=17,
                           mode='warmstart_only', initial_plan=recovery['initial_plan'])
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=WT)
    if not report['ready']:
        raise ValueError('recovery initialization failed: '+'; '.join(report['errors']))
    plan = prepared.initial_plan; evidence = plan.history_evidence
    if (len(plan.records)!=8 or evidence is None or len(evidence['screening_records'])!=16
            or evidence['costs']['software_calls']!=32 or evidence['costs']['solver_calls']!=0
            or evidence['costs']['llm_requests']!=0):
        raise ValueError('recovery requires verified software-only 16-select-8 screening')
    protocol.update(recovery=deepcopy(recovery), max_software_candidates=480, max_software_calls=960)
    return protocol


class FitObserver:
    """Observe calls, including audit refits, without changing the GP state."""
    def __init__(self, path, *, phase):
        self.path, self.phase = Path(path), phase

    def __enter__(self):
        from llmbo_para.surrogate import Matern52GP
        self.cls = Matern52GP; self.original = Matern52GP.fit
        observer = self
        def fit(model, *args, **kwargs):
            start = time.perf_counter()
            result = observer.original(model, *args, **kwargs)
            _append(observer.path, dict(phase=observer.phase, elapsed_s=time.perf_counter()-start,
                max_sweeps=model.max_sweeps, sweeps_completed=model.fit_diagnostics['sweeps_completed']))
            return result
        self.cls.fit = fit
        return self

    def __exit__(self, *_):
        self.cls.fit = self.original


class SoftwareBoundary:
    def __init__(self):
        self.network_attempts = self.battery_solve_attempts = 0
        self.restores = []

    def __enter__(self):
        def patch(obj, name, value):
            self.restores.append((obj, name, getattr(obj, name))); setattr(obj, name, value)
        def network(*args, **kwargs):
            self.network_attempts += 1
            raise RuntimeError('zero network budget')
        for obj, name in ((socket.socket, 'connect'), (socket.socket, 'connect_ex'), (socket, 'create_connection')):
            patch(obj, name, network)
        import pybamm
        def battery(*args, **kwargs):
            self.battery_solve_attempts += 1
            raise RuntimeError('zero battery solve budget')
        patch(pybamm.Simulation, 'solve', battery)
        patch(pybamm.BaseSolver, 'solve', battery)
        return self

    def __exit__(self, *_):
        for obj, name, original in reversed(self.restores):
            setattr(obj, name, original)

    def counts(self):
        return dict(network_attempts=self.network_attempts, battery_solve_attempts=self.battery_solve_attempts)


class SoftwareBudget:
    def __init__(self, path, *, max_candidates, max_rate_calls):
        self.path = Path(path); self.maximum = max_candidates; self.rate_maximum = max_rate_calls
        self.candidate_evaluations = self.rate_calls = 0

    def counts(self):
        return dict(new_objective_evaluations=self.candidate_evaluations, software_calls=self.rate_calls)

    @contextmanager
    def observe(self):
        from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
        from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
        original_eval, original_sim = ElectrothermalEvaluator.evaluate, SyntheticElectrothermalSimulator.simulate
        budget = self
        def evaluate(evaluator, candidate, dataset):
            if (budget.candidate_evaluations >= budget.maximum
                    or budget.rate_maximum-budget.rate_calls < len(dataset.fit_rates)):
                raise RuntimeError('software candidate/call budget exhausted')
            budget.candidate_evaluations += 1
            _append(budget.path, dict(kind='candidate_started', **budget.counts()))
            result = original_eval(evaluator, candidate, dataset)
            _append(budget.path, dict(kind='candidate_finished', complete_pair_valid=result.complete_pair_valid,
                                     evaluation_id=result.evaluation_id, **budget.counts()))
            return result
        def simulate(simulator, parameters, case):
            if budget.rate_calls >= budget.rate_maximum:
                raise RuntimeError('software rate-call budget exhausted')
            budget.rate_calls += 1
            _append(budget.path, dict(kind='software_call', rate=case.rate, **budget.counts()))
            return original_sim(simulator, parameters, case)
        ElectrothermalEvaluator.evaluate, SyntheticElectrothermalSimulator.simulate = evaluate, simulate
        try:
            yield self
        finally:
            ElectrothermalEvaluator.evaluate, SyntheticElectrothermalSimulator.simulate = original_eval, original_sim


class FixedSoftwareActions:
    def __init__(self, space, region):
        self.space, self.region = space, region

    def post(self, payload):
        if payload['task'] == 'warm_start_electrothermal':
            from llmbo_para.sobol import Sobol6
            return {k: payload[k] for k in ('schema_version', 'parameter_profile', 'fit_rates', 'signatures')} | {
                'candidates': [{'parameters': dict(zip((s.name for s in self.space.specs), self.space.denormalize(x)))}
                               for x in Sobol6(17).draw(16)]}
        from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id
        return dict(request_id=lgbo_request_id(payload), region=deepcopy(self.region))


def summarize_numerical_ablation(case_results: list[dict]) -> dict:
    expected = {c['case_id'] for c in _cases()}; seen = set()
    shared = None
    for row in case_results:
        ident = f"{row['cell']}_{row['seed']}_{row['mode']}"
        if row['case_id'] != ident or ident not in expected or ident in seen:
            raise ValueError('unexpected or duplicate case')
        seen.add(ident)
        identities = [row[k] for k in ('initial_plan_sha256', 'source_fingerprint', 'comparison_protocol', 'initialization_ids')]
        if shared is None:
            shared = identities
        if shared != identities or len(row['initialization_ids']) != 8 or len(set(row['initialization_ids'])) != 8:
            raise ValueError('mixed source/comparison/initialization')
        if row['status'] == 'completed' and (not row['audit_passed'] or row['summary']['BO_rounds'] != 20):
            raise ValueError('case cannot be certified complete')
        hv = row.get('summary', {}).get('HV')
        if (hv is None and row['status']=='completed'
                or hv is not None and (type(hv) not in (int, float) or not math.isfinite(hv) or hv<0)):
            raise ValueError('invalid HV')
    completed = {r['case_id']: r for r in case_results if r['status'] == 'completed'}
    missing = sorted(expected-set(completed))
    contrasts, effects = [], []
    for cell, _, _ in MATRIX:
        for seed in SEEDS:
            pair = [completed.get(f'{cell}_{seed}_{mode}') for mode in MODES]
            if all(pair) and all(r['summary'].get('HV') is not None for r in pair):
                contrasts.append(dict(cell=cell, seed=seed, delta_HV=pair[1]['summary']['HV']-pair[0]['summary']['HV']))
    for seed in SEEDS:
        d = {r['cell']: r['delta_HV'] for r in contrasts if r['seed'] == seed}
        if len(d) == 4:
            effects.append(dict(seed=seed, density_S0=d['G512_S0']-d['G016_S0'],
                density_S4=d['G512_S4']-d['G016_S4'], fit_G016=d['G016_S4']-d['G016_S0'],
                fit_G512=d['G512_S4']-d['G512_S0'],
                interaction=d['G512_S4']-d['G016_S4']-d['G512_S0']+d['G016_S0']))
    return dict(status='incomplete' if missing else 'completed', cases=case_results,
                missing_cases=missing, contrasts=contrasts, factorial_effects=effects, HV=None)


def _csv(path, rows):
    if not rows:
        Path(path).write_text('', encoding='utf-8'); return
    with Path(path).open('x', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, list(rows[0])); writer.writeheader(); writer.writerows(rows)


class CaseTimeout(TimeoutError):
    def __init__(self, case_id):
        self.case_id = case_id
        super().__init__('owned workflow deadline exhausted: '+case_id)


def _supervise_ablation(worker, args, *, deadline):
    """The existing owned-pipe protocol, extended with hard workflow phases.

    Keep the entire batch in one child for cumulative instrumentation; the
    parent enforces both clocks, including while the child is in native code.
    No changes to the scientific execution module or descendant workers.
    """
    parent, child = multiprocessing.get_context('spawn').Pipe()
    process = multiprocessing.get_context('spawn').Process(target=worker, args=(*args,child), daemon=True)
    process.start(); child.close()
    active = None; phase_deadline = deadline
    try:
        while True:
            now = time.monotonic()
            if active is not None and now >= phase_deadline:
                raise CaseTimeout(active)
            if now >= deadline:
                raise TimeoutError('stage deadline exhausted')
            if parent.poll(min(deadline-now, phase_deadline-now, .05)):
                try:
                    kind, value = parent.recv()
                except EOFError:
                    raise RuntimeError('owned ablation worker closed without a result') from None
                if time.monotonic()>=deadline:
                    raise TimeoutError('stage deadline exhausted')
                if kind == 'case_started':
                    if active is not None or value not in {'initialization',*[c['case_id'] for c in _cases()]}:
                        raise RuntimeError('invalid workflow start')
                    active = value; phase_deadline = min(deadline,time.monotonic()+PER_RUN_WALL_CLOCK_S)
                    parent.send('continue')
                elif kind == 'case_finished':
                    if value != active or active is None:
                        raise RuntimeError('invalid workflow finish')
                    if time.monotonic() >= phase_deadline:
                        raise CaseTimeout(active)
                    active = None; phase_deadline = deadline; parent.send('continue')
                elif kind == 'result':
                    if active is not None:
                        raise RuntimeError('result before workflow finished')
                    return value
                else:
                    raise RuntimeError('invalid ablation worker protocol')
            if not process.is_alive() and not parent.poll():
                raise RuntimeError('owned ablation worker exited without a result')
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=1)
        if process.is_alive():
            process.kill(); process.join(timeout=1)
        parent.close()


def _export_rounds(run, case):
    records = {_read(p)['evaluation_id']: _read(p) for p in (run/'electrothermal-evaluations').glob('*.json')}
    rounds = [_read(p) for p in sorted((run/'mo-rounds').glob('*.json'))]
    rows = []
    for event in rounds:
        record = records[event['evaluation_id']]
        for rate in record['rates']:
            region = event['region'] or {}
            rows.append(dict(case_id=case['case_id'], round=event['context']['ordinal'],
                evaluation_id=record['evaluation_id'], rate=rate['rate'],
                F_U=record['objective_components']['F_U'], F_T=record['objective_components']['F_T'],
                complete_pair=record['complete_pair_valid'], voltage_valid=rate['voltage']['valid'],
                temperature_valid=rate['cell_temperature']['valid'], rmse_v=rate['voltage']['rmse_v'],
                rmse_k=rate['cell_temperature']['rmse_k'], voltage_failure=rate['voltage']['reason'],
                temperature_failure=rate['cell_temperature']['reason'], cached=event['feedback']['cached'],
                selection_changed=region.get('selection_changed', False),
                in_region_count=sum(all(.3 <= v <= .8 for v in x) for x in event['context']['pool']),
                pool_count=len(event['context']['pool'])))
    return rows, records


def _ablation_worker(protocol: dict, output: str, connection) -> None:
    _environment()
    root = Path(output); deadline = protocol['monotonic_deadline']
    results, round_rows, representatives = [], [], []
    stage_started = protocol.get('perf_counter_started', time.perf_counter())
    budget = SoftwareBudget(root/'software-costs.jsonl', max_candidates=protocol['max_software_candidates'],
                            max_rate_calls=protocol['max_software_calls'])
    with SoftwareBoundary() as boundary:
        try:
            from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment, run_electrothermal_experiment
            from llmbo_para.electrothermal_llm import ElectrothermalLLMController
            from llmbo_para.electrothermal_audit import audit_electrothermal_run
            from llmbo_para.scalarization import augmented_tchebycheff
            def check_time():
                if time.monotonic() >= deadline:
                    raise TimeoutError('stage deadline exhausted')
                if any(boundary.counts().values()):
                    raise RuntimeError('zero API/DFN boundary was attempted')
            def audit(run, label):
                check_time()
                with FitObserver(root/'fit-times.jsonl', phase='audit:'+label):
                    result = audit_electrothermal_run(run, deep=True)
                _write(root/'audits'/f'{label}.json', result)
                if not result['passed']:
                    raise RuntimeError('deep audit failed: '+label)
            @contextmanager
            def workflow_phase(label):
                connection.send(('case_started',label))
                if connection.recv()!='continue':
                    raise RuntimeError('invalid workflow start acknowledgement')
                try:
                    yield
                finally:
                    connection.send(('case_finished',label))
                    if connection.recv()!='continue':
                        raise RuntimeError('invalid workflow finish acknowledgement')
            cfg = deepcopy(protocol['base_config'])
            cfg['optimization'].update(mode='warmstart_only', total_candidate_budget=8)
            recovery = protocol.get('recovery')
            if recovery is not None:
                # Recheck the original bytes, screening curves and signatures in
                # this child. No optimizer or evaluator is called for reuse.
                recovery_protocol(protocol['base_config'], recovery)
                cfg['optimization']['initial_plan'] = deepcopy(recovery['initial_plan'])
            cfg['budgets']['wall_clock_s'] = min(PER_RUN_WALL_CLOCK_S, deadline-time.monotonic())
            report, prepared = prepare_electrothermal_experiment(cfg, base_dir=WT)
            if not report['ready']:
                raise ValueError(str(report['errors']))
            if recovery is None:
                controller = ElectrothermalLLMController(transport=FixedSoftwareActions(prepared.space, protocol['fixed_mock_region']), is_mock=True)
                with workflow_phase('initialization'), budget.observe():
                    initial = run_electrothermal_experiment(cfg, root/'init', base_dir=WT, llm_controller=controller)
                init_run = Path(initial['run_directory'])
                plan = init_run/'initial-plan.json'
                spec = dict(path=str(plan.resolve()), sha256=_sha(plan))
                screening_costs = initial['initialization_cost_attribution']
            else:
                spec = deepcopy(recovery['initial_plan']); plan = (WT/spec['path']).resolve(); init_run = plan.parent
                screening_costs = dict(historical_costs=prepared.initial_plan.history_evidence['costs'],
                    included_in_current_costs=False, origin_run_id=prepared.initial_plan.history_evidence['origin_run_id'])
            audit(init_run, 'initialization')
            plan_data = _read(plan)
            initialization_ids = [r['evaluation_id'] for r in plan_data['records']]
            _write(root/'initialization-reference.json', dict(spec=spec, initialization_ids=initialization_ids,
                screening_costs=screening_costs, prior_costs=recovery['prior_costs'] if recovery else
                    dict(new_objective_evaluations=0,software_calls=0)))
            for case in protocol['cases']:
                check_time()
                cfg = make_case_config(protocol['base_config'], **{k:case[k] for k in ('global_pool_size','gp_sweeps','seed','mode')}, initial_plan=spec)
                cfg['budgets']['wall_clock_s'] = min(PER_RUN_WALL_CLOCK_S, deadline-time.monotonic())
                _write(root/'case-configs'/(case['case_id']+'.json'), cfg)
                report, prepared = prepare_electrothermal_experiment(cfg, base_dir=WT)
                if not report['ready']:
                    raise ValueError(str(report['errors']))
                controller = ElectrothermalLLMController(transport=FixedSoftwareActions(prepared.space, protocol['fixed_mock_region']), is_mock=True)
                case_started = time.perf_counter()
                with workflow_phase(case['case_id']), budget.observe(), FitObserver(root/'fit-times.jsonl', phase='BO:'+case['case_id']):
                    result = run_electrothermal_experiment(cfg, case_output_root(root, case), base_dir=WT, llm_controller=controller)
                run = Path(result['run_directory']); audit(run, case['case_id'])
                rows, records = _export_rounds(run, case); round_rows.extend(rows)
                row = dict(**case, status='completed', run_directory=str(run), summary=result,
                    initial_plan_sha256=spec['sha256'], initialization_ids=initialization_ids,
                    source_fingerprint=prepared.signatures.source, comparison_protocol=prepared.signatures.comparison_protocol,
                    audit_passed=True, elapsed_s=time.perf_counter()-case_started)
                results.append(row); _append(root/'run-index.jsonl', row)
                front = result['pareto']
                best = min(front, key=lambda r:(float(augmented_tchebycheff([r['objectives']], [.5,.5], [.1,1.], rho_aug=.05)[0]),
                    tuple(prepared.space.normalize(r['parameters'])), r['evaluation_id']))
                record = records[best['evaluation_id']]
                for rate in record['rates']:
                    representatives.append(dict(case_id=case['case_id'], evaluation_id=best['evaluation_id'],
                        parameters=json.dumps(best['parameters']), F_U=best['objectives'][0], F_T=best['objectives'][1],
                        rate=rate['rate'], rmse_v=rate['voltage']['rmse_v'], rmse_k=rate['cell_temperature']['rmse_k']))
                _write(root/'case-results'/(case['case_id']+'.json'), row)
            result = summarize_numerical_ablation(results)
            result.update(boundary=boundary.counts(), costs=budget.counts(), failure=None)
            if _sha(plan) != spec['sha256']:
                raise ValueError('initialization was mutated')
            _csv(root/'round-RMSE.csv', round_rows); _csv(root/'representative-RMSE.csv', representatives)
            _csv(root/'factorial-contrasts.csv', result['contrasts'])
            _csv(root/'factorial-effects.csv', result['factorial_effects'])
            check_time()
        except Exception as exc:
            result = summarize_numerical_ablation(results)
            result.update(status='incomplete', boundary=boundary.counts(), costs=budget.counts(), failure=type(exc).__name__+': '+str(exc))
            _write(root/'worker-failure.json', result)
        result['elapsed_s'] = time.perf_counter()-stage_started
        prior = protocol.get('recovery',{}).get('prior_costs',dict(new_objective_evaluations=0,software_calls=0))
        result['prior_costs'] = prior
        result['cumulative_costs'] = {k:prior[k]+budget.counts()[k] for k in prior}
        _write(root/'summary.json', result)
        (root/'exit-code.txt').write_text('0\n' if result['status']=='completed' else '1\n', encoding='utf-8')
        files = {}
        for path in sorted(root.rglob('*')):
            if time.monotonic() >= deadline:
                raise TimeoutError('stage sealing deadline exhausted')
            if path.is_file():
                files[path.relative_to(root).as_posix()] = _sha(path)
        _write(root/'stage-a-seal.json', dict(status=result['status'], source_fingerprint=protocol['source_fingerprint'],
            script_sha256=protocol['script_sha256'], files=files, elapsed_s=time.perf_counter()-stage_started))
        connection.send(('result', result))


def _interrupted_costs(root, protocol):
    """Keep the durable cost prefix; a killed writer cannot certify totals."""
    costs = dict(new_objective_evaluations=0, software_calls=0)
    prior = deepcopy(protocol.get('recovery', {}).get('prior_costs', costs))
    limits = dict(new_objective_evaluations=protocol['max_software_candidates'],
                  software_calls=protocol['max_software_calls'])
    issue = None
    try:
        with (root/'software-costs.jsonl').open('rb') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                    counts = {key:event[key] for key in costs}
                    if (event['kind'] not in ('candidate_started','candidate_finished','software_call')
                            or any(type(value) is not int or not costs[key]<=value<=limits[key]
                                   for key,value in counts.items())
                            or counts['software_calls']>2*counts['new_objective_evaluations']):
                        raise ValueError('invalid counters')
                except (UnicodeDecodeError, ValueError, KeyError, TypeError):
                    issue = 'invalid_or_truncated_record'; break
                costs = counts
    except FileNotFoundError:
        issue = 'missing'
    except OSError:
        issue = 'unreadable'
    return dict(costs=costs, prior_costs=prior,
        cumulative_costs={key:prior[key]+costs[key] for key in prior},
        costs_complete=False, costs_attribution='persisted_lower_bound_after_termination', cost_ledger_issue=issue)


def run_software_ablation(base_config: dict, output: Path, *, recovery: dict | None = None) -> dict:
    _environment()
    from llmbo_para.electrothermal_provenance import source_fingerprint
    from llmbo_para.runstore import canonical_json
    protocol = recovery_protocol(base_config,recovery) if recovery is not None else ablation_protocol(base_config)
    root = Path(output).resolve()
    layout = validate_archive_paths(root)
    root.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    deadline = time.monotonic()+STAGE_WALL_CLOCK_S
    protocol.update(dry_run=False, monotonic_deadline=deadline, source_fingerprint=source_fingerprint(),
                    script_sha256=_sha(__file__), archive_paths=layout, perf_counter_started=started)
    _write(root/'protocol.json', protocol)
    try:
        result = _supervise_ablation(_ablation_worker, (protocol, str(root)), deadline=deadline)
        seal = _read(root/'stage-a-seal.json')
        if (seal['status'] != result['status'] or seal['source_fingerprint'] != protocol['source_fingerprint']
                or seal['script_sha256'] != protocol['script_sha256']
                or seal['files']['summary.json'] != _sha(root/'summary.json')
                or canonical_json(_read(root/'summary.json')) != canonical_json(result)):
            raise ValueError('owned worker seal differs')
        return result
    except (RuntimeError, TimeoutError, EOFError, OSError, KeyError, ValueError) as exc:
        rows = [_read(p) for p in sorted((root/'case-results').glob('*.json'))] if (root/'case-results').exists() else []
        result = summarize_numerical_ablation(rows)
        result.update(status='incomplete', boundary=None, failure=type(exc).__name__, **_interrupted_costs(root,protocol))
        if isinstance(exc,CaseTimeout):
            result['timed_out_case'] = exc.case_id
    result['elapsed_s'] = time.perf_counter()-started
    # Do not overwrite a partial worker summary/seal: preserve both accounts.
    _write(root/'supervisor-incomplete.json', result)
    if not (root/'summary.json').exists():
        _write(root/'summary.json', result)
    (root/'supervisor-exit-code.txt').write_text('1\n', encoding='utf-8')
    return result


def main():
    _environment()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-config', type=Path, default=WT/'configs/electrothermal-lgbo-numerical-ablation-software.json')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--recovery-spec', type=Path, help='Strict original initialization and already-used 16/32 costs')
    args = parser.parse_args()
    if args.execute and args.dry_run:
        parser.error('choose either execute or dry-run')
    cfg = _read(args.base_config)
    recovery = _read(args.recovery_spec) if args.recovery_spec is not None else None
    result = (run_software_ablation(cfg, args.output, recovery=recovery) if args.execute else
              recovery_protocol(cfg,recovery) if recovery is not None else ablation_protocol(cfg))
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if not args.execute or result['status']=='completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
