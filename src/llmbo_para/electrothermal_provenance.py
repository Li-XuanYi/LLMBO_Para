"""Semantic signatures and curve-verified v2 initialization; no legacy relaxation."""
from dataclasses import asdict,dataclass,replace
import math
from pathlib import Path
import json
import numpy as np
from .runstore import digest_value,sha256_file
from .electrothermal_evaluation import result_from_dict


def source_fingerprint(root=None):
    root=Path(root) if root is not None else Path(__file__).resolve().parents[2]
    files=[*sorted((root/'src/llmbo_para').rglob('*.py')),*sorted((root/'src/llmbo_para/prompts').glob('*.txt'))]
    files += [root/n for n in ('requirements-py312.lock','requirements-research.lock','requirements-test.lock','pyproject.toml')]
    return digest_value({p.relative_to(root).as_posix():sha256_file(p) for p in files if p.is_file()})


@dataclass(frozen=True)
class SignatureBundle:
    config:str
    data:str
    model_evaluation:str
    evaluation_protocol:str
    comparison_protocol:str
    initialization_compatibility:str
    algorithm:str
    source:str
    fit_rates:tuple


def build_electrothermal_signatures(config,dataset,*,source_root=None):
    dataset.validate_integrity()
    if tuple(config['fit_rates'])!=dataset.fit_rates:raise ValueError('configuration and dataset rate order differs')
    source=source_fingerprint(source_root)
    physical={k:config[k] for k in ('problem_type','parameter_profile','fit_rates','parameters','fixed','property_law','conditions_by_rate','model')}
    model=digest_value({'physical':physical,'source':source,'data':dataset.data_signature,'exclusions':config['data']['exclusions']})
    evaluation=digest_value({'model':model,'data':dataset.data_signature,'objective_order':['F_U_V','F_T_K'],
                             'aggregation':'equal_selected_rate_RMSE','grid':'complete_independent_no_extrapolation'})
    opt=config['optimization']
    comparison=digest_value({'evaluation':evaluation,'scales':opt['objective_scales'],'HV_reference':opt['hv_reference'],
        'HV_space':'Y/scales','rho_aug':opt['rho_aug'],'transform':'identity','ideal':[0.,0.]})
    init=digest_value({'evaluation':evaluation,'comparison':comparison,'source':source,'initial_count':opt['initial_count'],
                      'selection':'pareto_maximin_v1','warmstart':opt['warmstart']})
    algorithm=digest_value({'optimization':opt,'budgets':config['budgets'],'llm':config['llm']})
    return SignatureBundle(digest_value(config),dataset.data_signature,model,evaluation,comparison,init,algorithm,source,dataset.fit_rates)


def candidate_key(parameters,profile,signatures):
    if profile!='electrothermal_4e2t' or len(parameters)!=6 or any(type(v) not in (int,float) or not math.isfinite(v) for v in parameters):raise ValueError('wrong parameter semantics or nonfinite candidate')
    return digest_value({'parameters':tuple(parameters),'profile':profile,'fit_rates':signatures.fit_rates,
        'model':signatures.model_evaluation,'data':signatures.data,'evaluation':signatures.evaluation_protocol})


def verify_evaluation(record,dataset,*,require_complete=False):
    """Recompute errors from raw curves using a residual norm independent of rmse()."""
    if record.parameter_profile!='electrothermal_4e2t' or tuple(record.fit_rates)!=dataset.fit_rates or record.data_signature!=dataset.data_signature:
        raise ValueError('evaluation profile/data/rate signature differs')
    if record.source_kind not in ('fresh_simulation','validated_cache'):raise ValueError('objective source is not a real evaluation or validated cache')
    if tuple(r.rate for r in record.rates)!=dataset.fit_rates:raise ValueError('incomplete rate results')
    errors={'F_U':[],'F_T':[]}
    for row in record.rates:
        case=dataset.cases[row.rate];trace=row.trace
        if trace and (row.solution_id!=trace.get('solution_id') or not row.solution_id):raise ValueError('U/T solution identity differs')
        for name,observed,prediction,key in (('F_U',case.voltage,row.voltage,'voltage_v'),('F_T',case.cell_temperature_k,row.cell_temperature,'temperature_k')):
            if tuple(prediction.time_s)!=observed.time_s or tuple(prediction.observed)!=observed.values or prediction.unit!=observed.unit:raise ValueError('archived observation grid/values/units differ')
            value=None;aligned=None
            try:
                if trace is None:raise ValueError('no trace')
                if name=='F_T' and trace['temperature_variable']!='Volume-averaged cell temperature [K]':raise ValueError('wrong temperature variable')
                t=np.asarray(trace['time_s'],dtype=float);v=np.asarray(trace[key],dtype=float)
                if t.ndim!=1 or t.shape!=v.shape or len(t)<2 or np.any(~np.isfinite(t)) or np.any(~np.isfinite(v)) or np.any(np.diff(t)<=0):raise ValueError('invalid curve')
                if name=='F_T' and np.any(v<=0):raise ValueError('nonpositive Kelvin')
                if observed.time_s[0]<t[0] or observed.time_s[-1]>t[-1]:raise ValueError('uncovered grid')
                aligned=np.interp(observed.time_s,t,v)
                value=math.hypot(*[float(a-b) for a,b in zip(aligned,observed.values)])/math.sqrt(len(aligned))
            except (ValueError,TypeError,KeyError):pass
            saved=prediction.rmse_v if name=='F_U' else prediction.rmse_k
            if prediction.valid!=(value is not None):raise ValueError('output validity does not reproduce')
            if value is None:
                if saved is not None or not prediction.reason:raise ValueError('invalid output has fabricated error or no reason')
                errors[name].append(None)
            else:
                if saved is None or not math.isclose(saved,value,rel_tol=1e-10,abs_tol=1e-12) or not np.allclose(prediction.predicted,aligned,rtol=0,atol=1e-12):raise ValueError('raw curve RMSE/alignment does not reproduce')
                errors[name].append(value)
    components={name:math.fsum(v)/len(dataset.fit_rates) if all(x is not None for x in v) else None for name,v in errors.items()}
    for key,value in components.items():
        saved=record.objective_components.get(key)
        if (value is None)!=(saved is None) or value is not None and not math.isclose(saved,value,rel_tol=1e-10,abs_tol=1e-12):raise ValueError('objective component does not reproduce')
    complete=all(v is not None for v in components.values())
    if record.complete_pair_valid!=complete or complete!=(record.objectives is not None):raise ValueError('complete pair flag differs')
    if complete and not np.allclose(record.objectives,[components['F_U'],components['F_T']],rtol=1e-10,atol=1e-12):raise ValueError('objective pair differs')
    if require_complete and not complete:raise ValueError('only complete true objective pairs are eligible')
    return True


@dataclass(frozen=True)
class InitialPlan:
    records:tuple
    fit_rates:tuple
    signatures:dict
    plan_sha256:str
    history_evidence:dict|None=None


def write_initial_plan(path,records,*,signatures,history_evidence=None):
    if len(records)<2 or any(not r.complete_pair_valid for r in records):raise ValueError('initial plan needs >=2 complete evaluated records')
    signed=[replace(r,signatures=asdict(signatures)).to_dict() for r in records]
    payload={'schema_version':2,'parameter_profile':'electrothermal_4e2t','fit_rates':signatures.fit_rates,
             'signatures':asdict(signatures),'records':signed,'history_evidence':history_evidence}
    payload['plan_sha256']=digest_value(payload)
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(payload,stream,ensure_ascii=False,indent=2,allow_nan=False)
    return payload['plan_sha256']


def load_initial_plan(path,*,space,dataset,signatures):
    payload=json.loads(Path(path).read_text(encoding='utf-8'));claimed=payload.pop('plan_sha256',None)
    if claimed!=digest_value(payload) or payload.get('schema_version')!=2 or payload.get('parameter_profile')!=space.profile or tuple(payload.get('fit_rates',()))!=dataset.fit_rates:
        raise ValueError('initial plan schema/profile/rate/hash differs')
    if payload.get('signatures',{}).get('initialization_compatibility')!=signatures.initialization_compatibility:raise ValueError('initialization signatures incompatible')
    records=[];keys=set()
    for raw in payload.get('records',[]):
        record=result_from_dict(raw);space.validate(record.parameters)
        if not record.signatures or any(record.signatures.get(k)!=getattr(signatures,k) for k in ('data','model_evaluation','evaluation_protocol','initialization_compatibility','source')):raise ValueError('record semantic signatures differ')
        verify_evaluation(record,dataset,require_complete=True)
        key=candidate_key(record.parameters,record.parameter_profile,signatures)
        if key in keys:raise ValueError('initial plan duplicates physical inputs')
        keys.add(key);records.append(record)
    if len(records)<2:raise ValueError('insufficient complete initial records')
    evidence=payload.get('history_evidence')
    if evidence is not None:
        from .electrothermal_store import CostLedger
        from .electrothermal_llm import warmstart_selection_details
        pool=[];pool_by_id={}
        if not isinstance(evidence,dict) or set(evidence)!={'origin_run_id','screening_records','selection','cost_events','costs'}:raise ValueError('complete historical initialization evidence required')
        for raw in evidence['screening_records']:
            record=result_from_dict(raw);space.validate(record.parameters);verify_evaluation(record,dataset)
            if not record.signatures or any(record.signatures.get(k)!=getattr(signatures,k) for k in ('data','model_evaluation','evaluation_protocol','initialization_compatibility','source')):raise ValueError('screening semantic signatures differ')
            if record.evaluation_id in pool_by_id:raise ValueError('duplicate screening ID')
            pool.append(record);pool_by_id[record.evaluation_id]=record
        selection=evidence['selection'];details=warmstart_selection_details(pool,space=space,count=len(records),objective_scales=selection['objective_scales'],rho_aug=selection['rho_aug'])
        for key,value in details.items():
            if digest_value(selection[key])!=digest_value(value):raise ValueError('historical selection does not reproduce')
        if details['selected_ids']!=[r.evaluation_id for r in records]:raise ValueError('historical selected records differ')
        for record in records:
            original=pool_by_id[record.evaluation_id]
            if digest_value([record.parameters,record.objectives,record.to_dict()['rates']])!=digest_value([original.parameters,original.objectives,original.to_dict()['rates']]):raise ValueError('selected record is not from screening pool')
        costs=CostLedger()
        for event in evidence['cost_events']:costs.record(event)
        if costs.summary()!=evidence['costs']:raise ValueError('historical cost attribution differs')
        actual=sum(e['kind']=='solver_call' for e in costs.events.values());software=sum(e['kind']=='software_call' for e in costs.events.values())
        if actual!=sum(r.costs['solver_calls'] for r in pool) or software!=sum(r.costs['software_calls'] for r in pool):raise ValueError('historical costs do not match screening evaluations')
    return InitialPlan(tuple(records),dataset.fit_rates,payload['signatures'],claimed,evidence)
