"""Explicit algebraic fixtures; never presented as real DFN physics."""
from .electrothermal_data import TimeSignal,Observation,ElectrothermalCase,ElectrothermalDataset


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
