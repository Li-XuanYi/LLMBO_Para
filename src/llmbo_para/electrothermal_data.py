"""Separate forcing and observations; canonical temperature is always Kelvin."""
from dataclasses import asdict,dataclass
from pathlib import Path
import math
from .electrothermal_config import validate_fit_rates,KNOWN_BAD_3C
from .runstore import digest_value,sha256_file


def temperature_to_kelvin(values,unit):
    if unit not in ('K','degC'):raise ValueError('temperature unit must be explicitly K or degC')
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in values):raise ValueError('invalid temperature values')
    result=tuple(float(v)+(273.15 if unit=='degC' else 0.) for v in values)
    if any(v<=0 for v in result):raise ValueError('temperature must exceed absolute zero')
    return result


@dataclass(frozen=True)
class TimeSignal:
    time_s:tuple[float,...]
    values:tuple[float,...]
    unit:str
    provenance:dict

    def __post_init__(self):
        t=tuple(self.time_s);v=tuple(self.values)
        if len(t)<2 or len(t)!=len(v) or any(type(x) not in (int,float) or not math.isfinite(x) for x in (*t,*v)) or t[0]<0 or any(b<=a for a,b in zip(t,t[1:])):
            raise ValueError('signals require aligned finite values on a nonnegative strictly increasing grid')
        if not self.unit or not isinstance(self.provenance,dict):raise ValueError('unit and provenance required')
        object.__setattr__(self,'time_s',tuple(map(float,t)));object.__setattr__(self,'values',tuple(map(float,v)))


@dataclass(frozen=True)
class Observation(TimeSignal):
    pass


@dataclass(frozen=True)
class ElectrothermalCase:
    rate:str
    current_a:TimeSignal
    ambient_temperature_k:TimeSignal
    voltage:Observation
    cell_temperature_k:Observation
    initial_state:dict
    cooling_group_id:str
    provenance:dict

    def __post_init__(self):
        validate_fit_rates((self.rate,))
        if (self.current_a.unit,self.ambient_temperature_k.unit,self.voltage.unit,self.cell_temperature_k.unit)!=('A','K','V','K'):
            raise ValueError('case forcing and observations must use canonical A/K/V/K units')
        horizon=max(self.voltage.time_s[-1],self.cell_temperature_k.time_s[-1])
        for signal in (self.current_a,self.ambient_temperature_k):
            if signal.time_s[0]!=0 or signal.time_s[-1]<horizon:raise ValueError('model forcing must cover the full U/T time window from zero')
        if not isinstance(self.initial_state,dict) or self.initial_state.get('mode') not in ('parameterization','explicit_soc') or type(self.initial_state.get('temperature_k')) not in (int,float) or not math.isfinite(self.initial_state['temperature_k']) or self.initial_state['temperature_k']<=0:
            raise ValueError('explicit initial state and initial cell temperature required')
        if any(t<=0 for t in (*self.ambient_temperature_k.values,*self.cell_temperature_k.values)) or not self.cooling_group_id:
            raise ValueError('positive Kelvin temperatures and cooling group required')


@dataclass(frozen=True)
class ElectrothermalDataset:
    fit_rates:tuple[str,...]
    cases:dict[str,ElectrothermalCase]
    data_signature:str|None=None

    def __post_init__(self):
        rates=validate_fit_rates(self.fit_rates);object.__setattr__(self,'fit_rates',rates)
        if set(self.cases)!=set(rates) or any(self.cases[r].rate!=r for r in rates):raise ValueError('cases must exactly match fit_rates')
        if len({self.cases[r].cooling_group_id for r in rates})!=1:raise ValueError('all selected rates require a shared cooling group')
        signature=digest_value({'fit_rates':rates,'cases':{r:asdict(self.cases[r]) for r in rates}})
        if self.data_signature is not None and self.data_signature!=signature:raise ValueError('dataset signature does not reproduce')
        object.__setattr__(self,'data_signature',signature)

    def to_dict(self):return asdict(self)

    def validate_integrity(self):
        return ElectrothermalDataset(self.fit_rates,self.cases,self.data_signature)


def dataset_from_dict(value):
    cases={}
    for rate,row in value['cases'].items():
        row=dict(row)
        for name,cls in (('current_a',TimeSignal),('ambient_temperature_k',TimeSignal),('voltage',Observation),('cell_temperature_k',Observation)):
            row[name]=cls(**row[name])
        cases[rate]=ElectrothermalCase(**row)
    return ElectrothermalDataset(tuple(value['fit_rates']),cases,value.get('data_signature'))


def load_electrothermal_dataset(config,base_dir):
    from .electrothermal_config import electrothermal_configuration_errors
    errors=electrothermal_configuration_errors(config)
    if errors:raise ValueError('; '.join(errors))
    data=config['data'];rates=validate_fit_rates(config['fit_rates'])
    if data['kind']=='builtin_synthetic':
        from .electrothermal_synthetic import make_synthetic_dataset
        return make_synthetic_dataset(rates)
    cases={};excluded={KNOWN_BAD_3C,*[x['source_id'] for x in data['exclusions']]}
    for rate in rates:
        item=data['by_rate'][rate];source=item['source_id'];condition=config['conditions_by_rate'][rate]
        if source in excluded:raise ValueError('selected source is excluded')
        if data['kind']=='inline':
            row=dict(item);signals={k:row[k] for k in ('current_a','ambient_temperature_k','voltage','cell_temperature_k')}
        else:
            from openpyxl import load_workbook
            path=(Path(base_dir)/item['path']).resolve();actual=sha256_file(path)
            if actual!=item['sha256'] or source!='xlsx:'+actual+':'+item['sheet']:raise ValueError('xlsx hash or source identity differs')
            book=load_workbook(path,read_only=True,data_only=True)
            try:
                rows=book[item['sheet']].iter_rows(values_only=True);headers=next(rows);rows=list(rows)
                indexes={str(h).strip():i for i,h in enumerate(headers) if h is not None};columns=item['columns']
                signals={}
                for field,column,unit in (('current_a','current','A'),('ambient_temperature_k','ambient_temperature',item['temperature_unit']),('voltage','voltage','V'),('cell_temperature_k','cell_temperature',item['temperature_unit'])):
                    value_name=columns[column];time_name=columns.get(column+'_time',columns.get('time'))
                    if not value_name or not time_name or value_name not in indexes or time_name not in indexes:raise ValueError('missing explicit time/current/temperature column mapping')
                    times=[];values=[]
                    for row in rows:
                        v=row[indexes[value_name]]
                        if v is None:continue
                        times.append(row[indexes[time_name]]);values.append(v)
                    signals[field]={'time_s':times,'values':values,'unit':unit,'provenance':{'source_id':source,'column':value_name}}
            finally:book.close()
        for field,value in signals.items():
            value=dict(value);provenance=dict(value.get('provenance',{}));provenance['source_id']=source
            if field in ('ambient_temperature_k','cell_temperature_k'):
                original=value['unit'];value['values']=temperature_to_kelvin(value['values'],original)
                value['unit']='K';provenance.update(original_unit=original,conversion='degC_to_K' if original=='degC' else 'identity')
            value['provenance']=provenance
            signals[field]=(Observation if field in ('voltage','cell_temperature_k') else TimeSignal)(**value)
        state={**condition['initial_state'],'temperature_k':condition['initial_temperature_k']}
        cases[rate]=ElectrothermalCase(rate,**signals,initial_state=state,cooling_group_id=condition['cooling_group_id'],provenance={'source_id':source})
    return ElectrothermalDataset(rates,cases)
