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
import os
from pathlib import Path
import socket
import sys
import time

WT = Path(__file__).resolve().parents[1]
STAGE_WALL_CLOCK_S = 3600
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
        wall_clock_s=STAGE_WALL_CLOCK_S, per_run_wall_clock_s=120,
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
        if hv is not None and (type(hv) not in (int, float) or not math.isfinite(hv)):
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
    started = time.perf_counter()
    budget = SoftwareBudget(root/'software-costs.jsonl', max_candidates=496, max_rate_calls=992)
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
            cfg = deepcopy(protocol['base_config'])
            cfg['optimization'].update(mode='warmstart_only', total_candidate_budget=8)
            cfg['budgets']['wall_clock_s'] = min(120., deadline-time.monotonic())
            report, prepared = prepare_electrothermal_experiment(cfg, base_dir=WT)
            if not report['ready']:
                raise ValueError(str(report['errors']))
            controller = ElectrothermalLLMController(transport=FixedSoftwareActions(prepared.space, protocol['fixed_mock_region']), is_mock=True)
            with budget.observe():
                initial = run_electrothermal_experiment(cfg, root/'initialization', base_dir=WT, llm_controller=controller)
            init_run = Path(initial['run_directory']); audit(init_run, 'initialization')
            plan = init_run/'initial-plan.json'; plan_data = _read(plan)
            spec = dict(path=str(plan.resolve()), sha256=_sha(plan))
            initialization_ids = [r['evaluation_id'] for r in plan_data['records']]
            _write(root/'initialization-reference.json', dict(spec=spec, initialization_ids=initialization_ids,
                screening_costs=initial['initialization_cost_attribution']))
            for case in protocol['cases']:
                check_time()
                cfg = make_case_config(protocol['base_config'], **{k:case[k] for k in ('global_pool_size','gp_sweeps','seed','mode')}, initial_plan=spec)
                cfg['budgets']['wall_clock_s'] = min(120., deadline-time.monotonic())
                _write(root/'case-configs'/(case['case_id']+'.json'), cfg)
                report, prepared = prepare_electrothermal_experiment(cfg, base_dir=WT)
                if not report['ready']:
                    raise ValueError(str(report['errors']))
                controller = ElectrothermalLLMController(transport=FixedSoftwareActions(prepared.space, protocol['fixed_mock_region']), is_mock=True)
                started = time.perf_counter()
                with budget.observe(), FitObserver(root/'fit-times.jsonl', phase='BO:'+case['case_id']):
                    result = run_electrothermal_experiment(cfg, root/'cases'/case['case_id'], base_dir=WT, llm_controller=controller)
                run = Path(result['run_directory']); audit(run, case['case_id'])
                rows, records = _export_rounds(run, case); round_rows.extend(rows)
                row = dict(**case, status='completed', run_directory=str(run), summary=result,
                    initial_plan_sha256=spec['sha256'], initialization_ids=initialization_ids,
                    source_fingerprint=prepared.signatures.source, comparison_protocol=prepared.signatures.comparison_protocol,
                    audit_passed=True, elapsed_s=time.perf_counter()-started)
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
        result['elapsed_s'] = time.perf_counter()-started
        _write(root/'summary.json', result)
        (root/'exit-code.txt').write_text('0\n' if result['status']=='completed' else '1\n', encoding='utf-8')
        files = {}
        for path in sorted(root.rglob('*')):
            if time.monotonic() >= deadline:
                raise TimeoutError('stage sealing deadline exhausted')
            if path.is_file():
                files[path.relative_to(root).as_posix()] = _sha(path)
        _write(root/'stage-a-seal.json', dict(status=result['status'], source_fingerprint=protocol['source_fingerprint'],
            script_sha256=protocol['script_sha256'], files=files, elapsed_s=time.perf_counter()-started))
        connection.send(('result', result))


def run_software_ablation(base_config: dict, output: Path) -> dict:
    _environment()
    from llmbo_para.electrothermal_execution import run_with_deadline
    from llmbo_para.electrothermal_provenance import source_fingerprint
    protocol = ablation_protocol(base_config)
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    deadline = time.monotonic()+STAGE_WALL_CLOCK_S
    protocol.update(dry_run=False, monotonic_deadline=deadline, source_fingerprint=source_fingerprint(),
                    script_sha256=_sha(__file__))
    _write(root/'protocol.json', protocol)
    started = time.perf_counter()
    try:
        result = run_with_deadline(_ablation_worker, (protocol, str(root)), deadline=deadline,
                                   on_solve_start=lambda: (_ for _ in ()).throw(RuntimeError('unexpected real solve/API')))
        seal = _read(root/'stage-a-seal.json')
        if (seal['status'] != result['status'] or seal['source_fingerprint'] != protocol['source_fingerprint']
                or seal['script_sha256'] != protocol['script_sha256']
                or seal['files']['summary.json'] != _sha(root/'summary.json')
                or _read(root/'summary.json') != result):
            raise ValueError('owned worker seal differs')
        return result
    except (RuntimeError, TimeoutError, EOFError, OSError, KeyError, ValueError) as exc:
        rows = [_read(p) for p in sorted((root/'case-results').glob('*.json'))] if (root/'case-results').exists() else []
        result = summarize_numerical_ablation(rows)
        result.update(status='incomplete', boundary=None, failure=type(exc).__name__)
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
    args = parser.parse_args()
    if args.execute and args.dry_run:
        parser.error('choose either execute or dry-run')
    cfg = _read(args.base_config)
    result = run_software_ablation(cfg, args.output) if args.execute else ablation_protocol(cfg)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 0 if not args.execute or result['status']=='completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
