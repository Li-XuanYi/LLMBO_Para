"""Explicit, bounded follow-up of quality screening with feasibility bootstrapping."""
from .quality_initialization import QualityWarmInitializer


class StagedQualityWarmInitializer(QualityWarmInitializer):
    """Keep all paid observations; change only the LLM proposal/selection priorities."""

    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.pool_phase=None

    def _coverage_observation(self,record):
        observation=self._observation(record)
        ratios,shortfalls,headroom={},{},{}
        for row in record['rates']:
            rate=row['rate'];target=float(self.series[rate].time_s[-1])
            cutoff=self.config['conditions_by_rate'][rate]['voltage_cutoff_v']
            covered=observation['covered_duration_s'][rate]
            ratios[rate]=min(1.,max(0.,covered/target)) if covered is not None and target>0 else 0.
            shortfalls[rate]=max(0.,target-covered) if covered is not None else target
            headroom[rate]=float(row['aligned_voltage_v'][-1]-cutoff) if row['valid'] else None
        return {**observation,'minimum_coverage_ratio':min(ratios.values()),'coverage_ratios':ratios,
            'coverage_shortfall_s':shortfalls,'terminal_voltage_headroom_v':headroom}

    def _context(self):
        context=super()._context()
        observations=[self._coverage_observation(r) for r in self.quality_records]
        complete=[r for r in observations if r['complete']]
        phase='coverage_bootstrap' if len(complete)<2 else 'quality_refinement'
        closest=sorted(observations,key=lambda r:(-r['minimum_coverage_ratio'],
            -sum(v is not None for v in r['rmse_v'].values()),
            sum(v for v in r['rmse_v'].values() if v is not None)))[:8]
        context['staged_screening']={'policy':'two_complete_then_quality','phase':phase,
            'bootstrap_target':2,'complete_count':len(complete),
            'target_duration_s':{rate:float(row.time_s[-1]) for rate,row in self.series.items()},
            'closest_coverage_observations':closest,
            'best_complete_observations':sorted(complete,key=lambda r:r['objective_v'])[:8],
            'new_candidate_evaluations':self.evaluations-getattr(self,'prior_candidate_evaluations',0),
            'new_candidate_limit':self.budget.max_evaluations-getattr(self,'prior_candidate_evaluations',0),
            'coverage_is_auxiliary_only':True,
            'cutoff_voltage_by_rate_v':{rate:self.config['conditions_by_rate'][rate]['voltage_cutoff_v'] for rate in self.series}}
        return context

    def _fill_pool(self):
        phase=self._context()['staged_screening']['phase']
        if self.pool_phase!=phase:
            # Existing untried proposals were made for a different priority.
            # Preserve their identities and the seen set; request a fresh pool.
            self.store.append_event({'type':'staged_priority_changed','previous_phase':self.pool_phase,'phase':phase,
                'abandoned_untried_parameters':[list(p) for p in self.pending_pool],
                'paid_observations_retained':len(self.quality_records)})
            self.pending_pool=[];self.pool_phase=phase
        super()._fill_pool()

    def plan(self):
        plan=super().plan()
        plan['staged_screening']=self._context()['staged_screening']
        return plan
