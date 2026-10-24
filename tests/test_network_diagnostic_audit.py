"""Independent replay of safe network evidence, including deletion of all fields."""
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def put(path, value):
    path.write_text(json.dumps(value), encoding='utf8')


@pytest.fixture(scope='module')
def archives():
    return {}


def fixture_run(archives, monkeypatch, tmp_path_factory):
    from test_region_failure_audit import _shared_initialization
    from test_lgbo_region_audit import run_fixture
    if 'shared' not in archives:
        archives['shared'] = _shared_initialization(tmp_path_factory.mktemp('networkinit'))
        # The full-suite baseline proved a 60s fixture susceptible to host delay.
        archives['shared']['budgets']['wall_clock_s'] = 300.
    return run_fixture(archives, monkeypatch, tmp_path_factory,
                       protocol='responses', kind='transport_failure')[0]


def synchronize_round_outcome(run, outcome):
    for p in (run / 'mo-rounds').glob('*.json'):
        d = read(p)
        if d['region']['request_outcome'].get('ordinal') == outcome['ordinal']:
            d['region']['request_outcome'] = deepcopy(outcome)
            put(p, d)


def test_complete_network_evidence_deep_replays(archives, monkeypatch, tmp_path_factory):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    run = fixture_run(archives, monkeypatch, tmp_path_factory)
    assert audit_electrothermal_run(run, deep=True)['passed']
    for p in (run / 'llm').glob('*.outcome.json'):
        d = read(p)
        assert d['network_diagnostic'] == {'category': 'unknown', 'cause_type': 'other'}


@pytest.mark.parametrize('damage', [
    'raw_change', 'supervision_change', 'outcome_change',
    'raw_delete', 'supervision_delete', 'outcome_delete',
    'delete_all_fields', 'delete_error_file_and_all_fields',
    'all_invalid_enum', 'all_invalid_number', 'all_free_text',
])
def test_network_evidence_tampering_is_detected(archives, monkeypatch, tmp_path_factory, tmp_path, damage):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    original = fixture_run(archives, monkeypatch, tmp_path_factory)
    run = tmp_path / 'copy'
    shutil.copytree(original, run)
    assert audit_electrothermal_run(run, deep=True)['passed']
    outcome_path = next((run / 'llm').glob('*.outcome.json'))
    outcome = read(outcome_path)
    ordinal = outcome['ordinal']
    payload = read(run / 'llm' / f'{ordinal:06d}.payload.json')
    artifact = payload['artifact_task']
    paths = {'raw': run / 'http' / (artifact + '.error.json'),
             'supervision': run / 'http' / (artifact + '.supervision.json'),
             'outcome': outcome_path}
    if damage.startswith('all_') or damage.startswith('delete_'):
        targets = list(paths.values())
    else:
        targets = [paths[damage.split('_')[0]]]
    for p in targets:
        d = read(p)
        if 'delete' in damage:
            d.pop('network_diagnostic')
        elif damage.endswith('change'):
            d['network_diagnostic'] = {'category': 'dns', 'cause_type': 'gaierror', 'os_errno': 11001}
        elif damage == 'all_invalid_enum':
            d['network_diagnostic']['category'] = 'untrusted-category'
        elif damage == 'all_invalid_number':
            d['network_diagnostic']['winerror'] = True
        else:
            d['network_diagnostic']['message'] = 'private free text'
        put(p, d)
    if damage == 'delete_error_file_and_all_fields':
        paths['raw'].unlink()  # Only this owned fixture copy.
    synchronize_round_outcome(run, read(outcome_path))
    result = audit_electrothermal_run(run, deep=True)
    assert not result['passed'], result
    assert any('network diagnostic' in issue for issue in result['issues'])


def test_old_source_missing_network_extension_remains_valid():
    from llmbo_para.electrothermal_audit import _audit_network_diagnostics
    _audit_network_diagnostics({'status': 'failed', 'reason': 'transport_error'},
                              {'error_type': 'URLError'}, {}, supported_source=False)


@pytest.mark.parametrize('position', [0, 1, 2])
@pytest.mark.parametrize('invalid', [[], None, 'invalid'])
def test_nonobject_machine_records_are_a_failed_audit(position, invalid):
    from llmbo_para.electrothermal_audit import _audit_network_diagnostics
    values = [{}, {}, {}]
    values[position] = invalid
    with pytest.raises(ValueError, match='network diagnostic'):
        _audit_network_diagnostics(*values, supported_source=True)
