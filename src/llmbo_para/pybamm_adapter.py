"""Optional PyBaMM bridge with injected lab parameters and solver configuration."""

from __future__ import annotations

from collections.abc import Callable
import inspect
from pathlib import Path
from typing import Mapping

import numpy as np

from .evaluation import DischargeSeries
from .metrics import RATE_ORDER
from .parameters import PARAMETER_NAMES
from .providers import load_factory
from .reference_cell import ScaledElectrolyteDiffusivity
from .runstore import sha256_file


class PyBaMMSimulator:
    """A six-parameter DFN runner; lab parameter values are supplied by a factory.

    PyBaMM is imported lazily. The factory must return the research group's
    version-matched ParameterValues object. Model options and solver are explicit
    constructor inputs so runs never inherit undocumented defaults silently.
    """

    def __init__(
        self,
        parameter_values_factory: Callable[[], object],
        *,
        model_options: Mapping,
        conditions_by_rate: Mapping,
        pinned_version: str,
        mesh_points: Mapping,
        solver_factory: Callable[[object], object],
        model_factory: Callable[[object, Mapping], object] | None = None,
        fixed_porosity: Mapping | None = None,
        initial_state_mode: str = "explicit_soc",
        output_at_measured_times: bool = False,
        fixed_electrolyte_diffusivity_multiplier: float = 1.0,
    ):
        if not callable(parameter_values_factory) or model_options is None or not callable(solver_factory):
            raise ValueError("explicit lab parameter factory, model options and solver factory are required")
        if set(conditions_by_rate) != set(RATE_ORDER) or not pinned_version or not mesh_points:
            raise ValueError("explicit four-rate initial conditions, PyBaMM version and mesh are required")
        self.parameter_values_factory = parameter_values_factory
        self.model_options = dict(model_options)
        self.solver_factory = solver_factory
        self.model_factory = model_factory
        self.conditions_by_rate = dict(conditions_by_rate)
        self.pinned_version = pinned_version
        self.mesh_points = dict(mesh_points)
        self._base_parameters = None
        self.fixed_porosity = dict(fixed_porosity) if fixed_porosity is not None else None
        if initial_state_mode not in ("explicit_soc", "parameterization"):
            raise ValueError("initial_state_mode must be explicit_soc or parameterization")
        if initial_state_mode == "parameterization" and any(v.get("initial_soc") is not None for v in self.conditions_by_rate.values()):
            raise ValueError("parameterization initial concentrations cannot be combined with an explicit initial SOC")
        self.initial_state_mode = initial_state_mode
        self.output_at_measured_times = output_at_measured_times
        if (isinstance(fixed_electrolyte_diffusivity_multiplier, bool)
                or not np.isfinite(fixed_electrolyte_diffusivity_multiplier)
                or fixed_electrolyte_diffusivity_multiplier <= 0):
            raise ValueError("fixed electrolyte diffusivity multiplier must be finite and positive")
        self.fixed_electrolyte_diffusivity_multiplier = float(fixed_electrolyte_diffusivity_multiplier)

    def base_parameters(self):
        if self._base_parameters is None:
            base = self.parameter_values_factory().copy()
            if self.fixed_electrolyte_diffusivity_multiplier != 1.0:
                key = "Electrolyte diffusivity [m2.s-1]"
                reference_function = base[key]
                if not callable(reference_function):
                    raise ValueError("fixed electrolyte scaling requires a reference concentration/temperature function")
                base.update({key: ScaledElectrolyteDiffusivity(
                    reference_function, self.fixed_electrolyte_diffusivity_multiplier)}, check_already_exists=True)
            if self.fixed_porosity is not None:
                for electrode in ("negative", "positive"):
                    key = electrode.capitalize() + " electrode porosity"
                    if key not in base or not np.isclose(float(base[key]), self.fixed_porosity[electrode], rtol=0, atol=1e-12):
                        raise ValueError(f"lab parameterization {key} differs from the configured physical constraint")
            self._base_parameters = base
        return self._base_parameters

    def save_parameterization(self, store) -> None:
        """Record fixed parameter values and callable source files before solving."""
        values = self.base_parameters()
        file_hashes = {}

        def describe(value):
            if value is None or isinstance(value, (str, bool, int, float)):
                return value
            if isinstance(value, np.generic):
                return value.item()
            if isinstance(value, np.ndarray):
                return value.tolist()
            if isinstance(value, (tuple, list)):
                return [describe(v) for v in value]
            if isinstance(value, dict):
                return {str(k): describe(v) for k, v in value.items()}
            if isinstance(value, ScaledElectrolyteDiffusivity):
                return {"scaled_reference_function": describe(value.reference_function),
                        "fixed_multiplier": value.multiplier,
                        "implementation": describe(value.__call__)}
            if callable(value):
                source = inspect.getsourcefile(value)
                if not source or not Path(source).is_file():
                    raise ValueError("parameter callable source must be available for reproducibility")
                digest = sha256_file(source)
                if digest not in file_hashes:
                    target = store.path / "parameterization-source" / (digest[:12] + "_" + Path(source).name)
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(Path(source).read_bytes())
                    file_hashes[digest] = str(target.relative_to(store.path))
                return {"callable": value.__module__ + ":" + value.__qualname__, "source_sha256": digest}
            raise ValueError(f"unsupported fixed parameter value type: {type(value).__name__}; provide a serializable lab adapter")

        data = {str(k): describe(v) for k, v in values.items()}
        data["factory"] = describe(self.parameter_values_factory)
        store.write_json("parameterization.json", {"values": data, "source_files": file_hashes})

    def simulate(self, parameters: Mapping[str, float], series: DischargeSeries):
        try:
            import pybamm
        except ImportError as exc:
            raise RuntimeError("PyBaMM is not installed in this Python 3.12 environment") from exc
        if pybamm.__version__ != self.pinned_version:
            raise RuntimeError("installed PyBaMM version differs from the explicit run configuration")
        base = self.base_parameters().copy()
        if set(parameters) != set(PARAMETER_NAMES):
            raise ValueError("the PyBaMM adapter requires exactly the six documented parameter keys")
        values = {str(k): float(v) for k, v in parameters.items()}
        base.update(values, check_already_exists=True)
        times = np.asarray(series.time_s, dtype=float)
        if series.current_a is None:
            raise ValueError("PyBaMM requires measured or explicitly assumed current")
        current = np.asarray(series.current_a, dtype=float)
        if current.shape != times.shape:
            raise ValueError("the PyBaMM adapter requires one current value at each fixed time")
        if times[0] != 0:
            raise ValueError("PyBaMM input time must begin at zero; configure the time origin explicitly upstream")
        if series.discharge_current_sign not in {-1, 1}:
            raise ValueError("the measured discharge-current sign must be explicitly specified")
        current = current * series.discharge_current_sign
        conditions = self.conditions_by_rate[series.rate]
        base.update({"Initial temperature [K]": conditions["initial_temperature_k"],
                     "Ambient temperature [K]": conditions["ambient_temperature_k"],
                     "Lower voltage cut-off [V]": conditions["voltage_cutoff_v"]}, check_already_exists=True)
        model = (
            pybamm.lithium_ion.DFN(options=self.model_options)
            if self.model_factory is None else self.model_factory(pybamm, self.model_options)
        )
        current_function = pybamm.Interpolant(times, current, pybamm.t, interpolator="linear", extrapolate=False)
        base.update({"Current function [A]": current_function}, check_already_exists=True)
        solver = self.solver_factory(pybamm)
        var_pts = {getattr(pybamm.standard_spatial_vars, key): value for key, value in self.mesh_points.items()}
        simulation = pybamm.Simulation(model, parameter_values=base, solver=solver, var_pts=var_pts)
        solve_settings = {"t_eval": times}
        if self.output_at_measured_times:
            solve_settings = {"t_eval": times[[0, -1]], "t_interp": times}
        if self.initial_state_mode == "explicit_soc":
            solve_settings["initial_soc"] = conditions["initial_soc"]
        from .evaluation import SimulationTrace, SimulationSolverError
        try:
            if self.initial_state_mode == "explicit_soc":
                from .pybamm_compat import electrode_soh_numpy_compat
                with electrode_soh_numpy_compat():
                    solution = simulation.solve(**solve_settings)
            else:
                solution = simulation.solve(**solve_settings)
        except Exception as exc:
            if isinstance(exc, getattr(pybamm, "SolverError", ())):
                raise SimulationSolverError(str(exc), solver_error_type=type(exc).__name__) from exc
            raise
        termination = getattr(solution, "termination", None)
        termination = str(termination) if termination is not None else None
        is_event = termination is not None and termination.lower().startswith("event:")
        cutoff = ("voltage" in termination.lower()) if is_event else (False if termination == "final time" else None)
        return SimulationTrace(solution["Time [s]"].entries, solution["Terminal voltage [V]"].entries,
            termination=termination, voltage_cutoff=cutoff,
            simulation_completed=(termination == "final time") if termination is not None else None)


def build_simulator(config: dict) -> PyBaMMSimulator:
    model = config["model"]
    solver = model["solver"]
    if solver["name"] == "IDAKLUSolver":
        solver_factory = lambda pybamm: pybamm.IDAKLUSolver(
            rtol=solver["rtol"], atol=solver["atol"],
            options={"num_threads": solver["num_threads"], "num_solvers": 1, "dt_max": solver["dt_max"]})
    else:
        solver_factory = lambda pybamm: pybamm.CasadiSolver(
            mode=solver["mode"], rtol=solver["rtol"], atol=solver["atol"], dt_max=solver["dt_max"])
    return PyBaMMSimulator(
        load_factory(model["parameter_values_factory"]),
        model_options=model["options"], conditions_by_rate=config["conditions_by_rate"],
        pinned_version=model["pybamm_version"], mesh_points=model["mesh_points"],
        fixed_porosity=config["physical_constraints"]["fixed_porosity"],
        initial_state_mode=model.get("initial_state_mode", "explicit_soc"),
        solver_factory=solver_factory,
        output_at_measured_times=solver["name"] == "IDAKLUSolver",
        fixed_electrolyte_diffusivity_multiplier=model.get("fixed_electrolyte_diffusivity_multiplier", 1.0),
    )
