"""Source-isolated worker for the approved LGBO comparison; no new method."""
from copy import deepcopy
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def config_for(base, *, kind, arm, seed, remaining, initial):
    """Copy the frozen template; keep physical data and numerical settings."""
    config = deepcopy(base)
    config['optimization'].update(seed=seed,
        mode='warmstart_only' if arm == 'plain' or kind == 'initialization' else 'full_llmbo_mo')
    if kind == 'initialization':
        config['optimization']['total_candidate_budget'] = 8
    if initial is not None:
        config['optimization']['initial_plan'] = deepcopy(initial)
    config['budgets'] = {'max_solver_calls': 16 if kind == 'initialization' else 40,
                         'max_llm_requests': 20 if kind == 'arm' and arm != 'plain' else 0,
                         'wall_clock_s': float(remaining)}
    config['llm']['enabled'] = config['budgets']['max_llm_requests'] > 0
    return config


def independent_hv(points, reference):
    """Rectangle sweep independent of the production Pareto/HV implementation."""
    rx, ry = reference
    front = sorted({(float(x), float(y)) for x, y in points if x < rx and y < ry})
    area, last_y = 0., ry
    for x, y in front:
        if not all(math.isfinite(v) and v >= 0 for v in (x, y)):
            raise ValueError('invalid metric coordinates')
        if y < last_y:
            area += (rx-x)*(last_y-y)
            last_y = y
    return area


def representative(rows, *, normalize):
    def key(row):
        u, t = row['objectives']
        q = (.5*u/.1, .5*t)
        return (max(q)+.05*math.fsum(q), tuple(normalize(row['parameters'])), row['evaluation_id'])
    return min(rows, key=key)


class RPCBudget:
    def __init__(self, connection, *, deadline, maximum, prefix):
        self.connection, self.deadline = connection, deadline
        self.maximum, self.prefix = maximum, prefix
        self.calls = 0

    def _call(self, kind, value):
        if time.monotonic() >= self.deadline:
            raise TimeoutError('global experiment deadline exhausted')
        self.connection.send((kind, value))
        response, _ = self.connection.recv()
        if response != 'ok':
            raise RuntimeError('parent denied budget authorization')

    def require_candidate(self, calls):
        if self.calls + calls > self.maximum:
            raise RuntimeError('scoped solver budget exhausted')
        self._call('require', calls)

    def before_solve(self):
        self.require_candidate(1)
        self._call('charge', ('DFN', self.prefix + ':solve:' + str(self.calls+1)))
        self.calls += 1

    def charge_api(self, ident):
        self._call('charge', ('API', self.prefix + ':api:' + ident))


def prepare_preflight(base_dir, *, config_root=None):
    """Fresh genuine software context; never replace identities with fixtures."""
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.scalarization import build_scalarization_context
    from llmbo_para.surrogate import Matern52GP
    from llmbo_para.mo_optimizer import MORoundContext
    from llmbo_para.sobol import Sobol6
    from llmbo_para.runstore import canonical_json, digest_value
    from llmbo_para.electrothermal_lgbo_wire import lgbo_wire_payload
    from llmbo_para.electrothermal_responses import responses_request_body
    root = Path(config_root) if config_root is not None else Path('C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para')
    cfg = read(root/'configs/electrothermal-lgbo-numerical-ablation-software.json')
    cfg['optimization']['region_method'] = 'lgbo_v2'
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=base_dir)
    if prepared is None:
        raise ValueError('software preflight context configuration failed')
    evaluator = ElectrothermalEvaluator(prepared.space, SyntheticElectrothermalSimulator(), fit_rates=prepared.dataset.fit_rates)
    history = [evaluator.evaluate(prepared.space.denormalize([v]*6), prepared.dataset) for v in (.2, .8)]
    scalar = build_scalarization_context([prepared.space.normalize(r.parameters) for r in history],
        [r.objectives for r in history], [r.evaluation_id for r in history],
        weights=(.8, .2), objective_scales=(.1, 1.), rho_aug=.05,
        protocol_signature=prepared.signatures.comparison_protocol)
    gp = Matern52GP(max_sweeps=4).fit(scalar.x, scalar.labels, group=())
    pool = tuple(tuple(map(float, x)) for x in Sobol6(1).draw(32))
    state = gp.state_dict()
    data = {'scalarization': scalar.to_dict(), 'fit_rates': prepared.dataset.fit_rates,
            'signatures': asdict(prepared.signatures), 'gp_state': state, 'pool': pool, 'ordinal': 1}
    context = MORoundContext(scalar, prepared.dataset.fit_rates,
        canonical_json(asdict(prepared.signatures)).decode(), canonical_json(state).decode(),
        pool, 1, digest_value(data))
    payload = build_electrothermal_payload('region_preference_electrothermal',
        prepared=prepared, history=history, context=context)
    payload['artifact_task'] = 'region_preference_electrothermal_preflight'
    body = responses_request_body(lgbo_wire_payload(payload), model='deepseek-v4-pro', max_tokens=8192, json_mode=True)
    return payload, body


def preflight(spec, budget):
    from llmbo_para.runstore import RunStore, canonical_json
    from llmbo_para.electrothermal_responses import BoundedResponsesTransport, decode_responses_json
    from llmbo_para.electrothermal_region_wire import decode_region_wire
    from llmbo_para.electrothermal_lgbo import validate_lgbo_region
    from run_lgbo_real_gain import check_payload
    payload, body = prepare_preflight(spec['source_root'], config_root=spec['source_root'])
    check_payload(payload)
    store = RunStore(spec['output'], {'kind': 'real_API_software_context_contract_only',
        'source': spec['source'], 'protocol_sha256': spec['protocol_sha']}, command='bounded LGBO v2 API preflight')
    store.write_json('source-execution-pin.json', {'source_root': spec['source_root'],
        'source_fingerprint': spec['source'], 'approved_commit': spec.get('source_commit')})
    store.write_json('frozen-payload.json', payload)
    store.write_json('frozen-request-body.json', body)
    transport = BoundedResponsesTransport('https://sidrune.ai/v1/responses', 'SUB2API_API_KEY',
        model='deepseek-v4-pro', max_tokens=8192, json_mode=True,
        timeout_s=120., run_store=store)
    budget.charge_api('preflight')
    try:
        formal = transport.post(payload, deadline=budget.deadline)
        task = payload['artifact_task']
        request = read(store.path/'http'/f'{task}.request.json')
        raw = read(store.path/'http'/f'{task}.response.json')
        decoded, issue = decode_responses_json(raw)
        if issue is not None:
            raise ValueError('preflight completion invalid')
        restored = decode_region_wire(decoded, payload)
        validate_lgbo_region(formal, expected_context_id=payload['context_id'],
            expected_signatures=payload['signatures'], expected_region_method='lgbo_v2')
        diagnostic = transport.last_request_diagnostic
        if (canonical_json(request['body']) != canonical_json(body)
                or canonical_json(restored) != canonical_json(formal)
                or request['endpoint'] != 'https://sidrune.ai/v1/responses'
                or diagnostic.get('http_status') != 200 or not diagnostic.get('http_request_started')):
            raise ValueError('preflight raw/formal/body/supervision mismatch')
        result = {'passed': True, 'actual_request': True, 'status': 'completed',
                  'region_kind': formal['region']['kind'], 'run_directory': str(store.path),
                  'diagnostic': diagnostic, 'software_context_only': True,
                  'software_fixture_evaluations': 2, 'software_fixture_rate_calls': 4}
        store.write_json('preflight-proof.json', result)
        store.finish('completed', result)
        return result
    except Exception as exc:
        store.finish('failed', {'error_type': type(exc).__name__,
                               'diagnostic': transport.last_request_diagnostic})
        raise


def _attach_api_charges(store, budget):
    original = store.ledger.record
    def record(event):
        if event['kind'] == 'llm_request' and event['event_id'] not in store.ledger.events:
            budget.charge_api(store.run_id + ':' + event['event_id'])
        return original(event)
    store.ledger.record = record


def _controller(prepared, budget, *, software_fixture=False):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from run_lgbo_real_gain import check_payload
    class CheckedController(ElectrothermalLLMController):
        def request(self, payload, **kwargs):
            check_payload(payload)
            response = super().request(payload, **kwargs)
            outcome = self.last_request_outcome or {}
            if permanent_api_failure(outcome):
                raise RuntimeError('nonrecoverable API authentication/model error')
            return response
    class NoneReply:
        def post(self, payload):
            from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id
            return {'request_id': lgbo_request_id(payload), 'region': {'kind': 'none'}}
    controller = CheckedController(transport=NoneReply() if software_fixture else None, is_mock=software_fixture)
    controller.prepared, controller.execution_budget = prepared, budget
    return controller


def permanent_api_failure(outcome):
    # Provider free text is intentionally absent from public diagnostics.
    # Stop conservatively for missing/unsupported model routes and channels.
    return outcome.get('http_status') in (401, 403, 404, 503)


def initialization(spec, prepared, store, budget, backend):
    from inspect import signature
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    from llmbo_para.electrothermal_provenance import write_initial_plan, load_initial_plan
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    evaluator = ElectrothermalEvaluator(prepared.space, backend,
        fit_rates=prepared.dataset.fit_rates, max_rate_attempts=1)
    records = []
    for point in spec['coordinates']:
        budget.require_candidate(0 if spec.get('software_fixture') else 2)
        record = evaluator.evaluate(point, prepared.dataset)
        store.save_evaluation(record, phase='fresh_fixed_initialization')
        records.append(replace(record, signatures=asdict(prepared.signatures)))
    if len(records) != 8 or any(not r.complete_pair_valid for r in records):
        raise ValueError('fresh initialization requires eight complete pairs')
    selection_rule = prepared.config['optimization']['warmstart'].get('selection_rule', 'pareto_maximin_v1')
    if type(selection_rule) is not str or selection_rule not in ('pareto_maximin_v1', 'pareto_core_spacefill_v2'):
        raise ValueError('invalid warmstart.selection_rule')
    selection_options = {'space': prepared.space, 'count': 8,
                         'objective_scales': (.1, 1.), 'rho_aug': .05}
    if 'rule' in signature(warmstart_selection_details).parameters:
        selection_options['rule'] = selection_rule
    elif selection_rule != 'pareto_maximin_v1':
        raise ValueError('old source only supports pareto_maximin_v1')
    details = warmstart_selection_details(records, **selection_options)
    by_id = {r.evaluation_id: r for r in records}
    selected = [by_id[ident] for ident in details['selected_ids']]
    evidence = {'origin_run_id': store.run_id, 'screening_records': [r.to_dict() for r in records],
                'selection': details, 'cost_events': list(store.ledger.events.values()), 'costs': store.ledger.summary()}
    path = store.path/'initial-plan.json'
    write_initial_plan(path, selected, signatures=prepared.signatures, history_evidence=evidence)
    plan_options = {'space': prepared.space, 'dataset': prepared.dataset,
                    'signatures': prepared.signatures}
    if 'expected_selection_rule' in signature(load_initial_plan).parameters:
        plan_options['expected_selection_rule'] = selection_rule
    elif selection_rule != 'pareto_maximin_v1':
        raise ValueError('old source only supports pareto_maximin_v1')
    load_initial_plan(path, **plan_options)
    result = {'status': 'completed', 'candidate_count': 8, 'costs': store.ledger.summary(),
              'run_directory': str(store.path), 'plan_path': str(path),
              'ordered_records': [r.to_dict() for r in selected]}
    store.write_json('electrothermal-summary.json', result)
    store.finish('completed', result)
    audit = audit_electrothermal_run(store.path, deep=True)
    write(Path(spec['output'])/'audit.json', audit)
    if not audit['passed']:
        raise ValueError('fresh initialization deep audit failed')
    result['audit_passed'] = True
    return result


def arm(spec, prepared, store, budget, backend):
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.mo_optimizer import MOOptimizer
    from llmbo_para.runstore import sha256_file
    evaluator = ElectrothermalEvaluator(prepared.space, backend, fit_rates=prepared.dataset.fit_rates, max_rate_attempts=1)
    source = Path(spec['initial']['path'])
    destination = store.path/'inputs/initial-plan.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    controller = _controller(prepared, budget, software_fixture=spec.get('software_fixture', False)) if spec['arm'] != 'plain' else None
    optimizer = MOOptimizer(prepared.space, evaluator, prepared.dataset, store,
        prepared.config['optimization'], initial_plan=prepared.initial_plan,
        llm_controller=controller, execution_budget=budget)
    result = optimizer.optimize(28)
    evidence = prepared.initial_plan.history_evidence
    result['initial_plan_sha256'] = prepared.initial_plan.plan_sha256
    result['initialization_cost_attribution'] = {'origin_run_id': evidence['origin_run_id'],
        'historical_costs': evidence['costs'], 'included_in_current_costs': False,
        'plan_sha256': prepared.initial_plan.plan_sha256, 'status': 'verified_history'}
    store.write_json('electrothermal-summary.json', result)
    store.finish('completed', result)
    audit = audit_electrothermal_run(store.path, deep=True)
    write(Path(spec['output'])/'audit.json', audit)
    if not audit['passed']:
        raise ValueError('arm deep audit failed')
    records = {r['evaluation_id']: r for r in [read(p) for p in sorted((store.path/'electrothermal-evaluations').glob('*.json'))]}
    point = representative(result['pareto'], normalize=prepared.space.normalize)
    all_pairs = [r['objectives'] for r in records.values() if r['complete_pair_valid']]
    hv = independent_hv([[u/.1, t] for u, t in all_pairs], [10., 10.])
    if not math.isclose(hv, result['HV'], rel_tol=1e-12, abs_tol=1e-10):
        raise ValueError('independent HV differs')
    rounds = [read(p) for p in sorted((store.path/'mo-rounds').glob('*.json'))]
    exported = []
    for event in rounds:
        record = records[event['evaluation_id']]
        region = event.get('region') or {}
        exported.append({'ordinal': event['context']['ordinal'], 'evaluation_id': record['evaluation_id'],
            'objectives': record['objectives'], 'complete_pair_valid': record['complete_pair_valid'],
            'cached': event['feedback']['cached'], 'region': {k: region.get(k) for k in
                ('selection_changed', 'fallback_reason', 'request_outcome')},
            'rates': [{k: row[k] for k in ('rate', 'voltage', 'cell_temperature', 'solution_id')} for row in record['rates']]})
    first = rounds[0]['context']
    from llmbo_para.runstore import digest_value
    return {'status': 'completed', 'completed': True, 'audit_passed': True, 'seed': spec['seed'], 'arm': spec['arm'],
        'BO_rounds': result['BO_rounds'], 'HV': hv, 'F_U': point['objectives'][0], 'F_T': point['objectives'][1],
        'representative': records[point['evaluation_id']], 'summary': result, 'rounds': exported,
        'initial_file_sha': sha256_file(source), 'source': prepared.signatures.source,
        'first_numerical_context_sha': digest_value({k: first[k] for k in ('scalarization', 'gp_state', 'pool')}),
        'run_directory': str(store.path)}


def run_worker(spec, connection):
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
    sys.dont_write_bytecode = True
    source_root = Path(spec['source_root']).resolve()
    # No llmbo import occurs before this point in a fresh spawned worker.
    if any(name == 'llmbo_para' or name.startswith('llmbo_para.') for name in sys.modules):
        raise RuntimeError('worker source namespace was populated before source selection')
    sys.path.insert(0, str(source_root/'src'))
    store = None
    try:
        import llmbo_para.electrothermal_provenance as provenance
        if Path(provenance.__file__).resolve() != source_root/'src/llmbo_para/electrothermal_provenance.py' or provenance.source_fingerprint(source_root) != spec['source']:
            raise ValueError('worker imports or actual source bytes differ')
        budget = RPCBudget(connection, deadline=spec['deadline'], maximum=spec['solve_cap'], prefix=spec['label'])
        if spec['kind'] == 'preflight':
            result = preflight(spec, budget)
        else:
            from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment, make_electrothermal_backend
            from llmbo_para.electrothermal_store import ElectrothermalRunStore
            cfg = config_for(spec['base_config'], kind=spec['kind'], arm=spec['arm'], seed=spec['seed'],
                remaining=max(.001, budget.deadline-time.monotonic()), initial=spec.get('initial'))
            if spec.get('software_fixture'):
                cfg['model']['provider'] = 'software'
                cfg['run_kind'] = 'synthetic_software'
                cfg['llm']['enabled'] = False
                cfg['budgets']['max_solver_calls'] = cfg['budgets']['max_llm_requests'] = 0
            report, prepared = prepare_electrothermal_experiment(cfg, base_dir=source_root)
            if prepared is None:
                raise ValueError('source-specific preparation failed: ' + '; '.join(report['errors']))
            backend = make_electrothermal_backend(cfg, budget=budget)
            store = ElectrothermalRunStore(spec['output'], cfg, dataset=prepared.dataset,
                signatures=prepared.signatures, command='electrothermal multiobjective BO' if spec['kind'] == 'arm' else 'electrothermal bounded fixed initialization')
            store.write_json('source-execution-pin.json', {'source_root': str(source_root),
                'source_fingerprint': spec['source'], 'approved_commit': spec.get('source_commit'),
                'note': 'Scientific source is this verified snapshot; enclosing host Git metadata may identify its containing repository.'})
            _attach_api_charges(store, budget)
            result = initialization(spec, prepared, store, budget, backend) if spec['kind'] == 'initialization' else arm(spec, prepared, store, budget, backend)
        write(Path(spec['output'])/'worker-result.json', result)
        connection.send(('result', result))
    except Exception as exc:
        failure = {'status': 'failed', 'error_type': type(exc).__name__, 'label': spec['label']}
        if store is not None and not (store.path/'terminal.json').exists():
            store.finish('failed', failure)
        write(Path(spec['output'])/'worker-failure.json', failure)
        connection.send(('error', type(exc).__name__))
    finally:
        connection.close()
