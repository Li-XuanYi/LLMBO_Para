"""Production request workers and deep replay, with HTTP alone replaced offline."""
from copy import deepcopy
from functools import partial
from pathlib import Path
import json
import os

import pytest

MODE = 'compact_action_v2'
ENV = 'ACTION_REPLY_OFFLINE_CREDENTIAL'


def read(path): return json.loads(Path(path).read_text(encoding='utf8'))


def offline_action_worker(protocol, kind, spec, payload, run_path, connection):
    """Runs the real worker in its spawned child; no socket may be opened."""
    from unittest.mock import patch
    from test_electrothermal_responses import response
    class HTTPResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self, limit): return self.data[:limit]
    class Provider:
        def open(self, request, **kwargs):
            body = json.loads(request.data)
            wire = json.loads(body['input'] if protocol == 'responses' else body['messages'][1]['content'])
            assert body['stream'] is False
            assert request.get_header('Authorization') == 'Bearer ' + os.environ[spec['api_key_env']]
            region = {'kind': 'none' if kind in ('none', 'incomplete', 'nonjson') else 'region',
                'coordinate_space': 'normalized', 'confidence': 0. if kind == 'low' else .9,
                'proposal_binding': wire['proposal_binding']}
            if region['kind'] == 'region':
                region.update(region_id=wire['region_catalog']['entries'][0]['region_id'],
                    evidence_ids=[wire['history'][0]['evaluation_id']])
            if kind == 'invalid_id': region['region_id'] = 'not-a-sent-region'
            if wire['region_wire_format'] == 'compact_v1': region['reason'] = 'offline control'
            if kind == 'long': region['reason'] = 'x'*417
            formal = {'request_id': wire['request_id'], 'region': region}
            text = 'invalid JSON answer' if kind == 'nonjson' else json.dumps(formal)
            if protocol == 'responses':
                raw = response(formal, usage={'input_tokens': 31, 'output_tokens': 20, 'total_tokens': 51})
                raw['output'][0]['content'][0]['text'] = text
                if kind == 'incomplete':
                    raw.update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
            else:
                raw = {'choices': [{'finish_reason': 'length' if kind == 'incomplete' else 'stop',
                    'message': {'content': text}}], 'usage': {'prompt_tokens': 31, 'completion_tokens': 20, 'total_tokens': 51}}
            result = HTTPResponse()
            result.data = json.dumps(raw).encode('utf8')
            return result
    with patch('socket.socket.connect', side_effect=AssertionError('offline worker cannot use sockets')), \
         patch('socket.create_connection', side_effect=AssertionError('offline worker cannot use sockets')), \
         patch('llmbo_para.llm.build_opener', return_value=Provider()):
        if protocol == 'responses':
            from llmbo_para.electrothermal_responses import _responses_request_worker
            _responses_request_worker(spec, payload, run_path, connection)
        else:
            from llmbo_para.electrothermal_requests import _chat_request_worker
            _chat_request_worker(spec, payload, run_path, connection)


@pytest.fixture(scope='module')
def archives(): return {}


def run_fixture(archives, monkeypatch, tmp_path_factory, protocol='responses', kind='region', wire=MODE, mode='full_llmbo_mo'):
    key = (protocol, kind, wire, mode)
    if key in archives: return archives[key]
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para import electrothermal_responses, electrothermal_requests
    if 'initialization' not in archives:
        archives['initialization'] = _shared_initialization(tmp_path_factory.mktemp('ai'))
    root = tmp_path_factory.mktemp('aa')
    cfg = deepcopy(archives['initialization'])
    cfg['optimization'].update(mode=mode, gp_sweeps=0, region_evidence='dynamic_decision_v3',
        region_proposal='catalog_v1', region_advice='candidate_aware_v1', region_selection='fair_region_v1')
    # Wide gates exercise the transport/audit branches, not method efficacy.
    cfg['optimization']['region'].update(max_plain_log_ei_gap=100., min_sigma_ratio=0.)
    cfg['llm'].update(transport='openai_responses' if protocol == 'responses' else 'openai_chat_completions',
        enabled=False, endpoint='https://provider.invalid/v1/' + ('responses' if protocol == 'responses' else 'chat/completions'),
        api_key_env=ENV, model='offline-fixture', region_wire_format=wire, max_tokens=8192, timeout_s=15.)
    monkeypatch.setenv(ENV, 'offline-action-fixture-credential')
    worker = partial(offline_action_worker, protocol, kind)
    cls = electrothermal_responses.BoundedResponsesTransport if protocol == 'responses' else electrothermal_requests.BoundedChatCompletionsTransport
    module = electrothermal_responses if protocol == 'responses' else electrothermal_requests
    monkeypatch.setattr(module, '_responses_request_worker' if protocol == 'responses' else '_chat_request_worker', worker)
    client = cls(cfg['llm']['endpoint'], ENV, model=cfg['llm']['model'], max_tokens=8192, timeout_s=15., json_mode=True)
    controller = ElectrothermalLLMController(transport=client, is_mock=True)
    summary = run_electrothermal_experiment(cfg, root, base_dir=root, llm_controller=controller)
    assert summary['BO_rounds'] == 2 and summary['API_calls'] == summary['costs']['solver_calls'] == 0
    result = (Path(summary['run_directory']), summary)
    archives[key] = result
    return result


@pytest.mark.parametrize('protocol', ['responses', 'chat'])
@pytest.mark.parametrize('kind', ['region', 'none', 'long'])
def test_real_workers_accept_actions_without_a_required_explanation_and_deep_audit(archives, monkeypatch, tmp_path_factory, protocol, kind):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run, summary = run_fixture(archives, monkeypatch, tmp_path_factory, protocol, kind)
    audit = audit_electrothermal_run(run, deep=True)
    assert audit['passed'], audit['issues']
    events = [json.loads(line) for line in (run/'events.jsonl').read_text().splitlines()]
    assert sum(e['type'] == 'llm_http_started' for e in events) == 2
    for path in sorted((run/'llm').glob('*.outcome.json')):
        outcome = read(path)
        assert outcome['status'] == 'received' and outcome['hard_deadline_enforced']
        assert outcome['wire_format'] == MODE
    for path in (run/'http').glob('*.response.json'):
        raw = read(path)
        text = raw['output'][0]['content'][0]['text'] if protocol == 'responses' else raw['choices'][0]['message']['content']
        region = json.loads(text)['region']
        assert ('reason' not in region) if kind != 'long' else len(region['reason']) == 417
    assert summary['costs']['llm_requests'] == 0


@pytest.mark.parametrize('protocol', ['responses', 'chat'])
@pytest.mark.parametrize('kind', ['low', 'invalid_id', 'incomplete', 'nonjson'])
def test_failed_or_low_confidence_actions_keep_plain_fallback_without_retry(archives, monkeypatch, tmp_path_factory, protocol, kind):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run, _ = run_fixture(archives, monkeypatch, tmp_path_factory, protocol, kind)
    audit = audit_electrothermal_run(run, deep=True)
    assert audit['passed'], audit['issues']
    for path in (run/'mo-rounds').glob('*.json'):
        event = read(path)
        assert not event['region']['accepted']
        assert event['selected_index'] == event['region']['plain_index']
        outcome = event['region']['request_outcome']
        assert outcome['status'] == ('received' if kind == 'low' else 'failed')
    assert len(list((run/'http').glob('*.request.json'))) == 2


def test_same_actions_preserve_two_round_gp_lift_ei_and_selection(archives, monkeypatch, tmp_path_factory):
    paths = [run_fixture(archives, monkeypatch, tmp_path_factory, kind=kind, wire=wire)[0]
        for kind, wire in [('region', 'compact_v1'), ('region', MODE), ('long', MODE)]]
    histories = [[read(p) for p in sorted((root/'mo-rounds').glob('*.json'))] for root in paths]
    for old, plain, verbose in zip(*histories):
        for actual in (plain, verbose):
            assert actual['selected_index'] == old['selected_index']
            assert actual['context']['gp_state'] == old['context']['gp_state']
            for field in ('mean', 'std', 'shift', 'adjusted_mean', 'plain_ei', 'effective_ei', 'trust_before'):
                assert actual['region'][field] == old['region'][field]


@pytest.mark.parametrize('mode', ['parego', 'warmstart_only', 'full_llmbo_mo'])
def test_three_routes_keep_the_same_validated_initial_plan_and_zero_real_costs(archives, monkeypatch, tmp_path_factory, mode):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.runstore import sha256_file
    run, summary = run_fixture(archives, monkeypatch, tmp_path_factory, kind='none', mode=mode)
    audit = audit_electrothermal_run(run, deep=True)
    assert audit['passed'], audit['issues']
    origin = archives['initialization']['optimization']['initial_plan']
    assert sha256_file(run/'inputs/initial-plan.json') == origin['sha256']
    assert summary['initial_plan_sha256'] == read(origin['path'])['plan_sha256']
    assert summary['costs']['solver_calls'] == summary['API_calls'] == 0


@pytest.mark.parametrize('damage', ['wire', 'prompt', 'weights', 'scales', 'catalog', 'raw_binding', 'raw_ID', 'raw_evidence', 'canonical'])
def test_action_deep_audit_detects_independent_archive_tampering(archives, monkeypatch, tmp_path_factory, damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run, _ = run_fixture(archives, monkeypatch, tmp_path_factory)
    assert audit_electrothermal_run(run, deep=True)['passed']
    payload_path = run/'llm/000000.payload.json'
    payload_value = read(payload_path)
    artifact = payload_value['artifact_task']
    path = (run/'http'/(artifact+'.response.json')) if damage.startswith('raw_') else (
        run/'llm/000000.catalog-resolution.json' if damage == 'canonical' else payload_path)
    original = path.read_bytes()
    try:
        value = read(path)
        if damage == 'wire': value['region_wire_format'] = 'compact_v1'
        elif damage == 'prompt': value['instructions'] += ' Altered prompt.'
        elif damage == 'weights': value['context']['weights'] = [.99, .01]
        elif damage == 'scales': value['objective_scales'] = [999., 999.]
        elif damage == 'catalog': value['region_catalog']['entries'][0]['lb'][0] += .001
        elif damage == 'canonical': value['canonical_response']['region']['lb'][0] += .001
        else:
            formal = json.loads(value['output'][0]['content'][0]['text'])
            if damage == 'raw_binding': formal['request_id'] = 'wrong-request'
            elif damage == 'raw_ID': formal['region']['region_id'] = 'wrong-region'
            else: formal['region']['evidence_ids'] = ['future-observation']
            value['output'][0]['content'][0]['text'] = json.dumps(formal)
        path.write_text(json.dumps(value), encoding='utf8')
        assert not audit_electrothermal_run(run, deep=True)['passed']
    finally:
        path.write_bytes(original)


def test_new_template_is_disabled_and_uses_the_approved_output_allowance(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from llmbo_para.electrothermal_requests import request_controls
    root = Path(__file__).resolve().parents[1]
    target = root/'configs/electrothermal-sub2api-action-software-template.json'
    assert target.is_file(), 'action-only zero-budget template missing'
    cfg = read(target)
    baseline = read(root/'configs/electrothermal-sub2api-software-template.json')
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=root)
    assert prepared is not None, report['errors']
    assert cfg['optimization']['mode'] == 'parego' and cfg['llm']['enabled'] is False
    assert cfg['budgets']['max_solver_calls'] == cfg['budgets']['max_llm_requests'] == 0
    assert cfg['llm']['region_wire_format'] == MODE and 'thinking' not in cfg['llm']
    for name in ('parameters', 'fixed', 'property_law', 'fit_rates', 'conditions_by_rate', 'data', 'model'):
        assert cfg[name] == baseline[name]
    assert request_controls(cfg, 'region_preference_electrothermal') == {'max_tokens': 8192, 'timeout_s': 120.}
    assert request_controls(cfg, 'warm_start_electrothermal') == {'max_tokens': 4096, 'timeout_s': 120.}
