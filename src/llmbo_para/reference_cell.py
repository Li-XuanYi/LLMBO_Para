"""Explicit parameter factory for the user-authorized Reference cell design."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ScaledElectrolyteDiffusivity:
    """Preserve the reference concentration/temperature law with a fixed scale."""

    reference_function: object
    multiplier: float

    def __call__(self, concentration, temperature):
        return self.multiplier * self.reference_function(concentration, temperature)


def chen2020_reference_parameters():
    """Load a fresh Chen2020 set, matching Reference/LLAMBO-master/P2D.ipynb.

    Candidate parameters are applied by the existing DFN adapter. All other
    values, including initial concentrations, remain in the pinned set.
    """
    import pybamm

    return pybamm.ParameterValues("Chen2020")
