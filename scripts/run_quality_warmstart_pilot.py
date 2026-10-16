"""Approved quality-feedback WarmStart (20..80 evaluations, 8 seeds, 5 BO)."""
import os
for key in ('OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS'):os.environ[key]='1'
os.environ['PYBAMM_DISABLE_TELEMETRY']='true'
os.environ['MPLBACKEND']='Agg'
import argparse
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from dataclasses import asdict
import getpass
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run,read_json
from llmbo_para.config import load_json
from llmbo_para.quality_initialization import QualityScreeningBudget,QualityWarmInitializer
from llmbo_para.runstore import RunStore,sha256_file
from llmbo_para.workflow import prepare_experiment,build_transport,run_experiment,run_status
from run_ablation_suite import screen_family
from resource_snapshot import snapshot


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'runs/quality-warmstart-pilots')
    parser.add_argument('--resume-plan',type=Path)
    parser.add_argument('--staged',action='store_true',help='authorized follow-up: at most 40 new candidates, two feasible then quality')
    parser.add_argument('--prompt-for-key',action='store_true')
    parser.add_argument('--proxy',default='http://127.0.0.1:7897')
    parser.add_argument('--kernel-control',type=Path,default=ROOT/'runs/gp-kernel-controls/20261014T121959Z_15c7243a7865_0b473be9')
    args=parser.parse_args()
    if args.proxy:
        from urllib.parse import urlsplit
        proxy=urlsplit(args.proxy)
        if proxy.scheme not in {'http','https'} or not proxy.hostname or proxy.username or proxy.password or proxy.query or proxy.fragment:
            parser.error('proxy must be HTTP(S) without credentials')
        for name in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):os.environ[name]=args.proxy
    template=load_json(args.config)
    template['data']['path']=str((args.config.resolve().parent/template['data']['path']).resolve())
    template['optimization'].update(seed=20261014,total_candidate_budget=13,warm_start_llm_points=0,sobol_points=8,
        llm_enabled=True,llm_warm_start_enabled=False,llm_gp_groups_enabled=True,llm_informed_enabled=False)
    if template['optimization'].get('surrogate_mode')!='per_rate' or template['model'].get('initial_state_mode')!='parameterization':
        parser.error('approved pilot retains four GPs and fixed parameterization initial state')
    if read_json(args.kernel_control/'terminal.json')['status']!='completed':parser.error('matched GP control must complete first')
    key_env=template['llm']['api_key_env'];supplied=False
    if args.prompt_for_key and not os.environ.get(key_env):
        os.environ[key_env]=getpass.getpass('OpenCode credential (hidden; memory only): ');supplied=True
    budget=QualityScreeningBudget();initializer_type=QualityWarmInitializer;prior_evaluations=0
    if args.staged:
        if not args.resume_plan:parser.error('staged follow-up requires the preceding paid screening plan')
        from llmbo_para.staged_initialization import StagedQualityWarmInitializer
        prior=read_json(args.resume_plan);cost=prior['screening_cost'];prior_evaluations=cost['candidate_evaluations']
        if prior.get('complete') or len(prior['parameters'])>=8:parser.error('follow-up requires insufficient feasible seeds')
        budget=QualityScreeningBudget(max_evaluations=prior_evaluations+40,
            max_warm_batches=cost['batches']+10,max_selection_requests=cost['selection_requests']+10)
        initializer_type=StagedQualityWarmInitializer
    protocol={'study':'quality_feedback_warmstart_small_pilot','experiment':template,'budget':asdict(budget),
        'bo_iterations':5,'initial_seed_count':8,'all_screening_labels_retained':True,'parallel_workers':1,
        'kernel_control':{'directory':str(args.kernel_control.resolve()),'result_sha256':sha256_file(args.kernel_control/'result.json')},
        'resume_plan':str(args.resume_plan.resolve()) if args.resume_plan else None,'proxy':args.proxy,
        'scientific_settings':'same full four-rate objective, no extrapolation, no fixed physics intervention',
        'limits':'fresh small pilot, not a matched-cost or multi-seed efficacy experiment'}
    if args.staged:
        protocol.update(study='staged_coverage_then_quality_followup',prior_candidate_evaluations=prior_evaluations,
            max_new_screening_candidates=40,stages=['two complete feasible points','RMSE and diversity refinement'],
            limits='adaptive follow-up reuses previous failed screening; not an independent or matched-cost ablation')
    suite=RunStore(args.output,protocol,command=subprocess.list2cmdline([sys.executable,*sys.argv]))
    suite.write_json('study-plan.json',protocol)
    print(json.dumps({'pilot_directory':str(suite.path),'stage':'preflight'}),flush=True)
    started=time.perf_counter()
    with (suite.path/'stdout.log').open('x',encoding='utf-8',buffering=1) as out,(suite.path/'stderr.log').open('x',encoding='utf-8',buffering=1) as err:
        with redirect_stdout(out),redirect_stderr(err):
            try:
                resources=snapshot();suite.write_json('resources-before.json',resources)
                if resources.get('memory_available_bytes',4e9)<1024**3+256*1024**2 or resources['disk_free_bytes']<2e9:
                    raise RuntimeError('insufficient memory/disk headroom for serial pilot')
                screen=deepcopy(template);screen['optimization'].update(reuse_screening_history=False,
                    llm_warm_start_enabled=True,llm_gp_groups_enabled=False)
                report,prepared=prepare_experiment(screen);suite.write_json('preflight-screening.json',report)
                if prepared is None:raise ValueError('; '.join(report['errors']))
                probe_settings={**template['llm'],'max_tokens':128}
                probe=RunStore(suite.path/'connectivity',{'llm':probe_settings,'data_sent':'none'},command='minimal authorized API connectivity probe')
                response=build_transport(probe_settings,probe).post({'task':'connectivity_probe',
                    'instructions':'Return only the JSON object {"ok":true}.','purpose':'connectivity'})
                if response!={'ok':True}:raise ValueError('unexpected connectivity response')
                probe.finish('completed',{'response':response})
                suite.append_event({'type':'quality_pilot_stage','stage':'screening'})
                plan,path=screen_family(screen,'llm',suite,ROOT,budget=budget,resume_plan=args.resume_plan,
                    artifact_root=suite.path/'initialization',initializer_type=initializer_type)
                suite.write_json('initial-plan.json',plan)
                if not plan['complete'] or len(plan['parameters'])!=8 or plan['screening_cost']['candidate_evaluations']<20:
                    raise RuntimeError('quality plan does not satisfy approved minimum/seed count')
                if args.staged and plan['screening_cost']['new_candidate_evaluations']>40:
                    raise RuntimeError('staged follow-up exceeded its 40-new-candidate cap')
                config=arm_config(template,plan,path,warm_start=True,gp_groups=True,bo_iterations=5)
                config['status']='quality_feedback_20_to_80_screening_8_seeds_5_bo_pilot'
                if args.staged:config['status']='staged_coverage_then_quality_max40_new_8_seeds_5_bo_pilot'
                suite.write_json('experiment-config.json',config)
                report,prepared=prepare_experiment(config);suite.write_json('preflight-optimization.json',report)
                if prepared is None:raise ValueError('; '.join(report['errors']))
                suite.append_event({'type':'quality_pilot_stage','stage':'BO'})
                result=run_experiment(config,suite.path/'optimization',command='quality-feedback WarmStart: 8 cached seeds then 5 BO updates')
                audit=audit_run(result['run_directory'],deep=True);suite.write_json('deep-audit.json',audit)
                if not audit['passed']:raise RuntimeError('deep pilot audit failed')
                if result['cache_hits']!=8 or result['new_candidate_evaluations']!=5 or result['rate_solve_attempts']!=20:
                    raise RuntimeError('pilot cache/evaluation budget differs from approved design')
                sources=plan['quality_observation_sources'];screening_records=[read_json(s['path']) for s in sources]
                opt_records=[read_json(p) for p in sorted((Path(result['run_directory'])/'attempts').glob('*.json'))]
                errors=[{'parameters':r['parameters'],'rate':q['rate'],'failure_kind':q['failure_kind']}
                    for r in screening_records+opt_records[8:] for q in r['rates'] if q['failure_kind'] not in (None,'voltage_cutoff','coverage_shortfall')]
                if errors:
                    suite.write_json('unexpected-execution-errors.json',errors);raise RuntimeError('unexpected solver/data errors require diagnosis')
                summary={'result':result,'run_status':run_status(result['run_directory']),'screening_cost':plan['screening_cost'],
                    'quality_selection':plan['quality_selection'],'actual_candidate_evaluations':len(screening_records)+5,
                    'actual_rate_solves':plan['screening_cost']['rate_solve_attempts']+20,
                    'screening_valid_candidates':sum(r['valid'] for r in screening_records),
                    'execution_errors':0,'completed_pilots':1,'running_pilots':0,'pending_pilots':0,
                    'elapsed_s':time.perf_counter()-started,'eta_minutes':0}
                suite.write_json('resources-after.json',snapshot());suite.write_json('result.json',summary)
                suite.finish('completed',summary);print(json.dumps(summary,ensure_ascii=False),flush=True);return 0
            except BaseException as exc:
                message=str(exc);trace=traceback.format_exc();key=os.environ.get(key_env)
                if key:message=message.replace(key,'[REDACTED]');trace=trace.replace(key,'[REDACTED]')
                failure={'error_type':type(exc).__name__,'message':message,'traceback':trace,'elapsed_s':time.perf_counter()-started}
                suite.write_json('failure.json',failure);suite.finish('failed',failure);print(json.dumps(failure),flush=True);return 1
            finally:
                if supplied:os.environ.pop(key_env,None)


if __name__=='__main__':raise SystemExit(main())
