"""Production workers with an offline HTTP boundary, and independent LGBO replay."""
from copy import deepcopy
from functools import partial
from pathlib import Path
import json
import os

import pytest

ENV = 'OFFLINE_LGBO_WORKER_CREDENTIAL'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def lgbo_offline_worker(protocol, kind, spec, payload, run_path, connection):
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
            action = {'kind': 'none'} if kind == 'none' else {
                'kind': 'region', 'lb': [.3]*6, 'ub': [.8]*6, 'confidence': .65}
            formal = {'request_id': wire['request_id'], 'region': action}
            if kind == 'invalid_binding': formal['request_id'] = 'old'
            text = 'not JSON' if kind == 'nonjson' else json.dumps(formal)
            if protocol == 'responses':
                raw = response(formal, usage={'input_tokens': 7, 'output_tokens': 8, 'total_tokens': 15})
                raw['output'][0]['content'][0]['text'] = text
                if kind == 'incomplete':
                    raw.update(status='incomplete', incomplete_details={'reason': 'max_output_tokens'})
            else:
                raw = {'choices': [{'finish_reason': 'length' if kind == 'incomplete' else 'stop',
                                    'message': {'content': text}}],
                       'usage': {'prompt_tokens': 7, 'completion_tokens': 8, 'total_tokens': 15}}
            result = HTTPResponse(); result.data = json.dumps(raw).encode('utf-8')
            return result
    with patch('socket.socket.connect', side_effect=AssertionError('no network in software worker')), \
         patch('socket.create_connection', side_effect=AssertionError('no network in software worker')), \
         patch('llmbo_para.llm.build_opener', return_value=Provider()):
        if protocol == 'responses':
            from llmbo_para.electrothermal_responses import _responses_request_worker
            _responses_request_worker(spec, payload, run_path, connection)
        else:
            from llmbo_para.electrothermal_requests import _chat_request_worker
            _chat_request_worker(spec, payload, run_path, connection)


@pytest.fixture(scope='module')
def archives():
    return {}


def run_fixture(archives, monkeypatch, tmp_path_factory, *, protocol='responses', kind='region', mode='full_llmbo_mo'):
    from test_region_failure_audit import _shared_initialization
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para import electrothermal_requests, electrothermal_responses
    key = (protocol, kind, mode)
    if key in archives: return archives[key]
    if 'shared' not in archives:
        archives['shared'] = _shared_initialization(tmp_path_factory.mktemp('li'))
    cfg = deepcopy(archives['shared'])
    cfg['optimization'].pop('region')
    cfg['optimization'].update(region_method='lgbo_v1', gp_sweeps=0, mode=mode)
    cfg['llm'].update(transport='openai_responses' if protocol == 'responses' else 'openai_chat_completions',
        enabled=False, endpoint='https://provider.invalid/v1/'+('responses' if protocol == 'responses' else 'chat/completions'),
        api_key_env=ENV, model='offline', max_tokens=2048, timeout_s=15.)
    monkeypatch.setenv(ENV, 'offline-lgbo-fixture')
    module = electrothermal_responses if protocol == 'responses' else electrothermal_requests
    cls = module.BoundedResponsesTransport if protocol == 'responses' else module.BoundedChatCompletionsTransport
    monkeypatch.setattr(module, '_responses_request_worker' if protocol == 'responses' else '_chat_request_worker',
                        partial(lgbo_offline_worker, protocol, kind))
    client = cls(cfg['llm']['endpoint'], ENV, model='offline', max_tokens=2048, timeout_s=15., json_mode=True)
    controller = ElectrothermalLLMController(transport=client, is_mock=True)
    root = tmp_path_factory.mktemp('lr')
    summary = run_electrothermal_experiment(cfg, root, base_dir=root, llm_controller=controller)
    result = Path(summary['run_directory']), summary
    archives[key] = result
    return result


@pytest.mark.parametrize('protocol', ['chat', 'responses'])
@pytest.mark.parametrize('kind', ['region', 'none', 'incomplete', 'nonjson', 'invalid_binding'])
def test_production_workers_and_deep_replay(archives, monkeypatch, tmp_path_factory, protocol, kind):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run, summary = run_fixture(archives, monkeypatch, tmp_path_factory, protocol=protocol, kind=kind)
    result = audit_electrothermal_run(run, deep=True)
    assert result['passed'], result['issues']
    assert summary['BO_rounds'] == 2 and summary['API_calls'] == summary['costs']['solver_calls'] == 0
    assert len(list((run/'http').glob('*.request.json'))) == 2
    for p in (run/'mo-rounds').glob('*.json'):
        event = read(p); region = event['region']
        assert 'trust' not in event['feedback']
        assert region['action_valid'] == (kind in ('region', 'none'))
        assert region['request_outcome']['wire_format'] == 'lgbo_action_v1'
        if kind not in ('region', 'none'):
            assert not region['tilt_applied']


@pytest.mark.parametrize('mode', ['parego', 'warmstart_only', 'full_llmbo_mo'])
def test_three_routes_share_strict_initialization(archives, monkeypatch, tmp_path_factory, mode):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run, summary = run_fixture(archives, monkeypatch, tmp_path_factory, mode=mode)
    assert audit_electrothermal_run(run, deep=True)['passed']
    assert summary['initial_plan_sha256'] == read(archives['shared']['optimization']['initial_plan']['path'])['plan_sha256']
    if mode != 'full_llmbo_mo':
        assert not list((run/'http').glob('*.request.json'))


@pytest.mark.parametrize('damage', ['weights', 'scales', 'dynamic', 'temperature', 'confidence',
                                  'delta', 'variance', 'raw_binding', 'prompt'])
def test_independent_audit_detects_scientific_and_wire_tampering(archives, monkeypatch, tmp_path_factory, damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run, _ = run_fixture(archives, monkeypatch, tmp_path_factory)
    assert audit_electrothermal_run(run, deep=True)['passed']
    round_file = sorted((run/'mo-rounds').glob('*.json'))[0]
    if damage in ('weights', 'scales', 'dynamic'):
        path = run/'llm/000000.payload.json'
    elif damage == 'temperature':
        path = sorted((run/'electrothermal-evaluations').glob('*.json'))[0]
    elif damage == 'raw_binding':
        path = sorted((run/'http').glob('*.response.json'))[0]
    elif damage == 'prompt':
        path = run/'source/src/llmbo_para/prompts/region_preference_lgbo_electrothermal.txt'
    else: path = round_file
    original = path.read_bytes()
    try:
        if damage == 'prompt': path.write_bytes(original+b'\naltered')
        else:
            value = read(path)
            if damage == 'weights': value['context']['weights'] = [.5, .5]
            elif damage == 'scales': value['objective_scales'][0] *= 2
            elif damage == 'dynamic': value['history'][0]['dynamic_residuals'] = {}
            elif damage == 'temperature': value['rates'][0]['trace']['temperature_k'][1] += 1.
            elif damage == 'confidence': value['region']['response']['region']['confidence'] = .99
            elif damage == 'delta': value['region']['signed_delta'][0] += 1.
            elif damage == 'variance': value['region']['std'][0] *= 2
            elif damage == 'raw_binding':
                text = json.loads(value['output'][0]['content'][0]['text'])
                text['request_id'] = 'wrong'
                value['output'][0]['content'][0]['text'] = json.dumps(text)
            path.write_text(json.dumps(value), encoding='utf-8')
        result = audit_electrothermal_run(run, deep=True)
        assert not result['passed'], result
    finally:
        path.write_bytes(original)
