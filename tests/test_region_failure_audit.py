"""Audit real controller failure records using injected, network-free transports."""
from copy import deepcopy
import json
from pathlib import Path

import pytest


def _shared_initialization(root):
    from electrothermal_fixtures import et_config
    from llmbo_para.electrothermal_workflow import (
        prepare_electrothermal_experiment, run_electrothermal_experiment,
    )
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.runstore import sha256_file
    from test_electrothermal_llm import Proposed

    cfg = et_config()
    cfg['optimization']['mode'] = 'warmstart_only'
    cfg['optimization']['total_candidate_budget'] = cfg['optimization']['initial_count']
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=root)
    proposed = Proposed(prepared.space, [[.2] * 6, [.8] * 6, [.21] * 6, [.7] * 6])
    result = run_electrothermal_experiment(
        cfg, root, base_dir=root,
        llm_controller=ElectrothermalLLMController(transport=proposed, is_mock=True),
    )
    plan = Path(result['run_directory']) / 'initial-plan.json'
    cfg = deepcopy(cfg)
    cfg['optimization'].update(
        mode='full_llmbo_mo', total_candidate_budget=4,
        initial_plan={'path': str(plan), 'sha256': sha256_file(plan)},
    )
    return cfg


@pytest.mark.parametrize('damage', [None, 'context_id', 'fallback_reason', 'outcome_artifact'])
def test_controller_timeout_outcome_replays_and_tampering_is_detected(tmp_path_factory, damage):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_audit import audit_electrothermal_run

    root = tmp_path_factory.mktemp('rfa')
    cfg = _shared_initialization(root)

    class TimeoutTransport:
        def __init__(self):
            self.calls = 0

        def post(self, payload):
            self.calls += 1
            assert payload['task'] == 'region_preference_electrothermal'
            raise TimeoutError('offline injected timeout')

    transport = TimeoutTransport()
    controller = ElectrothermalLLMController(transport=transport, is_mock=True)
    result = run_electrothermal_experiment(
        cfg, root, base_dir=root, llm_controller=controller,
    )
    run = Path(result['run_directory'])
    assert transport.calls == controller.requests == result['BO_rounds'] == 2
    assert result['API_calls'] == 0
    files = sorted((run / 'mo-rounds').glob('*.json'))
    for file in files:
        event = json.loads(file.read_text(encoding='utf8'))
        region = event['region']
        assert region['fallback_reason'] == 'request_timeout'
        assert not region['accepted']
        assert event['selected_index'] == region['plain_index']
        outcome = region['request_outcome']
        assert outcome['context_id'] == event['context']['context_id']
        assert outcome['status'] == 'failed' and outcome['reason'] == 'timeout'
        assert outcome['error_type'] == 'TimeoutError'
        assert not outcome['http_request_started']
    assert audit_electrothermal_run(run, deep=True)['passed']

    if damage is not None:
        if damage == 'outcome_artifact':
            # The independent request archive must agree with the MO decision,
            # not merely replay the decision against its own embedded fields.
            artifact = run / 'llm' / '000000.outcome.json'
            outcome = json.loads(artifact.read_text(encoding='utf8'))
            outcome['reason'] = 'transport_error'
            artifact.write_text(json.dumps(outcome), encoding='utf8')
        else:
            event = json.loads(files[0].read_text(encoding='utf8'))
            if damage == 'context_id':
                event['region']['request_outcome']['context_id'] = 'unrelated-context'
            else:
                event['region']['fallback_reason'] = 'invalid_response'
            files[0].write_text(json.dumps(event), encoding='utf8')
        audit = audit_electrothermal_run(run, deep=True)
        assert not audit['passed'], audit
        assert audit['issues']


def test_inactive_region_imported_plan_needs_zero_requests_and_audits(tmp_path_factory):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_audit import audit_electrothermal_run

    root = tmp_path_factory.mktemp('rfi')
    cfg = _shared_initialization(root)
    cfg['optimization']['region']['active_until'] = 1

    class ForbiddenTransport:
        def post(self, payload):
            pytest.fail('inactive Region must not make any transport request')

    controller = ElectrothermalLLMController(transport=ForbiddenTransport(), is_mock=True)
    result = run_electrothermal_experiment(
        cfg, root, base_dir=root, llm_controller=controller,
    )
    run = Path(result['run_directory'])
    assert controller.requests == 0
    assert result['API_calls'] == result['costs']['mock_llm_requests'] == 0
    assert not list((run / 'llm').glob('*.payload.json'))
    assert result['BO_rounds'] == 2
    for file in sorted((run / 'mo-rounds').glob('*.json')):
        event = json.loads(file.read_text(encoding='utf8'))
        assert event['region']['fallback_reason'] == 'inactive'
        assert event['region']['request_outcome'] == {
            'status': 'skipped', 'reason': 'inactive',
            'context_id': event['context']['context_id'],
        }
        assert not event['region']['accepted']
        assert event['selected_index'] == event['region']['plain_index']
    audit = audit_electrothermal_run(run, deep=True)
    assert audit['passed'], audit


@pytest.mark.parametrize('inactive', [False, True])
def test_region_summary_separates_request_failures_and_inactive_rounds(tmp_path_factory, inactive):
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController

    root = tmp_path_factory.mktemp('rfs')
    cfg = _shared_initialization(root)
    if inactive:
        cfg['optimization']['region']['active_until'] = 1

    class TimeoutTransport:
        def post(self, payload):
            assert not inactive, 'inactive Region must not issue a request'
            raise TimeoutError('offline injected timeout')

    controller = ElectrothermalLLMController(transport=TimeoutTransport(), is_mock=True)
    result = run_electrothermal_experiment(
        cfg, root, base_dir=root, llm_controller=controller,
    )
    # request_attempts deliberately includes mock Region attempts. API_calls
    # retains its existing meaning of actual paid/real requests only.
    expected = {
        'rounds': 2, 'request_attempts': 0 if inactive else 2,
        'responses': 0, 'accepted': 0,
        'request_failures': 0 if inactive else 2,
        'fallback_counts': {'inactive' if inactive else 'request_timeout': 2},
    }
    assert result['region_diagnostics'] == expected
    assert result['API_calls'] == 0
    assert controller.requests == expected['request_attempts']
    archived = json.loads((Path(result['run_directory']) / 'electrothermal-summary.json').read_text(encoding='utf8'))
    assert archived['region_diagnostics'] == expected
