"""Versioned WarmStart quality gate contracts."""

import pytest


from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluationResult
from llmbo_para.electrothermal_llm import warmstart_selection_details


class UnitSpace:
    profile = "electrothermal_4e2t"

    def validate(self, point):
        return tuple(point)

    def normalize(self, point):
        return tuple(point)


def row(ident, x, targets):
    return ElectrothermalEvaluationResult(
        ident, tuple([x] * 6), "electrothermal_4e2t", ("0.5C", "1C"), (),
        {"F_U": targets[0], "F_T": targets[1]}, True, tuple(targets),
        "quality-gate-fixture", "fresh_simulation",
        {"solver_calls": 0, "software_calls": 0}, {"fixture": "quality-gate"},
    )


def test_quality_gate_excludes_far_poor_fill():
    rows = [row("A", .2, (.1, .9)), row("B", .3, (.2, .5)),
            row("C", .21, (.25, 1.5)), row("D", .8, (.3, 2.))]
    kwargs = {"space": UnitSpace(), "count": 3, "objective_scales": [.1, 1.]}
    v1 = warmstart_selection_details(rows, rule="pareto_maximin_v1", **kwargs)
    v2 = warmstart_selection_details(rows, rule="pareto_core_spacefill_v2", **kwargs)
    v3 = warmstart_selection_details(rows, rule="pareto_quality_gated_spacefill_v3", **kwargs)
    assert v1["selected_ids"] == ["A", "B", "C"]
    assert v2["selected_ids"] == ["A", "B", "D"]
    assert v3["selected_ids"] == ["A", "B", "C"]
    assert v3["q_gate"] == max(v1["quality"][i] for i in v1["selected_ids"])
    assert v3["baseline_selected_ids"] == v1["selected_ids"]
    assert all(v3["quality"][i] <= v3["q_gate"] for i in v3["selected_ids"])


def test_quality_gate_can_keep_coverage_beyond_v1_without_v2_poor_extreme():
    rows = [row("A", .5, (.1, .1)), row("B", .49, (.2, .2)),
            row("C", .55, (1., .15)), row("D", .9, (.3, .3)),
            row("E", 0., (1.2, 1.2))]
    kwargs = {"space": UnitSpace(), "count": 3, "objective_scales": [1., 1.]}
    v1 = warmstart_selection_details(rows, rule="pareto_maximin_v1", **kwargs)
    v2 = warmstart_selection_details(rows, rule="pareto_core_spacefill_v2", **kwargs)
    v3 = warmstart_selection_details(rows, rule="pareto_quality_gated_spacefill_v3", **kwargs)
    assert v1["selected_ids"] == ["A", "C", "B"]
    assert v2["selected_ids"] == ["A", "E", "D"]
    assert v3["selected_ids"] == ["A", "D", "C"]
    assert v3["quality"]["D"] <= v3["q_gate"] < v3["quality"]["E"]


def test_quality_gate_front_over_budget_keeps_existing_order():
    rows = [row("A", .2, (.1, 3.)), row("B", .5, (.2, 2.)),
            row("C", .8, (.3, 1.))]
    kwargs = {"space": UnitSpace(), "count": 2, "objective_scales": [.1, 1.]}
    v1 = warmstart_selection_details(rows, rule="pareto_maximin_v1", **kwargs)
    v3 = warmstart_selection_details(rows, rule="pareto_quality_gated_spacefill_v3", **kwargs)
    assert v3["selected_ids"] == v1["selected_ids"]
    assert v3["q_gate"] == max(v1["quality"][i] for i in v1["selected_ids"])


def test_unknown_unversioned_quality_gate_is_rejected():
    rows = [row("A", .2, (.1, .9)), row("B", .8, (.2, .5))]
    with pytest.raises(ValueError, match="selection rule"):
        warmstart_selection_details(rows, space=UnitSpace(), count=2,
                                    objective_scales=[.1, 1.], rule="pareto_quality_gated")
