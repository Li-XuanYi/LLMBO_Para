"""Immutable electrothermal archives with a deduplicated event cost ledger."""
from dataclasses import asdict,replace
import json
from .runstore import RunStore,canonical_json,digest_value
from .electrothermal_provenance import verify_evaluation


class CostLedger:
    def __init__(self,store=None):self.events={};self.store=store

    def record(self,event):
        ident=event.get('event_id')
        if not isinstance(ident,str) or not ident or not event.get('kind'):raise ValueError('cost events require stable ID and kind')
        value=json.loads(canonical_json(event))
        if ident in self.events:
            if self.events[ident]!=value:raise ValueError('conflicting immutable cost event ID')
            return ident
        self.events[ident]=value
        if self.store:self.store.append_event({'type':'electrothermal_cost',**value})
        return ident

    def summary(self):
        names={'solver_call':'solver_calls','software_call':'software_calls','cache_hit':'cache_hits','cache_rejected':'cache_rejections',
               'screening_rejected':'screening_rejections','llm_request':'llm_requests','mock_llm_request':'mock_llm_requests'}
        result={name:0 for name in names.values()}
        for event in self.events.values():
            if event['kind'] in names:result[names[event['kind']]]+=1
        result['failed_solver_calls']=sum(e['kind']=='solver_call' and e.get('outcome')=='solver_error' for e in self.events.values())
        result['event_count']=len(self.events)
        return result


class ElectrothermalRunStore(RunStore):
    def __init__(self,root,config,*,dataset,signatures,command):
        super().__init__(root,config,data_hashes={'electrothermal_dataset':dataset.data_signature},command=command)
        self.dataset=dataset;self.signatures=signatures;self.ledger=CostLedger(self);self.evaluation_count=0
        self.write_json('electrothermal-input.json',dataset.to_dict());self.write_json('electrothermal-signatures.json',asdict(signatures))

    def save_evaluation(self,result,*,phase='BO',cached=False):
        verify_evaluation(result,self.dataset)
        result=replace(result,signatures=asdict(self.signatures))
        relative=f'electrothermal-evaluations/{self.evaluation_count:06d}.json';self.evaluation_count+=1
        self.write_json(relative,result.to_dict())
        self.append_event({'type':'electrothermal_evaluation_saved','relative':relative,'content_sha256':digest_value(result.to_dict()),
                           'evaluation_id':result.evaluation_id,'phase':phase,'cached':bool(cached)})
        if cached:
            self.ledger.record({'event_id':relative+':cache','kind':'cache_hit','phase':phase,'source_evaluation_id':result.evaluation_id})
        else:
            for row in result.rates:
                for attempt in row.attempts:
                    kind=attempt['type'] if attempt['type']!='solver_call' or attempt.get('solver_calls',1) else 'preparation_failure'
                    self.ledger.record({'event_id':relative+':'+attempt['event_id'],'kind':kind,'phase':phase,
                        'rate':row.rate,'outcome':attempt['status'],'elapsed_s':attempt['elapsed_s']})
        return relative
