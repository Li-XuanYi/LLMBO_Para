"""Paired four-arm ablation settings, without changing the scientific domain."""
from copy import deepcopy
from pathlib import Path
import numpy as np

from .runstore import sha256_file

ARMS = (("baseline", False, False), ("warm_start_only", True, False),
        ("gp_llm_only", False, True), ("full", True, True))


def random_initial_points(space, count, seed):
    """Uniform in the configured normalized space, rejecting physical violations."""
    rng = np.random.default_rng(seed)
    points, seen = [], set()
    for _ in range(max(10000, count * 1000)):
        normalized = rng.random(space.dimension)
        try:
            point = space.denormalize(normalized)
        except ValueError:
            continue
        if point in seen:
            continue
        seen.add(point)
        points.append(point)
        if len(points) == count:
            return points
    raise RuntimeError("could not generate the requested number of legal random initial points")


def arm_config(template, plan, plan_file, *, warm_start, gp_groups, bo_iterations):
    config = deepcopy(template)
    count = len(plan["parameters"])
    config["status"] = f"paired_four_arm_ablation_{count}_initial_then_{bo_iterations}_bo"
    config["optimization"].update(llm_enabled=warm_start or gp_groups,
        llm_warm_start_enabled=warm_start, llm_gp_groups_enabled=gp_groups,
        strict_llm_tasks=True, warm_start_llm_points=count if warm_start else 0,
        sobol_points=0 if warm_start else count, total_candidate_budget=count + bo_iterations,
        initial_candidates=plan["parameters"], initial_candidates_source=plan["source"],
        initial_candidates_evidence={"path": str(Path(plan_file).resolve()), "sha256": sha256_file(plan_file)})
    if "evaluations" in plan and config["model"]["provider"] == "pybamm":
        config["optimization"]["inventory_feasibility_filter"] = True
    return config
