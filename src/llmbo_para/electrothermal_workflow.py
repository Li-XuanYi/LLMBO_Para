"""Version-2 preparation and explicit, budgeted electrothermal execution."""
from dataclasses import dataclass,asdict,replace
from pathlib import Path
import json
import math
import time
import numpy as np
from .electrothermal_config import electrothermal_configuration_errors
from .electrothermal_data import load_electrothermal_dataset,ElectrothermalDataset
from .electrothermal_evaluation import ElectrothermalEvaluator
from .electrothermal_provenance import build_electrothermal_signatures,load_initial_plan
from .electrothermal_store import ElectrothermalRunStore
from .config import parameter_space_from_config
from .runstore import sha256_file,RunStore,digest_value


@dataclass
class PreparedElectrothermalExperiment:
    config:dict
    space:object
    dataset:object
    signatures:object
    initial_plan:object=None

    @property
    def input_hashes(self):return {'electrothermal_dataset':self.dataset.data_signature}


def prepare_electrothermal_experiment(config,*,base_dir):
    errors=electrothermal_configuration_errors(config)
    report={'ready':False,'errors':errors,'warnings':[],'paid_api_calls_made':0,'battery_simulations_made':0}
    if errors:return report,None
    try:
        space=parameter_space_from_config(config);dataset=load_electrothermal_dataset(config,base_dir)
        signatures=build_electrothermal_signatures(config,dataset);initial=None
        if config['optimization'].get('initial_plan'):
            spec=config['optimization']['initial_plan'];path=(Path(base_dir)/spec['path']).resolve()
            if sha256_file(path)!=spec['sha256']:raise ValueError('initial plan file hash differs')
            initial=load_initial_plan(path,space=space,dataset=dataset,signatures=signatures)
        report.update(ready=True,fit_rates=list(dataset.fit_rates),signatures=asdict(signatures))
        return report,PreparedElectrothermalExperiment(config,space,dataset,signatures,initial)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        errors.append(str(exc));return report,None


class SolverBudget:
    def __init__(self,max_calls,wall_clock_s):
        if type(max_calls) is not int or max_calls<0 or type(wall_clock_s) not in (int,float) or not math.isfinite(wall_clock_s) or wall_clock_s<=0:raise ValueError('explicit finite solver budget required')
        self.maximum=max_calls;self.calls=0;self.started=time.perf_counter();self.wall_clock_s=wall_clock_s

    def before_solve(self):
        if self.calls>=self.maximum or time.perf_counter()-self.started>=self.wall_clock_s:raise RuntimeError('actual solver call/wall-clock budget exhausted')
        self.calls+=1


def make_electrothermal_backend(config,*,budget=None):
    if config['model']['provider']=='software':
        from .electrothermal_synthetic import SyntheticElectrothermalSimulator
        return SyntheticElectrothermalSimulator()
    if budget is None or budget.maximum<=0:raise ValueError('explicit positive DFN solver budget required')
    from .pybamm_adapter import build_electrothermal_simulator
    backend=build_electrothermal_simulator(config);backend.before_solve=budget.before_solve
    return backend


def run_electrothermal_fixed_candidates(prepared,candidates,output,*,simulator=None,budget=None):
    config=prepared.config
    if not candidates:raise ValueError('explicit fixed candidates required')
    for point in candidates:prepared.space.validate(point)
    if config['model']['provider']=='pybamm' and any(
        c.voltage.provenance.get('kind')=='generation_grid_only_not_observations' for c in prepared.dataset.cases.values()):
        raise ValueError('DFN synthetic observation templates must be generated under the explicit smoke budget first')
    if config['model']['provider']=='pybamm' and (budget is None or budget.maximum-budget.calls<len(candidates)*len(prepared.dataset.fit_rates)*config['optimization']['max_rate_attempts']):
        raise ValueError('explicit DFN budget insufficient for all fixed candidate attempts')
    backend=simulator or make_electrothermal_backend(config,budget=budget)
    store=ElectrothermalRunStore(output,config,dataset=prepared.dataset,signatures=prepared.signatures,command='electrothermal fixed-candidate evaluation')
    evaluator=ElectrothermalEvaluator(prepared.space,backend,fit_rates=prepared.dataset.fit_rates,max_rate_attempts=config['optimization']['max_rate_attempts'])
    records=[]
    try:
        for point in candidates:
            record=evaluator.evaluate(point,prepared.dataset);store.save_evaluation(record,phase='fixed');records.append(record)
        result={'run_directory':str(store.path),'fit_rates':list(prepared.dataset.fit_rates),'complete_pairs':sum(r.complete_pair_valid for r in records),
                'candidate_evaluations':len(records),'objectives':[r.objectives for r in records],'costs':store.ledger.summary(),'API_calls':0}
        store.write_json('electrothermal-summary.json',result);store.finish('completed' if all(r.complete_pair_valid for r in records) else 'completed_with_failures',result)
        return result
    except Exception as exc:
        store.finish('failed',{'message':str(exc),'costs':store.ledger.summary()});raise


def run_electrothermal_experiment(config,output,*,base_dir,simulator=None,llm_controller=None):
    from .mo_optimizer import MOOptimizer
    report,prepared=prepare_electrothermal_experiment(config,base_dir=base_dir)
    if prepared is None:raise ValueError('; '.join(report['errors']))
    if config['model']['provider']=='pybamm' and any(c.voltage.provenance.get('kind')=='generation_grid_only_not_observations' for c in prepared.dataset.cases.values()):
        raise ValueError('DFN synthetic templates are not measured observations; use explicit generation entry')
    budget=SolverBudget(config['budgets']['max_solver_calls'],config['budgets']['wall_clock_s'])
    backend=simulator or make_electrothermal_backend(config,budget=budget)
    store=ElectrothermalRunStore(output,config,dataset=prepared.dataset,signatures=prepared.signatures,command='electrothermal multiobjective BO')
    evaluator=ElectrothermalEvaluator(prepared.space,backend,fit_rates=prepared.dataset.fit_rates,max_rate_attempts=config['optimization']['max_rate_attempts'])
    try:
        initial=prepared.initial_plan;controller=llm_controller
        if initial is not None:
            import shutil
            spec=config['optimization']['initial_plan'];source=(Path(base_dir)/spec['path']).resolve()
            destination=store.path/'inputs/initial-plan.json';destination.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,destination)
        if config['optimization']['mode']!='parego' and initial is None:
            from .electrothermal_llm import ElectrothermalLLMController
            controller=controller or ElectrothermalLLMController()
            controller.evaluator=evaluator;controller.solver_budget=budget
            initial=controller.generate_warmstart(prepared,store=store,budgets=config['budgets'])
        if config['optimization']['mode']=='full_llmbo_mo':
            from .electrothermal_llm import ElectrothermalLLMController
            controller=controller or ElectrothermalLLMController();controller.prepared=prepared
        optimizer=MOOptimizer(prepared.space,evaluator,prepared.dataset,store,config['optimization'],initial_plan=initial,llm_controller=controller)
        result=optimizer.optimize(config['optimization']['total_candidate_budget'])
        result['initial_plan_sha256']=initial.plan_sha256 if initial is not None else None
        store.write_json('electrothermal-summary.json',result);store.finish('completed',result);return result
    except Exception as exc:
        store.finish('failed',{'message':str(exc),'costs':store.ledger.summary()});raise


def plan_electrothermal_smoke(config,candidates,budget):
    errors=electrothermal_configuration_errors(config);points=[]
    try:
        space=parameter_space_from_config(config);points=[space.validate(p) for p in candidates]
        if not points:errors.append('explicit candidates required')
    except (KeyError,ValueError,TypeError) as exc:errors.append(str(exc))
    rates=config.get('fit_rates',[]);dfn=config.get('model',{}).get('provider')=='pybamm'
    generation=1 if dfn and config.get('run_kind')=='synthetic_dfn' else 0
    maximum=len(rates)*(len(points)+generation)*config.get('optimization',{}).get('max_rate_attempts',1) if dfn else 0
    if dfn:
        if not isinstance(budget,dict):errors.append('explicit approved DFN budget file is required')
        else:
            if budget.get('approved') is not True:errors.append('DFN budget must be explicitly approved')
            if type(budget.get('max_solver_calls')) is not int or budget['max_solver_calls']<maximum:errors.append('solver budget too small')
            if budget.get('fit_rates')!=rates:errors.append('budget fitting rates differ')
            if type(budget.get('wall_clock_s')) not in (int,float) or not math.isfinite(budget['wall_clock_s']) or budget['wall_clock_s']<=0:errors.append('explicit wall-clock budget required')
            if type(budget.get('max_rate_attempts')) is not int or budget['max_rate_attempts']!=config['optimization']['max_rate_attempts']:errors.append('explicit retry budget differs')
            if generation and budget.get('generation_parameters') is None:errors.append('explicit synthetic generation parameters required')
            window=budget.get('time_window_s')
            if not isinstance(window,list) or len(window)!=2 or type(window[0]) not in (int,float) or window[0]!=0 or type(window[1]) not in (int,float) or not math.isfinite(window[1]) or window[1]<=0:errors.append('explicit time window required')
    return {'ready':not errors,'errors':errors,'fit_rates':rates,'candidates':points,'generation_candidate_count':generation,
            'maximum_solver_calls':maximum,'actual_solver_calls':0,'API_calls':0,
            'tasks':[{'phase':phase,'candidate':i,'rate':r} for phase,n in (('generation',generation),('validation',len(points))) for i in range(n) for r in rates]}


def run_electrothermal_smoke(config,candidates,output,*,base_dir,budget=None,dry_run=False):
    plan=plan_electrothermal_smoke(config,candidates,budget)
    if dry_run:return plan
    if not plan['ready']:raise ValueError('; '.join(plan['errors']))
    report,prepared=prepare_electrothermal_experiment(config,base_dir=base_dir)
    if prepared is None:raise ValueError('; '.join(report['errors']))
    if config['model']['provider']=='software':return run_electrothermal_fixed_candidates(prepared,candidates,output)
    controller=SolverBudget(budget['max_solver_calls'],budget['wall_clock_s']);backend=make_electrothermal_backend(config,budget=controller)
    session=RunStore(output,{'electrothermal_smoke':config,'explicit_solver_budget':budget},command='explicit budgeted DFN synthetic smoke')
    try:
        cases={}
        if plan['generation_candidate_count']:
            theta=prepared.space.validate(budget['generation_parameters']);mapping=dict(zip((s.name for s in prepared.space.specs),theta))
            for rate in prepared.dataset.fit_rates:
                case=prepared.dataset.cases[rate]
                horizon=max(case.voltage.time_s[-1],case.cell_temperature_k.time_s[-1])
                if horizon!=budget['time_window_s'][-1]:raise ValueError('data and approved solve time window differ')
                trace=backend.simulate(mapping,case);session.write_json('generation/'+rate+'.json',trace.to_dict())
                if trace.time_s[-1]<horizon:raise ValueError('synthetic generation did not cover the requested window')
                source={'kind':'real_DFN_synthetic_generation','solution_id':trace.solution_id,'parameters':theta}
                cases[rate]=replace(case,voltage=replace(case.voltage,values=tuple(np.interp(case.voltage.time_s,trace.time_s,trace.voltage_v)),provenance=source),
                    cell_temperature_k=replace(case.cell_temperature_k,values=tuple(np.interp(case.cell_temperature_k.time_s,trace.time_s,trace.temperature_k)),provenance=source))
            dataset=ElectrothermalDataset(prepared.dataset.fit_rates,cases)
            prepared=replace(prepared,dataset=dataset,signatures=build_electrothermal_signatures(config,dataset))
        result=run_electrothermal_fixed_candidates(prepared,candidates,session.path/'validation',simulator=backend,budget=controller)
        result['total_actual_solver_calls_including_generation']=controller.calls
        session.write_json('smoke-summary.json',result);session.finish('completed',result);return result
    except Exception as exc:
        session.finish('failed',{'message':str(exc),'actual_solver_calls':controller.calls});raise
