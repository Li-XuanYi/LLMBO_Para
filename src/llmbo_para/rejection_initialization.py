"""Direct parameter proposals with bounded rejection feedback and original paid-record auditing."""
from dataclasses import asdict,dataclass
from copy import deepcopy
import json
from pathlib import Path

from .feasibility import simulation_signature
from .initialization import validated_simulation_sources
from .quality_initialization import QualityScreeningBudget,QualityWarmInitializer,select_quality_initial
from .runstore import sha256_file
from .screening_history import validate_record


def verified_success_record(config,series,path,expected_sha256=None):
    path=Path(path).resolve()
    if expected_sha256 and sha256_file(path)!=expected_sha256:raise ValueError('positive reference record hash differs')
    directory=path.parent.parent
    old_config=json.loads((directory/'manifest.json').read_text(encoding='utf-8'))['config']
    old_config=old_config.get('experiment',old_config)
    if old_config['data'].get('sha256')!=config['data'].get('sha256') or simulation_signature(old_config,series)!=simulation_signature(config,series):
        raise ValueError('positive reference physical/data signature differs')
    validated_simulation_sources(directory)
    record=json.loads(path.read_text(encoding='utf-8'));validate_record(record,config,series)
    if not record['valid']:raise ValueError('positive reference must be complete at all four rates')
    return record


def verified_feedback_plan(config,series,path,_visited=None):
    path=Path(path).resolve();saved=json.loads(path.read_text(encoding='utf-8'))
    visited=set() if _visited is None else _visited
    if path in visited:raise ValueError('prior feedback chain contains a cycle')
    visited.add(path)
    if saved['simulation_signature']!=simulation_signature(config,series):
        raise ValueError('prior feedback simulation/data signature differs')
    validated_simulation_sources(saved['screening_directory'])
    for source in saved['quality_observation_sources']:
        record_path=Path(source['path'])
        if sha256_file(record_path)!=source['sha256']:raise ValueError('prior feedback record hash differs')
        validate_record(json.loads(record_path.read_text(encoding='utf-8')),config,series)
    prior=saved.get('prior_feedback_plan')
    if prior:
        if sha256_file(prior['path'])!=prior['sha256']:raise ValueError('prior feedback chain plan hash differs')
        verified_feedback_plan(config,series,prior['path'],visited)
    for reference in saved.get('positive_reference_examples',[]):
        verified_success_record(config,series,reference['path'],reference['sha256'])
    return saved


@dataclass(frozen=True)
class RejectionFeedbackBudget(QualityScreeningBudget):
    max_evaluations:int=40  # also the hard budget for ALL returned proposals
    warm_batch_size:int=4
    max_warm_batches:int=10
    max_selection_requests:int=1  # legacy positive schema; selector is never called
    min_evaluations:int=8

    def __post_init__(self):
        # Unlike a one-shot pool, a direct batch may be smaller than the target.
        if any(type(v) is not int or v<1 for v in asdict(self).values()):
            raise ValueError('Agent feedback budgets must be positive integers')
        if self.target<2 or self.min_evaluations!=self.target or self.max_evaluations<self.target or self.warm_batch_size>self.max_evaluations:
            raise ValueError('Agent feedback target/batch must fit the total proposal budget')


class RejectionFeedbackInitializer(QualityWarmInitializer):
    def __init__(self,*args,budget=None,**kwargs):
        budget=budget or RejectionFeedbackBudget()
        if not isinstance(budget,RejectionFeedbackBudget):raise ValueError('explicit Agent feedback budget required')
        super().__init__(*args,budget=budget,**kwargs)
        self.feedback=[];self.prior_feedback_plan=None;self.stop_reason=None
        self.unprocessed_generated_parameters=[]
        self.positive_reference_examples=[]
        self.min_history_distance=float(self.config.get('llm',{}).get('min_diversity_distance',1e-3))

    def progress(self):
        previous=self.prior_feedback_plan['screening_cost'] if self.prior_feedback_plan else {}
        return {**super().progress(),'initialization_policy':'agent_rejection',
            'submitted_points':self.draws,'remaining_candidate_budget':max(0,self.budget.max_evaluations-self.draws),
            'remaining_request_budget':max(0,self.budget.max_warm_batches-self.api_requests),
            'candidate_pool_used':False,'unused_generated_after_target':len(self.unprocessed_generated_parameters),
            'attributed_total_rate_solves':previous.get('attributed_total_rate_solves',previous.get('rate_solve_attempts',0))+self.rate_solves,
            'attributed_total_API_requests':previous.get('attributed_total_API_requests',previous.get('api_requests',0))+self.api_requests,
            'attributed_total_returned_candidates':previous.get('attributed_total_returned_candidates',previous.get('generated_draws',0))+self.draws,
            'positive_reference_example_count':len(self.positive_reference_examples),
            'positive_reference_saved_rate_solves':sum(r['saved_rate_solves'] for r in self.positive_reference_examples)}

    def _feedback_observation(self,record):
        observation=self._observation(record)
        required={rate:row.time_s[-1] for rate,row in self.series.items()}
        observation.update(reason='complete' if record['valid'] else 'four_rate_incomplete',
            required_duration_s=required,coverage_shortfall_s={rate:max(0,required[rate]-end) if end is not None else None
                for rate,end in observation['covered_duration_s'].items()},
            termination={row['rate']:row['termination'] for row in record['rates']})
        return observation

    def _context(self):
        base=super()._context()['initialization_recovery']
        failed=[r for r in self.feedback if not r.get('complete',False)]
        recent=failed[-20:]
        covered=[r for r in failed if r.get('covered_duration_s',{}).get('3C') is not None]
        if covered:
            closest=max(covered,key=lambda r:r['covered_duration_s']['3C'])
            if closest not in recent:recent=[closest,*recent]
        spread=[{'name':s.name,'distinct_values':len({p[i] for p in self.seen})}
            for i,s in enumerate(self.space.specs)]
        successes=sorted((r for r in self.feedback if r.get('complete') and r.get('objective_v') is not None),key=lambda r:r['objective_v'])[:3]
        return {'initialization_policy':'agent_rejection','agent_feedback_policy':{
            'instruction':'直接提出新的完整六维候选。根据真实拒绝原因修订；库存条件是必要条件，提前截止仍须修复。若提供verified_success_examples，先对照成功与失败参数，在成功案例邻域提出小幅、可解释的联合修订，优先取得四倍率完整覆盖，再改善RMSE；不要照抄成功案例或再次大幅跳向已有失败区域。六个变量均可改变，Reference名义值不是固定决策值，尤其不要固定两个扩散系数。不得重复已评价/已拒绝点，不得虚构可行性或RMSE。',
            'no_llm_pool_selection':True,'all_returned_points_consume_budget':True,
            'minimum_normalized_distance_from_previous_or_reference':self.min_history_distance,
            'remaining_candidate_budget':self.budget.max_evaluations-self.draws,
            'remaining_request_budget':self.budget.max_warm_batches-self.api_requests},
            'initialization_recovery':{'accepted_count':len(self.accepted),'target':self.budget.target,
                'accepted_parameters':[r['parameters'] for r in self.accepted],
                'best_completed_observation':successes[0] if successes else None,
                'verified_success_examples':successes,
                'previous_generated_parameters':[list(p) for p in sorted(self.seen)],
                'failed_candidates':recent,'inventory_check':base['inventory_check'],
                'derived_necessary_parameter_ranges':base['derived_necessary_parameter_ranges'],
                'observed_parameter_spread':spread}}

    def seed_feedback_from_plan(self,path):
        if self.feedback or self.draws or self.prior_feedback_plan:raise ValueError('prior feedback can only be seeded once before requests')
        path=Path(path).resolve();saved=verified_feedback_plan(self.config,self.series,path)
        chain=[];node=saved
        while True:
            chain.append(node);prior=node.get('prior_feedback_plan')
            if not prior:break
            node=json.loads(Path(prior['path']).read_text(encoding='utf-8'))
        observations={}
        for node in chain:
            for source in node['quality_observation_sources']:
                record=json.loads(Path(source['path']).read_text(encoding='utf-8'))
                observations[tuple(record['parameters'])]=self._feedback_observation(record)
            for reference in node.get('positive_reference_examples',[]):
                if reference not in self.positive_reference_examples:self.positive_reference_examples.append(reference)
                record=verified_success_record(self.config,self.series,reference['path'],reference['sha256'])
                observations[tuple(record['parameters'])]=self._feedback_observation(record)
        if 'rejection_feedback' in saved:
            self.feedback=deepcopy(saved['rejection_feedback'])
            for entry in self.feedback:
                if 'covered_duration_s' in entry and entry!=observations.get(tuple(entry['parameters'])):
                    raise ValueError('inherited feedback summary differs from verified curves')
        else:
            self.feedback=list(observations.values())
            events_path=Path(saved['screening_directory'])/'events.jsonl'
            for line in events_path.read_text(encoding='utf-8').splitlines():
                row=json.loads(line)
                if row['type']=='screening_rejected':
                    self.feedback.append({'parameters':row['parameters'],'reason':row['reason'],'complete':False,
                        'inventory':{k:row[k] for k in ('ideal_discharge_upper_bound_ah','required_discharge_ah')}})
        self.seen.update(self.space.validate(p) for p in saved['seen_parameters'])
        totals={key:sum(node['screening_cost'].get(field,0) for node in chain) for key,field in (
            ('attributed_total_rate_solves','rate_solve_attempts'),('attributed_total_API_requests','api_requests'),
            ('attributed_total_returned_candidates','generated_draws'))}
        self.prior_feedback_plan={'path':str(path),'sha256':sha256_file(path),'screening_cost':{**saved['screening_cost'],**totals},
            'records_used_for_feedback':len(observations),'feedback_entries_retained':len(self.feedback),
            'verified_chain_length':len(chain),'prior_valid_points_reused_as_seeds':0}
        self.store.write_json('prior-feedback-plan.json',saved)
        self.store.append_event({'type':'prior_rejection_feedback_verified',**self.prior_feedback_plan})

    def add_verified_success_example(self,path,expected_sha256=None):
        if self.api_requests or self.evaluations:raise ValueError('success references must be fixed before generation starts')
        path=Path(path).resolve();record=verified_success_record(self.config,self.series,path,expected_sha256)
        if any(r['parameters']==record['parameters'] for r in self.positive_reference_examples):return
        metadata={'path':str(path),'sha256':sha256_file(path),'parameters':record['parameters'],
            'objective_v':record['objective_v'],'saved_rate_solves':sum(len(q['attempts']) for q in record['rates']),
            'role':'context_only_not_initial_seed','historical_search_cost_not_fully_attributed':True}
        self.positive_reference_examples.append(metadata);self.feedback.append(self._feedback_observation(record))
        self.seen.add(self.space.validate(record['parameters']))
        self.store.append_event({'type':'positive_reference_verified',**metadata})

    def _warm(self):
        while len(self.accepted)<self.budget.target and self.draws<self.budget.max_evaluations and self.api_requests<self.budget.max_warm_batches:
            context=self._context();count=min(self.budget.warm_batch_size,self.budget.max_evaluations-self.draws)
            self.batches+=1;self.api_requests+=1
            client=self.llm_factory('generate',self.batches,context)
            try:proposals=client.warm_start(self.space,count)
            except ValueError as exc:
                rejection={'parameters':None,'reason':'response_contract','error':str(exc),'complete':False}
                self.feedback.append(rejection);self.store.append_event({'type':'agent_contract_rejected',**rejection,**self.progress()})
                continue
            statistics=getattr(client,'last_warm_statistics',{'received':len(proposals)})
            received=statistics['received'];self.draws+=received
            self.analytical_rejections+=received-len(proposals)
            self.store.append_event({'type':'agent_generation','requested_count':count,'statistics':statistics,**self.progress()})
            if self.draws>self.budget.max_evaluations:
                self.stop_reason='candidate_response_overflow'
                raise ValueError('Agent returned beyond remaining candidate budget; no extra evaluations allowed')
            for rejected in getattr(client,'last_warm_rejections',[]):
                self.feedback.append({**rejected,'complete':False})
            if received==0:self.feedback.append({'parameters':None,'reason':'empty_candidate_response','complete':False})
            for index,raw in enumerate(proposals):
                if len(self.accepted)>=self.budget.target:
                    self.unprocessed_generated_parameters.extend(list(p) for p in proposals[index:]);break
                point=self.space.validate(raw)
                normalized=self.space.normalize(point);key=tuple(round(v,12) for v in normalized)
                duplicate=any(tuple(round(v,12) for v in self.space.normalize(p))==key for p in self.seen)
                distance=min((sum((a-b)**2 for a,b in zip(normalized,self.space.normalize(p)))**.5 for p in self.seen),default=None)
                too_close=distance is not None and distance<self.min_history_distance
                self.seen.add(point)
                check=self.gate.check(point) if self.gate else {'feasible':True}
                if duplicate or too_close or not check['feasible']:
                    self.analytical_rejections+=1
                    rejection={'parameters':list(point),'reason':'duplicate' if duplicate else 'minimum_history_diversity' if too_close else 'necessary_inventory_bound',
                        'inventory':check,'complete':False,'normalized_distance_from_history':distance}
                    self.feedback.append(rejection);self.store.append_event({'type':'agent_proposal_rejected',**rejection,**self.progress()})
                    continue
                self._evaluate(point)
                self.feedback.append(self._feedback_observation(self.quality_records[-1]))
        if len(self.accepted)<self.budget.target:
            self.stop_reason='candidate_budget_exhausted' if self.draws>=self.budget.max_evaluations else 'request_budget_exhausted'
            self.store.append_event({'type':'agent_feedback_finished','stop_reason':self.stop_reason,**self.progress()});return
        self.quality_selection=select_quality_initial(self.quality_records,self.space,self.budget.target)
        indices=self.quality_selection['selected_candidate_ids']
        self.accepted=[self.quality_records[i] for i in indices];self.accepted_sources=[self.quality_sources[i] for i in indices]
        self.quality_finished=True;self.stop_reason='target_reached'
        self.store.write_json('quality-selection.json',self.quality_selection)
        self.store.append_event({'type':'agent_feedback_finished','stop_reason':self.stop_reason,**self.progress()})

    def plan(self):
        return {**super().plan(),'warm_start_method':'agent_rejection','stop_reason':self.stop_reason,
            'prior_feedback_plan':self.prior_feedback_plan,'rejection_feedback':self.feedback,
            'positive_reference_examples':self.positive_reference_examples,
            'unprocessed_generated_parameters':self.unprocessed_generated_parameters,
            'no_llm_selection':True,'no_random_replacement':True}

    def restore_llm(self,plan,plan_path):
        raise ValueError('use verified rejection feedback seeding; do not reset or silently extend a stopped budget')
