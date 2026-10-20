"""Read-only v2 audit from archived curves, physical metadata and past history."""
from dataclasses import asdict
import json
import math
from pathlib import Path
import numpy as np
from .config import parameter_space_from_config
from .electrothermal_config import electrothermal_configuration_errors
from .electrothermal_data import dataset_from_dict
from .electrothermal_evaluation import result_from_dict
from .electrothermal_provenance import build_electrothermal_signatures,verify_evaluation,load_initial_plan
from .electrothermal_store import CostLedger
from .runstore import digest_value,sha256_file,canonical_json


def audit_electrothermal_run(run_directory,*,deep=False):
    root=Path(run_directory).resolve();issues=[];checks=[]
    def read(name):return json.loads((root/name).read_text(encoding='utf8'))
    def require(condition,message):
        if not condition:raise ValueError(message)
    def equal(a,b,message):require(digest_value(a)==digest_value(b),message)
    try:
        manifest=read('manifest.json');cfg=manifest['config']
        require(not electrothermal_configuration_errors(cfg),'archived v2 configuration invalid')
        equal(digest_value(cfg),manifest['config_sha256'],'configuration hash mismatch')
        hashes=read('source-sha256.json');require(bool(hashes),'empty source snapshot')
        for relative,expected in hashes.items():
            file=(root/'source'/relative).resolve()
            require(file.is_relative_to(root/'source') and file.is_file() and sha256_file(file)==expected,'source snapshot differs: '+relative)
        dataset=dataset_from_dict(read('electrothermal-input.json'));space=parameter_space_from_config(cfg)
        signatures=build_electrothermal_signatures(cfg,dataset,source_root=root/'source')
        equal(read('electrothermal-signatures.json'),asdict(signatures),'semantic signature mismatch')
        equal(manifest['data_sha256'],{'electrothermal_dataset':dataset.data_signature},'data digest mismatch');checks.append('config_source_data_protocol')
        files=sorted((root/'electrothermal-evaluations').glob('*.json'));records=[];by_id={}
        events=[json.loads(line) for line in (root/'events.jsonl').read_text(encoding='utf8').splitlines() if line.strip()]
        saved_events=[e for e in events if e.get('type')=='electrothermal_evaluation_saved']
        require(len(saved_events)==len(files),'evaluation archive/reference count differs')
        references={e['relative']:e for e in saved_events}
        for file in files:
            raw_record=json.loads(file.read_text(encoding='utf8'));reference=references[file.relative_to(root).as_posix()]
            equal(digest_value(raw_record),reference['content_sha256'],'full curve/evaluation content fingerprint differs')
            record=result_from_dict(raw_record);space.validate(record.parameters)
            verify_evaluation(record,dataset);equal(record.signatures,asdict(signatures),'evaluation signatures differ')
            for row in record.rates:
                if row.trace is None:continue
                mapping=row.trace['applied_parameters']
                if cfg['model']['provider']=='software':equal(mapping,{'kind':'analytic_software_fixture'},'software trace has unexpected physical mapping')
                else:
                    theta=dict(zip((s.name for s in space.specs),record.parameters));native=mapping['native'];fixed=cfg['fixed'];law=cfg['property_law']
                    equal(mapping['theta'],theta,'parameter mapping theta differs')
                    expected={'Cell heat capacity [J.K-1.m-3]':theta['C_th']/fixed['cell_volume_m3'],
                              'Total heat transfer coefficient [W.m-2.K-1]':theta['G_th']/fixed['cooling_area_m2'],
                              'Cell volume [m3]':fixed['cell_volume_m3'],'Cell cooling surface area [m2]':fixed['cooling_area_m2'],
                              'Negative electrode active material volume fraction':theta['eps_s_n'],'Positive electrode active material volume fraction':theta['eps_s_p'],
                              'Negative electrode conductivity [S.m-1]':fixed['negative_conductivity_s_m'],'Positive electrode conductivity [S.m-1]':fixed['positive_conductivity_s_m'],
                              'Negative electrode porosity':fixed['negative_porosity'],'Positive electrode porosity':fixed['positive_porosity']}
                    equal(native,expected,'native C/V or G/A or fixed mapping differs')
                    equal(mapping['fixed_sources'],fixed['sources'],'fixed physical sources differ')
                    for name,short in (('Negative','n'),('Positive','p')):
                        item=mapping['diffusivity_laws'][name+' particle diffusivity [m2.s-1]']
                        equal(item,{'kind':law['kind'],'reference_value':theta['D_s_'+short+'_ref'],'reference_temperature_k':law['reference_temperature_k'],
                                    'activation_energy_j_mol':law['activation_energy_'+short+'_j_mol'],'source':law['sources']['activation_energy_'+short+'_j_mol']},'temperature diffusivity law differs')
            if record.evaluation_id in by_id:
                previous=by_id[record.evaluation_id]
                equal([record.parameters,record.objectives,record.to_dict()['rates']],[previous.parameters,previous.objectives,previous.to_dict()['rates']],'conflicting evaluation identity')
            by_id[record.evaluation_id]=record;records.append(record)
        checks.append('raw_curves_independent_RMSE_and_native_mapping')
        ledger=CostLedger();cost_events={}
        for e in events:
            if e.get('type')=='electrothermal_cost':
                clean={k:v for k,v in e.items() if k not in ('type','timestamp_utc')};ledger.record(clean);cost_events[clean['event_id']]=clean
        expected_actual=set()
        for file,record in zip(files,records):
            relative=file.relative_to(root).as_posix();cache=cost_events.get(relative+':cache')
            if cache is not None:
                require(cache['kind']=='cache_hit' and cache['source_evaluation_id']==record.evaluation_id,'invalid cache cost reference');continue
            for row in record.rates:
                for a in row.attempts:
                    ident=relative+':'+a['event_id'];e=cost_events.get(ident);require(e is not None,'missing actual evaluation cost')
                    kind=a['type'] if a['type']!='solver_call' or a.get('solver_calls',1) else 'preparation_failure'
                    require(e['kind']==kind and e['rate']==row.rate and e['outcome']==a['status'],'evaluation cost differs');expected_actual.add(ident)
        require(all(e['event_id'] in expected_actual for e in cost_events.values() if e['kind'] in ('solver_call','software_call','preparation_failure')),'orphan actual evaluation cost')
        require(len(list((root/'llm').glob('*.payload.json')))==sum(e['kind'] in ('llm_request','mock_llm_request') for e in cost_events.values()),'LLM payload/request count differs')
        summary=read('electrothermal-summary.json');equal(summary['costs'],ledger.summary(),'summary costs differ');checks.append('actual_cache_screening_request_costs')
        round_files=sorted((root/'mo-rounds').glob('*.json'))
        if manifest['command']=='electrothermal multiobjective BO' or 'BO_rounds' in summary or round_files:
            require((root/'initialization.json').is_file(),'required MO initialization archive is missing')
        if (root/'initialization.json').exists():
            initial=read('initialization.json');selected=initial['selected_ids'];history=[by_id[i] for i in selected]
            require(len(history)>=2 and all(r.complete_pair_valid for r in history),'invalid initialization')
            if initial.get('kind')=='imported_plan':
                planfile=root/'initial-plan.json' if (root/'initial-plan.json').exists() else root/'inputs/initial-plan.json'
                plan=load_initial_plan(planfile,space=space,dataset=dataset,signatures=signatures)
                equal(plan.plan_sha256,initial['plan_sha256'],'shared initialization plan digest differs')
                equal(selected,[r.evaluation_id for r in plan.records],'selected plan IDs differ')
                evidence=plan.history_evidence
                equal(summary['initialization_cost_attribution'],{'origin_run_id':evidence['origin_run_id'] if evidence else None,
                    'historical_costs':evidence['costs'] if evidence else None,'included_in_current_costs':bool(evidence and evidence['origin_run_id']==manifest['run_id']),
                    'plan_sha256':plan.plan_sha256,'status':'verified_history' if evidence else 'not_applicable_or_not_supplied'},'initialization historical cost attribution differs')
            if (root/'warmstart-selection.json').exists():
                from .electrothermal_llm import warmstart_selection_details
                saved=read('warmstart-selection.json');pool=[by_id[i] for i in saved['pool_ids']]
                details=warmstart_selection_details(pool,space=space,count=cfg['optimization']['initial_count'],objective_scales=cfg['optimization']['objective_scales'],rho_aug=cfg['optimization']['rho_aug'])
                for key,value in details.items():equal(saved[key],value,'WarmStart selection differs: '+key)
            from .scalarization import WeightScheduler,build_scalarization_context
            from .surrogate import Matern52GP
            from .acquisition import gaussian_ei
            from .informed import InformedSettings
            from .mo_optimizer import MORoundContext
            from .electrothermal_llm import apply_electrothermal_region,update_electrothermal_trust
            opt=cfg['optimization'];scheduler=WeightScheduler(opt['weights'],opt['seed']);settings=InformedSettings.parse(opt['region']);trust=settings.trust_init
            advice_mode=opt.get('region_advice','legacy_v1');region_request_references=set()
            selection_mode=opt.get('region_selection','global_lift_v1')
            for ordinal,file in enumerate(round_files,1):
                event=json.loads(file.read_text(encoding='utf8'));saved=event['context'];weights=scheduler.next()
                y=np.asarray([r.objectives for r in history]);w=np.asarray(weights);a=w*(y/np.asarray(opt['objective_scales']));raw=a.max(axis=1)+opt['rho_aug']*a.sum(axis=1)
                mean=float(raw.mean());std=float(raw.std());std=1. if std<1e-12 else std;labels=(raw-mean)/std
                require(np.allclose(saved['scalarization']['raw_labels'],raw,rtol=0,atol=1e-12) and np.allclose(saved['scalarization']['labels'],labels,rtol=0,atol=1e-12),'independent scalar labels differ')
                context=build_scalarization_context([space.normalize(r.parameters) for r in history],y,[r.evaluation_id for r in history],
                    weights=weights,objective_scales=opt['objective_scales'],rho_aug=opt['rho_aug'],protocol_signature=signatures.comparison_protocol)
                equal(saved['scalarization'],context.to_dict(),'frozen scalarization context differs')
                equal(saved['signatures'],asdict(signatures),'round signatures differ');equal(saved['fit_rates'],dataset.fit_rates,'round rates differ');equal(saved['ordinal'],ordinal,'round ordinal differs')
                context_base={k:v for k,v in saved.items() if k!='context_id'};equal(saved['context_id'],digest_value(context_base),'round context fingerprint differs')
                state=saved['gp_state'];equal(state['x'],context.x,'GP x differs');equal(state['y'],context.labels,'GP labels differ')
                require(state['group']==[] and state['lengthscale_prior'] is None,'new MO must use plain ARD kernel')
                gp=Matern52GP(max_sweeps=opt['gp_sweeps']).fit(context.x,context.labels,group=()) if deep else Matern52GP.from_state(state)
                if deep:equal(gp.state_dict(),state,'fresh GP posterior differs')
                pool=saved['pool'];m,s=gp.predict(pool);ei=gaussian_ei(m,s,context.best)
                for key,expected in (('mean',m),('std',s),('ei',ei)):require(np.allclose(event[key],expected,rtol=1e-11,atol=1e-12),'Gaussian acquisition differs: '+key)
                index=int(np.argmax(ei));record=by_id[event['evaluation_id']]
                require(np.allclose(space.normalize(record.parameters),pool[event['selected_index']],rtol=0,atol=1e-12),'selected parameters differ')
                weighted=w*(np.asarray(record.objectives)/np.asarray(opt['objective_scales'])) if record.complete_pair_valid else None
                new=float(weighted.max()+opt['rho_aug']*weighted.sum()) if weighted is not None else None
                feedback=event['feedback'];equal(feedback['context_id'],saved['context_id'],'feedback context differs')
                equal(feedback['previous_best'],float(raw.min()),'frozen incumbent differs');equal(feedback['new_scalar'],new,'frozen feedback scalar differs')
                require(feedback['improved']==(new is not None and new<float(raw.min())),'improvement differs')
                if advice_mode=='candidate_aware_v1' and opt['mode']=='full_llmbo_mo':
                    require(isinstance(event.get('region'),dict),'candidate-aware round requires Region precheck evidence')
                if event.get('region') is not None:
                    c=MORoundContext(context,dataset.fit_rates,canonical_json(asdict(signatures)).decode(),canonical_json(state).decode(),tuple(map(tuple,pool)),ordinal,saved['context_id'])
                    outcome=event['region'].get('request_outcome')
                    if advice_mode=='candidate_aware_v1':
                        from .electrothermal_region_advice import build_region_candidate_advice,candidate_region_requirements
                        advice=build_region_candidate_advice(c,space=space,settings=settings)
                        equal(event['region']['candidate_advice'],advice,'Region candidate advice differs')
                        require(isinstance(outcome,dict),'candidate-aware Region requires request outcome')
                        require(outcome.get('status') in ('received','failed','skipped'),'invalid Region request status')
                        require(('ordinal' in outcome)==(outcome['status'] in ('received','failed')),'Region request ordinal/status differs')
                        if ordinal>=settings.active_until:
                            equal(outcome,{'status':'skipped','reason':'inactive','context_id':saved['context_id']},'inactive Region outcome differs')
                        elif not advice['eligible_alternative_count']:
                            equal(outcome,{'task':'region_preference_electrothermal','context_id':saved['context_id'],
                                           'status':'skipped','reason':'no_eligible_alternative'},'no-alternative Region outcome differs')
                        else:
                            require(outcome.get('reason')!='no_eligible_alternative','false no-alternative skip')
                            if outcome['status']=='skipped':
                                require(outcome.get('reason') in ('disabled','global_budget','task_budget','missing_mock_transport'),'invalid active Region skip reason')
                            if outcome.get('status') in ('received','failed'):require('ordinal' in outcome,'Region request is missing ordinal')
                    if outcome is not None:
                        equal(outcome.get('context_id'),saved['context_id'],'request outcome context differs')
                        if 'ordinal' in outcome:
                            n=outcome['ordinal'];require(type(n) is int and n>=0,'invalid request ordinal')
                            equal(read(f'llm/{n:06d}.outcome.json'),outcome,'independent request outcome differs')
                            payload=read(f'llm/{n:06d}.payload.json')
                            require(payload['task']=='region_preference_electrothermal' and payload['context_id']==saved['context_id'],'request payload context differs')
                            require(cost_events.get(f'llm:{n}',{}).get('phase')==payload['task'],'request outcome lacks matching cost event')
                            if advice_mode=='candidate_aware_v1':
                                require(n not in region_request_references,'Region request referenced more than once')
                                region_request_references.add(n)
                                equal(payload['candidate_advice'],advice,'request candidate advice differs')
                                equal(payload['region_requirements'],candidate_region_requirements(settings,selection_mode=selection_mode),'request Region gates differ')
                                equal(payload['signatures'],asdict(signatures),'request signatures differ')
                            if cfg['llm'].get('region_wire_format','full_v1')=='compact_v1' and outcome.get('hard_deadline_enforced') and outcome.get('http_request_started'):
                                from .electrothermal_region_wire import region_wire_payload,decode_region_wire
                                require(payload.get('region_wire_format')=='compact_v1','compact Region payload marker differs')
                                artifact=payload['artifact_task'];wire=region_wire_payload(payload)
                                request=read('http/'+artifact+'.request.json')['body']
                                equal(json.loads(request['messages'][1]['content']),{k:v for k,v in wire.items() if k!='instructions'},'compact Region HTTP request differs')
                                instructions=wire['instructions']+('\nReturn exactly one JSON object matching the supplied response contract.' if cfg['llm']['json_mode'] else '')
                                equal(request['messages'][0]['content'],instructions,'compact Region HTTP instructions differ')
                                if outcome['status']=='received':
                                    choice=read('http/'+artifact+'.response.json')['choices'][0]
                                    require(choice.get('finish_reason')=='stop','compact Region completion unfinished')
                                    decoded=decode_region_wire(json.loads(choice['message']['content']),payload)
                                    from .electrothermal_llm import validate_electrothermal_region
                                    try:checked=validate_electrothermal_region(decoded,expected_context_id=saved['context_id'],expected_signatures=asdict(signatures))
                                    except (ValueError,TypeError,KeyError):require(event['region']['response'] is None,'invalid compact Region was accepted')
                                    else:
                                        checked['region']['reason']='structured_region_response'
                                        equal(event['region']['response'],checked,'compact Region decoded response differs')
                    request_details={'request_outcome':event['region']['request_outcome']} if 'request_outcome' in event['region'] else {}
                    region=apply_electrothermal_region(gp,c,pool,event['region']['response'],settings=settings,trust=trust,space=space,
                        advice_mode=advice_mode,selection_mode=selection_mode,**request_details)
                    equal(region,event['region'],'Region-Lift replay differs');index=region['selected_index']
                    tf=update_electrothermal_trust(c,record,previous_trust=trust,beta=settings.trust_beta,adoption={'accepted':region['accepted'],'cached':feedback['cached']})
                    equal(tf,feedback['trust'],'frozen trust feedback differs');trust=tf['trust_after']
                require(event['selected_index']==index,'EI selection differs')
                if record.complete_pair_valid and tuple(record.parameters) not in {tuple(r.parameters) for r in history}:history.append(record)
            if advice_mode=='candidate_aware_v1':
                actual_region_requests={int(e['event_id'].split(':')[1]) for e in cost_events.values()
                    if e['kind'] in ('llm_request','mock_llm_request') and e.get('phase')=='region_preference_electrothermal'}
                equal(sorted(region_request_references),sorted(actual_region_requests),'orphan Region request cost')
            from .pareto import pareto_indices,hypervolume_2d
            front=pareto_indices([r.objectives for r in history]);expected=[{'evaluation_id':history[i].evaluation_id,'parameters':history[i].parameters,'objectives':history[i].objectives} for i in front]
            equal(summary['pareto'],expected,'Pareto parameter set differs');equal(summary['HV'],hypervolume_2d([r.objectives for r in history],objective_scales=opt['objective_scales'],reference_point=opt['hv_reference']),'fixed HV differs')
            require(summary['complete_pairs']==len(history) and summary['BO_rounds']==len(round_files),'history summary differs')
            if 'region_diagnostics' in summary:
                from collections import Counter
                regions=[json.loads(f.read_text(encoding='utf8'))['region'] for f in round_files]
                regions=[r for r in regions if r is not None];outcomes=[r.get('request_outcome') or {} for r in regions]
                expected_diagnostics={'rounds':len(regions),'request_attempts':sum('ordinal' in o for o in outcomes),
                    'responses':sum(o.get('status')=='received' or not o and r['response'] is not None for r,o in zip(regions,outcomes)),
                    'accepted':sum(r['accepted'] for r in regions),'request_failures':sum(o.get('status')=='failed' for o in outcomes),
                    'fallback_counts':dict(Counter(r['fallback_reason'] for r in regions if r['fallback_reason'] is not None))}
                equal(summary['region_diagnostics'],expected_diagnostics,'Region request/adoption summary differs')
            checks.append('past_only_context_labels_GP_EI_Region_Pareto_HV')
        terminal=read('terminal.json');equal(terminal['summary'],summary,'terminal/summary mismatch')
        require(terminal['status'] in ('completed','completed_with_failures'),'run not completed')
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:issues.append(str(exc))
    return {'passed':not issues,'issues':issues,'checks':checks,'deep':deep,'run_directory':str(root),'solver_calls_made':0,'API_calls':0}
