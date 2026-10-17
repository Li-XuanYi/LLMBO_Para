"""Electrothermal-only LLM contracts, bounded requests and Pareto/diversity seeds."""
from dataclasses import asdict
from pathlib import Path
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
    return {'task':task,'schema_version':2,'parameter_profile':prepared.space.profile,'fit_rates':list(prepared.dataset.fit_rates),
        'signatures':asdict(prepared.signatures),'parameters':[{'name':s.name,'unit':s.unit,'lower':s.lower,'upper':s.upper,'transform':s.transform} for s in prepared.space.specs],
        'fixed':cfg['fixed'],'property_law':cfg['property_law'],'conditions_by_rate':cfg['conditions_by_rate'],
        'objective_scales':cfg['optimization']['objective_scales'],'objective_order':['F_U_V','F_T_K'],
        'history':rows,'pareto':[{'evaluation_id':r.evaluation_id,'objectives':r.objectives} for r in front],
        'instructions':(Path(__file__).parent/'prompts'/(task+'.txt')).read_text(encoding='utf8')}


def validate_warmstart_response(response,*,prepared):
    required={'schema_version','parameter_profile','fit_rates','signatures','candidates'}
    if not isinstance(response,dict) or set(response)!=required:raise ValueError('new electrothermal response schema required')
    if type(response['schema_version']) is not int or response['schema_version']!=2 or response['parameter_profile']!=prepared.space.profile or response['fit_rates']!=list(prepared.dataset.fit_rates) or response['signatures']!=asdict(prepared.signatures):raise ValueError('stale or mismatched electrothermal response')
    if not isinstance(response['candidates'],list):raise ValueError('candidate list required')
    return response['candidates']


class ElectrothermalLLMController:
    def __init__(self,*,transport=None,is_mock=False,evaluator=None,solver_budget=None):
        self.transport=transport;self.is_mock=is_mock;self.evaluator=evaluator;self.solver_budget=solver_budget;self.requests=0

    def request(self,payload,*,prepared,store,budgets,request_cap):
        if self.requests>=request_cap:return None
        if not self.is_mock and (not prepared.config['llm']['enabled'] or self.requests>=budgets['max_llm_requests']):return None
        if self.transport is None:
            if self.is_mock:return None
            from .llm import ChatCompletionsTransport
            llm=prepared.config['llm'];self.transport=ChatCompletionsTransport(llm['endpoint'],llm['api_key_env'],model=llm['model'],
                max_tokens=llm['max_tokens'],json_mode=llm['json_mode'],timeout_s=llm['timeout_s'],run_store=store)
        ordinal=self.requests;self.requests+=1
        payload={**payload,'artifact_task':payload['task']+'_request_'+'a'*(ordinal+1)}
        store.ledger.record({'event_id':f'llm:{ordinal}','kind':'mock_llm_request' if self.is_mock else 'llm_request','phase':payload['task']})
        store.write_json(f'llm/{ordinal:06d}.payload.json',payload)
        try:return self.transport.post(payload)
        except Exception as exc:
            store.write_json(f'llm/{ordinal:06d}.error.json',{'error_type':type(exc).__name__});return None

    def generate_warmstart(self,prepared,*,store,budgets):
        options=prepared.config['optimization'];settings=options['warmstart'];records=[];cache={};returned=0;evaluations=0;started=time.perf_counter();reason='request_budget'
        while len([r for r in records if r.complete_pair_valid])<settings['pool_size'] and self.requests<settings['max_requests']:
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
        path=store.path/'initial-plan.json';write_initial_plan(path,selected,signatures=prepared.signatures)
        return load_initial_plan(path,space=prepared.space,dataset=prepared.dataset,signatures=prepared.signatures)
