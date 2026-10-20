"""Strict schema v2; the legacy four-rate schema is validated separately."""
import math
from .electrothermal_parameters import ELECTROTHERMAL_NAMES,ELECTROTHERMAL_UNITS

FitRates=tuple[str,...]
KNOWN_BAD_3C='xlsx:6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7:3C'
FIXED_KEYS=('cell_volume_m3','cooling_area_m2','negative_porosity','positive_porosity',
            'negative_conductivity_s_m','positive_conductivity_s_m','electrolyte_diffusivity_multiplier')
LAW_KEYS=('reference_temperature_k','activation_energy_n_j_mol','activation_energy_p_j_mol')
CONFIRMATIONS=('current','time','temperature_unit','temperature_probe','initial_state','ambient_temperature','cooling')


def validate_fit_rates(value:object)->FitRates:
    if not isinstance(value,(list,tuple)) or not value or any(type(r) is not str or r not in ('0.5C','1C','2C','3C') for r in value) or len(set(value))!=len(value):
        raise ValueError('fit_rates requires an explicit nonempty ordered unique supported-rate list')
    return tuple(value)


def electrothermal_space_from_config(config):
    from .parameters import ParameterSpace
    if config.get('parameter_profile')!='electrothermal_4e2t':raise ValueError('wrong electrothermal parameter_profile')
    params=config['parameters'];fixed=config['fixed']
    if set(params)!=set(ELECTROTHERMAL_NAMES):raise ValueError('electrothermal parameter names must exactly match the profile')
    return ParameterSpace.from_bounds({n:(params[n]['lower'],params[n]['upper']) for n in ELECTROTHERMAL_NAMES},
        {n:params[n]['transform'] for n in ELECTROTHERMAL_NAMES},{n:params[n]['unit'] for n in ELECTROTHERMAL_NAMES},
        negative_porosity=fixed.get('negative_porosity'),positive_porosity=fixed.get('positive_porosity'),profile='electrothermal_4e2t')


def electrothermal_configuration_errors(config):
    from .runstore import reject_inline_secrets
    reject_inline_secrets(config)
    errors=[]
    allowed={'schema_version','problem_type','parameter_profile','run_kind','cell_id','fit_rates','parameters','fixed','property_law',
             'conditions_by_rate','data','model','optimization','budgets','llm','research_confirmations'}
    errors += ['unrecognized v2 setting: '+str(k) for k in set(config)-allowed]
    def section(name):
        value=config.get(name)
        if not isinstance(value,dict):errors.append(name+' must be an object');return {}
        return value
    def numeric(v,name,*,positive=True,integer=False):
        good=type(v) in (int,float) and math.isfinite(v) and (v>0 if positive else v>=0) and (not integer or type(v) is int)
        if not good:errors.append(name+' requires a finite '+('positive' if positive else 'nonnegative')+(' integer' if integer else ' number'))
        return good
    def strict(obj,keys,name):errors.extend(name+': unrecognized '+str(k) for k in set(obj)-set(keys))
    if type(config.get('schema_version')) is not int or config['schema_version']!=2:errors.append('schema_version must be 2')
    if config.get('problem_type')!='electrothermal_identification':errors.append('problem_type must be electrothermal_identification')
    if config.get('parameter_profile')!='electrothermal_4e2t':errors.append('parameter_profile must be electrothermal_4e2t')
    if config.get('run_kind') not in ('synthetic_software','synthetic_dfn','research'):errors.append('invalid run_kind')
    try:rates=validate_fit_rates(config.get('fit_rates'))
    except ValueError as exc:errors.append(str(exc));rates=()
    params=section('parameters')
    if set(params)!=set(ELECTROTHERMAL_NAMES):errors.append('parameters must contain exactly the six electrothermal names')
    for i,(name,unit) in enumerate(zip(ELECTROTHERMAL_NAMES,ELECTROTHERMAL_UNITS)):
        item=params.get(name,{})
        if not isinstance(item,dict):errors.append(name+' definition missing');continue
        strict(item,('lower','upper','unit','transform','source'),name)
        lo,hi=item.get('lower'),item.get('upper')
        if numeric(lo,name+'.lower') and numeric(hi,name+'.upper') and lo>=hi:errors.append(name+' bounds require lower < upper')
        if item.get('unit')!=unit:errors.append(name+' unit must be '+unit)
        if item.get('transform') not in (('linear',) if i<2 else ('log10',) if i<4 else ('linear','log10')):errors.append(name+' invalid transform')
        if not item.get('source') or item.get('source')=='pending':errors.append(name+' bounds source pending')
    fixed=section('fixed');law=section('property_law')
    strict(fixed,(*FIXED_KEYS,'sources'),'fixed');strict(law,(*LAW_KEYS,'kind','sources'),'property_law')
    if law.get('kind')!='arrhenius_diffusion_v1':errors.append('explicit arrhenius_diffusion_v1 property_law required')
    for obj,keys,label in ((fixed,FIXED_KEYS,'fixed'),(law,LAW_KEYS,'property_law')):
        for key in keys:
            numeric(obj.get(key),label+'.'+key,positive='porosity' not in key)
            if not isinstance(obj.get('sources'),dict) or not obj['sources'].get(key) or obj['sources'][key]=='pending':errors.append(label+'.'+key+' source pending')
    try:electrothermal_space_from_config(config)
    except (ValueError,TypeError,KeyError) as exc:errors.append('parameter space: '+str(exc))
    conditions=section('conditions_by_rate')
    if set(conditions)!=set(rates):errors.append('conditions_by_rate must exactly match fit_rates')
    groups=[]
    for rate in rates:
        c=conditions.get(rate,{})
        if not isinstance(c,dict):errors.append(rate+' conditions invalid');continue
        strict(c,('initial_state','initial_temperature_k','voltage_cutoff_v','cooling_group_id'),rate)
        numeric(c.get('initial_temperature_k'),rate+'.initial_temperature_k');numeric(c.get('voltage_cutoff_v'),rate+'.voltage_cutoff_v')
        state=c.get('initial_state',{})
        if not isinstance(state,dict) or state.get('mode') not in ('parameterization','explicit_soc'):errors.append(rate+' initial_state pending')
        elif state['mode']=='explicit_soc' and (type(state.get('soc')) not in (int,float) or not 0<=state['soc']<=1):errors.append(rate+' initial soc invalid')
        if not c.get('cooling_group_id'):errors.append(rate+' cooling group pending')
        groups.append(c.get('cooling_group_id'))
    if len(set(groups))>1:errors.append('all selected cases must share the same confirmed cooling group')
    data=section('data');strict(data,('kind','by_rate','exclusions'),'data')
    if data.get('kind') not in ('builtin_synthetic','inline','xlsx'):errors.append('invalid electrothermal data kind')
    by_rate=data.get('by_rate',{})
    if not isinstance(by_rate,dict) or set(by_rate)!=set(rates):errors.append('data.by_rate must exactly match fit_rates');by_rate={}
    exclusions=data.get('exclusions',[])
    if not isinstance(exclusions,list) or any(not isinstance(x,dict) or set(x)!= {'source_id','reason'} or not x['source_id'] or not x['reason'] for x in exclusions):errors.append('data.exclusions must record source_id and reason');exclusions=[]
    excluded={KNOWN_BAD_3C,*[x['source_id'] for x in exclusions]}
    for rate,item in by_rate.items():
        if not isinstance(item,dict) or not item.get('source_id'):errors.append(rate+' data source_id required')
        elif item['source_id'] in excluded:errors.append(rate+' selected source is excluded')
    model=section('model');strict(model,('provider','name','parameterization_id','pybamm_version','options','mesh_points','solver','output_period_s'),'model')
    if 'output_period_s' in model:numeric(model['output_period_s'],'model.output_period_s')
    if model.get('provider') not in ('software','pybamm') or model.get('name')!='DFN' or model.get('parameterization_id')!='Chen2020':errors.append('explicit DFN/Chen2020 model required')
    if config.get('run_kind')=='synthetic_software' and model.get('provider')!='software':errors.append('software fixture must not silently use a DFN backend')
    if config.get('run_kind') in ('research','synthetic_dfn') and model.get('provider')!='pybamm':errors.append('model.provider must be pybamm for research/synthetic_dfn')
    if model.get('pybamm_version')!='25.10.2':errors.append('locked PyBaMM 25.10.2 required')
    if model.get('options')!={'thermal':'lumped','use lumped thermal capacity':'true','surface temperature':'ambient'}:errors.append('verified lumped thermal options required')
    opt=section('optimization');strict(opt,('mode','initial_count','total_candidate_budget','seed','gp_sweeps','global_pool_size','local_pool_size','local_radius','max_rate_attempts','parallel_workers','objective_scales','rho_aug','weights','hv_reference','warmstart','region','region_advice','region_selection','region_evidence','initial_plan'),'optimization')
    if opt.get('mode') not in ('parego','warmstart_only','full_llmbo_mo'):errors.append('invalid MO mode')
    if opt.get('region_advice','legacy_v1') not in ('legacy_v1','candidate_aware_v1'):errors.append('invalid Region advice policy')
    if opt.get('region_selection','global_lift_v1') not in ('global_lift_v1','eligible_region_v1','fair_region_v1'):errors.append('invalid Region selection policy')
    if opt.get('region_selection')=='eligible_region_v1' and opt.get('region_advice')!='candidate_aware_v1':errors.append('eligible regional selection requires candidate-aware advice')
    if opt.get('region_selection')=='fair_region_v1' and opt.get('region_advice')!='candidate_aware_v1':errors.append('fair regional selection requires candidate-aware advice')
    if opt.get('region_evidence','legacy_v1') not in ('legacy_v1','signed_residual_v1'):errors.append('invalid Region evidence policy')
    if opt.get('region_evidence')=='signed_residual_v1' and (opt.get('region_advice')!='candidate_aware_v1' or opt.get('region_selection')!='fair_region_v1'):
        errors.append('signed residual evidence requires candidate-aware fair regional selection')
    warm=opt.get('warmstart')
    if not isinstance(warm,dict):errors.append('warmstart must be an object')
    else:
        strict(warm,('count','pool_size','max_requests','max_candidates','max_evaluations'),'warmstart')
        for name in ('count','pool_size','max_requests','max_candidates','max_evaluations'):numeric(warm.get(name),'warmstart.'+name,integer=True)
        if warm.get('count')!=opt.get('initial_count'):errors.append('warmstart count must equal initial_count')
        if type(warm.get('pool_size')) is int and type(opt.get('initial_count')) is int and warm['pool_size']<opt['initial_count']:errors.append('warmstart pool smaller than seed count')
    for name in ('initial_count','total_candidate_budget','seed','gp_sweeps','global_pool_size','local_pool_size','max_rate_attempts'):
        numeric(opt.get(name),'optimization.'+name,positive=name not in ('seed','gp_sweeps','local_pool_size'),integer=True)
    if type(opt.get('initial_count')) is int and opt['initial_count']<2:errors.append('initial_count must be >=2')
    if type(opt.get('total_candidate_budget')) is int and type(opt.get('initial_count')) is int and opt['total_candidate_budget']<opt['initial_count']:errors.append('candidate budget smaller than initialization')
    if opt.get('parallel_workers')!=1 or type(opt.get('parallel_workers')) is not int:errors.append('parallel_workers must be 1')
    for name in ('objective_scales','weights'):
        values=opt.get(name)
        if name=='objective_scales':
            if not isinstance(values,list) or len(values)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values):errors.append('two positive objective_scales required')
        elif not isinstance(values,list) or not values or any(not isinstance(w,list) or len(w)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<0 for v in w) or abs(sum(w)-1)>1e-12 for w in values):errors.append('explicit two-dimensional simplex weights required')
    numeric(opt.get('rho_aug'),'rho_aug',positive=False);numeric(opt.get('local_radius'),'local_radius')
    ref=opt.get('hv_reference')
    if ref is not None and (not isinstance(ref,list) or len(ref)!=2 or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in ref)):errors.append('hv_reference must be null or two positive fixed metric coordinates')
    budget=section('budgets');strict(budget,('max_solver_calls','max_llm_requests','wall_clock_s'),'budgets')
    for key in ('max_solver_calls','max_llm_requests'):numeric(budget.get(key),'budgets.'+key,positive=False,integer=True)
    numeric(budget.get('wall_clock_s'),'budgets.wall_clock_s')
    llm=section('llm');strict(llm,('enabled','endpoint','api_key_env','model','max_tokens','timeout_s','json_mode','task_options','region_wire_format','thinking'),'llm')
    from .electrothermal_region_wire import region_wire_format
    try:region_wire_format(config)
    except (ValueError,TypeError,KeyError):errors.append('invalid Region wire format')
    if type(llm.get('enabled')) is not bool:errors.append('llm.enabled must be boolean')
    if type(llm.get('json_mode')) is not bool:errors.append('llm.json_mode must be boolean')
    from .electrothermal_requests import request_controls
    try:
        for task in ('warm_start_electrothermal','region_preference_electrothermal'):request_controls(config,task)
    except (ValueError,TypeError,KeyError):errors.append('invalid LLM task limits or global ceilings')
    if llm.get('enabled'):
        from urllib.parse import urlsplit
        url=urlsplit(llm.get('endpoint') or '')
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.query or url.fragment or not url.path.endswith('/chat/completions'):errors.append('LLM HTTPS chat endpoint required')
        if not llm.get('api_key_env') or not llm.get('model'):errors.append('explicit LLM model and credential environment name required')
    if config.get('run_kind')=='research':
        confirmations=section('research_confirmations')
        for key in CONFIRMATIONS:
            if confirmations.get(key) is not True:errors.append('research confirmation pending: '+key)
        if data.get('kind')=='builtin_synthetic':errors.append('research cannot use a software data fixture')
        for obj in (params,fixed.get('sources',{}),law.get('sources',{})):
            if 'synthetic_fixture_only' in str(obj):errors.append('synthetic physical values are not confirmed research properties')
    return errors
