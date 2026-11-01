"""Cold-spawn four-arm worker. Scientific modules are imported only in run_worker."""
from copy import deepcopy
from pathlib import Path
import json
import os
import sys
import time

ARMS={'A00':('numeric','parego'),'A10':('llm_v3','warmstart_only'),
      'A01':('numeric','full_llmbo_mo'),'A11':('llm_v3','full_llmbo_mo')}
RULE='pareto_quality_gated_spacefill_v3'


def config_for(base,*,kind,arm,seed,rounds,initial=None,software=False):
    if kind not in ('numeric','llm_v3','arm') or (kind=='arm' and (arm not in ARMS or not initial)):
        raise ValueError('explicit factorial mode and signed initial plan required')
    cfg=deepcopy(base);opt=cfg['optimization']
    opt.update(seed=seed,initial_count=8,total_candidate_budget=8+rounds,region_method='lgbo_v2',
               mode=ARMS[arm][1] if kind=='arm' else 'parego' if kind=='numeric' else 'warmstart_only')
    opt.pop('initial_plan',None)
    if initial:opt['initial_plan']={k:initial[k] for k in ('path','sha256')}
    opt['warmstart'].update(count=8,pool_size=16,max_requests=3,max_candidates=48,max_evaluations=16,selection_rule=RULE)
    api=(rounds if ARMS[arm][1]=='full_llmbo_mo' else 0) if kind=='arm' else (3 if kind=='llm_v3' else 0)
    # Complete sixteen initial pairs; up to 64 unique attempts is an algorithmic
    # liveness guard, not a spending allowance. Failed attempts remain archived.
    cfg['budgets']={'max_solver_calls':2*rounds if kind=='arm' else 128,'max_llm_requests':api,'wall_clock_s':21600.}
    cfg['llm']['enabled']=bool(api);cfg['llm']['warmstart_preheader_tls_eof_continue']=False
    cfg['llm']['warmstart_wire_format']='candidate_only_v1'
    if software:
        cfg['model']['provider']='software';cfg['run_kind']='synthetic_software';cfg['llm']['enabled']=False
        cfg['budgets']['max_solver_calls']=cfg['budgets']['max_llm_requests']=0
        opt.update(gp_sweeps=0,global_pool_size=16,local_pool_size=8)
    return cfg


def complete_pool(proposals,fill,*,evaluate,valid,key,target=16):
    """A small reusable bounded completion primitive, without duplicate evaluations."""
    records=[];seen=set()
    for stream,origin in ((proposals,'proposal'),(fill,'sobol_fill')):
        for point in stream:
            if len(records)==target:return records
            try:p=valid(point);ident=key(p)
            except (ValueError,TypeError):continue
            if ident in seen:continue
            seen.add(ident);r=evaluate(p,origin)
            if not (r.get('complete_pair_valid') if isinstance(r,dict) else r.complete_pair_valid):raise ValueError('incomplete pool evaluation')
            records.append(r)
    if len(records)!=target:raise ValueError('incomplete candidate pool')
    return records


def _controller(prepared,budget,*,software,kind,seed):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from run_lgbo_real_gain import check_payload
    class CheckedController(ElectrothermalLLMController):
        def request(self,payload,**kwargs):
            check_payload(payload)
            return super().request(payload,**kwargs)
    class SoftwareReply:
        def post(self,payload):
            if payload['task']=='warm_start_electrothermal':
                from llmbo_para.sobol import Sobol6
                # Fifteen repeatedly offered points deliberately exercise the missing-point path.
                points=[prepared.space.denormalize(x) for x in Sobol6(seed*1024+64).draw(15)]
                return {'candidates':[{'parameters':dict(zip((s.name for s in prepared.space.specs),p))} for p in points]}
            from llmbo_para.electrothermal_lgbo_wire import lgbo_request_id
            return {'request_id':lgbo_request_id(payload),'region':{'kind':'region','lb':[.15]*6,'ub':[.85]*6,'confidence':.65}}
    c=CheckedController(transport=SoftwareReply() if software else None,is_mock=software)
    c.prepared=prepared;c.execution_budget=budget
    return c


def initialize_pool(spec,prepared,store,budget,backend):
    from dataclasses import asdict,replace
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_llm import build_electrothermal_payload,warmstart_selection_details
    from llmbo_para.electrothermal_warmstart_wire import decode_candidate_only_reply
    from llmbo_para.electrothermal_provenance import write_initial_plan,load_initial_plan,candidate_key
    from llmbo_para.sobol import Sobol6
    from llmbo_para.runstore import sha256_file
    evaluator=ElectrothermalEvaluator(prepared.space,backend,fit_rates=prepared.dataset.fit_rates,max_rate_attempts=1,stop_on_failure=True)
    records=[];origins=[];seen=set();rejections=[];count_returned=0
    def complete_count():return sum(r.complete_pair_valid for r in records)
    def reject(origin,reason):
        rejections.append({'origin':origin,'reason':reason})
        store.ledger.record({'event_id':f'factorial-screen:{len(rejections)}','kind':'screening_rejected','reason':reason,'origin':origin})
    def accept(point,origin):
        try:p=prepared.space.validate(point);key=candidate_key(p,prepared.space.profile,prepared.signatures)
        except (TypeError,ValueError):reject(origin,'invalid');return
        if key in seen:reject(origin,'duplicate');return
        if complete_count()>=16 or len(records)>=64:return
        budget.require_candidate(0 if spec['software_fixture'] else len(prepared.dataset.fit_rates))
        result=evaluator.evaluate(p,prepared.dataset);store.save_evaluation(result,phase='warmstart_screening' if origin['kind']=='llm' else 'factorial_numeric')
        seen.add(key);records.append(replace(result,signatures=asdict(prepared.signatures)))
        origins.append({'evaluation_id':result.evaluation_id,**origin})
    if spec['kind']=='llm_v3':
        controller=_controller(prepared,budget,software=spec['software_fixture'],kind='llm_v3',seed=spec['seed'])
        for attempt in range(3):
            if complete_count()>=16 or len(records)>=64 or count_returned>=48:break
            payload=build_electrothermal_payload('warm_start_electrothermal',prepared=prepared,history=records)
            payload['sampling_request']={'remaining_unique_candidates':16-complete_count(),'require_novel_parameters':True}
            response=controller.request(payload,prepared=prepared,store=store,budgets=prepared.config['budgets'],request_cap=3)
            if response is None:continue
            try:proposals=decode_candidate_only_reply(response,prepared=prepared,expected_request=response.request)
            except (ValueError,TypeError):reject({'request':attempt},'invalid_reply');continue
            for index,item in enumerate(proposals[:48-count_returned]):
                if complete_count()>=16 or len(records)>=64:break
                try:
                    if set(item)!= {'parameters'} or set(item['parameters'])!={s.name for s in prepared.space.specs}:raise ValueError('named parameters required')
                    p=[item['parameters'][s.name] for s in prepared.space.specs]
                except (TypeError,KeyError,ValueError):reject({'request':attempt,'index':index},'invalid_proposal');continue
                accept(p,{'kind':'llm','request':controller.requests-1,'index':index})
            count_returned+=len(proposals)
    start=spec['seed']*1024+(256 if spec['kind']=='llm_v3' else 0)
    sobol=Sobol6(start)
    for index in range(128):
        if complete_count()>=16 or len(records)>=64:break
        x=sobol.draw(1)[0]
        try:p=prepared.space.denormalize(x)
        except ValueError:continue
        accept(p,{'kind':'sobol_fill' if spec['kind']=='llm_v3' else 'sobol','index':start+index})
    if complete_count()!=16:raise ValueError('sixteen complete unique pool points required')
    details=warmstart_selection_details(records,space=prepared.space,count=8,objective_scales=prepared.config['optimization']['objective_scales'],rho_aug=.05,rule=RULE)
    selected={r.evaluation_id:r for r in records}
    evidence={'origin_run_id':store.run_id,'screening_records':[r.to_dict() for r in records],
              'selection':details,'cost_events':list(store.ledger.events.values()),'costs':store.ledger.summary()}
    path=store.path/'initial-plan.json'
    write_initial_plan(path,[selected[i] for i in details['selected_ids']],signatures=prepared.signatures,history_evidence=evidence)
    checked=load_initial_plan(path,space=prepared.space,dataset=prepared.dataset,signatures=prepared.signatures,expected_selection_rule=RULE)
    store.write_json('factorial-initialization.json',{'kind':spec['kind'],'origins':origins,'rejections':rejections,'selection':details,
                     'sobol_fill_count':sum(x['kind']=='sobol_fill' for x in origins),'request_count':len(list((store.path/'llm').glob('*.payload.json')))})
    return {'status':'completed','kind':spec['kind'],'plan_path':str(path),'plan_sha256':checked.plan_sha256,
            'plan_file_sha256':sha256_file(path),'pool_count':16,'attempted_pool_points':len(records),'selected_ids':details['selected_ids'],
            'costs':store.ledger.summary(),'run_directory':str(store.path)}


def run_formal(spec,prepared,store,budget,backend):
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.mo_optimizer import MOOptimizer
    from llmbo_para.runstore import sha256_file
    import shutil
    src=Path(spec['initial']['path']);dest=store.path/'inputs/initial-plan.json';dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    if sha256_file(dest)!=spec['initial']['sha256']:raise ValueError('initial plan copy differs')
    controller=_controller(prepared,budget,software=spec['software_fixture'],kind='arm',seed=spec['seed']) if ARMS[spec['arm']][1]=='full_llmbo_mo' else None
    evaluator=ElectrothermalEvaluator(prepared.space,backend,fit_rates=prepared.dataset.fit_rates,max_rate_attempts=1,stop_on_failure=True)
    optimizer=MOOptimizer(prepared.space,evaluator,prepared.dataset,store,prepared.config['optimization'],
                          initial_plan=prepared.initial_plan,llm_controller=controller,execution_budget=budget)
    summary=optimizer.optimize(8+spec['rounds'])
    evidence=prepared.initial_plan.history_evidence
    summary.update(initial_plan_sha256=prepared.initial_plan.plan_sha256,initialization_cost_attribution={
        'origin_run_id':evidence['origin_run_id'],'historical_costs':evidence['costs'],'included_in_current_costs':False,
        'plan_sha256':prepared.initial_plan.plan_sha256,'status':'verified_history'})
    return {'status':'completed','seed':spec['seed'],'arm':spec['arm'],'BO_rounds':summary['BO_rounds'],
            'selected_ids':[r.evaluation_id for r in prepared.initial_plan.records],
            'initial_file_sha':sha256_file(src),'summary':summary,'costs':store.ledger.summary(),'run_directory':str(store.path)}


def run_worker(spec,connection):
    for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'):os.environ[name]='1'
    os.environ['PYBAMM_DISABLE_TELEMETRY']='true';sys.dont_write_bytecode=True
    if any(n=='llmbo_para' or n.startswith('llmbo_para.') for n in sys.modules):raise RuntimeError('worker source was not cold')
    root=Path(spec['source_root']);sys.path.insert(0,str(root/'src'));store=None
    try:
        from llmbo_para.electrothermal_provenance import source_fingerprint
        if source_fingerprint(root)!=spec['source']:raise ValueError('scientific source changed')
        from lgbo_real_gain_worker import RPCBudget,_attach_api_charges
        from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment,make_electrothermal_backend
        from llmbo_para.electrothermal_store import ElectrothermalRunStore
        from llmbo_para.electrothermal_audit import audit_electrothermal_run
        cfg=config_for(spec['base_config'],kind=spec['kind'],arm=spec.get('arm'),seed=spec['seed'],rounds=spec['rounds'],initial=spec.get('initial'),software=spec['software_fixture'])
        report,prepared=prepare_electrothermal_experiment(cfg,base_dir=root)
        if prepared is None:raise ValueError('preparation failed: '+';'.join(report['errors']))
        budget=RPCBudget(connection,deadline=spec['deadline'],maximum=cfg['budgets']['max_solver_calls'],prefix=spec['label'])
        backend=make_electrothermal_backend(cfg,budget=budget)
        store=ElectrothermalRunStore(spec['output'],cfg,dataset=prepared.dataset,signatures=prepared.signatures,
                                    command='electrothermal multiobjective BO' if spec['kind']=='arm' else 'factorial initialization')
        _attach_api_charges(store,budget)
        store.write_json('source-execution-pin.json',{'source_root':str(root),'source_fingerprint':spec['source'],
                         'factorial_kind':spec['kind'],'arm':spec.get('arm'),'rounds':spec['rounds']})
        result=run_formal(spec,prepared,store,budget,backend) if spec['kind']=='arm' else initialize_pool(spec,prepared,store,budget,backend)
        store.write_json('electrothermal-summary.json',result.get('summary',result));store.finish('completed',result.get('summary',result))
        audit=audit_electrothermal_run(store.path,deep=True);store.write_json('audit.json',audit)
        if not audit['passed']:raise ValueError('deep audit failed: '+str(audit.get('errors')))
        result['audit_passed']=True
        from et_factorial_budget import atomic_json
        atomic_json(Path(spec['output'])/'worker-result.json',result);connection.send(('result',result))
    except Exception as exc:
        failure={'status':'failed','error_type':type(exc).__name__,'reason':str(exc),'run_directory':str(store.path) if store else None}
        if store and not (store.path/'terminal.json').exists():store.finish('failed',failure)
        from et_factorial_budget import atomic_json
        atomic_json(Path(spec['output'])/'worker-failure.json',failure);connection.send(('error',type(exc).__name__))
    finally:connection.close()
