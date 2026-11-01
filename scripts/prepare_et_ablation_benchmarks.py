"""Prepare disabled factorial/benchmark inputs. This entry has no live-run mode."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
SELECTION = 'pareto_quality_gated_spacefill_v3'
EXCLUDED_SEEDS = (376330, 633262, 789058, 609653, 362724, 260437, 152325,
                  947445, 235695, 299924, 659578, 564327, 336546, 769762, 465948)
ARMS = (
    {'id': 'A00', 'label': 'BO', 'warmstart': False, 'region': False, 'mode': 'parego', 'initialization_group': 'numeric'},
    {'id': 'A10', 'label': 'BO+WarmStart(v3)', 'warmstart': True, 'region': False, 'mode': 'warmstart_only', 'initialization_group': 'llm_v3'},
    {'id': 'A01', 'label': 'BO+Region', 'warmstart': False, 'region': True, 'mode': 'full_llmbo_mo', 'initialization_group': 'numeric'},
    {'id': 'A11', 'label': 'LLMBO(v3+Region)', 'warmstart': True, 'region': True, 'mode': 'full_llmbo_mo', 'initialization_group': 'llm_v3'},
)
BASELINES = {
    'B0': {'label': 'Sobol', 'family': 'space_filling', 'adapter_status': 'evaluation_wrapper_required'},
    'B1': {'label': 'ParEGO-16', 'family': 'classical_mobo', 'adapter_status': 'initialization_wrapper_required'},
    'B2': {'label': 'NSGA-II-steady-state', 'family': 'classical_evolution', 'adapter_status': 'not_implemented', 'population_size': 16, 'offspring': 1},
    'B3': {'label': 'MOEA/D', 'family': 'classical_decomposition', 'adapter_status': 'not_implemented', 'population_size': 16, 'neighbors': 5},
    'B4': {'label': 'qLogNEHVI', 'family': 'modern_mobo', 'adapter_status': 'not_implemented', 'q': 1},
    'B5': {'label': 'multiobjective-JES', 'family': 'modern_information_mobo', 'adapter_status': 'not_implemented', 'q': 1},
}


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf8')).hexdigest()


def build_design(template: dict, *, template_path: str, replicates: int = 5,
                 rounds: int = 10) -> dict:
    """Produce a new protocol; copying inputs never enables requests or solves."""
    if type(replicates) is not int or replicates not in (5, 10) or type(rounds) is not int or rounds not in (10, 50):
        raise ValueError('supported designs are 5/10 seeds and 10/50 rounds')
    if str(ROOT/'src') not in sys.path:
        sys.path.insert(0, str(ROOT/'src'))
    from llmbo_para.electrothermal_config import electrothermal_configuration_errors
    from llmbo_para.scalarization import WeightScheduler

    errors = electrothermal_configuration_errors(template)
    if errors:
        raise ValueError('invalid template: ' + '; '.join(errors))
    if template['parameter_profile'] != 'electrothermal_4e2t' or template['fit_rates'] != ['0.5C', '1C']:
        raise ValueError('this short synthetic design requires explicit 0.5C/1C 4E+2T inputs')
    if template['run_kind'] not in ('synthetic_dfn', 'synthetic_software'):
        raise ValueError('measured experiment is outside this design')
    if template['optimization']['objective_scales'] != [.1, 1.] or template['optimization']['hv_reference'] != [10., 10.]:
        raise ValueError('fixed metric space differs')
    rng = random.Random(20261101)
    seeds = []
    while len(seeds) < 10:
        seed = rng.randrange(100000, 1000000)
        if seed not in EXCLUDED_SEEDS and seed not in seeds:
            seeds.append(seed)
    selected = seeds[:replicates]
    factor_orders = [('A00','A10','A11','A01'), ('A10','A01','A00','A11'),
                     ('A01','A11','A10','A00'), ('A11','A00','A01','A10')]
    baseline_order = list(BASELINES)
    rng.shuffle(baseline_order)
    arms = [{**deepcopy(arm), 'initial_plan_required': True,
             'training_initial_count': 8, 'initial_evaluation_count': 16} for arm in ARMS]
    methods = {key: {**deepcopy(value), 'initialization_group': 'numeric_all16',
                     'training_initial_count': 16, 'initial_evaluation_count': 16}
               for key, value in BASELINES.items()}
    methods['A11'] = {'label': 'LLMBO(v3+Region)', 'reuse_ablation_arm': 'A11',
                      'training_initial_count': 8, 'initial_evaluation_count': 16}
    rates = len(template['fit_rates'])
    ablation = replicates * (32 + 4*rounds) * rates
    extra = replicates * len(BASELINES) * rounds * rates
    api = replicates * (3 + 2*rounds)
    schedules = {}
    for seed in selected:
        scheduler = WeightScheduler(template['optimization']['weights'], seed)
        schedules[str(seed)] = [list(scheduler.next()) for _ in range(rounds)]
    protocol = {
        'schema_version': 1, 'experiment_id': 'et-factorial-benchmarks-20261101',
        'status': 'design_prepared_live_disabled',
        'source_spec': 'docs/superpowers/specs/2026-11-01-ablation-and-benchmark-design.md',
        'template_path': str(template_path), 'template_semantic_sha256': digest(template),
        'selection_rule': SELECTION, 'region_method': 'lgbo_v2',
        'screening_seeds': seeds[:5], 'confirmation_seeds': seeds[5:],
        'active_seeds': selected, 'excluded_seeds': list(EXCLUDED_SEEDS),
        'fit_rates': list(template['fit_rates']), 'post_initial_rounds': rounds,
        'ablation_arms': arms, 'baseline_methods': methods,
        'ablation_order': {str(seed): list(factor_orders[i % 4]) for i, seed in enumerate(selected)},
        'baseline_order': {str(seed): baseline_order[i % 6:] + baseline_order[:i % 6] for i, seed in enumerate(selected)},
        'weight_schedule_by_seed': schedules,
        'sobol_streams': {str(seed): {'numeric_start': seed*1024, 'fill_start': seed*1024+256,
                                     'baseline_start': seed*1024+512} for seed in selected},
        'initial_pools': {'numeric': {'evaluations': 16, 'source': 'sobol6_indexed_block_v1', 'selected_gp_count': 8},
                          'llm_v3': {'evaluations': 16, 'source': 'llm_then_sobol_fill_v1', 'selected_gp_count': 8,
                                     'max_requests': 3, 'max_proposals': 48, 'max_fill_proposals': 128}},
        'metrics': {'rounds': list(range(11)), 'checkpoints': [0,1,3,5,10,20,50],
                    'primary': 'trapezoid_mean_HV_0_10', 'objective_scales': [.1,1.],
                    'minimization_reference': [10.,10.],
                    'initial_metric_archive': 'all_16_complete_evaluated_candidates',
                    'representative': {'weights': [.5,.5], 'ideal': [0.,0.], 'rho_aug': .05,
                                       'same_parameters_for_both_RMSE': True},
                    'replicate_unit': 'paired_seed', 'failed_curve': 'right_censored_not_zero_filled'},
        'resource_estimate': {'ablation_DFN': ablation, 'API': api, 'baseline_extra_DFN': extra,
                              'combined_DFN': ablation+extra,
                              'includes_shared_initial_pools': True,
                              'observation_generation_DFN': 0},
        'live_authorization': {'API': 0, 'DFN': 0},
        'required_before_live': ['signed_initial_plans','actual_source_and_runtime_freeze',
                                 'absolute_deadline_and_cumulative_budget','verified_four_arm_worker',
                                 'verified_external_adapters_and_actual_dependency_lock'],
    }
    configs, jobs, initialization_jobs = {}, [], []
    for seed in selected:
        for group, arms_using in (('numeric',['A00','A01','B0','B1','B2','B3','B4','B5']),
                                  ('llm_v3',['A10','A11'])):
            initialization_jobs.append({'seed': seed, 'group': group, 'candidate_evaluation_cap': 16,
                                        'request_cap': 3 if group=='llm_v3' else 0,
                                        'reused_by': arms_using, 'status': 'worker_required'})
        for arm in arms:
            config = deepcopy(template)
            config['optimization'].update(seed=seed, mode=arm['mode'], initial_count=8,
                                           total_candidate_budget=8+rounds, region_method='lgbo_v2')
            config['optimization'].pop('initial_plan', None)
            config['optimization']['warmstart'].update(count=8, pool_size=16, max_requests=3,
                                                        max_candidates=48, max_evaluations=16, selection_rule=SELECTION)
            config['budgets'] = {'max_solver_calls': 0, 'max_llm_requests': 0, 'wall_clock_s': 28800}
            config['llm']['enabled'] = False
            config['llm']['warmstart_preheader_tls_eof_continue'] = False
            if electrothermal_configuration_errors(config):
                raise ValueError('derived blueprint failed configuration validation')
            name = f'seed-{seed}-{arm["id"]}.disabled.json'
            configs[name] = config
            jobs.append({'seed': seed, 'arm': arm['id'], 'panel': 'ablation',
                         'config': 'configs/'+name, 'initialization_group': arm['initialization_group'],
                         'status': 'initial_plan_binding_and_worker_required',
                         'region_enabled_in_live_plan': arm['region'],
                         'logical_initial_evaluations': 16, 'new_evaluations': rounds})
        for key in BASELINES:
            jobs.append({'seed': seed, 'arm': key, 'panel': 'external_baselines',
                         'initialization_group': 'numeric_all16', 'settings': deepcopy(methods[key]),
                         'status': methods[key]['adapter_status'],
                         'logical_initial_evaluations': 16, 'new_evaluations': rounds})
    return {'protocol': protocol, 'configs': configs, 'jobs': jobs,
            'initialization_jobs': initialization_jobs, 'template': deepcopy(template)}


def write_bundle(bundle: dict, output: Path) -> dict:
    """Exclusive new output; templates and old archives are never overwritten."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'configs').mkdir()
    files = {'protocol.json': bundle['protocol'], 'jobs.json': bundle['jobs'],
             'initialization-jobs.json': bundle['initialization_jobs'],
             'template.snapshot.json': bundle['template']}
    files.update({'configs/'+name: value for name, value in bundle['configs'].items()})
    hashes = {}
    for relative, value in files.items():
        path = output/relative
        raw = (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False)+'\n').encode('utf8')
        with path.open('xb') as stream:
            stream.write(raw)
        hashes[relative] = hashlib.sha256(raw).hexdigest()
    installed = {}
    for name in ('pybamm','numpy','scipy','torch','gpytorch','botorch','pymoo'):
        try:
            installed[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed[name] = None
    manifest = {'status': 'prepared_not_executed', 'files_sha256': hashes,
                'installed_versions_at_preparation': installed,
                'actual_calls': {'API': 0, 'DFN': 0}}
    with (output/'manifest.json').open('x', encoding='utf8') as stream:
        json.dump(manifest, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--template', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, choices=(10,50), default=10)
    parser.add_argument('--replicates', type=int, choices=(5,10), default=5)
    args = parser.parse_args()
    template = json.loads(args.template.read_text(encoding='utf-8-sig'))
    bundle = build_design(template, template_path=str(args.template.resolve()),
                          rounds=args.rounds, replicates=args.replicates)
    write_bundle(bundle, args.output)
    print(json.dumps({'status': 'prepared_not_executed', 'seeds': bundle['protocol']['active_seeds'],
                      'configs': len(bundle['configs']), 'formal_jobs': len(bundle['jobs']),
                      'resource_estimate': bundle['protocol']['resource_estimate'],
                      'actual_API': 0, 'actual_DFN': 0, 'output': str(args.output)}))


if __name__ == '__main__':
    main()
