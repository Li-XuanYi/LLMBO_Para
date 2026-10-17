"""Artificial values only; these are not recommended cell parameters."""
from copy import deepcopy

R3=('0.5C','1C','2C')
R4=(*R3,'3C')
NAMES=('eps_s_n','eps_s_p','D_s_n_ref','D_s_p_ref','C_th','G_th')


def et_config(fit_rates=R3):
    units=('1','1','m2.s-1','m2.s-1','J.K-1','W.K-1')
    bounds=((.3,.7),(.3,.65),(1e-15,1e-12),(1e-15,1e-12),(20.,80.),(.02,.3))
    fixed={'cell_volume_m3':2e-5,'cooling_area_m2':.005,'negative_porosity':.25,'positive_porosity':.335,
           'negative_conductivity_s_m':215.,'positive_conductivity_s_m':.18,'electrolyte_diffusivity_multiplier':1.}
    fixed['sources']={k:'synthetic_fixture_only' for k in fixed}
    law={'kind':'arrhenius_diffusion_v1','reference_temperature_k':298.15,
         'activation_energy_n_j_mol':22000.,'activation_energy_p_j_mol':29000.}
    law['sources']={k:'synthetic_fixture_only' for k in law if k!='kind'}
    return {'schema_version':2,'problem_type':'electrothermal_identification','parameter_profile':'electrothermal_4e2t',
        'run_kind':'synthetic_software','cell_id':'artificial_not_a_measured_cell','fit_rates':list(fit_rates),
        'parameters':{n:{'lower':a,'upper':b,'unit':u,'transform':'linear' if i<2 else 'log10','source':'synthetic_fixture_only'}
                      for i,(n,(a,b),u) in enumerate(zip(NAMES,bounds,units))},
        'fixed':fixed,'property_law':law,
        'conditions_by_rate':{r:{'initial_state':{'mode':'parameterization'},'initial_temperature_k':300.15,
            'voltage_cutoff_v':2.5,'cooling_group_id':'synthetic_shared'} for r in fit_rates},
        'data':{'kind':'builtin_synthetic','by_rate':{r:{'source_id':'synthetic-v1:'+r} for r in fit_rates},'exclusions':[]},
        'model':{'provider':'software','name':'DFN','parameterization_id':'Chen2020','pybamm_version':'25.10.2',
            'options':{'thermal':'lumped','use lumped thermal capacity':'true','surface temperature':'ambient'},
            'mesh_points':{'x_n':8,'x_s':8,'x_p':8,'r_n':8,'r_p':8},
            'solver':{'rtol':1e-6,'atol':1e-6,'dt_max':60.,'num_threads':1}},
        'optimization':{'mode':'parego','initial_count':2,'total_candidate_budget':4,'seed':17,'gp_sweeps':1,
            'global_pool_size':16,'local_pool_size':8,'local_radius':.2,'max_rate_attempts':1,'parallel_workers':1,
            'objective_scales':[.1,1.],'rho_aug':.05,'weights':[[.8,.2],[.2,.8],[.5,.5]],'hv_reference':[10.,10.],
            'warmstart':{'count':2,'pool_size':4,'max_requests':3,'max_candidates':8,'max_evaluations':8},
            'region':{}},
        'budgets':{'max_solver_calls':0,'max_llm_requests':0,'wall_clock_s':60.},
        'llm':{'enabled':False,'endpoint':None,'api_key_env':None,'model':None,'max_tokens':2048,'timeout_s':30.,'json_mode':True},
        'research_confirmations':{}}


def clone(value):return deepcopy(value)
