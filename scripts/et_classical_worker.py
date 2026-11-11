"""Cold DFN worker for locked external policies and native ParEGO-16."""
from copy import deepcopy
from pathlib import Path
import json
import os
import sys

METHODS=('parego16','nsga2','smpso')
RULE='pareto_quality_gated_spacefill_v3'


def config_for(base,*,seed,rounds,software):
    cfg=deepcopy(base);opt=cfg['optimization']
    opt.update(seed=seed,initial_count=16,total_candidate_budget=16+rounds,mode='parego')
    opt.pop('initial_plan',None)
    opt['warmstart'].update(count=16,pool_size=16,max_evaluations=16,selection_rule=RULE)
    cfg['llm']['enabled']=False
    cfg['budgets']={'max_solver_calls':0 if software else 2*rounds,'max_llm_requests':0,'wall_clock_s':21600.}
    if software:
        cfg['model']['provider']='software';cfg['run_kind']='synthetic_software'
        opt.update(gp_sweeps=0,global_pool_size=16,local_pool_size=8)
    return cfg


def derive_initial_plan(pool,prepared,path,*,software,backend):
    """Explicit checked migration of initialization semantics, never old-cache relaxation."""
    from dataclasses import asdict,replace
    from analyze_et_factorial_validation import verify_pool
    from llmbo_para.electrothermal_evaluation import result_from_dict,ElectrothermalEvaluator
    from llmbo_para.electrothermal_llm import warmstart_selection_details
    from llmbo_para.electrothermal_provenance import write_initial_plan,load_initial_plan
    from llmbo_para.electrothermal_store import CostLedger
    from llmbo_para.runstore import digest_value,sha256_file
    original=verify_pool(pool);target=asdict(prepared.signatures)
    records=[result_from_dict(r) for r in original]
    if len(records)!=16 or not all(r.complete_pair_valid for r in records):raise ValueError('sixteen complete verified numeric inputs required')
    original_plan=json.loads(Path(pool['plan_path']).read_text(encoding='utf8'))
    evidence=deepcopy(original_plan['history_evidence'])
    if software:
        evaluator=ElectrothermalEvaluator(prepared.space,backend,fit_rates=prepared.dataset.fit_rates,max_rate_attempts=1,stop_on_failure=True)
        records=[evaluator.evaluate(r.parameters,prepared.dataset) for r in records]
        costs=CostLedger()
        for i,r in enumerate(records):
            for rate in r.rates:
                for attempt in rate.attempts:
                    costs.record({'event_id':f'software-initial:{i}:'+attempt['event_id'],'kind':attempt['type'],
                                  'rate':rate.rate,'outcome':attempt['status'],'elapsed_s':attempt['elapsed_s']})
        evidence.update(origin_run_id='software-only-initial-recalculation',cost_events=list(costs.events.values()),costs=costs.summary())
    else:
        for r in records:
            for k in ('data','model_evaluation','evaluation_protocol','comparison_protocol','source','fit_rates'):
                a=r.signatures[k];b=target[k]
                if digest_value(a)!=digest_value(b):raise ValueError('physical signature migration forbidden: '+k)
    records=[replace(r,signatures=target) for r in records]
    details=warmstart_selection_details(records,space=prepared.space,count=16,
        objective_scales=prepared.config['optimization']['objective_scales'],rho_aug=.05,rule=RULE)
    by={r.evaluation_id:r for r in records}
    ordered=[by[i] for i in details['selected_ids']]
    evidence.update(screening_records=[r.to_dict() for r in records],selection=details)
    write_initial_plan(path,ordered,signatures=prepared.signatures,history_evidence=evidence)
    checked=load_initial_plan(path,space=prepared.space,dataset=prepared.dataset,signatures=prepared.signatures,expected_selection_rule=RULE)
    bridge={'kind':'derived_full16_plan_v1','source_plan':pool['plan_path'],'source_plan_sha256':sha256_file(pool['plan_path']),
        'original_pool':pool,'original_record_digests':[digest_value(r) for r in original],
        'target_initialization_compatibility':target['initialization_compatibility'],
        'ordered_ids':[r.evaluation_id for r in checked.records],'software_recalculation':software}
    return checked,bridge


def external_loop(spec,prepared,store,evaluator,budget):
    from dataclasses import replace
    import queue
    import subprocess
    import threading
    import time
    from llmbo_para.electrothermal_provenance import candidate_key
    from llmbo_para.runstore import digest_value
    initial=prepared.initial_plan.records
    cache={candidate_key(r.parameters,prepared.space.profile,prepared.signatures):r for r in initial}
    for r in initial:store.save_evaluation(r,phase='initial_plan',cached=True)
    store.write_json('initialization.json',{'status':'completed','kind':'imported_plan',
        'plan_sha256':prepared.initial_plan.plan_sha256,'selected_ids':[r.evaluation_id for r in initial]})
    policy_spec={'method':spec['method'],'seed':spec['seed'],'rounds':spec['rounds'],
                 'initial_x':[list(prepared.space.normalize(r.parameters)) for r in initial]}
    store.write_json('baseline-policy-input.json',policy_spec)
    policy=Path(spec['source_root'])/'scripts/et_classical_policy.py'
    allowed={'SYSTEMROOT','WINDIR','TEMP','TMP','PATH','PATHEXT','COMSPEC'}
    env={k:v for k,v in os.environ.items() if k.upper() in allowed}
    new=[];q=queue.Queue()
    with (store.path/'baseline-policy-stderr.log').open('x',encoding='utf8') as errorlog:
        process=subprocess.Popen([spec['policy_python'],'-u',str(policy)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=errorlog,
            text=True,encoding='utf8',env=env)
        def reader():
            for line in process.stdout:q.put(line)
            q.put(None)
        thread=threading.Thread(target=reader,daemon=True);thread.start()
        def send(value):process.stdin.write(json.dumps(value,allow_nan=False)+'\n');process.stdin.flush()
        try:
            send(policy_spec);ordinal=0
            while True:
                timeout=min(120.,spec['deadline']-time.monotonic())
                if timeout<=0:raise TimeoutError('external policy deadline')
                line=q.get(timeout=timeout)
                if line is None:raise RuntimeError('policy closed without terminal message')
                message=json.loads(line)
                if message['type']=='completed':
                    process.wait(timeout=10)
                    if process.returncode or len(new)!=spec['rounds']:raise ValueError('external policy stopped before exact budget')
                    store.write_json('baseline-policy-terminal.json',message)
                    return new,message['state']
                if message['type']!='evaluate':raise ValueError('external policy failure: '+str(message))
                if message['ordinal']!=ordinal:raise ValueError('external proposal order differs')
                p=prepared.space.denormalize(message['x']);key=candidate_key(p,prepared.space.profile,prepared.signatures)
                if ordinal<16 and key!=candidate_key(initial[ordinal].parameters,prepared.space.profile,prepared.signatures):
                    raise ValueError('official initial population differs from signed plan')
                cached=key in cache
                if cached:result=cache[key]
                else:
                    if len(new)>=spec['rounds']:raise ValueError('policy exceeded new-evaluation count')
                    budget.require_candidate(0 if spec['software_fixture'] else len(prepared.dataset.fit_rates))
                    result=replace(evaluator.evaluate(p,prepared.dataset),evaluation_id='baseline-'+key[:32])
                    store.save_evaluation(result,phase='external_baseline');cache[key]=result;new.append(result)
                    store.write_json(f'baseline-rounds/{len(new):06d}.json',{'evaluation_id':result.evaluation_id,
                        'proposal_ordinal':ordinal,'normalized_x':message['x'],'complete_pair_valid':result.complete_pair_valid})
                objective=None if not result.complete_pair_valid else [a/b for a,b in zip(result.objectives,prepared.config['optimization']['objective_scales'])]
                feedback={'complete_pair_valid':result.complete_pair_valid,'objectives':objective,'cached':cached,'evaluation_id':result.evaluation_id}
                store.write_json(f'baseline-policy-events/{ordinal:06d}.json',{'proposal':message,'feedback':feedback,'content_sha256':digest_value([message,feedback])})
                send(feedback);ordinal+=1
        finally:
            if process.poll() is None:process.kill()
            process.wait(timeout=10)
            process.stdin.close();process.stdout.close();thread.join(timeout=2)


def run_worker(spec,connection):
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
    os.environ['PYBAMM_DISABLE_TELEMETRY']='true';sys.dont_write_bytecode=True
    if any(n=='llmbo_para' or n.startswith('llmbo_para.') for n in sys.modules):raise RuntimeError('baseline worker is not cold')
    root=Path(spec['source_root']);sys.path[:0]=[str(root/'src'),str(root/'scripts')];store=None
    try:
        from dataclasses import asdict
        from et_factorial_budget import atomic_json
        from lgbo_real_gain_worker import RPCBudget
        from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment,make_electrothermal_backend
        from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
        from llmbo_para.electrothermal_provenance import source_fingerprint
        from llmbo_para.electrothermal_store import ElectrothermalRunStore
        from llmbo_para.electrothermal_audit import audit_electrothermal_run
        from llmbo_para.runstore import sha256_file
        if source_fingerprint(root)!=spec['source']:raise ValueError('scientific source changed')
        cfg=config_for(spec['base_config'],seed=spec['seed'],rounds=spec['rounds'],software=spec['software_fixture'])
        report,prepared=prepare_electrothermal_experiment(cfg,base_dir=root)
        if prepared is None:raise ValueError('baseline configuration: '+str(report['errors']))
        budget=RPCBudget(connection,deadline=spec['deadline'],maximum=cfg['budgets']['max_solver_calls'],prefix=spec['label'])
        backend=make_electrothermal_backend(cfg,budget=budget)
        inputs=Path(spec['output'])/'inputs';inputs.mkdir(exist_ok=False)
        path=inputs/'full16-plan.json'
        _,bridge=derive_initial_plan(spec['pool'],prepared,path,software=spec['software_fixture'],backend=backend)
        cfg['optimization']['initial_plan']={'path':str(path),'sha256':sha256_file(path)}
        report,prepared=prepare_electrothermal_experiment(cfg,base_dir=root)
        if prepared is None:raise ValueError('derived plan configuration: '+str(report['errors']))
        store=ElectrothermalRunStore(spec['output'],cfg,dataset=prepared.dataset,signatures=prepared.signatures,
            command='electrothermal multiobjective BO' if spec['method']=='parego16' else 'external electrothermal baseline')
        import shutil
        archived_plan=store.path/'inputs/initial-plan.json'
        archived_plan.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(path,archived_plan)
        if sha256_file(archived_plan)!=sha256_file(path):raise ValueError('initial plan archive differs')
        store.write_json('baseline-initialization-bridge.json',bridge)
        store.write_json('baseline-contract.json',{k:spec[k] for k in ('method','seed','rounds','policy_python','policy_environment')})
        evaluator=ElectrothermalEvaluator(prepared.space,backend,fit_rates=prepared.dataset.fit_rates,max_rate_attempts=1,stop_on_failure=True)
        if spec['method']=='parego16':
            from llmbo_para.mo_optimizer import MOOptimizer
            summary=MOOptimizer(prepared.space,evaluator,prepared.dataset,store,cfg['optimization'],
                initial_plan=prepared.initial_plan,execution_budget=budget).optimize(16+spec['rounds'])
        else:
            records,state=external_loop(spec,prepared,store,evaluator,budget)
            from llmbo_para.pareto import pareto_indices,hypervolume_2d
            initial=list(prepared.initial_plan.records)
            front=pareto_indices([r.objectives for r in initial])
            summary={'external_rounds':len(records),'method':spec['method'],'policy_state':state,
                'audit_summary_scope':'initialization_only',
                'pareto':[{'evaluation_id':initial[i].evaluation_id,'parameters':initial[i].parameters,
                           'objectives':initial[i].objectives} for i in front],
                'HV':hypervolume_2d([r.objectives for r in initial],objective_scales=cfg['optimization']['objective_scales'],
                                    reference_point=cfg['optimization']['hv_reference']),
                'complete_pairs':len(initial),'BO_rounds':0,'costs':store.ledger.summary()}
        evidence=prepared.initial_plan.history_evidence
        summary['initialization_cost_attribution']={'origin_run_id':evidence['origin_run_id'],'historical_costs':evidence['costs'],
            'included_in_current_costs':False,'plan_sha256':prepared.initial_plan.plan_sha256,'status':'verified_history'}
        store.write_json('electrothermal-summary.json',summary);store.finish('completed',summary)
        proof=audit_electrothermal_run(store.path,deep=True);store.write_json('audit.json',proof)
        if not proof['passed']:raise ValueError('baseline deep audit: '+str(proof.get('issues')))
        result={'status':'completed','seed':spec['seed'],'method':spec['method'],'rounds':spec['rounds'],
            'run_directory':str(store.path),'costs':store.ledger.summary(),'audit_passed':True,'summary':summary,
            'ordered_ids':[r.evaluation_id for r in prepared.initial_plan.records],'plan_sha256':prepared.initial_plan.plan_sha256}
        atomic_json(Path(spec['output'])/'worker-result.json',result);connection.send(('result',result))
    except Exception as exc:
        from et_factorial_budget import atomic_json
        failure={'status':'failed','error_type':type(exc).__name__,'reason':str(exc),'run_directory':str(store.path) if store else None}
        if store and not (store.path/'terminal.json').exists():store.finish('failed',failure)
        atomic_json(Path(spec['output'])/'worker-failure.json',failure);connection.send(('error',type(exc).__name__))
    finally:connection.close()
