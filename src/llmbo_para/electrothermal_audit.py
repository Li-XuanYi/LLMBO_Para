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


def _audit_responses_warmstart(root,*,cfg,space,dataset,signatures,events,by_id,read,require,equal):
    """Replay reply-to-screening provenance, without evaluating a model."""
    from types import SimpleNamespace
    from .electrothermal_llm import validate_warmstart_response
    from .electrothermal_provenance import candidate_key
    saved_path=root/'warmstart-selection.json'
    if not saved_path.exists():return
    selection=read('warmstart-selection.json');settings=cfg['optimization']['warmstart']
    prepared=SimpleNamespace(space=space,dataset=dataset,signatures=signatures)
    requests=[(i,e) for i,e in enumerate(events) if e.get('type')=='electrothermal_cost'
        and e.get('kind') in ('llm_request','mock_llm_request')]
    warm=[(i,e) for i,e in requests if e.get('phase')=='warm_start_electrothermal']
    processed=[];seen=set();returned=0;screening_ids=set()
    for position,(start,cost) in enumerate(warm):
        n=int(cost['event_id'].split(':')[1]);outcome=read(f'llm/{n:06d}.outcome.json')
        end=next((i for i,_ in requests if i>start),len(events))
        actual=[]
        for e in events[start+1:end]:
            if e.get('type')=='electrothermal_evaluation_saved' and e.get('phase')=='warmstart_screening':
                actual.append(('evaluation',e));screening_ids.add(e['relative'])
            elif e.get('type')=='electrothermal_cost' and (e.get('event_id','').startswith('screen:')
                    or e.get('event_id','').startswith('cache:')):actual.append(('cost',e))
        if outcome['status']!='received':
            require(not actual,'failed Responses WarmStart reply produced screening results');continue
        receipt=read(f'llm/{n:06d}.responses-formal.json')
        require(set(receipt)=={'version','response_json'} and receipt['version']=='responses_formal_v1',
                'Responses WarmStart formal receipt is invalid')
        reply=json.loads(receipt['response_json'])
        try:proposals=validate_warmstart_response(reply,prepared=prepared)
        except ValueError:
            expected={'event_id':f'screen:reply:{n+1}','kind':'screening_rejected','reason':'invalid_reply'}
            equal([{k:v for k,v in e.items() if k not in ('type','timestamp_utc')} for _,e in actual],
                  [expected],'invalid WarmStart envelope screening differs');continue
        remaining=settings['max_candidates']-returned;returned+=len(proposals);cursor=0
        for index,proposal in enumerate(proposals[:max(0,remaining)]):
            if len(processed)>=settings['max_evaluations'] or sum(r.complete_pair_valid for r in processed)>=settings['pool_size']:break
            # Timing/reservation stops can leave an unprocessed suffix, but can
            # never manufacture evaluations or jump over a preceding proposal.
            if cursor==len(actual) and position==len(warm)-1 and selection['stop_reason'] in ('wall_clock_budget','insufficient_solver_reservation'):break
            require(cursor<len(actual),'WarmStart reply processing evidence is missing')
            kind,event=actual[cursor];cursor+=1
            try:
                if not isinstance(proposal,dict) or set(proposal)!={'parameters'} or not isinstance(proposal['parameters'],dict) or set(proposal['parameters'])!={s.name for s in space.specs}:
                    raise ValueError('invalid named parameters')
                point=space.validate([proposal['parameters'][s.name] for s in space.specs])
                key=candidate_key(point,space.profile,signatures)
            except (ValueError,TypeError):
                require(kind=='cost','invalid WarmStart candidate was evaluated')
                equal({k:v for k,v in event.items() if k not in ('type','timestamp_utc')},
                    {'event_id':f'screen:{n+1}:{index}','kind':'screening_rejected','reason':'invalid_candidate'},
                    'WarmStart invalid-candidate screening differs');continue
            if key in seen:
                require(kind=='cost','duplicate WarmStart candidate was evaluated')
                equal({k:v for k,v in event.items() if k not in ('type','timestamp_utc')},
                    {'event_id':f'cache:{n+1}:{index}','kind':'cache_hit','phase':'warmstart'},
                    'WarmStart duplicate cost differs');continue
            require(kind=='evaluation','valid unique WarmStart candidate was not evaluated in reply order')
            record=by_id[event['evaluation_id']]
            equal(record.parameters,point,'WarmStart evaluated parameters differ from formal reply')
            require(event.get('cached') is False,'unique WarmStart candidate falsely marked cached')
            seen.add(key);processed.append(record)
        require(cursor==len(actual),'WarmStart screening results have no corresponding reply candidate')
    equal(sorted(screening_ids),sorted(e['relative'] for e in events if e.get('type')=='electrothermal_evaluation_saved'
        and e.get('phase')=='warmstart_screening'),'orphan WarmStart screening evaluation')
    equal(selection['pool_ids'],sorted(r.evaluation_id for r in processed if r.complete_pair_valid),'WarmStart pool provenance differs')
    equal(selection['returned_candidates'],returned,'WarmStart returned candidate count differs')
    equal(selection['evaluations'],len(processed),'WarmStart evaluation count differs')
    equal(selection['requests'],len(warm),'WarmStart request count differs')
    require(len(warm)<=settings['max_requests'] and len(processed)<=settings['max_evaluations'],
            'WarmStart processing exceeded configured budgets')


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
        from .electrothermal_requests import request_controls,completion_summary
        transport_kind=cfg['llm'].get('transport','openai_chat_completions')
        if transport_kind=='openai_responses':
            request_ids={int(p.name.split('.')[0]) for p in (root/'llm').glob('*.payload.json')}
            outcome_ids={int(p.name.split('.')[0]) for p in (root/'llm').glob('*.outcome.json')}
            equal(sorted(request_ids),sorted(outcome_ids),'Responses request/outcome coverage differs')
            equal(sorted(request_ids),list(range(len(request_ids))),'Responses request ordinals are not contiguous')
            equal(sorted(request_ids),sorted(int(e['event_id'].split(':')[1]) for e in cost_events.values()
                if e['kind'] in ('llm_request','mock_llm_request')),'Responses request/cost coverage differs')
        controlled=False
        for file in sorted((root/'llm').glob('*.outcome.json')):
            outcome=json.loads(file.read_text(encoding='utf8'));controls=request_controls(cfg,outcome['task'])
            if 'thinking' in controls:
                equal(outcome.get('thinking'),controls['thinking'],'request thinking control differs');controlled=True
            payload=read('llm/'+file.name.replace('.outcome.json','.payload.json'));artifact=payload['artifact_task']
            if transport_kind=='openai_responses':
                n=int(file.name.split('.')[0])
                equal(outcome.get('ordinal'),n,'Responses request ordinal differs')
                equal(artifact,outcome['task']+'_request_'+'a'*(n+1),'Responses artifact task differs')
            request_path=root/'http'/(artifact+'.request.json');response=root/'http'/(artifact+'.response.json')
            supervision_path=root/'http'/(artifact+'.supervision.json')
            if transport_kind=='openai_responses' and (outcome['status']=='received' or outcome.get('reason') in ('invalid_catalog_response','invalid_lgbo_response')):
                live_cost=any(e.get('type')=='electrothermal_cost' and e.get('event_id')==f'llm:{n}'
                    and e.get('kind')=='llm_request' for e in events)
                if live_cost:
                    require(request_path.is_file() and response.is_file() and supervision_path.is_file(),
                            'received Responses request lacks raw HTTP supervision evidence')
                    require((root/'llm'/file.name.replace('.outcome.json','.responses-formal.json')).is_file(),
                            'received Responses request lacks formal receipt')
            started=any(e.get('type')=='llm_http_started' and e.get('task')==artifact for e in events)
            has_http=started or request_path.exists() or response.exists()
            if has_http or outcome.get('hard_deadline_enforced') and outcome.get('http_request_started'):
                request=read('http/'+artifact+'.request.json')['body']
                supervision=read('http/'+artifact+'.supervision.json') if supervision_path.exists() else {}
                if transport_kind=='openai_responses':
                    from types import SimpleNamespace
                    from .electrothermal_responses import responses_request_body
                    from .electrothermal_region_wire import region_wire_payload
                    from .electrothermal_region_catalog import decode_catalog_http_response,catalog_archival_json
                    require(outcome.get('hard_deadline_enforced') is True and outcome.get('http_request_started') is True,
                            'Responses HTTP supervision flags differ')
                    equal(outcome.get('response_protocol'),transport_kind,'Responses outcome protocol differs')
                    equal(supervision.get('response_protocol'),transport_kind,'Responses supervision protocol differs')
                    equal(supervision.get('configured_timeout_s'),controls['timeout_s'],'Responses supervised timeout differs')
                    equal(supervision.get('max_tokens'),controls['max_tokens'],'Responses supervised output ceiling differs')
                    archived_request=read('http/'+artifact+'.request.json')
                    equal(archived_request.get('endpoint'),cfg['llm']['endpoint'],'Responses endpoint differs')
                    require(not any(str(k).lower()=='authorization' for k in archived_request.get('headers',{})),
                            'Responses archive contains authorization header')
                    equal(payload['signatures'],asdict(signatures),'Responses request signatures differ')
                    equal(payload['fit_rates'],dataset.fit_rates,'Responses request rate set differs')
                    if outcome['task']=='warm_start_electrothermal':
                        from .electrothermal_llm import build_electrothermal_payload
                        past=[]
                        for e in events:
                            if e.get('type')=='electrothermal_cost' and e.get('event_id')==f'llm:{outcome["ordinal"]}':break
                            if e.get('type')=='electrothermal_evaluation_saved' and e.get('phase')=='warmstart_screening':past.append(by_id[e['evaluation_id']])
                        expected=build_electrothermal_payload(outcome['task'],
                            prepared=SimpleNamespace(config=cfg,space=space,dataset=dataset,signatures=signatures),history=past)
                        expected['instructions']=(root/'source/src/llmbo_para/prompts/warm_start_electrothermal.txt').read_text(encoding='utf8')
                        expected['artifact_task']=artifact
                        equal(payload,expected,'independently rebuilt Responses WarmStart request differs')
                    frozen_payload=json.loads(canonical_json(payload)) if payload.get('region_proposal')=='catalog_v1' or payload.get('region_method')=='lgbo_v1' else payload
                    expected_body=responses_request_body(region_wire_payload(frozen_payload),model=cfg['llm']['model'],
                        max_tokens=controls['max_tokens'],json_mode=cfg['llm']['json_mode'])
                    equal(request,expected_body,'Responses final HTTP request differs')
                    formal_path=root/'llm'/file.name.replace('.outcome.json','.responses-formal.json')
                    needs_formal=outcome['status']=='received' or outcome.get('reason') in ('invalid_catalog_response','invalid_lgbo_response')
                    if response.exists():
                        decoded,issue=decode_catalog_http_response(json.loads(response.read_text(encoding='utf8')),
                            payload=payload,transport=transport_kind)
                        if needs_formal:
                            require(issue is None,'Responses received reply is not complete or request-bound')
                            evidence=json.loads(formal_path.read_text(encoding='utf8'))
                            require(set(evidence)=={'version','response_json'} and evidence['version']=='responses_formal_v1',
                                    'Responses formal receipt version differs')
                            equal(evidence['response_json'],catalog_archival_json(decoded),'Responses formal receipt differs from raw HTTP')
                        else:
                            require(not formal_path.exists(),'orphan Responses formal receipt')
                            if outcome.get('reason')=='protocol_error' or outcome.get('protocol_issue') is not None:
                                require(issue is not None,'valid Responses reply has an impossible protocol failure')
                                if 'protocol_issue' in outcome:equal(outcome['protocol_issue'],issue,'Responses protocol failure differs from raw HTTP')
                                if 'protocol_issue' in supervision:equal(supervision['protocol_issue'],issue,'Responses supervised protocol failure differs')
                                error_path=root/'http'/(artifact+'.parse-error.json')
                                if error_path.exists():equal(json.loads(error_path.read_text(encoding='utf8'))['protocol_issue'],issue,'Responses parse error differs')
                    else:require(not needs_formal and not formal_path.exists(),'Responses received reply has no raw HTTP evidence')
                if 'thinking' in controls or 'completion' in outcome or 'completion' in supervision:
                    require(outcome.get('http_request_started') is True,'HTTP start flag contradicts wire evidence')
                    if supervision_path.exists():require(outcome.get('hard_deadline_enforced') is True,'bounded flag contradicts supervision evidence')
                if 'thinking' in controls:
                    equal(request.get('thinking'),{'type':controls['thinking']},'sent thinking control differs')
                    equal(supervision.get('thinking'),controls['thinking'],'supervised thinking control differs')
                    equal(request.get('max_tokens'),controls['max_tokens'],'sent output ceiling differs')
                    equal(supervision.get('configured_timeout_s'),controls['timeout_s'],'supervised timeout differs')
                if response.exists() and (transport_kind=='openai_responses' or 'thinking' in controls or 'completion' in outcome or 'completion' in supervision):
                    expected=completion_summary(json.loads(response.read_text(encoding='utf8')),controls['max_tokens'],transport=transport_kind)
                    equal(outcome.get('completion'),expected,'completion evidence differs from raw response')
                    equal(supervision.get('completion'),expected,'supervised completion evidence differs');controlled=True
        if controlled:checks.append('LLM_sent_controls_and_raw_completion_evidence')
        if transport_kind=='openai_responses':
            _audit_responses_warmstart(root,cfg=cfg,space=space,dataset=dataset,signatures=signatures,
                events=events,by_id=by_id,read=read,require=require,equal=equal)
            checks.append('Responses_reply_to_WarmStart_screening_provenance')
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
            opt=cfg['optimization'];scheduler=WeightScheduler(opt['weights'],opt['seed'])
            lgbo=opt.get('region_method')=='lgbo_v1'
            settings=None if lgbo else InformedSettings.parse(opt['region'])
            trust=None if lgbo else settings.trust_init
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
                if event.get('region') is not None and lgbo:
                    from types import SimpleNamespace
                    from .electrothermal_lgbo_audit import audit_lgbo_round
                    c=MORoundContext(context,dataset.fit_rates,canonical_json(asdict(signatures)).decode(),
                        canonical_json(state).decode(),tuple(map(tuple,pool)),ordinal,saved['context_id'])
                    checked=audit_lgbo_round(root,event=event,context=c,gp=gp,history=history,
                        prepared=SimpleNamespace(config=cfg,space=space,dataset=dataset,signatures=signatures),
                        cost_events=cost_events)
                    for ident in checked['request_ordinals']:
                        require(ident not in region_request_references,'LGBO request referenced more than once')
                        region_request_references.add(ident)
                    index=checked['selected_index']
                elif event.get('region') is not None:
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
                                allowed=('disabled','global_budget','task_budget','missing_mock_transport')
                                if transport_kind=='openai_responses':allowed+=('missing_credential',)
                                require(outcome.get('reason') in allowed,'invalid active Region skip reason')
                                if outcome.get('reason')=='missing_credential':
                                    require(cfg['llm']['enabled'] is True and cfg['budgets']['max_llm_requests']>0
                                        and outcome.get('http_request_started') is False and outcome.get('hard_deadline_enforced') is False,
                                        'invalid missing-credential request flags or configuration')
                                    require(any(e.get('type')=='electrothermal_llm_skipped'
                                        and e.get('context_id')==saved['context_id'] and e.get('reason')=='missing_credential' for e in events),
                                        'missing-credential skip event is absent')
                                    require(not any(e.get('phase')=='region_preference_electrothermal'
                                        and read(f'llm/{int(e["event_id"].split(":")[1]):06d}.payload.json').get('context_id')==saved['context_id']
                                        for e in cost_events.values() if e['kind'] in ('llm_request','mock_llm_request')),
                                        'missing-credential skip has a request cost')
                            if outcome.get('status') in ('received','failed'):require('ordinal' in outcome,'Region request is missing ordinal')
                    if outcome is not None:
                        equal(outcome.get('context_id'),saved['context_id'],'request outcome context differs')
                        if 'ordinal' in outcome:
                            n=outcome['ordinal'];require(type(n) is int and n>=0,'invalid request ordinal')
                            equal(read(f'llm/{n:06d}.outcome.json'),outcome,'independent request outcome differs')
                            payload=read(f'llm/{n:06d}.payload.json')
                            require(payload['task']=='region_preference_electrothermal' and payload['context_id']==saved['context_id'],'request payload context differs')
                            require(cost_events.get(f'llm:{n}',{}).get('phase')==payload['task'],'request outcome lacks matching cost event')
                            if opt.get('region_evidence','legacy_v1') in ('signed_residual_v1','decision_geometry_v2','dynamic_decision_v3'):
                                from .electrothermal_residuals import residual_evidence_contract,signed_record_summary
                                equal(payload.get('history_evidence'),residual_evidence_contract(),'signed residual evidence contract differs')
                                past={r.evaluation_id:r for r in history};seen=set()
                                for row in payload['history']:
                                    ident=row['evaluation_id'];require(ident in past and ident not in seen,'signed residual evidence is not past-only unique history')
                                    seen.add(ident);equal(row.get('signed_residuals'),signed_record_summary(past[ident]),'signed residual evidence differs from curves')
                                require(bool(seen) and context.incumbent_id in seen,'signed residual evidence omits current incumbent')
                                prompt='region_preference_residual_electrothermal'
                                if opt.get('region_evidence') in ('decision_geometry_v2','dynamic_decision_v3'):
                                    from .electrothermal_region_evidence import build_region_decision_evidence
                                    scalar_by_id=dict(zip(context.observation_ids,context.raw_labels))
                                    top=sorted(context.observation_ids,key=lambda i:(scalar_by_id[i],i))[:4]
                                    extremes=[min(history,key=lambda r:(r.objectives[j],r.evaluation_id)) for j in range(2)]
                                    selected={r.evaluation_id:r for r in [*[past[i] for i in top],*extremes,*history[-3:]]}
                                    expected_ids=list(selected)
                                    equal([r['evaluation_id'] for r in payload['history']],expected_ids,'decision history selection or order differs')
                                    equal(payload.get('decision_evidence'),build_region_decision_evidence(c,
                                        advice=advice,settings=settings,observation_ids=expected_ids),'Region decision evidence differs')
                                    for row in payload['history']:
                                        actual=selected[row['evaluation_id']]
                                        expected_row={'evaluation_id':actual.evaluation_id,'parameters':actual.parameters,
                                            'objectives':actual.objectives,'complete_pair_valid':actual.complete_pair_valid,
                                            'rates':{q.rate:{'voltage_valid':q.voltage.valid,'temperature_valid':q.cell_temperature.valid,
                                                'rmse_v':q.voltage.rmse_v,'rmse_k':q.cell_temperature.rmse_k,
                                                'failure':q.cell_temperature.reason or q.voltage.reason} for q in actual.rates},
                                            'normalized_parameters':[round(float(x),6) for x in space.normalize(actual.parameters)],
                                            'current_scalar_g':scalar_by_id[actual.evaluation_id],
                                            'signed_residuals':signed_record_summary(actual)}
                                        if opt.get('region_evidence')=='dynamic_decision_v3':
                                            from .electrothermal_dynamic_evidence import dynamic_record_summary
                                            expected_row['dynamic_residuals']=dynamic_record_summary(actual)
                                        equal(row,expected_row,'decision history row differs')
                                    prompt='region_preference_decision_electrothermal'
                                    if opt.get('region_evidence')=='dynamic_decision_v3':
                                        from .electrothermal_dynamic_evidence import dynamic_evidence_contract
                                        equal(payload.get('dynamic_history_evidence'),dynamic_evidence_contract(),'dynamic residual evidence contract differs')
                                        prompt=('region_preference_action_electrothermal' if cfg['llm'].get('region_wire_format')=='compact_action_v2'
                                            else 'region_preference_catalog_electrothermal') if opt.get('region_proposal')=='catalog_v1' else 'region_preference_dynamic_electrothermal'
                                equal(payload['instructions'],(root/('source/src/llmbo_para/prompts/'+prompt+'.txt')).read_text(encoding='utf8'),'signed evidence prompt differs')
                            if advice_mode=='candidate_aware_v1':
                                require(n not in region_request_references,'Region request referenced more than once')
                                region_request_references.add(n)
                                equal(payload['candidate_advice'],advice,'request candidate advice differs')
                                equal(payload['region_requirements'],candidate_region_requirements(settings,selection_mode=selection_mode),'request Region gates differ')
                                equal(payload['signatures'],asdict(signatures),'request signatures differ')
                            if opt.get('region_proposal')=='catalog_v1':
                                from types import SimpleNamespace
                                from .electrothermal_llm import build_electrothermal_payload
                                from .electrothermal_region_catalog import catalog_proposal_binding,catalog_region_contract,resolve_catalog_region,catalog_archival_json,decode_catalog_http_response
                                from .electrothermal_region_wire import region_wire_payload,decode_region_wire
                                expected=build_electrothermal_payload('region_preference_electrothermal',
                                    prepared=SimpleNamespace(config=cfg,space=space,dataset=dataset,signatures=signatures),
                                    history=history,context=c)
                                catalog_prompt=('region_preference_action_electrothermal' if cfg['llm'].get('region_wire_format')=='compact_action_v2'
                                    else 'region_preference_catalog_electrothermal')
                                expected['instructions']=(root/('source/src/llmbo_para/prompts/'+catalog_prompt+'.txt')).read_text(encoding='utf8')
                                expected['proposal_binding']=catalog_proposal_binding(expected)
                                expected['response_contract']['properties']['region']=catalog_region_contract(expected)
                                expected['artifact_task']=expected['task']+'_request_'+'a'*(n+1)
                                # Rebuild the exact JSON-native request frozen by
                                # the controller, before comparing clone or wire
                                # evidence. Scientific host values may be tuples
                                # or NumPy scalars; model replies remain strict.
                                expected=json.loads(canonical_json(expected))
                                equal(payload,expected,'independently rebuilt catalog request differs')
                                raw_path=root/f'llm/{n:06d}.catalog-response.json'
                                resolution_path=root/f'llm/{n:06d}.catalog-resolution.json'
                                mutation_path=root/f'llm/{n:06d}.catalog-mutation.json'
                                needs_reply=outcome['status']=='received' or outcome.get('reason')=='invalid_catalog_response'
                                if needs_reply:
                                    raw=read(f'llm/{n:06d}.catalog-response.json')
                                    require(set(raw)=={'version','response_json'} and raw['version']=='catalog_response_v1'
                                        and isinstance(raw['response_json'],str),'formal catalog reply evidence missing')
                                    proposed=json.loads(raw['response_json'])
                                    if mutation_path.exists():
                                        mutation=read(f'llm/{n:06d}.catalog-mutation.json')
                                        require(set(mutation)=={'version','sent_payload_json'} and mutation['version']=='catalog_mutation_v1'
                                            and isinstance(mutation['sent_payload_json'],str),'invalid transport mutation evidence')
                                        sent_clone=json.loads(mutation['sent_payload_json'])
                                        require(isinstance(sent_clone,dict),'transport clone must remain a request object')
                                        require(catalog_archival_json(sent_clone)!=catalog_archival_json(expected),
                                            'transport mutation evidence does not show a changed request')
                                    try:
                                        if mutation_path.exists():
                                            raise ValueError('transport mutated the frozen catalog request')
                                        canonical,resolution=resolve_catalog_region(proposed,payload=expected)
                                    except ValueError:
                                        require(outcome['status']=='failed' and outcome['reason']=='invalid_catalog_response'
                                            and event['region']['response'] is None and not resolution_path.exists(),'invalid catalog reply was not rejected')
                                    else:
                                        require(outcome['status']=='received','valid catalog reply has unexplained failure')
                                        equal(read(f'llm/{n:06d}.catalog-resolution.json'),resolution,'catalog resolution differs from original reply')
                                        canonical['region']['reason']='structured_region_response'
                                        equal(event['region']['response'],canonical,'canonical catalog response differs')
                                else:
                                    require(not raw_path.exists() and not resolution_path.exists() and not mutation_path.exists(),'orphan catalog reply or resolution')
                                artifact=expected['artifact_task']
                                if (root/'http'/(artifact+'.request.json')).exists():
                                    wire=region_wire_payload(expected);request=read('http/'+artifact+'.request.json')['body']
                                    if transport_kind=='openai_responses':
                                        equal(request,responses_request_body(wire,model=cfg['llm']['model'],
                                            max_tokens=request_controls(cfg,payload['task'])['max_tokens'],json_mode=cfg['llm']['json_mode']),
                                            'catalog Responses HTTP request differs')
                                    else:
                                        equal(json.loads(request['messages'][1]['content']),{k:v for k,v in wire.items() if k!='instructions'},'catalog HTTP request differs')
                                        instructions=wire['instructions']+('\nReturn exactly one JSON object matching the supplied response contract.' if cfg['llm']['json_mode'] else '')
                                        equal(request['messages'][0]['content'],instructions,'catalog HTTP instructions differ')
                                    http_response=root/'http'/(artifact+'.response.json')
                                    if http_response.exists():
                                        provider,issue=decode_catalog_http_response(read('http/'+artifact+'.response.json'),payload=expected,transport=transport_kind)
                                        if outcome.get('reason')=='protocol_error':
                                            require(outcome['status']=='failed' and issue is not None,'claimed catalog protocol failure contradicts HTTP reply')
                                            if 'protocol_issue' in outcome:equal(outcome['protocol_issue'],issue,'catalog protocol failure category differs')
                                            parse_error=root/'http'/(artifact+'.parse-error.json')
                                            if parse_error.exists():equal(read('http/'+artifact+'.parse-error.json')['protocol_issue'],issue,'catalog parse error differs from HTTP reply')
                                        if needs_reply:
                                            require(issue is None,'catalog HTTP completion or binding differs')
                                            require(catalog_archival_json(provider)==catalog_archival_json(proposed),
                                                'formal catalog reply differs from HTTP response')
                                    else:require(not needs_reply,'catalog HTTP formal reply is missing')
                            if opt.get('region_proposal','bounds_v1')!='catalog_v1' and (transport_kind=='openai_responses' or cfg['llm'].get('region_wire_format','full_v1')=='compact_v1') and outcome.get('hard_deadline_enforced') and outcome.get('http_request_started'):
                                from .electrothermal_region_wire import region_wire_payload,decode_region_wire
                                if cfg['llm'].get('region_wire_format','full_v1')=='compact_v1':require(payload.get('region_wire_format')=='compact_v1','compact Region payload marker differs')
                                artifact=payload['artifact_task'];wire=region_wire_payload(payload)
                                request=read('http/'+artifact+'.request.json')['body']
                                if transport_kind=='openai_responses':
                                    equal(request,responses_request_body(wire,model=cfg['llm']['model'],
                                        max_tokens=request_controls(cfg,payload['task'])['max_tokens'],json_mode=cfg['llm']['json_mode']),
                                        'compact Responses HTTP request differs')
                                else:
                                    equal(json.loads(request['messages'][1]['content']),{k:v for k,v in wire.items() if k!='instructions'},'compact Region HTTP request differs')
                                    instructions=wire['instructions']+('\nReturn exactly one JSON object matching the supplied response contract.' if cfg['llm']['json_mode'] else '')
                                    equal(request['messages'][0]['content'],instructions,'compact Region HTTP instructions differ')
                                if outcome['status']=='received':
                                    if transport_kind=='openai_responses':
                                        from .electrothermal_region_catalog import decode_catalog_http_response
                                        decoded,issue=decode_catalog_http_response(read('http/'+artifact+'.response.json'),payload=payload,transport=transport_kind)
                                        require(issue is None,'compact Responses completion or binding differs')
                                    else:
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
            if advice_mode=='candidate_aware_v1' or lgbo:
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
                if lgbo:
                    expected_diagnostics.update(valid_actions=sum(r['action_valid'] for r in regions),
                        tilt_applied=sum(r['tilt_applied'] for r in regions),
                        selection_changed=sum(r['selection_changed'] for r in regions))
                equal(summary['region_diagnostics'],expected_diagnostics,'Region request/adoption summary differs')
            checks.append('past_only_context_labels_GP_EI_Region_Pareto_HV')
        terminal=read('terminal.json');equal(terminal['summary'],summary,'terminal/summary mismatch')
        require(terminal['status'] in ('completed','completed_with_failures'),'run not completed')
    except (ValueError,KeyError,TypeError,OSError,IndexError) as exc:issues.append(str(exc))
    return {'passed':not issues,'issues':issues,'checks':checks,'deep':deep,'run_directory':str(root),'solver_calls_made':0,'API_calls':0}
