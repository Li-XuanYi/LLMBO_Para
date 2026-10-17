"""Six optimization roles; fixed material properties are not hidden variables."""
ELECTROTHERMAL_NAMES=('eps_s_n','eps_s_p','D_s_n_ref','D_s_p_ref','C_th','G_th')
ELECTROTHERMAL_UNITS=('1','1','m2.s-1','m2.s-1','J.K-1','W.K-1')
PARAMETER_ROLES=dict(zip(ELECTROTHERMAL_NAMES,(
    'negative active material volume fraction','positive active material volume fraction',
    'negative solid diffusivity at reference temperature','positive solid diffusivity at reference temperature',
    'whole-cell heat capacity','effective thermal conductance to ambient')))

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ReferenceDiffusivity:
    reference_value:float
    reference_temperature_k:float
    activation_energy_j_mol:float

    def __call__(self,stoichiometry,temperature):
        import pybamm
        return self.reference_value*pybamm.exp(self.activation_energy_j_mol/float(pybamm.constants.R.value)*
                    (1/self.reference_temperature_k-1/temperature))


@dataclass
class AppliedParameters:
    parameter_values:object
    mapping:dict


def apply_electrothermal_parameters(base,theta,fixed):
    from .electrothermal_config import FIXED_KEYS,LAW_KEYS
    from .reference_cell import ScaledElectrolyteDiffusivity
    if set(theta)!=set(ELECTROTHERMAL_NAMES) or any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in theta.values()):
        raise ValueError('exact positive electrothermal parameter names and values required')
    if set(fixed)!=set((*FIXED_KEYS,'sources','property_law')):raise ValueError('fixed properties must be explicit and recognized')
    law=fixed['property_law']
    if law.get('kind')!='arrhenius_diffusion_v1':raise ValueError('explicit reference diffusivity law required')
    for obj,keys in ((fixed,FIXED_KEYS),(law,LAW_KEYS)):
        for key in keys:
            v=obj.get(key)
            if type(v) not in (int,float) or not math.isfinite(v) or (v<0 if 'porosity' in key else v<=0):raise ValueError('fixed physical value missing: '+key)
            if not obj.get('sources',{}).get(key) or obj['sources'][key]=='pending':raise ValueError('fixed source missing: '+key)
    if any(theta[name]+fixed[key]>1+1e-12 for name,key in (('eps_s_n','negative_porosity'),('eps_s_p','positive_porosity'))):raise ValueError('solid fraction plus fixed porosity exceeds one')
    values=base.copy();c=theta['C_th'];g=theta['G_th'];volume=fixed['cell_volume_m3'];area=fixed['cooling_area_m2']
    native={'Negative electrode active material volume fraction':theta['eps_s_n'],
        'Positive electrode active material volume fraction':theta['eps_s_p'],
        'Negative electrode conductivity [S.m-1]':fixed['negative_conductivity_s_m'],
        'Positive electrode conductivity [S.m-1]':fixed['positive_conductivity_s_m'],
        'Negative electrode porosity':fixed['negative_porosity'],'Positive electrode porosity':fixed['positive_porosity'],
        'Cell volume [m3]':volume,'Cell cooling surface area [m2]':area,
        'Total heat transfer coefficient [W.m-2.K-1]':g/area}
    values.update(native,check_already_exists=True)
    # Exactly this version-verified concentrated-capacity key may be added.
    values.update({'Cell heat capacity [J.K-1.m-3]':c/volume},check_already_exists=False)
    native['Cell heat capacity [J.K-1.m-3]']=c/volume
    laws={}
    for electrode,short in (('Negative','n'),('Positive','p')):
        fn=ReferenceDiffusivity(theta['D_s_'+short+'_ref'],law['reference_temperature_k'],law['activation_energy_'+short+'_j_mol'])
        key=electrode+' particle diffusivity [m2.s-1]';values.update({key:fn},check_already_exists=True)
        laws[key]={'kind':law['kind'],'reference_value':fn.reference_value,'reference_temperature_k':fn.reference_temperature_k,
                   'activation_energy_j_mol':fn.activation_energy_j_mol,'source':law['sources']['activation_energy_'+short+'_j_mol']}
    multiplier=fixed['electrolyte_diffusivity_multiplier']
    if multiplier!=1.:
        key='Electrolyte diffusivity [m2.s-1]';values.update({key:ScaledElectrolyteDiffusivity(values[key],multiplier)},check_already_exists=True)
    return AppliedParameters(values,{'profile':'electrothermal_4e2t','theta':dict(theta),'native':native,'diffusivity_laws':laws,
        'fixed_sources':dict(fixed['sources']),'property_law_sources':dict(law['sources']),
        'thermal_units':{'C_th':'J.K-1','G_th':'W.K-1','volume_capacity':'J.K-1.m-3','heat_transfer':'W.m-2.K-1'},
        'kinetics':'unchanged Chen2020 exchange-current functions','fixed_electrolyte_diffusivity_multiplier':multiplier})
