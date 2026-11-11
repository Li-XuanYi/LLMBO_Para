"""Supervise zero-API classical baseline rehearsals and DFN comparisons."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--software', action='store_true')
    mode.add_argument('--execute', action='store_true')
    parser.add_argument('--factorial-root', type=Path, required=True)
    parser.add_argument('--policy-python', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=10)
    parser.add_argument('--seed-count', type=int, default=5, choices=range(1, 6))
    parser.add_argument('--software-proof', type=Path)
    args = parser.parse_args()
    if args.rounds < 1:
        raise ValueError('positive rounds required')
    if args.execute and args.software_proof is None:
        raise ValueError('software proof required')
    if args.execute and (args.rounds != 50 or args.seed_count != 5):
        raise ValueError('real comparison requires five seeds and fifty rounds')
    for k in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[k] = '1'
    os.environ['PYBAMM_DISABLE_TELEMETRY'] = 'true'
    sys.path.insert(0, str(ROOT/'src'))
    import et_classical_worker as worker
    import run_lgbo_real_gain as helper
    import analyze_et_classical_validation as analyzer
    from et_factorial_budget import FactorialBudget, atomic_json
    from llmbo_para.electrothermal_provenance import source_fingerprint
    old = json.loads((args.factorial_root/'result.json').read_text(encoding='utf8'))
    template = json.loads((args.factorial_root/'template.json').read_text(encoding='utf8'))
    seeds = old['seeds'][:args.seed_count]
    names = ['scripts/et_classical_worker.py','scripts/et_classical_policy.py',
             'scripts/analyze_et_classical_validation.py','scripts/run_et_classical_validation.py',
             'scripts/run_lgbo_real_gain.py','scripts/et_factorial_budget.py',
             'scripts/lgbo_real_gain_worker.py','scripts/analyze_et_factorial_validation.py']
    def filehash(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    def pins_now():
        package = args.policy_python.resolve().parent.parent/'Lib/site-packages/jmetal'
        return {'scientific_source': source_fingerprint(ROOT),
                'scripts': {n:filehash(ROOT/n) for n in names},
                'policy_python': filehash(args.policy_python),
                'jmetal_sources': {str(p.relative_to(package)):filehash(p) for p in sorted(package.rglob('*.py'))},
                'template':filehash(args.factorial_root/'template.json'),
                'factorial_result':filehash(args.factorial_root/'result.json')}
    pins = pins_now()
    if not pins['jmetal_sources']: raise ValueError('policy jmetal installation missing')
    if args.execute:
        proof = json.loads((args.software_proof/'result.json').read_text(encoding='utf8'))
        proof_pins = json.loads((args.software_proof/'source-pins.json').read_text(encoding='utf8'))
        if proof_pins != pins or proof['status'] != 'completed' or proof['rounds'] != 10 or proof['counts'] != {'DFN':0,'API':0}:
            raise ValueError('software proof or source differs')
        expected = {(s['seed'],m) for s in seeds for m in worker.METHODS}
        if {(x['seed'],x['method']) for x in proof['phases']} != expected or len(proof['phases']) != 15:
            raise ValueError('software proof phases differ')
        for x in proof['phases']:
            if x['status'] != 'completed' or not x['audit_passed']:
                raise ValueError('software proof phase failed')
            if x['method'] != 'parego16' and not analyzer.audit_external(x['run_directory'],expected_rounds=10)['passed']:
                raise ValueError('software external replay failed')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output/'source-pins.json',pins)
    protocol = {'mode': 'software' if args.software else 'real_DFN_synthetic', 'rounds': args.rounds,
                'seeds': [s['seed'] for s in seeds], 'methods': list(worker.METHODS)}
    atomic_json(output/'protocol.json', protocol)
    digest = hashlib.sha256((output/'protocol.json').read_bytes()).hexdigest()
    phases = {f"{s['seed']}-{m}": {'DFN': 0 if args.software else 2*args.rounds, 'API': 0} for s in seeds for m in worker.METHODS}
    budget = FactorialBudget.start(output/'budget.jsonl', phases=phases, protocol_sha=digest)
    result = {'status': 'running', 'rounds': args.rounds, 'phases': [], 'counts': budget.counts()}
    atomic_json(output/'result.json', result)
    for seed in seeds:
        for method in worker.METHODS:
            label = f"{seed['seed']}-{method}"
            phase_dir = output/label
            phase_dir.mkdir()
            budget.begin(label)
            spec = {'method': method, 'seed': seed['seed'], 'rounds': args.rounds,
                    'pool': seed['pools']['numeric'], 'base_config': template, 'software_fixture': args.software,
                    'source_root': str(ROOT), 'source': source_fingerprint(ROOT), 'output': str(phase_dir),
                    'policy_python': str(args.policy_python.resolve()), 'policy_environment': {'mode': 'software'},
                    'label': label, 'deadline': budget.deadline}
            try:
                def integrity():
                    if pins_now() != pins: raise ValueError('pinned source or dependencies changed')
                value = helper.supervise(worker.run_worker, spec, budget, deadline=budget.deadline,
                                         metadata=output/(label+'-owned.json'),integrity_check=integrity)
                if method != 'parego16':
                    verification = analyzer.audit_external(value['run_directory'],expected_rounds=args.rounds)
                    if not verification['passed']:raise ValueError('external audit failed: '+verification['reason'])
                    value['external_audit'] = verification
                budget.finish(True)
            except Exception as exc:
                budget.finish(False)
                value = {'status': 'failed', 'seed': seed['seed'], 'method': method,
                         'rounds': args.rounds, 'error': str(exc)}
            result['phases'].append(value)
            result['counts'] = budget.counts()
            atomic_json(output/'result.json', result)
            print(json.dumps(value), flush=True)
    result['status'] = 'completed' if all(x['status'] == 'completed' for x in result['phases']) else 'completed_with_failures'
    atomic_json(output/'result.json', result)
    return 0 if result['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
