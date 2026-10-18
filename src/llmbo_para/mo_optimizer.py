"""Two-error ParEGO with complete unique observations and fresh per-round GPs."""
from dataclasses import dataclass,asdict,replace
import json
import numpy as np
from .scalarization import build_scalarization_context,WeightScheduler
from .surrogate import Matern52GP
from .acquisition import gaussian_ei
from .pareto import pareto_indices,hypervolume_2d
from .sobol import Sobol6
from .electrothermal_provenance import candidate_key,verify_evaluation
from .runstore import digest_value,canonical_json


@dataclass(frozen=True)
class MORoundContext:
    scalarization:object
    fit_rates:tuple
    signatures_json:str
    gp_state_json:str
    pool:tuple
    ordinal:int
    context_id:str

    def to_dict(self):
        return {'scalarization':self.scalarization.to_dict(),'fit_rates':self.fit_rates,'signatures':json.loads(self.signatures_json),
                'gp_state':json.loads(self.gp_state_json),'pool':self.pool,'ordinal':self.ordinal,'context_id':self.context_id}


class MOOptimizer:
    def __init__(self,space,evaluator,dataset,store,options,initial_plan=None,llm_controller=None,execution_budget=None):
        self.space=space;self.evaluator=evaluator;self.dataset=dataset;self.store=store;self.options=options
        self.initial_plan=initial_plan;self.llm_controller=llm_controller;self.history=[];self.cache={};self.rounds=[];self.attempts=0
        self.execution_budget=execution_budget
        for k in ('initial_count','total_candidate_budget','global_pool_size','local_pool_size','gp_sweeps','seed'):
            if type(options[k]) is not int or options[k]<0:raise ValueError('nonnegative integer '+k+' required')
        if options['initial_count']<2 or options['total_candidate_budget']<options['initial_count'] or options['global_pool_size']<1:raise ValueError('at least two initial points and nonempty pool required')
        self.scheduler=WeightScheduler(options['weights'],options['seed']);self.rng=np.random.default_rng(options['seed']);self.sobol=Sobol6(1)
        self.initialized=False;self.gp=None;self.last_context=None
        from .informed import InformedSettings
        self.region_settings=InformedSettings.parse(options['region']);self.trust=self.region_settings.trust_init

    def key(self,parameters):return candidate_key(parameters,self.space.profile,self.store.signatures)

    def remember(self,result):
        verify_evaluation(result,self.dataset)
        key=self.key(result.parameters)
        if key not in self.cache:
            self.cache[key]=result
            if result.complete_pair_valid:self.history.append(result)

    def evaluate(self,point,*,phase='BO'):
        point=self.space.validate(point);key=self.key(point);cached=key in self.cache
        if self.execution_budget is not None:
            self.execution_budget.require_candidate(len(self.dataset.fit_rates)*self.evaluator.max_rate_attempts if not cached and getattr(self.evaluator.simulator,'backend_kind',None)=='dfn' else 0)
        result=replace(self.cache[key],source_kind='validated_cache') if cached else self.evaluator.evaluate(point,self.dataset)
        if not cached and phase=='BO':result=replace(result,evaluation_id='mo-'+key[:32])
        self.store.save_evaluation(result,phase=phase,cached=cached);self.attempts+=1;self.remember(result)
        return result,cached

    def initialize(self):
        if self.execution_budget is not None:self.execution_budget.require_candidate(0)
        if self.initialized:return
        if self.initial_plan is not None:
            if len(self.initial_plan.records)!=self.options['initial_count']:raise ValueError('initial plan size differs from initial_count')
            for r in self.initial_plan.records:
                self.store.save_evaluation(r,phase='initial_plan',cached=True);self.remember(r)
            self.attempts=len(self.initial_plan.records)
            self.store.write_json('initialization.json',{'status':'completed','kind':'imported_plan','plan_sha256':self.initial_plan.plan_sha256,
                'selected_ids':[r.evaluation_id for r in self.initial_plan.records]})
        else:
            for _ in range(self.options['initial_count']):
                point=self._legal_global(1)[0];self.evaluate(self.space.denormalize(point),phase='initialization')
            self.store.write_json('initialization.json',{'status':'completed' if len(self.history)>=2 else 'insufficient_initialization',
                'kind':'sobol','selected_ids':[r.evaluation_id for r in self.history]})
        self.initialized=True
        if len(self.history)<2:raise ValueError('insufficient_initialization: two complete unique objective pairs required')

    def _legal_global(self,count):
        points=[];seen=set()
        for _ in range(max(100,count*100)):
            if len(points)==count:return points
            x=tuple(self.sobol.draw(1)[0])
            try:p=self.space.denormalize(x)
            except ValueError:continue
            key=self.key(p)
            if key not in self.cache and key not in seen:points.append(x);seen.add(key)
        raise ValueError('no sufficient legal unseen global candidates')

    def candidate_pool(self,center):
        points=self._legal_global(self.options['global_pool_size']);seen=set(points)
        for _ in range(self.options['local_pool_size']):
            x=tuple(np.clip(np.asarray(center)+self.rng.uniform(-self.options['local_radius'],self.options['local_radius'],6),0,1))
            try:p=self.space.denormalize(x)
            except ValueError:continue
            if x not in seen and self.key(p) not in self.cache:points.append(x);seen.add(x)
        return tuple(points)

    def step(self):
        if self.execution_budget is not None:self.execution_budget.require_candidate(0)
        self.initialize()
        scalar=build_scalarization_context([self.space.normalize(r.parameters) for r in self.history],[r.objectives for r in self.history],
            [r.evaluation_id for r in self.history],weights=self.scheduler.next(),objective_scales=self.options['objective_scales'],
            rho_aug=self.options['rho_aug'],protocol_signature=self.store.signatures.comparison_protocol)
        self.gp=Matern52GP(max_sweeps=self.options['gp_sweeps'],lengthscale_prior=None).fit(scalar.x,scalar.labels,group=())
        pool=self.candidate_pool(scalar.local_center);state=self.gp.state_dict()
        context_data={'scalarization':scalar.to_dict(),'fit_rates':self.dataset.fit_rates,'signatures':asdict(self.store.signatures),
                      'gp_state':state,'pool':pool,'ordinal':len(self.rounds)+1}
        context=MORoundContext(scalar,self.dataset.fit_rates,canonical_json(asdict(self.store.signatures)).decode(),canonical_json(state).decode(),
                               pool,len(self.rounds)+1,digest_value(context_data));self.last_context=context
        mean,std=self.gp.predict(pool);ei=gaussian_ei(mean,std,scalar.best);index=int(np.argmax(ei))
        region=None
        if self.options['mode']=='full_llmbo_mo':
            from .electrothermal_llm import apply_electrothermal_region
            response=None;request_outcome=None
            if context.ordinal<self.region_settings.active_until and self.llm_controller is not None:
                response=self.llm_controller.request_region(self.llm_controller.prepared,self.history,context,self.store)
                request_outcome=getattr(self.llm_controller,'last_request_outcome',None)
            elif context.ordinal>=self.region_settings.active_until:
                request_outcome={'status':'skipped','reason':'inactive','context_id':context.context_id}
            region=apply_electrothermal_region(self.gp,context,pool,response,settings=self.region_settings,trust=self.trust,space=self.space,
                request_outcome=request_outcome)
            index=region['selected_index']
        old_best=min(scalar.raw_labels)
        result,cached=self.evaluate(self.space.denormalize(pool[index]))
        new=float(scalar.scalarize([result.objectives])[0]) if result.complete_pair_valid else None
        feedback={'context_id':context.context_id,'previous_best':old_best,'new_scalar':new,'improved':new is not None and new<old_best,'cached':cached}
        if region is not None:
            from .electrothermal_llm import update_electrothermal_trust
            feedback['trust']=update_electrothermal_trust(context,result,previous_trust=self.trust,beta=self.region_settings.trust_beta,
                adoption={'accepted':region['accepted'],'cached':cached})
            self.trust=feedback['trust']['trust_after']
        event={'context':context.to_dict(),'mean':mean.tolist(),'std':std.tolist(),'ei':ei.tolist(),'selected_index':index,
               'evaluation_id':result.evaluation_id,'feedback':feedback,'result_complete':result.complete_pair_valid,'region':region}
        self.rounds.append(event);self.store.write_json(f'mo-rounds/{len(self.rounds):06d}.json',event)
        return event

    def summary(self):
        from collections import Counter
        front=pareto_indices([r.objectives for r in self.history]);hv=hypervolume_2d([r.objectives for r in self.history],
            objective_scales=self.options['objective_scales'],reference_point=self.options['hv_reference'])
        regions=[r['region'] for r in self.rounds if r['region'] is not None]
        outcomes=[r.get('request_outcome') or {} for r in regions]
        diagnostics={'rounds':len(regions),'request_attempts':sum('ordinal' in o for o in outcomes),
            'responses':sum(o.get('status')=='received' or not o and r['response'] is not None for r,o in zip(regions,outcomes)),
            'accepted':sum(r['accepted'] for r in regions),'request_failures':sum(o.get('status')=='failed' for o in outcomes),
            'fallback_counts':dict(Counter(r['fallback_reason'] for r in regions if r['fallback_reason'] is not None))}
        return {'fit_rates':list(self.dataset.fit_rates),'complete_pairs':len(self.history),'candidate_evaluations':self.attempts,
                'BO_rounds':len(self.rounds),'pareto':[{'evaluation_id':self.history[i].evaluation_id,'parameters':self.history[i].parameters,'objectives':self.history[i].objectives} for i in front],
                'HV':hv,'HV_reason':None if hv is not None else 'no_fixed_reference','comparison_protocol':self.store.signatures.comparison_protocol,
                'costs':self.store.ledger.summary(),'API_calls':self.store.ledger.summary()['llm_requests'],
                'region_diagnostics':diagnostics,'run_directory':str(self.store.path)}

    def optimize(self,total_candidate_budget):
        if type(total_candidate_budget) is not int or total_candidate_budget<self.options['initial_count']:raise ValueError('explicit total attempt budget required')
        self.initialize()
        while self.attempts<total_candidate_budget:self.step()
        return self.summary()
