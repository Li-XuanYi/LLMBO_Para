"""Bounded, score-informed WarmStart with independently replayable seed selection."""
from dataclasses import asdict, dataclass
import json
from pathlib import Path

import numpy as np

from .initialization import FeasibleInitializer, ScreeningBudget
from .runstore import sha256_file

SELECTION_POLICY = 'best_then_maximin_in_top_2k_by_full_rmse'


@dataclass(frozen=True)
class QualityScreeningBudget(ScreeningBudget):
    max_evaluations: int = 80
    max_warm_batches: int = 20
    max_selection_requests: int = 20
    min_evaluations: int = 20
    min_candidate_pool: int = 20
    selection_batch: int = 4

    def __post_init__(self):
        super().__post_init__()
        if not self.target <= self.min_evaluations <= self.max_evaluations:
            raise ValueError('quality screening needs target <= minimum evaluations <= maximum evaluations')
        if self.min_candidate_pool <= self.selection_batch:
            raise ValueError('quality screening pool must offer a real choice beyond the evaluation batch')


def select_quality_initial(records, space, target):
    """Keep the best, then maximize separation within the best 2k complete points."""
    valid = [i for i, row in enumerate(records) if row['valid']]
    if len(valid) < target or target < 1:
        raise ValueError('quality selection requires enough complete valid records')
    shortlist = sorted(valid, key=lambda i: (records[i]['objective_v'], i))[:2 * target]
    chosen = [shortlist[0]]
    normalized = {i: np.array(space.normalize(records[i]['parameters'])) for i in shortlist}
    distances = [None]
    while len(chosen) < target:
        remaining = [i for i in shortlist if i not in chosen]
        def key(i):
            distance = min(float(np.linalg.norm(normalized[i]-normalized[j])) for j in chosen)
            return distance, -records[i]['objective_v'], -i
        selected = max(remaining, key=key)
        distances.append(key(selected)[0]); chosen.append(selected)
    return {'policy': SELECTION_POLICY, 'target': target, 'evaluated_candidates': len(records),
        'valid_candidates': len(valid), 'shortlist_candidate_ids': shortlist,
        'selected_candidate_ids': chosen, 'normalized_min_distances_at_selection': distances}


def validate_quality_selection(plan, records, space):
    """Replay the selection, rather than trusting an extra-valid-cache declaration."""
    saved = plan.get('quality_selection')
    if not saved or saved != select_quality_initial(records, space, len(plan['parameters'])):
        raise ValueError('quality selection does not reproduce from original screening records')
    expected = [records[i]['parameters'] for i in saved['selected_candidate_ids']]
    if expected != plan['parameters'] or len(records) < plan['quality_screening']['min_evaluations']:
        raise ValueError('quality selection parameters/minimum evaluation budget differ')
    if plan['evaluations'] != [records[i] for i in saved['selected_candidate_ids']]:
        raise ValueError('quality selection evaluation order differs')


class QualityWarmInitializer(FeasibleInitializer):
    """Reuse original evaluation/cache logic; retain every paid complete/partial label."""

    def __init__(self, *args, budget=None, **kwargs):
        super().__init__(*args, budget=budget or QualityScreeningBudget(), **kwargs)
        if self.source != 'llm' or not isinstance(self.budget, QualityScreeningBudget):
            raise ValueError('quality WarmStart requires an LLM source and explicit quality budget')
        self.pending_pool = []
        self.quality_records, self.quality_sources = [], []
        self.quality_selection = None
        self.quality_finished = False

    def progress(self):
        row = super().progress()
        row.update(valid_observations=sum(r['valid'] for r in self.quality_records),
            min_evaluations=self.budget.min_evaluations,
            pending_min_evaluations=max(0,self.budget.min_evaluations-self.evaluations),
            pending_legal_pool=len(self.pending_pool), initialization_policy='quality_feedback')
        return row

    def _observation(self, record):
        errors, residuals, coverage, failures = {}, {}, {}, {}
        for row in record['rates']:
            rate = row['rate']; errors[rate] = row['rmse_v']
            coverage[rate] = row['t_end_s'] if row.get('t_end_s') is not None else (row['simulation_time_s'][-1] if row['simulation_time_s'] else None)
            failures[rate] = row['failure_kind']
            if row['valid']:
                residual = np.asarray(row['aligned_voltage_v'])-np.asarray(self.series[rate].voltage_v)
                tail = residual[-max(1,int(np.ceil(.1*len(residual)))):]
                residuals[rate] = {'final_error_v':float(residual[-1]),'last10_mean_v':float(tail.mean()),
                    'last10_rmse_v':float(np.sqrt(np.mean(tail**2)))}
            else:
                residuals[rate] = None
        return {'parameters':record['parameters'],'complete':record['valid'],'objective_v':record['objective_v'],
            'rmse_v':errors,'tail_residuals':residuals,'covered_duration_s':coverage,'failure_kind':failures}

    def _context(self):
        observations = [self._observation(r) for r in self.quality_records]
        complete = [row for row in observations if row['complete']]
        ranges = [{'name':s.name,'lower':s.lower,'upper':s.upper} for s in self.space.specs]
        for i,porosity in enumerate((self.space.negative_porosity,self.space.positive_porosity)):
            if porosity is not None:ranges[i]['upper']=min(ranges[i]['upper'],1-porosity)
        if self.gate:
            for i,coefficient in enumerate((self.gate.negative_ah_per_fraction,self.gate.positive_ah_per_fraction)):
                ranges[i]['lower']=max(ranges[i]['lower'],self.gate.required_ah/coefficient)
        return {'initialization_policy':'quality_feedback','initialization_recovery':{
            'accepted_count':len(complete),'target':self.budget.target,'generation_batch':self.batches+1,
            'accepted_parameters':[row['parameters'] for row in complete],
            'previous_generated_parameters':[list(p) for p in sorted(self.seen)][-200:],
            'failed_candidates':self.failures[-20:], 'inventory_check':asdict(self.gate) if self.gate else None,
            'derived_necessary_parameter_ranges':ranges,
            'evaluated_observations':observations[-20:],
            'best_completed_observation':min(complete,key=lambda r:r['objective_v']) if complete else None,
            'evaluations_completed':self.evaluations,'minimum_evaluations':self.budget.min_evaluations,
            'evaluation_budget_remaining':self.budget.max_evaluations-self.evaluations}}

    def _evaluate(self, point):
        before = self.evaluations
        callback = self.checkpoint_callback
        # The base evaluator checkpoints immediately after the second success.
        # Delay that callback until the quality ledger includes this same record.
        self.checkpoint_callback = None
        try:
            success = super()._evaluate(point)
        finally:
            self.checkpoint_callback = callback
        if self.evaluations > before:
            path = self.store.path/'attempts'/f'candidate-{self.evaluations-1:06d}-attempt-001.json'
            # Use the immutable JSON form (lists), as cache provenance compares
            # the selected records byte-for-byte with their archived sources.
            record = json.loads(path.read_text(encoding='utf-8'))
            self.quality_records.append(record)
            self.quality_sources.append({'path':str(path),'sha256':sha256_file(path)})
            if success and len(self.accepted)==2 and callback:
                checkpoint_plan=self.plan()
                checkpoint=self.store.write_json('two-point-checkpoint.json',checkpoint_plan)
                callback(checkpoint_plan,checkpoint)
            if not success:
                self.failures.append(self._observation(record))
            self.store.append_event({'type':'quality_screening_progress',**self.progress()})
        return success

    def _fill_pool(self):
        while len(self.pending_pool)<self.budget.min_candidate_pool and self.batches<self.budget.max_warm_batches:
            context = self._context()
            self.batches+=1; self.api_requests+=1
            client = self.llm_factory('generate',self.batches,context)
            proposals = client.warm_start(self.space,self.budget.warm_batch_size)
            statistics = getattr(client,'last_warm_statistics',{'received':len(proposals)})
            self.draws+=statistics['received'];self.analytical_rejections+=statistics['received']-len(proposals)
            self.store.append_event({'type':'screening_generation','batch':self.batches,'statistics':statistics})
            for raw in proposals:
                try:
                    point=self.space.validate(raw)
                    check=self.gate.check(point) if self.gate else {'feasible':True}
                    reason='duplicate' if point in self.seen else 'necessary_inventory_bound' if not check['feasible'] else None
                except (ValueError,TypeError) as exc:
                    self.analytical_rejections+=1
                    self.store.append_event({'type':'screening_proposal_rejected','reason':'invalid_parameter_vector','error':str(exc)})
                    continue
                if reason:
                    self.analytical_rejections+=1
                    self.store.append_event({'type':'screening_proposal_rejected','parameters':point,'reason':reason,'inventory':check})
                    continue
                self.seen.add(point);self.pending_pool.append(point)
            self.store.append_event({'type':'quality_pool_refilled','legal_pool':len(self.pending_pool),'required':self.budget.min_candidate_pool})
        if len(self.pending_pool)<self.budget.min_candidate_pool:
            raise RuntimeError('quality candidate pool remains below the minimum after the generation budget; no select-all/random fallback')

    def _warm(self):
        while (self.evaluations<self.budget.min_evaluations or len(self.accepted)<self.budget.target) and self.evaluations<self.budget.max_evaluations:
            if self.selection_requests>=self.budget.max_selection_requests:break
            self._fill_pool()
            self.selection_requests+=1
            context=self._context()
            client=self.llm_factory('select',self.selection_requests,context)
            count=min(self.budget.selection_batch,self.budget.max_evaluations-self.evaluations)
            try:selected=client.select_warm_start(self.space,self.pending_pool,count)
            finally:self.api_requests+=getattr(client,'last_selection_request_attempts',1)
            selected=tuple(self.space.validate(p) for p in selected)
            if len(selected)!=count or len(set(selected))!=count or any(p not in self.pending_pool for p in selected):
                raise ValueError('quality selection must return distinct existing proposals')
            self.store.append_event({'type':'quality_pool_selection','pool_size':len(self.pending_pool),'selected_count':count,
                'quality_observations_supplied':len(context['initialization_recovery']['evaluated_observations'])})
            for point in selected:
                self.pending_pool.remove(point);self._evaluate(point)
        if self.evaluations<self.budget.min_evaluations or len(self.accepted)<self.budget.target:
            raise RuntimeError('quality screening budget ended before minimum evaluations/eight valid seeds were obtained')
        self.quality_selection=select_quality_initial(self.quality_records,self.space,self.budget.target)
        indices=self.quality_selection['selected_candidate_ids']
        self.accepted=[self.quality_records[i] for i in indices]
        self.accepted_sources=[self.quality_sources[i] for i in indices]
        self.quality_finished=True
        self.store.write_json('quality-selection.json',self.quality_selection)

    def plan(self):
        plan=super().plan()
        if len(plan['parameters'])>self.budget.target:
            # Incomplete checkpoints still expose at most the requested seed count.
            indices=select_quality_initial(plan['evaluations'],self.space,self.budget.target)['selected_candidate_ids']
            for name in ('parameters','evaluations','evaluation_sources'):plan[name]=[plan[name][i] for i in indices]
        plan.update(complete=self.quality_finished,quality_screening=asdict(self.budget),
            quality_observation_sources=list(self.quality_sources),quality_pending_pool=[list(p) for p in self.pending_pool])
        if self.quality_selection is not None:plan['quality_selection']=self.quality_selection
        return plan

    def restore_llm(self, plan, plan_path):
        saved=plan.get('quality_screening',{})
        if any(saved.get(k)!=getattr(self.budget,k) for k in ('target','min_evaluations','min_candidate_pool','selection_batch')):
            raise ValueError('quality continuation policy differs from the original plan')
        super().restore_llm(plan,plan_path)
        directory=Path(plan['screening_directory'])
        for name in ('warm_start_quality.txt','warm_start_select_quality.txt'):
            if sha256_file(directory/'source/src/llmbo_para/prompts'/name)!=sha256_file(Path(__file__).parent/'prompts'/name):
                raise ValueError('quality continuation Prompt differs')
        from .screening_history import validate_record
        self.quality_sources=list(plan['quality_observation_sources'])
        for source in self.quality_sources:
            path=Path(source['path'])
            if sha256_file(path)!=source['sha256']:raise ValueError('quality continuation record hash differs')
            record=json.loads(path.read_text(encoding='utf-8'));validate_record(record,self.config,self.series)
            self.quality_records.append(record)
        if len(self.quality_records)!=self.evaluations:raise ValueError('quality continuation cost differs')
        self.accepted=[r for r in self.quality_records if r['valid']]
        self.accepted_sources=[s for r,s in zip(self.quality_records,self.quality_sources) if r['valid']]
        evaluated={tuple(r['parameters']) for r in self.quality_records}
        self.pending_pool=[self.space.validate(p) for p in plan['quality_pending_pool']]
        if any(p not in self.seen or p in evaluated for p in self.pending_pool) or len(set(self.pending_pool))!=len(self.pending_pool):
            raise ValueError('quality continuation pending pool provenance differs')
