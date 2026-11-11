"""One prompt, fixed candidates, verified eight-point cache; no feedback/refill."""
from dataclasses import dataclass

from .quality_initialization import QualityScreeningBudget,QualityWarmInitializer,select_quality_initial


@dataclass(frozen=True)
class PromptOnlyBudget(QualityScreeningBudget):
    max_evaluations:int=24
    warm_batch_size:int=24
    min_evaluations:int=8
    max_warm_batches:int=1
    max_selection_requests:int=1  # compatibility with positive-only budget schema; never used

    def __post_init__(self):
        super().__post_init__()
        if self.max_evaluations!=self.warm_batch_size or self.max_warm_batches!=1 or self.min_evaluations!=self.target:
            raise ValueError('pure-prompt budget requires one fixed design and target-sized minimum')


class PromptOnlyInitializer(QualityWarmInitializer):
    """Promote the tested one-shot path while reusing all paid-record/cache auditing."""
    def __init__(self,*args,budget=None,**kwargs):
        budget=budget or PromptOnlyBudget()
        if not isinstance(budget,PromptOnlyBudget):raise ValueError('pure prompting needs its explicit fixed budget')
        super().__init__(*args,budget=budget,**kwargs)

    def progress(self):
        return {**super().progress(),'initialization_policy':'prompt_only',
            'requested_candidates':self.budget.warm_batch_size,'submitted_points':self.draws,
            'candidate_pool_used':False,'no_replenishment':True}

    def _context(self):
        # Reuse the same derived physical ranges, but do not expose recorded
        # simulation outcomes or route to either feedback Prompt.
        recovery=super()._context()['initialization_recovery']
        return {'prompt_only_policy':{'one_generation_request':True,'requested_points':self.budget.warm_batch_size,
            'no_evaluation_feedback':True,'no_llm_selection':True,'no_replenishment':True},
            'initialization_recovery':{key:recovery[key] for key in ('inventory_check','derived_necessary_parameter_ranges')}}

    def _warm(self):
        if self.evaluations or self.seen:raise ValueError('pure prompting starts from an empty evaluation/proposal history')
        self.batches=self.api_requests=1
        client=self.llm_factory('generate',1,self._context())
        proposals=client.warm_start(self.space,self.budget.warm_batch_size)
        statistics=getattr(client,'last_warm_statistics',{'received':len(proposals)})
        self.draws=statistics['received'];self.analytical_rejections+=self.draws-len(proposals)
        self.store.append_event({'type':'prompt_only_generation','statistics':statistics,'requested_count':self.budget.warm_batch_size})
        if self.draws!=self.budget.warm_batch_size:
            raise ValueError('pure-prompt response count differs from the fixed design; no repair/replenishment')
        for raw in proposals:
            point=self.space.validate(raw)
            if point in self.seen:self.analytical_rejections+=1;continue
            self.seen.add(point);self._evaluate(point)
        self.store.append_event({'type':'prompt_only_finished',**self.progress()})
        if len(self.accepted)<self.budget.target:
            raise RuntimeError('pure-prompt fixed design ended without enough complete valid seeds; no refill or random replacement')
        self.quality_selection=select_quality_initial(self.quality_records,self.space,self.budget.target)
        selected=self.quality_selection['selected_candidate_ids']
        self.accepted=[self.quality_records[i] for i in selected]
        self.accepted_sources=[self.quality_sources[i] for i in selected]
        self.quality_finished=True
        self.store.write_json('quality-selection.json',self.quality_selection)

    def plan(self):
        return {**super().plan(),'warm_start_method':'prompt_only','one_generation_request':True,
            'no_evaluation_feedback':True,'no_llm_selection':True,'no_replenishment':True}

    def restore_llm(self,plan,plan_path):
        raise ValueError('pure-prompt initialization does not resume old proposals/evaluations or request another design')
