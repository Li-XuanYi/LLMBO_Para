"""Electrothermal-only LLM contracts, bounded requests and Pareto/diversity seeds."""
from dataclasses import asdict
from pathlib import Path
import json
import time
import numpy as np
from .scalarization import augmented_tchebycheff
from .pareto import pareto_indices
from .electrothermal_provenance import candidate_key,write_initial_plan,load_initial_plan
from .runstore import digest_value


def warmstart_selection_details(records,*,space,count,objective_scales,rho_aug=.05):
    if type(count) is not int or count<2:raise ValueError('at least two seeds required')
    ids={};unique={};duplicates={}
    for record in records:
        if record.evaluation_id in ids and digest_value(ids[record.evaluation_id].to_dict())!=digest_value(record.to_dict()):raise ValueError('conflicting evaluation ID')
        ids[record.evaluation_id]=record
        if not record.complete_pair_valid:continue
        if record.parameter_profile!=space.profile:raise ValueError('wrong parameter profile')
        point=space.validate(record.parameters)
        unique.setdefault(point,[]).append(record)
    pool=[]
    for point,group in unique.items():
        group.sort(key=lambda r:r.evaluation_id);pool.append(group[0]);duplicates[group[0].evaluation_id]=[r.evaluation_id for r in group[1:]]
    pool.sort(key=lambda r:r.evaluation_id)
    if pool and len({(r.data_signature,tuple(r.fit_rates),digest_value(r.signatures)) for r in pool})!=1:raise ValueError('mixed candidate pool semantics')
    x={r.evaluation_id:tuple(space.normalize(r.parameters)) for r in pool}
    q={r.evaluation_id:float(augmented_tchebycheff([r.objectives],[.5,.5],objective_scales,rho_aug=rho_aug)[0]) for r in pool}
    remaining=pool[:];selected=[];steps=[];rank=0;ranks={}
    while remaining:
        front=[remaining[i] for i in pareto_indices([r.objectives for r in remaining])]
        for r in front:ranks[r.evaluation_id]=rank
        layer=front[:]
        while layer and len(selected)<count:
            distances={r.evaluation_id:min((float(np.linalg.norm(np.asarray(x[r.evaluation_id])-x[s])/np.sqrt(6)) for s in selected),default=0.) for r in layer}
            key=lambda r:((-distances[r.evaluation_id],) if selected else ())+ (q[r.evaluation_id],x[r.evaluation_id],r.evaluation_id)
            chosen=min(layer,key=key);i=chosen.evaluation_id
            steps.append({'selected_id':i,'rank':rank,'distance':distances[i],'ordering_key':key(chosen)});selected.append(i);layer.remove(chosen)
        remaining=[r for r in remaining if r.evaluation_id not in {f.evaluation_id for f in front}];rank+=1
    return {'rule':'pareto_maximin_v1','selected_ids':selected,'ranks':ranks,'quality':q,'normalized_parameters':x,
            'duplicates':duplicates,'steps':steps,'objective_scales':list(objective_scales),'rho_aug':rho_aug,'pool_ids':[r.evaluation_id for r in pool]}


def select_electrothermal_warmstart(records,*,space,count,objective_scales,rho_aug=.05):
    return tuple(warmstart_selection_details(records,space=space,count=count,objective_scales=objective_scales,rho_aug=rho_aug)['selected_ids'])


def build_electrothermal_payload(task,*,prepared,history,context=None):
    if task not in ('warm_start_electrothermal','region_preference_electrothermal'):raise ValueError('unknown electrothermal LLM task')
    cfg=prepared.config;valid=[r for r in history if r.complete_pair_valid]
    front=[valid[i] for i in pareto_indices([r.objectives for r in valid])]
    selected={r.evaluation_id:r for r in [*front[:8],*history[-8:]]}
    rows=[{'evaluation_id':r.evaluation_id,'parameters':list(r.parameters),'objectives':r.objectives,'complete_pair_valid':r.complete_pair_valid,
           'objective_components':r.objective_components,'rates':{q.rate:{'voltage_valid':q.voltage.valid,'temperature_valid':q.cell_temperature.valid,
           'rmse_v':q.voltage.rmse_v,'rmse_k':q.cell_temperature.rmse_k,'failure':q.cell_temperature.reason or q.voltage.reason} for q in r.rates}} for r in selected.values()]
    payload={'task':task,'schema_version':2,'parameter_profile':prepared.space.profile,'fit_rates':list(prepared.dataset.fit_rates),
        'signatures':asdict(prepared.signatures),'parameters':[{'name':s.name,'unit':s.unit,'lower':s.lower,'upper':s.upper,'transform':s.transform} for s in prepared.space.specs],
        'fixed':cfg['fixed'],'property_law':cfg['property_law'],'conditions_by_rate':cfg['conditions_by_rate'],
        'objective_scales':cfg['optimization']['objective_scales'],'objective_order':['F_U_V','F_T_K'],
        'history':rows,'pareto':[{'evaluation_id':r.evaluation_id,'objectives':r.objectives} for r in front],
        'instructions':(Path(__file__).parent/'prompts'/(task+'.txt')).read_text(encoding='utf8')}
    if context is not None:
        c=context.scalarization
        payload['context_id']=context.context_id
        payload['context']={'weights':list(c.weights),'objective_scales':list(c.objective_scales),'ideal':list(c.ideal),'rho_aug':c.rho_aug,
            'mean':c.mean,'std':c.std,'incumbent_id':c.incumbent_id,'best':c.best,'history_ids':list(c.observation_ids),
            'current_scalar_top':[{'evaluation_id':c.observation_ids[i],'g':c.raw_labels[i]} for i in sorted(range(len(c.y)),key=lambda i:(c.raw_labels[i],c.observation_ids[i]))[:8]]}
    properties={key:{'const':value} for key,value in (('schema_version',2),('parameter_profile',prepared.space.profile),
        ('fit_rates',list(prepared.dataset.fit_rates)),('signatures',json.loads(json.dumps(asdict(prepared.signatures)))))}
    if task=='warm_start_electrothermal':
        names=[s.name for s in prepared.space.specs]
        parameters={'type':'object','additionalProperties':False,'required':names,
            'properties':{s.name:{'type':'number','minimum':s.lower,'maximum':s.upper} for s in prepared.space.specs}}
        properties['candidates']={'type':'array','minItems':1,'maxItems':cfg['optimization']['warmstart']['max_candidates'],
            'items':{'type':'object','additionalProperties':False,'required':['parameters'],'properties':{'parameters':parameters}}}
        payload['requested_candidate_count']=max(0,cfg['optimization']['warmstart']['pool_size']-len(valid))
    else:
        if context is None:raise ValueError('frozen context required for Region request')
        properties['context_id']={'const':context.context_id}
        base={'kind':{'enum':['region','none']},'coordinate_space':{'const':'normalized'},
              'confidence':{'type':'number','minimum':0,'maximum':1},'reason':{'type':'string','maxLength':2000}}
        bounds={'type':'array','minItems':6,'maxItems':6,'items':{'type':'number','minimum':0,'maximum':1}}
        properties['region']={'oneOf':[{'type':'object','additionalProperties':False,'required':list(base),
            'properties':{**base,'kind':{'const':'none'}}},{'type':'object','additionalProperties':False,'required':[*base,'lb','ub'],
            'properties':{**base,'kind':{'const':'region'},'lb':bounds,'ub':bounds}}]}
    payload['simulation_kind']=cfg['run_kind'];payload['model_provider']=cfg['model']['provider']
    def summary(signal):
        return {'first':signal.values[0],'last':signal.values[-1],'minimum':min(signal.values),'maximum':max(signal.values),
                'sample_count':len(signal.values),'time_span_s':[signal.time_s[0],signal.time_s[-1]],'unit':signal.unit}
    payload['case_summaries']={rate:{'current_A':summary(case.current_a),'ambient_temperature_K':summary(case.ambient_temperature_k),
        'initial_temperature_K':case.initial_state['temperature_k'],'voltage_target_V':summary(case.voltage),
        'temperature_target_K':summary(case.cell_temperature_k),'cooling_group_id':case.cooling_group_id}
        for rate,case in prepared.dataset.cases.items()}
    payload['response_contract']={'type':'object','additionalProperties':False,'required':list(properties),'properties':properties}
    return payload


def validate_warmstart_response(response,*,prepared):
    required={'schema_version','parameter_profile','fit_rates','signatures','candidates'}
    if not isinstance(response,dict) or set(response)!=required:raise ValueError('new electrothermal response schema required')
    if type(response['schema_version']) is not int or response['schema_version']!=2 or response['parameter_profile']!=prepared.space.profile or response['fit_rates']!=list(prepared.dataset.fit_rates) or digest_value(response['signatures'])!=digest_value(asdict(prepared.signatures)):raise ValueError('stale or mismatched electrothermal response')
    if not isinstance(response['candidates'],list):raise ValueError('candidate list required')
    return response['candidates']


class ElectrothermalLLMController:
    def __init__(self,*,transport=None,is_mock=False,evaluator=None,solver_budget=None):
        self.transport=transport;self.is_mock=is_mock;self.evaluator=evaluator;self.solver_budget=solver_budget;self.requests=0;self.task_requests={}

    def request(self,payload,*,prepared,store,budgets,request_cap):
        task=payload['task']
        if self.task_requests.get(task,0)>=request_cap:return None
        execution=getattr(self,'execution_budget',None) or self.solver_budget
        if execution is not None:execution.require_candidate(0)
        if not self.is_mock and (not prepared.config['llm']['enabled'] or self.requests>=budgets['max_llm_requests']):return None
        if self.transport is None:
            if self.is_mock:return None
            from .llm import ChatCompletionsTransport
            llm=prepared.config['llm'];self.transport=ChatCompletionsTransport(llm['endpoint'],llm['api_key_env'],model=llm['model'],
                max_tokens=llm['max_tokens'],json_mode=llm['json_mode'],timeout_s=llm['timeout_s'],run_store=store)
        ordinal=self.requests;self.requests+=1;self.task_requests[task]=self.task_requests.get(task,0)+1
        payload={**payload,'artifact_task':payload['task']+'_request_'+'a'*(ordinal+1)}
        store.ledger.record({'event_id':f'llm:{ordinal}','kind':'mock_llm_request' if self.is_mock else 'llm_request','phase':payload['task']})
        store.write_json(f'llm/{ordinal:06d}.payload.json',payload)
        try:return self.transport.post(payload)
        except Exception as exc:
            store.write_json(f'llm/{ordinal:06d}.error.json',{'error_type':type(exc).__name__});return None

    def generate_warmstart(self,prepared,*,store,budgets):
        options=prepared.config['optimization'];settings=options['warmstart'];records=[];cache={};returned=0;evaluations=0;started=time.perf_counter();reason='request_budget'
        while len([r for r in records if r.complete_pair_valid])<settings['pool_size'] and self.task_requests.get('warm_start_electrothermal',0)<settings['max_requests']:
            if time.perf_counter()-started>=budgets['wall_clock_s']:reason='wall_clock_budget';break
            if returned>=settings['max_candidates'] or evaluations>=settings['max_evaluations']:reason='candidate_or_evaluation_budget';break
            payload=build_electrothermal_payload('warm_start_electrothermal',prepared=prepared,history=records)
            response=self.request(payload,prepared=prepared,store=store,budgets=budgets,request_cap=settings['max_requests'])
            if response is None:reason='disabled_failed_or_exhausted_request';break
            try:proposals=validate_warmstart_response(response,prepared=prepared)
            except ValueError:
                store.ledger.record({'event_id':f'screen:reply:{self.requests}','kind':'screening_rejected','reason':'invalid_reply'});continue
            remaining=settings['max_candidates']-returned;returned+=len(proposals)
            for index,proposal in enumerate(proposals[:remaining]):
                if evaluations>=settings['max_evaluations'] or len([r for r in records if r.complete_pair_valid])>=settings['pool_size']:break
                if time.perf_counter()-started>=budgets['wall_clock_s']:reason='wall_clock_budget';break
                try:
                    if not isinstance(proposal,dict) or set(proposal)!={'parameters'} or not isinstance(proposal['parameters'],dict) or set(proposal['parameters'])!={s.name for s in prepared.space.specs}:raise ValueError('named electrothermal parameters required')
                    point=prepared.space.validate([proposal['parameters'][s.name] for s in prepared.space.specs]);key=candidate_key(point,prepared.space.profile,prepared.signatures)
                except (ValueError,TypeError):
                    store.ledger.record({'event_id':f'screen:{self.requests}:{index}','kind':'screening_rejected','reason':'invalid_candidate'});continue
                if key in cache:
                    store.ledger.record({'event_id':f'cache:{self.requests}:{index}','kind':'cache_hit','phase':'warmstart'});continue
                if self.solver_budget is not None and prepared.config['model']['provider']=='pybamm' and self.solver_budget.maximum-self.solver_budget.calls<len(prepared.dataset.fit_rates)*options['max_rate_attempts']:
                    reason='insufficient_solver_reservation';break
                result=self.evaluator.evaluate(point,prepared.dataset);evaluations+=1;cache[key]=result;records.append(result);store.save_evaluation(result,phase='warmstart_screening')
        details=warmstart_selection_details(records,space=prepared.space,count=options['initial_count'],objective_scales=options['objective_scales'],rho_aug=options['rho_aug'])
        good={r.evaluation_id:r for r in records};selected=[good[i] for i in details['selected_ids']]
        status='completed' if len(selected)==options['initial_count'] else 'insufficient_initialization'
        details.update(status=status,returned_candidates=returned,evaluations=evaluations,requests=self.requests,stop_reason='pool_complete' if len([r for r in records if r.complete_pair_valid])>=settings['pool_size'] else reason,
                       elapsed_s=time.perf_counter()-started,configured_budgets={**budgets,**settings})
        store.write_json('warmstart-selection.json',details)
        if status!='completed':
            store.write_json('initialization.json',details);raise ValueError('insufficient_initialization: no additional requests or random fillers permitted')
        evidence={'origin_run_id':store.run_id,'screening_records':[{**r.to_dict(),'signatures':asdict(prepared.signatures)} for r in records],
                  'selection':details,'cost_events':list(store.ledger.events.values()),'costs':store.ledger.summary()}
        path=store.path/'initial-plan.json';write_initial_plan(path,selected,signatures=prepared.signatures,history_evidence=evidence)
        return load_initial_plan(path,space=prepared.space,dataset=prepared.dataset,signatures=prepared.signatures)

    def request_region(self,prepared,history,context,store):
        payload=build_electrothermal_payload('region_preference_electrothermal',prepared=prepared,history=history,context=context)
        return self.request(payload,prepared=prepared,store=store,budgets=prepared.config['budgets'],
                            request_cap=prepared.config['optimization']['total_candidate_budget']-prepared.config['optimization']['initial_count'])


def validate_electrothermal_region(response,*,expected_context_id,expected_signatures):
    from .informed import validate_region_response
    if not isinstance(response,dict) or set(response)!={'schema_version','parameter_profile','fit_rates','signatures','context_id','region'}:raise ValueError('electrothermal region envelope required')
    if type(response['schema_version']) is not int or response['schema_version']!=2 or response['parameter_profile']!='electrothermal_4e2t' or response['context_id']!=expected_context_id or digest_value(response['signatures'])!=digest_value(expected_signatures) or response['fit_rates']!=list(expected_signatures['fit_rates']):raise ValueError('stale or incompatible region context')
    region=validate_region_response(response['region'])
    return {**response,'region':region}


def apply_electrothermal_region(gp,context,pool,region,*,settings,trust,space):
    from .acquisition import gaussian_ei
    from .sobol import Sobol6
    x=np.asarray(pool,dtype=float);mean,std=gp.predict(x);ei=gaussian_ei(mean,std,context.scalarization.best);plain=int(np.argmax(ei))
    result={'accepted':False,'selected_index':plain,'plain_index':plain,'fallback_reason':None,'context_id':context.context_id,
            'mean':mean.tolist(),'std':std.tolist(),'shift':np.zeros(len(x)).tolist(),'adjusted_mean':mean.tolist(),
            'plain_ei':ei.tolist(),'effective_ei':ei.tolist(),'response':None,'trust_before':float(trust)}
    def fallback(reason):result['fallback_reason']=reason;return result
    try:validated=validate_electrothermal_region(region,expected_context_id=context.context_id,expected_signatures=json_load(context.signatures_json))
    except (ValueError,TypeError,KeyError):return fallback('invalid_response')
    # Archive only the checked envelope; remove free text from untrusted providers.
    validated['region']={**validated['region'],'reason':'structured_region_response'};result['response']=validated
    p=validated['region']
    if p['kind']=='none':return fallback('abstention')
    if p['confidence']<settings.min_confidence:return fallback('low_confidence')
    if context.ordinal>=settings.active_until:return fallback('inactive')
    lb=np.asarray(p['lb']);ub=np.asarray(p['ub']);width=ub-lb
    if np.any(width<settings.min_width) or np.any(width>settings.max_width):return fallback('invalid_width')
    anchors=lb+Sobol6(1).draw(settings.n_anchors)*width;keep=[]
    for a in anchors:
        try:space.denormalize(a);keep.append(True)
        except ValueError:keep.append(False)
    result['feasible_anchor_ratio']=float(np.mean(keep))
    if not any(keep) or np.mean(keep)<settings.min_feasible_anchor_ratio:return fallback('insufficient_legal_anchors')
    anchors=anchors[np.asarray(keep)];novelty=np.linalg.norm(anchors[:,None,:]-np.asarray(gp.x)[None,:,:],axis=2).min(axis=1)
    result['close_fraction']=float(np.mean(novelty<settings.close_distance))
    if result['close_fraction']>settings.max_close_fraction:return fallback('too_close_to_observed')
    ma,sa=gp.predict(anchors);ae=gaussian_ei(ma,sa,context.scalarization.best)
    def z(v):return (v-v.mean())/max(float(v.std()),1e-12)
    signal=.60*z(np.log(np.maximum(ae,1e-12)))+.25*z(sa)+.15*z(novelty)
    logits=signal/settings.anchor_temperature;weights=np.exp(logits-logits.max());weights/=weights.sum()
    entropy=-float(np.sum(weights*np.log(weights+1e-12)))
    consistency=float(np.clip(.55*(1-entropy/np.log(len(weights)))+.45*np.tanh(signal.std()),0,1)) if len(weights)>1 else 0.
    kgg=gp.posterior_covariance(anchors)+np.eye(len(anchors))*1e-6;kxg=gp.posterior_covariance(x,anchors);norm=float(weights@kgg@weights)
    if not np.isfinite(norm) or norm<=1e-12 or np.any(~np.isfinite(kxg)):return fallback('degenerate_posterior_covariance')
    corr=np.clip((kxg@weights)/np.sqrt(np.maximum(std**2*norm,1e-12)),-1,1)
    anneal=max(0.,1-context.ordinal/settings.active_until)
    shift=np.clip(settings.lambda_max*anneal*p['confidence']*trust*consistency*np.maximum(corr,0),0,settings.max_shift_std)
    adjusted=mean-shift;lifted_ei=gaussian_ei(adjusted,std,context.scalarization.best);lifted=int(np.argmax(lifted_ei))
    gap=float(np.log(max(ei[plain],1e-12))-np.log(max(ei[lifted],1e-12)));sigma_ratio=float(std[lifted]/max(std[plain],1e-12))
    result.update(anchors=anchors.tolist(),anchor_weights=weights.tolist(),anchor_consistency=consistency,correlation=corr.tolist(),
        kernel_norm_sq=norm,anneal=anneal,shift=shift.tolist(),adjusted_mean=adjusted.tolist(),lifted_ei=lifted_ei.tolist(),
        lifted_index=lifted,plain_log_ei_gap=gap,sigma_ratio=sigma_ratio)
    if not np.any(shift>1e-12):return fallback('zero_shift')
    if lifted==plain:return fallback('same_as_plain')
    if gap>settings.max_plain_log_ei_gap:return fallback('plain_ei_gap')
    if np.any(x[lifted]<lb) or np.any(x[lifted]>ub):return fallback('outside_region')
    if sigma_ratio<settings.min_sigma_ratio:return fallback('low_sigma_ratio')
    result.update(accepted=True,selected_index=lifted,effective_ei=lifted_ei.tolist());return result


def json_load(value):
    return json.loads(value)


def update_electrothermal_trust(context,result,*,previous_trust,beta,adoption):
    if not 0<=previous_trust<=1 or not 0<=beta<=1:raise ValueError('bounded trust and beta required')
    c=context.scalarization;new=float(c.scalarize([result.objectives])[0]) if result.complete_pair_valid else None
    success=int(new is not None and new<min(c.raw_labels));adopted=bool(adoption.get('accepted') and not adoption.get('cached'))
    return {'context_id':context.context_id,'previous_best':min(c.raw_labels),'new_scalar':new,'success':success,
            'adopted':adopted,'trust_before':float(previous_trust),'trust_after':float((1-beta)*previous_trust+beta*success if adopted else previous_trust),
            'reason':'complete_pair' if new is not None else 'incomplete_pair_no_scalar'}
