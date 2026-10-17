"""One coupled solve per case, independently valid U/T, complete real pairs only."""
from dataclasses import asdict,dataclass
import time
import numpy as np
from .electrothermal_config import validate_fit_rates
from .evaluation import TransientSimulationError
from .metrics import rmse,mean_selected_rmse
from .runstore import digest_value


@dataclass(frozen=True)
class ElectrothermalTrace:
    time_s:object
    voltage_v:object
    temperature_k:object
    heat_generation_w:object
    termination:str|None
    solution_id:str
    applied_parameters:dict
    temperature_variable:str='Volume-averaged cell temperature [K]'
    heat_diagnostics:dict|None=None

    def to_dict(self):
        def safe(value):
            if isinstance(value,np.ndarray):return safe(value.tolist())
            if isinstance(value,(tuple,list)):return [safe(v) for v in value]
            if isinstance(value,dict):return {k:safe(v) for k,v in value.items()}
            if isinstance(value,(float,np.floating)):return float(value) if np.isfinite(value) else None
            if isinstance(value,np.integer):return int(value)
            return value
        return safe(asdict(self))


@dataclass(frozen=True)
class ObservedOutputResult:
    valid:bool
    rmse_v:float|None
    rmse_k:float|None
    time_s:tuple
    observed:tuple
    predicted:tuple|None
    unit:str
    variable_name:str
    reason:str|None=None


@dataclass(frozen=True)
class ElectrothermalRateResult:
    rate:str
    voltage:ObservedOutputResult
    cell_temperature:ObservedOutputResult
    solution_id:str|None
    trace:dict|None
    attempts:tuple


@dataclass(frozen=True)
class ElectrothermalEvaluationResult:
    evaluation_id:str
    parameters:tuple
    parameter_profile:str
    fit_rates:tuple
    rates:tuple[ElectrothermalRateResult,...]
    objective_components:dict
    complete_pair_valid:bool
    objectives:tuple|None
    data_signature:str
    source_kind:str
    costs:dict
    signatures:dict|None=None

    def to_dict(self):return asdict(self)


def result_from_dict(value):
    value=dict(value);rates=[]
    for row in value['rates']:
        row=dict(row)
        row['voltage']=ObservedOutputResult(**row['voltage']);row['cell_temperature']=ObservedOutputResult(**row['cell_temperature'])
        row['attempts']=tuple(row['attempts']);rates.append(ElectrothermalRateResult(**row))
    value['rates']=tuple(rates);value['parameters']=tuple(value['parameters']);value['fit_rates']=tuple(value['fit_rates'])
    if value['objectives'] is not None:value['objectives']=tuple(value['objectives'])
    return ElectrothermalEvaluationResult(**value)


def score_output(trace,observation,*,channel,reason=None):
    variable='Terminal voltage [V]' if channel=='voltage' else 'Volume-averaged cell temperature [K]'
    predicted=None;error=None
    try:
        if trace is None:raise ValueError(reason or 'no coupled solution')
        if not trace.solution_id:raise ValueError('solution identity is missing')
        if channel!='voltage' and trace.temperature_variable!=variable:raise ValueError('wrong cell temperature variable')
        t=np.asarray(trace.time_s,dtype=float)
        v=np.asarray(trace.voltage_v if channel=='voltage' else trace.temperature_k,dtype=float)
        if t.ndim!=1 or v.shape!=t.shape or len(t)<2 or np.any(~np.isfinite(t)) or np.any(~np.isfinite(v)) or np.any(np.diff(t)<=0):raise ValueError('missing/nonfinite/misaligned simulated output')
        if channel!='voltage' and np.any(v<=0):raise ValueError('cell temperature is not positive Kelvin')
        if observation.time_s[0]<t[0] or observation.time_s[-1]>t[-1]:raise ValueError('fixed observation grid is not covered; extrapolation forbidden')
        predicted=tuple(map(float,np.interp(observation.time_s,t,v)));error=rmse(observation.values,predicted)
    except (ValueError,TypeError) as exc:reason=str(exc)
    return ObservedOutputResult(error is not None,error if channel=='voltage' else None,error if channel!='voltage' else None,
        observation.time_s,observation.values,predicted,observation.unit,variable,reason if error is None else None)


class ElectrothermalEvaluator:
    def __init__(self,space,simulator,*,fit_rates,max_rate_attempts=1,event_callback=None):
        if space.profile!='electrothermal_4e2t':raise ValueError('electrothermal parameter profile required')
        if type(max_rate_attempts) is not int or max_rate_attempts<1:raise ValueError('positive integer retry budget required')
        self.space=space;self.simulator=simulator;self.fit_rates=validate_fit_rates(fit_rates)
        self.max_rate_attempts=max_rate_attempts;self.callback=event_callback;self.counter=0

    def evaluate(self,candidate,dataset):
        dataset.validate_integrity()
        if dataset.fit_rates!=self.fit_rates:raise ValueError('dataset fitting-rate protocol differs')
        point=self.space.validate(candidate);self.counter+=1
        ident=f'eval-{self.counter:06d}-'+digest_value(point)[:12]
        params=dict(zip((s.name for s in self.space.specs),point));results=[]
        backend=getattr(self.simulator,'backend_kind','test_double');cost={'solver_calls':0,'software_calls':0,'retry_calls':0}
        started=time.perf_counter()
        for rate in self.fit_rates:
            case=dataset.cases[rate];trace=None;reason=None;attempts=[]
            for number in range(1,self.max_rate_attempts+1):
                event={'event_id':ident+':'+rate+':'+str(number),'type':'solver_call' if backend=='dfn' else 'software_call','rate':rate,'attempt':number}
                if self.callback:self.callback({**event,'status':'started'})
                cost['solver_calls' if backend=='dfn' else 'software_calls']+=1
                if number>1:cost['retry_calls']+=1
                start=time.perf_counter()
                try:
                    trace=self.simulator.simulate(params,case)
                    if not isinstance(trace,ElectrothermalTrace):raise TypeError('simulator must return an ElectrothermalTrace')
                    attempts.append({**event,'status':'returned','elapsed_s':time.perf_counter()-start})
                    break
                except Exception as exc:
                    reason=type(exc).__name__+': '+str(exc)
                    attempts.append({**event,'status':'solver_error' if backend=='dfn' else 'software_error','reason':reason,'elapsed_s':time.perf_counter()-start})
                    if not isinstance(exc,TransientSimulationError):break
            voltage=score_output(trace,case.voltage,channel='voltage',reason=reason)
            temperature=score_output(trace,case.cell_temperature_k,channel='temperature',reason=reason)
            results.append(ElectrothermalRateResult(rate,voltage,temperature,trace.solution_id if trace else None,trace.to_dict() if trace else None,tuple(attempts)))
        u=mean_selected_rmse({r.rate:r.voltage.rmse_v for r in results},self.fit_rates) if all(r.voltage.valid for r in results) else None
        t=mean_selected_rmse({r.rate:r.cell_temperature.rmse_k for r in results},self.fit_rates) if all(r.cell_temperature.valid for r in results) else None
        cost['elapsed_s']=time.perf_counter()-started
        return ElectrothermalEvaluationResult(ident,point,self.space.profile,self.fit_rates,tuple(results),{'F_U':u,'F_T':t},
            u is not None and t is not None,(u,t) if u is not None and t is not None else None,dataset.data_signature,'fresh_simulation',cost)
