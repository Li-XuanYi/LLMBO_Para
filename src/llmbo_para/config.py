"""JSON run configuration parsing with required experimental values."""

from __future__ import annotations

import json
import math
from pathlib import Path

from .metrics import RATE_ORDER
from .parameters import PARAMETER_NAMES, ParameterSpace


def load_json(path: str | Path) -> dict:
    with Path(path).open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict):
        raise ValueError("configuration root must be a JSON object")
    return value


def parameter_space_from_config(config: dict) -> ParameterSpace:
    parameters = config.get("parameters")
    if not isinstance(parameters, dict):
        raise ValueError("configuration requires a parameters object")
    bounds, transforms, units = {}, {}, {}
    for name in PARAMETER_NAMES:
        item = parameters.get(name)
        if not isinstance(item, dict) or item.get("lower") is None or item.get("upper") is None:
            raise ValueError(f"research-group lower and upper bounds are required for {name}")
        bounds[name] = (item["lower"], item["upper"])
        transforms[name] = item.get("transform")
        units[name] = item.get("unit")
        if transforms[name] is None or units[name] is None:
            raise ValueError(f"transform and unit are required for {name}")
    physical = config.get("physical_constraints", {})
    porosity = physical.get("fixed_porosity", {})
    return ParameterSpace.from_bounds(
        bounds,
        transforms,
        units,
        negative_porosity=porosity.get("negative"),
        positive_porosity=porosity.get("positive"),
    )


def validate_experiment_config(config: dict) -> None:
    errors = configuration_errors(config)
    if errors:
        raise ValueError("configuration preflight failed:\n- " + "\n- ".join(errors))


def configuration_errors(config: dict) -> list[str]:
    """Collect all missing/unsupported settings before executing any plugin or API."""
    from .runstore import reject_inline_secrets

    reject_inline_secrets(config)
    errors = []
    allowed = {"schema_version", "status", "run_kind", "cell_id", "cell_format", "nominal_capacity_ah", "rates", "parameters", "physical_constraints", "conditions_by_rate", "data", "model", "optimization", "llm"}
    for key in sorted(set(config) - allowed):
        errors.append(f"unrecognized configuration setting: {key}")
    nested_allowed = {
        "data": {"kind", "path", "sha256", "evaluation_grid", "legacy_assumed_1s", "sample_period_s", "time_column", "current_column", "voltage_column", "temperature_column", "temperature_unit", "time_unit", "current_unit", "voltage_unit", "sheet_by_rate", "discharge_current_sign"},
        "model": {"provider", "name", "parameterization_id", "parameter_values_factory", "pybamm_version", "options", "mesh_points", "solver", "fixture_formula", "initial_state_mode", "fixed_electrolyte_diffusivity_multiplier"},
        "optimization": {"seed", "warm_start_llm_points", "sobol_points", "total_candidate_budget", "candidate_pool_size", "composite_ei_draws", "parallel_workers", "llm_enabled", "gpu_backend", "gp_sweeps", "max_rate_attempts", "llm_warm_start_enabled", "llm_gp_groups_enabled", "strict_llm_tasks", "initial_candidates", "initial_candidates_source", "initial_candidates_evidence", "inventory_feasibility_filter", "bo_repair", "surrogate_mode", "llm_informed_enabled", "llm_informed", "reuse_screening_history"},
        "llm": {"transport", "endpoint", "api_key_env", "model", "timeout_s", "min_diversity_distance", "max_tokens", "json_mode", "thinking"},
        "physical_constraints": {"fixed_porosity"},
        "parameters": set(PARAMETER_NAMES),
    }
    for name, keys in nested_allowed.items():
        if isinstance(config.get(name), dict):
            errors.extend(f"unrecognized setting: {name}.{key}" for key in sorted(set(config[name])-keys))

    def number(value, name, *, minimum=None, maximum=None, positive=False, integer=False):
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
            errors.append(f"{name} must be an explicit finite number")
        elif integer and not isinstance(value, int):
            errors.append(f"{name} must be an integer")
        elif positive and value <= 0 or minimum is not None and value < minimum or maximum is not None and value > maximum:
            errors.append(f"{name} is outside its allowed range")

    def section(name):
        value = config.get(name)
        if not isinstance(value, dict):
            errors.append(f"{name} must be an object")
            return {}
        return value

    try:
        parameter_space_from_config(config)
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        errors.append(str(exc))
    if config.get("schema_version") != 1 or isinstance(config.get("schema_version"), bool):
        errors.append("schema_version must be 1; use the current template")
    kind = config.get("run_kind") if isinstance(config.get("run_kind"), str) else None
    if kind not in {"research", "synthetic_software_smoke_only"}:
        errors.append("run_kind must explicitly identify research or synthetic_software_smoke_only")
    if not isinstance(config.get("cell_id"), str) or not config["cell_id"].strip():
        errors.append("cell_id is required")
    if not isinstance(config.get("cell_format"), str) or not config["cell_format"].strip():
        errors.append("cell_format is required; do not infer a parameter set from the form factor")
    if config.get("rates") != list(RATE_ORDER):
        errors.append(f"rates must be exactly {list(RATE_ORDER)}; holdout experiments use a separate future protocol")
    number(config.get("nominal_capacity_ah"), "nominal_capacity_ah", positive=True)
    if kind == "research":
        physical = config.get("physical_constraints", {})
        porosity = physical.get("fixed_porosity", {}) if isinstance(physical, dict) else {}
        if not isinstance(porosity, dict):
            porosity = {}
        errors.extend(f"unrecognized fixed porosity setting: {key}" for key in set(porosity)-{"negative", "positive"})
        for key in ("negative", "positive"):
            number(porosity.get(key), "physical_constraints.fixed_porosity." + key, minimum=0, maximum=1)
    expected_units = ("1", "1", "m2.s-1", "m2.s-1", "S.m-1", "S.m-1")
    parameters = config.get("parameters", {})
    if isinstance(parameters, dict):
        for index, (name, unit) in enumerate(zip(PARAMETER_NAMES, expected_units)):
            item = parameters.get(name)
            if isinstance(item, dict):
                for bound in ("lower", "upper"):
                    number(item.get(bound), f"parameters.{name}.{bound}", positive=True)
                errors.extend(f"unrecognized parameter setting: {name}.{key}" for key in set(item)-{"lower", "upper", "transform", "unit"})
                if item.get("unit") != unit:
                    errors.append(f"parameter {name} requires unit {unit}")
                if index < 2 and item.get("transform") != "linear" or index in (2, 3) and item.get("transform") != "log10":
                    errors.append(f"parameter {name} has a transform inconsistent with the specified method")
    model_settings = config.get("model", {}) if isinstance(config.get("model"), dict) else {}
    initial_state_mode = model_settings.get("initial_state_mode", "explicit_soc")
    if initial_state_mode not in ("explicit_soc", "parameterization"):
        errors.append("model.initial_state_mode must be explicit_soc or parameterization")
    if initial_state_mode == "parameterization" and model_settings.get("provider") != "pybamm":
        errors.append("parameterization initial state requires the PyBaMM provider")
    conditions = section("conditions_by_rate")
    if set(conditions) != set(RATE_ORDER):
        errors.append("conditions_by_rate needs exactly the four fitting rates")
    for rate in RATE_ORDER:
        condition = conditions.get(rate, {})
        if not isinstance(condition, dict):
            errors.append(f"conditions_by_rate.{rate} must be an object")
            continue
        for key in set(condition) - {"initial_soc", "initial_temperature_k", "ambient_temperature_k", "voltage_cutoff_v"}:
            errors.append(f"unknown rate condition {rate}.{key}")
        if initial_state_mode == "parameterization":
            if "initial_soc" not in condition or condition["initial_soc"] is not None:
                errors.append(f"{rate}.initial_soc must be null when retaining parameterization initial concentrations")
        else:
            number(condition.get("initial_soc"), f"{rate}.initial_soc", minimum=0, maximum=1)
        for key in ("initial_temperature_k", "ambient_temperature_k", "voltage_cutoff_v"):
            number(condition.get(key), f"{rate}.{key}", positive=True)

    data = section("data")
    if data.get("evaluation_grid") != "all_measured_samples_no_extrapolation":
        errors.append("data.evaluation_grid must explicitly select all_measured_samples_no_extrapolation")
    if not isinstance(data.get("discharge_current_sign"), int) or isinstance(data.get("discharge_current_sign"), bool) or data.get("discharge_current_sign") not in {-1, 1}:
        errors.append("data.discharge_current_sign must be explicitly -1 or +1")
    for key, unit in (("time_unit", "s"), ("current_unit", "A"), ("voltage_unit", "V")):
        if data.get(key) != unit:
            errors.append(f"data.{key} must be {unit}; convert other units explicitly before this workflow")
    if kind == "research" and data.get("kind") != "xlsx":
        errors.append("research data.kind must be xlsx")
    if kind == "synthetic_software_smoke_only" and data.get("kind") != "builtin_synthetic":
        errors.append("synthetic data.kind must be builtin_synthetic")
    if data.get("kind") == "xlsx":
        for key in ("path", "sha256", "voltage_column"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                errors.append(f"data.{key} is required")
        if isinstance(data.get("sha256"), str) and (len(data["sha256"]) != 64 or any(c not in "0123456789abcdef" for c in data["sha256"].lower())):
            errors.append("data.sha256 must be a SHA-256 hex digest")
        sheets = data.get("sheet_by_rate", {})
        if not isinstance(sheets, dict) or set(sheets) != set(RATE_ORDER) or any(not isinstance(v, str) or not v.strip() for v in sheets.values()) or len(set(sheets.values())) != 4:
            errors.append("data.sheet_by_rate requires four distinct named sheets")
        if not isinstance(data.get("legacy_assumed_1s"), bool):
            errors.append("data.legacy_assumed_1s must be explicitly true or false")
        if data.get("legacy_assumed_1s"):
            if data.get("sample_period_s") != 1.0:
                errors.append("legacy_assumed_1s requires an explicit sample_period_s=1.0")
        else:
            for key in ("time_column", "current_column"):
                if not isinstance(data.get(key), str) or not data[key].strip():
                    errors.append(f"strict measured input requires data.{key}")
        if data.get("temperature_column") is not None and (not isinstance(data.get("temperature_unit"), str) or data.get("temperature_unit") not in {"degC", "K"}):
            errors.append("a mapped temperature column needs its confirmed temperature_unit")

    model = section("model")
    if "fixed_electrolyte_diffusivity_multiplier" in model and model.get("provider") != "pybamm":
        errors.append("fixed electrolyte diffusivity scaling requires the PyBaMM provider")
    expected_provider = "pybamm" if kind == "research" else "synthetic"
    if model.get("provider") != expected_provider:
        errors.append(f"model.provider must be {expected_provider} for this run_kind")
    if model.get("name") != "DFN":
        errors.append("only the specified DFN model is supported")
    if model.get("provider") == "pybamm":
        if "fixed_electrolyte_diffusivity_multiplier" in model:
            number(model["fixed_electrolyte_diffusivity_multiplier"], "model.fixed_electrolyte_diffusivity_multiplier", positive=True)
        for key in ("parameterization_id", "pybamm_version", "parameter_values_factory"):
            if not isinstance(model.get(key), str) or not model[key].strip():
                errors.append(f"model.{key} is required from the research group")
        if isinstance(model.get("parameter_values_factory"), str) and ":" not in model["parameter_values_factory"]:
            errors.append("model.parameter_values_factory must be module:callable")
        if not isinstance(model.get("options"), dict) or model["options"].get("thermal") != "isothermal":
            errors.append("the built-in PyBaMM adapter currently requires an explicit isothermal thermal option")
        mesh = model.get("mesh_points")
        if not isinstance(mesh, dict) or set(mesh) != {"x_n", "x_s", "x_p", "r_n", "r_p"}:
            errors.append("model.mesh_points requires x_n, x_s, x_p, r_n, r_p")
        else:
            for key, value in mesh.items():
                number(value, "model.mesh_points." + key, minimum=2, integer=True)
        solver = model.get("solver", {})
        if isinstance(solver, dict):
            permitted = {"name", "rtol", "atol", "dt_max", "num_threads"} if solver.get("name") == "IDAKLUSolver" else {"name", "mode", "rtol", "atol", "dt_max"}
            errors.extend(f"unrecognized solver setting: {key}" for key in set(solver)-permitted)
        if not isinstance(solver, dict) or solver.get("name") not in {"CasadiSolver", "IDAKLUSolver"}:
            errors.append("the built-in solver requires explicit CasadiSolver or IDAKLUSolver settings")
        else:
            if solver["name"] == "CasadiSolver" and solver.get("mode") != "safe":
                errors.append("CasadiSolver requires safe mode")
            if solver["name"] == "IDAKLUSolver" and (solver.get("num_threads") != 1 or isinstance(solver.get("num_threads"), bool)):
                errors.append("IDAKLUSolver requires explicit num_threads=1")
            for key in ("rtol", "atol", "dt_max"):
                number(solver.get(key), "model.solver." + key, positive=True)

    optimization = section("optimization")
    surrogate_mode = optimization.get("surrogate_mode", "per_rate")
    if not isinstance(surrogate_mode, str) or surrogate_mode not in {"per_rate", "single_objective"}:
        errors.append("optimization.surrogate_mode must be per_rate or single_objective")
    if "bo_repair" in optimization:
        from .bo_repair import RepairSettings
        try:
            if not isinstance(optimization["bo_repair"], dict):
                raise ValueError("optimization.bo_repair must be an object")
            RepairSettings.parse(optimization["bo_repair"])
        except ValueError as exc:
            errors.append(str(exc))
    for key, minimum in (("seed", 0), ("warm_start_llm_points", 0), ("sobol_points", 0 if "initial_candidates" in optimization else 2), ("total_candidate_budget", 2), ("candidate_pool_size", 1), ("composite_ei_draws", 1), ("gp_sweeps", 0), ("max_rate_attempts", 1)):
        number(optimization.get(key), "optimization." + key, minimum=minimum, integer=True)
    sizes = [optimization.get(k) for k in ("warm_start_llm_points", "sobol_points", "total_candidate_budget")]
    if all(isinstance(v, int) for v in sizes) and sizes[2] < sizes[0] + sizes[1]:
        errors.append("candidate budget is smaller than the complete initial allocation")
    if optimization.get("parallel_workers") != 1 or isinstance(optimization.get("parallel_workers"), bool):
        errors.append("only parallel_workers=1 is implemented and validated")
    if optimization.get("gpu_backend") != "cpu":
        errors.append("only gpu_backend=cpu is implemented and validated")
    if not isinstance(optimization.get("llm_enabled"), bool):
        errors.append("optimization.llm_enabled must be explicitly true or false")
    for key in ("llm_warm_start_enabled", "llm_gp_groups_enabled", "strict_llm_tasks", "inventory_feasibility_filter", "llm_informed_enabled", "reuse_screening_history"):
        if key in optimization and not isinstance(optimization[key], bool):
            errors.append("optimization." + key + " must be boolean")
    if optimization.get("reuse_screening_history") and (
        "initial_candidates" not in optimization or surrogate_mode != "per_rate"
        or not isinstance(optimization.get("bo_repair"), dict)
        or optimization["bo_repair"].get("training_data") != "per_rate"):
        errors.append("screening history reuse requires a verified initial plan and per_rate GP/training policies")
    if optimization.get("inventory_feasibility_filter") and (model.get("provider") != "pybamm" or initial_state_mode != "parameterization"):
        errors.append("inventory feasibility filter requires PyBaMM with fixed parameterization initial concentrations")
    warm_enabled = optimization.get("llm_warm_start_enabled", optimization.get("llm_enabled"))
    groups_enabled = optimization.get("llm_gp_groups_enabled", optimization.get("llm_enabled"))
    if surrogate_mode == "single_objective":
        if groups_enabled:
            errors.append("single_objective requires llm_gp_groups_enabled=false (one full Matérn kernel)")
        repair = optimization.get("bo_repair", {})
        if isinstance(repair, dict) and repair.get("training_data", "complete") != "complete":
            errors.append("single_objective requires complete four-rate objective labels")
    informed_enabled = optimization.get("llm_informed_enabled", False)
    if informed_enabled and (surrogate_mode != "single_objective" or groups_enabled):
        errors.append("LLM-Informed requires single_objective and disabled group kernels")
    if "llm_informed" in optimization:
        from .informed import InformedSettings
        try:
            InformedSettings.parse(optimization["llm_informed"])
        except ValueError as exc:
            errors.append(str(exc))
    if bool(optimization.get("llm_enabled")) != bool(warm_enabled or groups_enabled or informed_enabled):
        errors.append("llm_enabled must match whether any LLM component is enabled")
    if "initial_candidates" in optimization:
        points = optimization["initial_candidates"]
        if not isinstance(points, list) or len(points) < 2 or (all(isinstance(v, int) for v in sizes) and len(points) != sizes[0] + sizes[1]):
            errors.append("shared initial_candidates must match the initial allocation and contain at least two points")
        else:
            try:
                space = parameter_space_from_config(config)
                checked = [space.validate(point) for point in points]
                if len(set(checked)) != len(checked):
                    errors.append("shared initial_candidates must be unique")
            except (ValueError, TypeError) as exc:
                errors.append("shared initial_candidates: " + str(exc))
        source = optimization.get("initial_candidates_source")
        if source not in {"random", "llm", "history"} or (source == "llm") != bool(warm_enabled):
            errors.append("shared initial source must match the WarmStart component switch")
        evidence = optimization.get("initial_candidates_evidence")
        if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}
                or not isinstance(evidence.get("path"), str) or not evidence["path"]
                or not isinstance(evidence.get("sha256"), str) or len(evidence["sha256"]) != 64
                or any(char not in "0123456789abcdef" for char in evidence["sha256"])):
            errors.append("shared initial candidates require an explicit evidence path and SHA-256")
    pool, draws = optimization.get("candidate_pool_size"), optimization.get("composite_ei_draws")
    if isinstance(pool, int) and isinstance(draws, int) and pool * draws > 8388608:
        errors.append("candidate_pool_size * composite_ei_draws exceeds the implemented 8,388,608-element memory guard; add validated batching before increasing it")
    llm = section("llm")
    number(llm.get("min_diversity_distance"), "llm.min_diversity_distance", minimum=0)
    if optimization.get("llm_enabled"):
        for key in ("endpoint", "api_key_env", "model"):
            if not isinstance(llm.get(key), str) or not llm[key].strip():
                errors.append(f"enabled LLM requires llm.{key}")
        if llm.get("transport") not in ("structured_json_service", "openai_chat_completions"):
            errors.append("LLM transport must explicitly select structured_json_service or openai_chat_completions")
        if llm.get("transport") == "openai_chat_completions":
            number(llm.get("max_tokens"), "llm.max_tokens", minimum=1, maximum=8192, integer=True)
            if not isinstance(llm.get("json_mode"), bool):
                errors.append("chat transport requires an explicit llm.json_mode boolean")
            if llm.get("thinking") is not None and llm["thinking"] not in ("enabled", "disabled"):
                errors.append("llm.thinking must be enabled, disabled or omitted")
        number(llm.get("timeout_s"), "llm.timeout_s", positive=True)
    return errors
