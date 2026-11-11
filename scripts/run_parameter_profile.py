"""Serial, bounded parameter-profile cases using the existing audited evaluator.

A case plan is an experimental intervention, not a BO or LLM recommendation.
Every case keeps the full measured horizon and all six original bounds.
"""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout,redirect_stderr
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from unittest.mock import patch

for variable in ('OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','OMP_NUM_THREADS'):
    os.environ[variable]='1'
os.environ['PYBAMM_DISABLE_TELEMETRY']='true'
os.environ['MPLBACKEND']='Agg'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from llmbo_para.audit import read_json,audit_run
from llmbo_para.feasibility import simulation_signature
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.runstore import RunStore,sha256_file
from llmbo_para.workflow import prepare_experiment,run_fixed_candidates
from resource_snapshot import snapshot
from run_reference_continuation import residual_summary,process_memory
import pybamm


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'runs/parameter-profiles')
    args=parser.parse_args()
    plan=read_json(args.plan)
    source=Path(plan['source_run'])
    config=read_json(source/'manifest.json')['config']
    config['data']['path']=str((source/'inputs/raw.xlsx').resolve())
    config['optimization'].update(llm_enabled=False,llm_warm_start_enabled=False,
        llm_gp_groups_enabled=False,llm_informed_enabled=False,reuse_screening_history=False)
    if 'initial_state_mode' in plan:
        if plan['initial_state_mode']!='explicit_soc' or plan.get('initial_soc')!=1.0:
            raise ValueError('The approved initial-state diagnostic supports explicit SOC=1 only')
        config['model']['initial_state_mode']='explicit_soc'
        for condition in config['conditions_by_rate'].values():condition['initial_soc']=1.0
    if not 1<=len(plan['cases'])<=12:raise ValueError('Profile plans must contain 1 to 12 bounded cases')
    prepared_report,prepared=prepare_experiment(config)
    if prepared is None:raise ValueError(str(prepared_report['errors']))
    for case in plan['cases']:
        prepared.space.validate(case['parameters'])
        if set(case)-{'name','parameters','mesh_points','solver_tolerance'}:raise ValueError('Unexpected intervention setting')
    protocol={'purpose':plan['purpose'],'plan':plan,'plan_sha256':sha256_file(args.plan),'experiment':config,
        'planned_candidate_evaluations':len(plan['cases']),'planned_rate_solves':4*len(plan['cases']),
        'simulation_signature':simulation_signature(config,prepared.series),'api_calls':0,'parallel_workers':1,
        'limits':'manual controlled diagnosis within the original domain; not a fair BO/LLM ablation'}
    store=RunStore(args.output,protocol,command=subprocess.list2cmdline([sys.executable,*sys.argv]))
    store.write_json('preflight.json',prepared_report)
    print(json.dumps({'session_directory':str(store.path),'cases':len(plan['cases'])}),flush=True)
    completed=[];started=time.perf_counter()
    with (store.path/'stdout.log').open('x',encoding='utf-8',buffering=1) as out,(store.path/'stderr.log').open('x',encoding='utf-8',buffering=1) as err:
        with redirect_stdout(out),redirect_stderr(err):
            try:
                for index,case in enumerate(plan['cases']):
                    resources=snapshot();store.write_json(f'resources/before-{index:03d}.json',{**resources,'process':process_memory()})
                    if resources['memory_available_bytes']<1024**3+256*1024**2 or resources['disk_free_bytes']<2e9:
                        raise RuntimeError('Insufficient RAM/disk headroom before '+case['name'])
                    local=deepcopy(config)
                    if 'mesh_points' in case:local['model']['mesh_points']={k:case['mesh_points'] for k in local['model']['mesh_points']}
                    if 'solver_tolerance' in case:local['model']['solver'].update(rtol=case['solver_tolerance'],atol=case['solver_tolerance'])
                    store.write_json(f'configs/{index:03d}-{case["name"]}.json',local)
                    effective=[]
                    original_solve=pybamm.Simulation.solve
                    concentration_keys=('Initial concentration in negative electrode [mol.m-3]',
                        'Initial concentration in positive electrode [mol.m-3]',
                        'Maximum concentration in negative electrode [mol.m-3]',
                        'Maximum concentration in positive electrode [mol.m-3]')
                    def observed_solve(simulation,*pos,**kw):
                        # Explicit SOC initializes via nested algebraic eSOH Simulations.
                        # Only the four outer DFN solves belong to the rate ledger.
                        if not isinstance(simulation.model,pybamm.lithium_ion.DFN):
                            return original_solve(simulation,*pos,**kw)
                        before={key:float(simulation.parameter_values[key]) for key in concentration_keys}
                        solution=original_solve(simulation,*pos,**kw)
                        after={key:float(simulation.parameter_values[key]) for key in concentration_keys}
                        effective.append({'rate':RATE_ORDER[len(effective)],'initial_soc_argument':kw.get('initial_soc'),
                            'before_initialization':before,'after_initialization':after})
                        return solution
                    with patch.object(pybamm.Simulation,'solve',observed_solve):
                        result=run_fixed_candidates(local,store.path/'cases'/case['name'],[(index,case['parameters'])],mode='smoke')
                    if len(effective)!=4:raise RuntimeError('Missing effective initial-state records')
                    store.write_json(f'effective-initial-state/{index:03d}.json',effective)
                    run=Path(result['run_directory']);record=read_json(next((run/'attempts').glob('*.json')))
                    if any(q['failure_kind'] not in (None,'voltage_cutoff','coverage_shortfall') for q in record['rates']):
                        raise RuntimeError('Unexpected solver/data failure in '+case['name'])
                    audit=audit_run(run);store.write_json(f'audits/{index:03d}.json',audit)
                    if not audit['passed']:raise RuntimeError('Case audit failed')
                    row={'case':case['name'],'run_directory':str(run),**residual_summary(record,prepared.series)}
                    completed.append(row);store.write_json(f'results/{index:03d}.json',row)
                    elapsed=time.perf_counter()-started
                    progress={'completed':index+1,'valid':sum(r['valid'] for r in completed),
                        'cutoff_candidates':sum(not r['valid'] for r in completed),'execution_errors':0,'running':0,
                        'pending':len(plan['cases'])-index-1,'rate_solves':4*(index+1),
                        'cases_per_min':(index+1)*60/elapsed,'eta_s':(len(plan['cases'])-index-1)*elapsed/(index+1)}
                    store.append_event({'type':'profile_case_complete',**progress,'latest':row})
                good=[r for r in completed if r['valid']]
                result={'cases':completed,'completed':len(completed),'valid':len(good),'cutoff_candidates':len(completed)-len(good),
                    'execution_errors':0,'pending':0,'running':0,'new_rate_solves':4*len(completed),'api_calls':0,
                    'elapsed_s':time.perf_counter()-started,'best':min(good,key=lambda r:r['objective_mV']) if good else None}
                store.write_json('result.json',result);store.write_json('resource-after.json',{**snapshot(),'process':process_memory()})
                store.finish('completed_with_failures' if len(good)!=len(completed) else 'completed',result)
            except BaseException as exc:
                failure={'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc(),'completed':len(completed),'elapsed_s':time.perf_counter()-started}
                store.write_json('failure.json',failure);store.finish('failed',failure);raise
    print(json.dumps({'session_directory':str(store.path),**result},ensure_ascii=False,indent=2),flush=True)
    return 0


if __name__=='__main__':raise SystemExit(main())
