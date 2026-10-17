"""Explicit algebraic fixtures; never presented as real DFN physics."""
from .electrothermal_data import TimeSignal,Observation,ElectrothermalCase,ElectrothermalDataset
import numpy as np


def analytic_lumped_temperature(times,c_th,g_th,t0,tamb,heat_w):
    if c_th<=0 or g_th<=0:raise ValueError('positive whole-cell capacity and conductance required')
    t=np.asarray(times,dtype=float)
    return tamb+heat_w/g_th+(t0-tamb-heat_w/g_th)*np.exp(-g_th*t/c_th)


class SyntheticElectrothermalSimulator:
    backend_kind='software'

    def simulate(self,parameters,case):
        from .electrothermal_evaluation import ElectrothermalTrace
        from .runstore import digest_value
        # Analytic constant-forcing fixture, with explicit synthetic thermal feedback.
        if len(set(case.current_a.values))!=1 or len(set(case.ambient_temperature_k.values))!=1:
            raise ValueError('analytic software fixture requires constant forcing')
        horizon=max(case.voltage.time_s[-1],case.cell_temperature_k.time_s[-1])
        t=np.unique(np.r_[np.linspace(0,horizon,33),case.voltage.time_s,case.cell_temperature_k.time_s])
        current=case.current_a.values[0];ambient=case.ambient_temperature_k.values[0]
        p=parameters;heat=.05*current**2*(1+abs(p['eps_s_n']-.5))
        temp=analytic_lumped_temperature(t,p['C_th'],p['G_th'],case.initial_state['temperature_k'],ambient,heat)
        voltage=4.2-.03*current*t+.1*(p['eps_s_n']-.5)-.1*(p['eps_s_p']-.5)+.005*np.log10(p['D_s_n_ref']/1e-13)-.005*np.log10(p['D_s_p_ref']/1e-13)+.001*(temp-298.15)
        ident='software-'+digest_value({'parameters':p,'rate':case.rate,'initial':case.initial_state,'current':current,'ambient':ambient})[:24]
        return ElectrothermalTrace(t,voltage,temp,np.full(len(t),heat),'final time',ident,{'kind':'analytic_software_fixture'})


def make_synthetic_dataset(fit_rates):
    cases={}
    for rate in fit_rates:
        provenance={'source_id':'synthetic-v1:'+rate,'kind':'artificial_software_fixture'}
        current=float(rate[:-1])
        cases[rate]=ElectrothermalCase(rate,
            TimeSignal((0.,4.),(current,current),'A',provenance),
            TimeSignal((0.,4.),(298.15,298.15),'K',provenance),
            Observation((0.,2.,4.),(4.2,4.1,4.),'V',provenance),
            Observation((0.,1.,4.),(300.15,300.25,300.55),'K',provenance),
            {'mode':'parameterization','temperature_k':300.15},'synthetic_shared',provenance)
    return ElectrothermalDataset(tuple(fit_rates),cases)
