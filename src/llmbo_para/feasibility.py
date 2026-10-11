"""Necessary lithium-inventory check; it never replaces a four-rate solve."""
from dataclasses import asdict, dataclass
import math
import numpy as np


@dataclass(frozen=True)
class InventoryGate:
    negative_ah_per_fraction: float
    positive_ah_per_fraction: float
    required_ah: float

    def __post_init__(self):
        if any(not math.isfinite(value) or value <= 0 for value in asdict(self).values()):
            raise ValueError("inventory coefficients and required charge must be positive and finite")

    @classmethod
    def from_parameters(cls, parameters, series):
        import pybamm
        factor = (float(parameters["Electrode height [m]"]) * float(parameters["Electrode width [m]"])
            * float(parameters["Number of electrodes connected in parallel to make a cell"])
            * float(pybamm.constants.F.value) / 3600.)
        required = []
        for row in series.values():
            if row.current_a is None or row.discharge_current_sign not in {-1, 1}:
                raise ValueError("inventory screening requires explicit signed discharge currents")
            current = np.asarray(row.current_a) * row.discharge_current_sign
            if np.any(current < 0):
                raise ValueError("inventory screening supports discharge-only records")
            required.append(float(np.trapezoid(current, row.time_s) / 3600.))
        return cls(
            factor * float(parameters["Negative electrode thickness [m]"]) * float(parameters["Initial concentration in negative electrode [mol.m-3]"]),
            factor * float(parameters["Positive electrode thickness [m]"]) * (float(parameters["Maximum concentration in positive electrode [mol.m-3]"]) - float(parameters["Initial concentration in positive electrode [mol.m-3]"])),
            max(required))

    def check(self, point):
        upper = min(self.negative_ah_per_fraction * point[0], self.positive_ah_per_fraction * point[1])
        return {"feasible": bool(upper + 1e-12 >= self.required_ah),
            "ideal_discharge_upper_bound_ah": float(upper), "required_discharge_ah": self.required_ah,
            "reason": "necessary_inventory_bound"}


def simulation_signature(config, series):
    from .runstore import digest_value
    return digest_value({"model": config["model"], "parameters": config["parameters"], "conditions_by_rate": config["conditions_by_rate"],
        "physical_constraints": config["physical_constraints"],
        "series": {rate: asdict(row) for rate, row in series.items()}})
