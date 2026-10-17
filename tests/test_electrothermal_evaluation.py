from dataclasses import replace
import numpy as np
import pytest
from llmbo_para.config import parameter_space_from_config
from electrothermal_fixtures import et_config,R3,R4


def test_selected_rate_means_are_not_fixed_three_or_four():
    from llmbo_para.metrics import mean_selected_rmse
    assert mean_selected_rmse(dict(zip(R3,[.01,.02,.03])),R3)==pytest.approx(.02)
    assert mean_selected_rmse(dict(zip(R4,[.01,.02,.03,.08])),R4)==pytest.approx(.035)
    with pytest.raises(ValueError):mean_selected_rmse({'1C':0.},R3)


@pytest.mark.parametrize('rates,expected',[(R3,[.02,2.]),(R4,[.035,2.5])])
def test_same_solution_and_independent_grid_rmse(rates,expected):
    from llmbo_para.electrothermal_evaluation import ElectrothermalTrace,ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    class Sim:
        backend_kind='test_double'
        def __init__(self):self.calls=[]
        def simulate(self,parameters,case):
            self.calls.append(case.rate);index=R4.index(case.rate);t=np.array([0.,1.,2.,4.])
            return ElectrothermalTrace(t,4.2-.05*t+[.01,.02,.03,.08][index],300.15+.1*t+index+1,np.ones(4),
                                       'final time','solution-'+case.rate,{})
    sim=Sim();ds=make_synthetic_dataset(rates);sp=parameter_space_from_config(et_config(rates))
    result=ElectrothermalEvaluator(sp,sim,fit_rates=rates).evaluate(sp.denormalize([.5]*6),ds)
    assert list(sim.calls)==list(rates) and result.objectives==pytest.approx(expected)
    assert result.complete_pair_valid
    assert all(r.solution_id=='solution-'+r.rate for r in result.rates)


@pytest.mark.parametrize('damage',['missing','nan','short'])
def test_one_temperature_failure_preserves_voltage_but_pair_is_none(damage):
    from llmbo_para.electrothermal_evaluation import ElectrothermalTrace,ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    class Sim:
        backend_kind='test_double'
        def simulate(self,p,case):
            temp=None if damage=='missing' else [300.,float('nan'),301.] if damage=='nan' else [300.,301.]
            return ElectrothermalTrace([0,2,4],[4.2,4.1,4.],temp,None,'final time',case.rate,{})
    sp=parameter_space_from_config(et_config());result=ElectrothermalEvaluator(sp,Sim(),fit_rates=R3).evaluate(sp.denormalize([.5]*6),make_synthetic_dataset(R3))
    assert result.objectives is None and not result.complete_pair_valid
    assert result.objective_components['F_U']==pytest.approx(0.) and result.objective_components['F_T'] is None
    assert all(r.voltage.valid and not r.cell_temperature.valid and r.cell_temperature.rmse_k is None for r in result.rates)


def test_only_targets_change_predictions_do_not():
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_data import ElectrothermalDataset
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset,SyntheticElectrothermalSimulator
    ds=make_synthetic_dataset(R3);cases=dict(ds.cases);c=cases['1C']
    cases['1C']=replace(c,cell_temperature_k=replace(c.cell_temperature_k,values=tuple(v+2 for v in c.cell_temperature_k.values)))
    altered=ElectrothermalDataset(R3,cases);sp=parameter_space_from_config(et_config());sim=SyntheticElectrothermalSimulator()
    a=ElectrothermalEvaluator(sp,sim,fit_rates=R3).evaluate(sp.denormalize([.5]*6),ds)
    b=ElectrothermalEvaluator(sp,sim,fit_rates=R3).evaluate(sp.denormalize([.5]*6),altered)
    assert a.rates[1].trace['temperature_k']==b.rates[1].trace['temperature_k']
    assert a.objectives!=b.objectives


def test_analytic_cooling_heat_capacity_and_equilibrium():
    from llmbo_para.electrothermal_synthetic import analytic_lumped_temperature
    assert analytic_lumped_temperature([0,10],40,.1,310,300,0)==pytest.approx([310,300+10*np.exp(-.1*10/40)])
    assert analytic_lumped_temperature([0,10],40,.1,310,300,1)==pytest.approx([310,310])
    assert analytic_lumped_temperature([10],80,.1,310,300,0)[0]>analytic_lumped_temperature([10],40,.1,310,300,0)[0]


def test_native_cost_counts_actual_solve_not_preparation_attempt():
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    class PreprocessFailure:
        backend_kind='dfn';native_solver_calls=0
        def simulate(self,p,case):raise ValueError('parameter processing failed before actual solve')
    sp=parameter_space_from_config(et_config())
    result=ElectrothermalEvaluator(sp,PreprocessFailure(),fit_rates=R3).evaluate(sp.denormalize([.5]*6),make_synthetic_dataset(R3))
    assert result.costs['solver_calls']==0 and result.objectives is None
