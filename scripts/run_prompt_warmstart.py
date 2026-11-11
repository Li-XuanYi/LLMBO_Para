"""WarmStart entry: pure prompt or bounded Agent rejection feedback; BO is opt-in."""
import os
for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):os.environ[name]='1'
os.environ['PYBAMM_DISABLE_TELEMETRY']='true'
os.environ['MPLBACKEND']='Agg'
import argparse
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
from dataclasses import asdict
import getpass
import json
from pathlib import Path
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from llmbo_para.ablation import arm_config
from llmbo_para.audit import audit_run,read_json
from llmbo_para.config import load_json,configuration_errors
from llmbo_para.prompt_initialization import PromptOnlyBudget,PromptOnlyInitializer
from llmbo_para.rejection_initialization import RejectionFeedbackBudget,RejectionFeedbackInitializer,verified_feedback_plan,verified_success_record
from llmbo_para.runstore import RunStore,sha256_file
from llmbo_para.screening_history import load_screening_history,validate_record
from llmbo_para.workflow import prepare_experiment,build_transport,run_experiment
from run_ablation_suite import screen_family
from resource_snapshot import snapshot


def main(*,default_settings='prompt-only-warmstart.json',default_output='runs/prompt-warmstart'):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings',type=Path,default=ROOT/'configs'/default_settings)
    parser.add_argument('--output',type=Path,default=ROOT/default_output)
    parser.add_argument('--preflight-only',action='store_true',help='validate settings and data; make no API/DFN calls')
    parser.add_argument('--prompt-for-key',action='store_true')
    parser.add_argument('--bo-iterations',type=int,help='explicit optional BO budget; default settings are initialization-only')
    args=parser.parse_args();settings=load_json(args.settings)
    method=settings.get('method')
    expected={'method','experiment_config','candidate_count','initial_valid_target','bo_iterations','proxy'}
    if method=='agent_rejection':expected=expected-{'candidate_count'}|{'max_candidates','generation_batch_size','max_generation_requests','feedback_plan'}
    if method=='agent_rejection' and 'success_examples' in settings:expected.add('success_examples')
    if method not in {'prompt_only','agent_rejection'} or set(settings)!=expected:parser.error('unexpected WarmStart settings/schema')
    count,target=settings['candidate_count' if method=='prompt_only' else 'max_candidates'],settings['initial_valid_target']
    if type(count) is not int or type(target) is not int or not 2<=target<=count:parser.error('need integer 2 <= target <= candidate_count')
    iterations=settings['bo_iterations'] if args.bo_iterations is None else args.bo_iterations
    if type(iterations) is not int or iterations<0:parser.error('BO budget must be a nonnegative integer')
    feedback_path=None;success_examples=[]
    if method=='prompt_only':
        budget=PromptOnlyBudget(target=target,min_evaluations=target,max_evaluations=count,warm_batch_size=count)
        initializer_type=PromptOnlyInitializer
    else:
        budget=RejectionFeedbackBudget(target=target,min_evaluations=target,max_evaluations=count,
            warm_batch_size=settings['generation_batch_size'],max_warm_batches=settings['max_generation_requests'])
        initializer_type=RejectionFeedbackInitializer
        if settings['feedback_plan']:feedback_path=(args.settings.resolve().parent/settings['feedback_plan']).resolve()
        for reference in settings.get('success_examples',[]):
            if set(reference)!={'record_path','sha256'}:parser.error('success references need record_path and sha256')
            success_examples.append({**reference,'record_path':str((args.settings.resolve().parent/reference['record_path']).resolve())})
    config_path=(args.settings.resolve().parent/settings['experiment_config']).resolve();template=load_json(config_path)
    template['data']['path']=str((config_path.parent/template['data']['path']).resolve())
    if template['optimization'].get('surrogate_mode')!='per_rate' or template['model'].get('initial_state_mode')!='parameterization':
        parser.error('current method retains four GPs and fixed parameterization initial state')
    proxy=settings['proxy']
    if proxy:
        from urllib.parse import urlsplit
        parsed=urlsplit(proxy)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            parser.error('proxy must be HTTP(S) without embedded credentials')
        for name in ('HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy'):os.environ[name]=proxy
    screen=deepcopy(template);screen['optimization'].update(reuse_screening_history=False,llm_enabled=True,
        llm_warm_start_enabled=True,llm_gp_groups_enabled=False,llm_informed_enabled=False)
    key_env=template['llm']['api_key_env'];supplied=False
    if not args.preflight_only and args.prompt_for_key and not os.environ.get(key_env):
        os.environ[key_env]=getpass.getpass('OpenCode credential (hidden; memory only): ');supplied=True
    protocol={'method':method,'settings':settings,'experiment':template,'screening_experiment':screen,'budget':asdict(budget),
        'settings_path':str(args.settings.resolve()),'settings_sha256':sha256_file(args.settings),
        'experiment_config_sha256':sha256_file(config_path),'bo_iterations':iterations,'preflight_only':args.preflight_only,
        'no_llm_selection':True,'no_evaluation_feedback':method=='prompt_only','no_replenishment':method=='prompt_only',
        'prior_results_reused':feedback_path is not None,'prior_results_reused_as_seeds':False,
        'prior_feedback_path':str(feedback_path) if feedback_path else None,
        'prior_feedback_sha256':sha256_file(feedback_path) if feedback_path else None,
        'success_examples_context_only':success_examples,
        'seed_selection':'best then maximin in top2k complete points','workers':1}
    suite=RunStore(args.output,protocol,command=subprocess.list2cmdline([sys.executable,*sys.argv]))
    suite.write_json('study-plan.json',protocol);print(json.dumps({'run_directory':str(suite.path)}),flush=True)
    with (suite.path/'stdout.log').open('x',encoding='utf-8',buffering=1) as out,(suite.path/'stderr.log').open('x',encoding='utf-8',buffering=1) as err:
        with redirect_stdout(out),redirect_stderr(err):
            try:
                if args.preflight_only:
                    errors=configuration_errors(screen)
                    try:build_transport(screen['llm'])
                    except (ValueError,TypeError) as exc:errors.append('transport configuration: '+str(exc))
                    data_config=deepcopy(screen);data_config['optimization'].update(llm_enabled=False,llm_warm_start_enabled=False,llm_gp_groups_enabled=False)
                    report,prepared=prepare_experiment(data_config)
                    if prepared is not None and feedback_path:
                        try:verified_feedback_plan(screen,prepared.series,feedback_path)
                        except (ValueError,KeyError,OSError) as exc:errors.append('prior feedback: '+str(exc))
                    if prepared is not None:
                        for reference in success_examples:
                            try:verified_success_record(screen,prepared.series,reference['record_path'],reference['sha256'])
                            except (ValueError,KeyError,OSError) as exc:errors.append('success reference: '+str(exc))
                    summary={'input_preflight_ready':prepared is not None and not errors,'configuration_errors':errors,
                        'data_model_preflight':report,'credential_present':bool(os.environ.get(key_env)),
                        'candidate_count':count,'initial_valid_target':target,'bo_iterations':iterations,
                        'paid_API_calls':0,'DFN_solves':0,'method':method,
                        'max_generation_requests':budget.max_warm_batches,'generation_batch_size':budget.warm_batch_size,
                        'prior_feedback_verified':feedback_path is not None and not errors,
                        'success_reference_count_verified':len(success_examples) if not errors else None}
                    suite.write_json('preflight.json',summary);suite.finish('completed' if summary['input_preflight_ready'] else 'preflight_failed',summary)
                    print(json.dumps(summary),flush=True);return 0 if summary['input_preflight_ready'] else 1
                resources=snapshot();suite.write_json('resources-before.json',resources)
                if resources.get('memory_available_bytes',4e9)<1.25*1024**3 or resources['disk_free_bytes']<2e9:
                    raise RuntimeError('insufficient memory/disk for serial initialization')
                report,prepared=prepare_experiment(screen);suite.write_json('preflight.json',report)
                if prepared is None:raise ValueError('; '.join(report['errors']))
                try:
                    plan,path=screen_family(screen,'llm',suite,ROOT,budget=budget,artifact_root=suite.path/'initialization',initializer_type=initializer_type,feedback_plan=feedback_path,success_examples=success_examples)
                except RuntimeError as exc:
                    if not str(exc).startswith('pure-prompt fixed design ended') or not hasattr(exc,'screening_directory'):raise
                    path=Path(exc.screening_directory)/'initial-plan.json';plan=read_json(path)
                suite.write_json('initial-plan.json',plan)
                for source in plan['quality_observation_sources']:
                    if sha256_file(source['path'])!=source['sha256']:raise ValueError('screening record hash differs')
                    validate_record(read_json(source['path']),screen,prepared.series)
                if not plan['complete']:
                    summary={'initialization_complete':False,'screening_cost':plan['screening_cost'],
                        'BO_updates':0,'bo_skipped':'insufficient complete valid points; stopped at configured budget without random fallback',
                        'method':method,'stop_reason':plan.get('stop_reason')}
                    suite.write_json('result.json',summary);suite.finish('completed_with_failures',summary);return 2
                history=load_screening_history(screen,prepared.series,plan,path)
                suite.write_json('screening-history-audit.json',{'passed':True,'catalog':history.catalog})
                summary={'initialization_complete':True,'screening_cost':plan['screening_cost'],
                    'selected_parameters':plan['parameters'],'best_initial_rmse_mV':min(r['objective_v'] for r in plan['evaluations'])*1000,'BO_updates':0}
                if iterations:
                    config=arm_config(template,plan,path,warm_start=True,gp_groups=template['optimization'].get('llm_gp_groups_enabled',True),bo_iterations=iterations)
                    config['optimization']['reuse_screening_history']=True;suite.write_json('experiment-config.json',config)
                    result=run_experiment(config,suite.path/'optimization',command=f'pure-prompt cached {target} seeds then {iterations} explicitly requested BO updates')
                    audit=audit_run(result['run_directory'],deep=True);suite.write_json('deep-audit.json',audit)
                    if not audit['passed']:raise RuntimeError('optimization deep audit failed')
                    summary.update(BO_updates=iterations,optimization=result)
                suite.write_json('result.json',summary);suite.finish('completed',summary);print(json.dumps(summary),flush=True);return 0
            except BaseException as exc:
                message=str(exc);trace=traceback.format_exc();key=os.environ.get(key_env)
                if key:message=message.replace(key,'[REDACTED]');trace=trace.replace(key,'[REDACTED]')
                failure={'error_type':type(exc).__name__,'message':message,'traceback':trace}
                suite.write_json('failure.json',failure);suite.finish('failed',failure);return 1
            finally:
                if supplied:os.environ.pop(key_env,None)


if __name__=='__main__':raise SystemExit(main())
