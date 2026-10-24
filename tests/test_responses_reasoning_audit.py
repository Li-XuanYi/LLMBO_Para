"""Native reasoning controls must survive independent scientific replay."""
from copy import deepcopy
import json
import shutil

import pytest

from test_network_diagnostic_audit import read, put, synchronize_round_outcome


@pytest.fixture(scope='module')
def archives():
    return {}


def fixture_run(archives, monkeypatch, tmp_path_factory, effort):
    from test_region_failure_audit import _shared_initialization
    from test_lgbo_region_audit import run_fixture
    if effort not in archives:
        cfg = _shared_initialization(tmp_path_factory.mktemp('reasoninginit'))
        cfg['budgets']['wall_clock_s'] = 300.
        if effort is not None:
            cfg['llm']['reasoning_effort'] = effort
        archives[effort] = {'shared': cfg}
    return run_fixture(archives[effort], monkeypatch, tmp_path_factory)[0]


@pytest.mark.parametrize('effort', [None, 'none'])
def test_complete_reply_deep_replays_with_unknown_reasoning_usage(archives, monkeypatch, tmp_path_factory, effort):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run = fixture_run(archives, monkeypatch, tmp_path_factory, effort)
    result = audit_electrothermal_run(run, deep=True)
    assert result['passed'], result['issues']
    for p in (run/'llm').glob('*.outcome.json'):
        outcome = read(p)
        assert ('reasoning_effort' in outcome) == (effort is not None)
        assert 'reasoning_tokens' not in outcome['completion']
        assert outcome['status'] == 'received'


@pytest.mark.parametrize('target', ['raw', 'supervision', 'outcome', 'all'])
@pytest.mark.parametrize('operation', ['delete', 'change'])
def test_configured_effort_tampering_fails(archives, monkeypatch, tmp_path_factory, tmp_path, target, operation):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run = tmp_path/'copy'
    shutil.copytree(fixture_run(archives, monkeypatch, tmp_path_factory, 'none'), run)
    outcome_path = sorted((run/'llm').glob('*.outcome.json'))[0]
    outcome = read(outcome_path)
    payload = read(run/'llm'/f'{outcome["ordinal"]:06d}.payload.json')
    paths = {'raw': run/'http'/(payload['artifact_task']+'.request.json'),
             'supervision': run/'http'/(payload['artifact_task']+'.supervision.json'),
             'outcome': outcome_path}
    for name in paths if target == 'all' else [target]:
        value = read(paths[name])
        holder, key = (value['body'], 'reasoning') if name == 'raw' else (value, 'reasoning_effort')
        if operation == 'delete': holder.pop(key)
        else: holder[key] = {'effort': 'high'} if name == 'raw' else 'high'
        put(paths[name], value)
    synchronize_round_outcome(run, read(outcome_path))
    result = audit_electrothermal_run(run, deep=True)
    assert not result['passed'], result


@pytest.mark.parametrize('target', ['raw', 'supervision', 'outcome'])
def test_unconfigured_effort_cannot_be_injected_in_archives(archives, monkeypatch, tmp_path_factory, tmp_path, target):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run = tmp_path/'copy'
    shutil.copytree(fixture_run(archives, monkeypatch, tmp_path_factory, None), run)
    assert audit_electrothermal_run(run, deep=True)['passed']
    outcome_path = sorted((run/'llm').glob('*.outcome.json'))[0]
    outcome = read(outcome_path)
    payload = read(run/'llm'/f'{outcome["ordinal"]:06d}.payload.json')
    paths = {'raw': run/'http'/(payload['artifact_task']+'.request.json'),
             'supervision': run/'http'/(payload['artifact_task']+'.supervision.json'), 'outcome': outcome_path}
    value = read(paths[target])
    if target == 'raw': value['body']['reasoning'] = {'effort': 'none'}
    else: value['reasoning_effort'] = 'none'
    put(paths[target], value)
    synchronize_round_outcome(run, read(outcome_path))
    result = audit_electrothermal_run(run, deep=True)
    assert not result['passed'], result


@pytest.mark.parametrize('count', [None, 0, 17])
def test_complete_native_response_preserves_observed_usage_without_inferring_server_mode(count):
    from test_electrothermal_responses import response
    from llmbo_para.electrothermal_requests import completion_summary, _public_diagnostic
    from llmbo_para.electrothermal_responses import decode_responses_json
    usage = {'input_tokens': 7, 'output_tokens': 20, 'total_tokens': 27}
    if count is not None: usage['output_tokens_details'] = {'reasoning_tokens': count}
    raw = response({'ok': True}, usage=usage)
    formal, issue = decode_responses_json(raw)
    assert issue is None and formal == {'ok': True}
    summary = completion_summary(raw, 8192, transport='openai_responses')
    public = _public_diagnostic({'completion': summary})['completion']
    for value in (summary, public):
        assert ('reasoning_tokens' in value) == (count is not None)
        if count is not None: assert value['reasoning_tokens'] == count
        assert value['state'] == 'complete_answer'


def test_effort_changes_config_and_algorithm_signatures(archives, monkeypatch, tmp_path_factory):
    from llmbo_para.electrothermal_provenance import build_electrothermal_signatures
    from llmbo_para.electrothermal_data import load_electrothermal_dataset
    run = fixture_run(archives, monkeypatch, tmp_path_factory, None)
    cfg = deepcopy(archives[None]['shared'])
    dataset = load_electrothermal_dataset(cfg, run)
    before = build_electrothermal_signatures(cfg, dataset)
    cfg['llm']['reasoning_effort'] = 'none'
    after = build_electrothermal_signatures(cfg, dataset)
    assert before.config != after.config and before.algorithm != after.algorithm
    assert before.data == after.data and before.initialization_compatibility == after.initialization_compatibility
