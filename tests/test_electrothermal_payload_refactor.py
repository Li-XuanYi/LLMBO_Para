"""Pre-refactor payload/wire goldens and separate task construction contracts."""
from copy import deepcopy
import importlib
import importlib.util
import json
from pathlib import Path

import pytest

from electrothermal_payload_fixtures import CASES, payload_case


def feature():
    name = 'llmbo_para.electrothermal_payloads'
    assert importlib.util.find_spec(name) is not None, 'separate electrothermal payload builders are missing'
    return importlib.import_module(name)


@pytest.mark.parametrize('case', CASES)
def test_payload_and_wire_match_pre_refactor_goldens(case, tmp_path):
    module = feature()
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    from llmbo_para.electrothermal_llm import build_electrothermal_payload
    from llmbo_para.runstore import digest_value
    goldens = json.loads((Path(__file__).parent / 'fixtures/electrothermal_payload_golden_20261023.json').read_text(encoding='utf8'))
    prepared, history, context = payload_case(case, tmp_path)
    task = 'warm_start_electrothermal' if case == 'warmstart' else 'region_preference_electrothermal'
    payload = module.build_electrothermal_payload(task, prepared=prepared, history=history, context=context)
    assert digest_value(payload) == goldens['cases'][case]['payload_sha256']
    assert digest_value(region_wire_payload(payload)) == goldens['cases'][case]['wire_sha256']
    assert build_electrothermal_payload(task, prepared=prepared, history=history, context=context) == payload
    assert [row['evaluation_id'] for row in payload['history']] == goldens['cases'][case]['history_ids']
    assert list(payload['case_summaries']) == ['0.5C', '1C']
    if case.startswith('catalog_'):
        assert payload['region_catalog']['entries']


def test_lgbo_dispatch_does_not_build_legacy_contract(tmp_path, monkeypatch):
    module = feature()
    prepared, history, context = payload_case('lgbo_v2', tmp_path)
    for name in ('build_warmstart_payload', 'build_lgbo_payload', 'build_legacy_region_payload'):
        assert callable(getattr(module, name, None))
    monkeypatch.setattr(module, 'build_legacy_region_payload', lambda **kwargs: pytest.fail('LGBO built a legacy payload'))
    value = module.build_electrothermal_payload('region_preference_electrothermal', prepared=prepared, history=history, context=context)
    assert value['region_method'] == 'lgbo_v2'
    assert 'reason' not in str(value['response_contract']['properties']['region'])
    assert all('weighted_objective_evidence' in row for row in value['history'])


@pytest.mark.parametrize('case', ['warmstart', 'legacy_bounds', 'lgbo_v2'])
def test_output_owns_nested_metadata_and_next_request_is_unmodified(case, tmp_path):
    module = feature()
    prepared, history, context = payload_case(case, tmp_path)
    task = 'warm_start_electrothermal' if case == 'warmstart' else 'region_preference_electrothermal'
    before_config, before_history = deepcopy(prepared.config), [deepcopy(row.to_dict()) for row in history]
    original = module.build_electrothermal_payload(task, prepared=prepared, history=history, context=context)
    altered = module.build_electrothermal_payload(task, prepared=prepared, history=history, context=context)
    altered['fixed']['cell_volume_m3'] = -99.
    altered['conditions_by_rate']['0.5C']['initial_temperature_k'] = -99.
    altered['objective_scales'][0] = 99.
    altered['history'][0]['rates']['0.5C']['rmse_v'] = 99.
    assert prepared.config == before_config
    assert [row.to_dict() for row in history] == before_history
    assert module.build_electrothermal_payload(task, prepared=prepared, history=history, context=context) == original


def test_error_boundaries_and_warmstart_task_separation(tmp_path):
    module = feature()
    prepared, history, context = payload_case('lgbo_v2', tmp_path)
    with pytest.raises(ValueError, match='unknown electrothermal LLM task'):
        module.build_electrothermal_payload('other', prepared=prepared, history=history)
    with pytest.raises(ValueError, match='frozen context required'):
        module.build_electrothermal_payload('region_preference_electrothermal', prepared=prepared, history=history)
    from dataclasses import replace
    outside = replace(history[0], evaluation_id='outside-frozen-history')
    with pytest.raises(ValueError, match='outside the frozen context'):
        module.build_electrothermal_payload('region_preference_electrothermal', prepared=prepared,
            history=[*history, outside], context=context)
    value = module.build_electrothermal_payload('warm_start_electrothermal', prepared=prepared, history=history)
    assert not {'context_id', 'coordinate_mapping', 'region_method', 'region_requirements'} & value.keys()
    assert 'candidates' in value['response_contract']['properties']
