from dataclasses import replace
from copy import deepcopy
import pytest
from electrothermal_fixtures import et_config,R3,R4


def test_voltage_temperature_grids_and_initial_vs_ambient_are_separate():
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    from llmbo_para.electrothermal_data import temperature_to_kelvin,dataset_from_dict
    ds=make_synthetic_dataset(R3);case=ds.cases['1C']
    assert case.voltage.time_s != case.cell_temperature_k.time_s
    assert case.initial_state['temperature_k'] != case.ambient_temperature_k.values[0]
    assert temperature_to_kelvin([25.],'degC')==(298.15,)
    assert temperature_to_kelvin([298.15],'K')==(298.15,)
    assert dataset_from_dict(ds.to_dict()).to_dict()==ds.to_dict()


def test_data_signature_includes_order_targets_and_provenance():
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    a=make_synthetic_dataset(R3);b=make_synthetic_dataset(tuple(reversed(R3)))
    assert a.data_signature!=b.data_signature
    assert make_synthetic_dataset(R4).fit_rates==R4


def test_invalid_grids_and_input_coverage_are_rejected():
    from llmbo_para.electrothermal_data import TimeSignal
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    with pytest.raises(ValueError):TimeSignal((0,0),(1,2),'A',{})
    with pytest.raises(ValueError):TimeSignal((0,1),(1,float('nan')),'A',{})
    case=make_synthetic_dataset(R3).cases['1C']
    with pytest.raises(ValueError):replace(case,current_a=TimeSignal((0,1),(5,5),'A',{}))


def test_unselected_bad_3c_is_not_loaded(tmp_path):
    from openpyxl import Workbook
    from llmbo_para.electrothermal_data import load_electrothermal_dataset
    from llmbo_para.runstore import sha256_file
    book=Workbook();book.remove(book.active)
    for r in R3:
        s=book.create_sheet(r);s.append(('t','I','Tamb','U','T'))
        s.append((0,1,25.,4.2,27.));s.append((4,1,25.,4.,28.))
    book.create_sheet('3C').append(('bad',));path=tmp_path/'fixture.xlsx';book.save(path);book.close()
    cfg=et_config();cfg['data']['kind']='xlsx'
    cfg['data']['by_rate']={r:{'path':str(path),'sha256':sha256_file(path),'sheet':r,
        'source_id':'xlsx:'+sha256_file(path)+':'+r,'temperature_unit':'degC',
        'columns':{'time':'t','current':'I','ambient_temperature':'Tamb','voltage':'U','cell_temperature':'T'}} for r in R3}
    ds=load_electrothermal_dataset(cfg,tmp_path)
    assert tuple(ds.cases)==R3 and ds.cases['1C'].cell_temperature_k.values[0]==300.15
    cfg['data']['by_rate']['1C']['source_id']='forged'
    with pytest.raises(ValueError):load_electrothermal_dataset(cfg,tmp_path)


def test_cooling_groups_and_missing_cases_rejected():
    from llmbo_para.electrothermal_data import ElectrothermalDataset
    from llmbo_para.electrothermal_synthetic import make_synthetic_dataset
    ds=make_synthetic_dataset(R3);cases=dict(ds.cases);cases['1C']=replace(cases['1C'],cooling_group_id='different')
    with pytest.raises(ValueError):ElectrothermalDataset(R3,cases)
    with pytest.raises(ValueError):ElectrothermalDataset(R3,{'1C':ds.cases['1C']})
