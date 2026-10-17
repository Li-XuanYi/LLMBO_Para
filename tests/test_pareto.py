import pytest


def test_known_front_duplicate_hv_and_fixed_metric_space():
    from llmbo_para.pareto import pareto_indices,hypervolume_2d,validate_hv_comparison
    y=[[1,2],[2,1],[1,2],[2,2]]
    assert pareto_indices(y)==(0,1,2)
    assert hypervolume_2d(y,objective_scales=[1,1],reference_point=[3,3])==3
    assert hypervolume_2d([[1000,2],[2000,1]],objective_scales=[1000,1],reference_point=[3,3])==3
    assert hypervolume_2d(y,objective_scales=[1,1],reference_point=None) is None
    assert validate_hv_comparison(['same','same'])=='same'
    with pytest.raises(ValueError):validate_hv_comparison(['R3','R4'])
    with pytest.raises(ValueError):hypervolume_2d([[-1,2]],objective_scales=[1,1],reference_point=[3,3])
