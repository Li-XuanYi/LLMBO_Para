import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FACTORIAL = Path(r'D:/Users/aa133/Desktop/LLMBO_Para/runs/f1101')
POLICY = Path(r'D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/environments/baselines312-20261102/Scripts/python.exe')


def test_real_run_requires_matching_software_proof(tmp_path):
    p = subprocess.run([sys.executable, str(ROOT/'scripts/run_et_classical_validation.py'),
        '--execute', '--factorial-root', str(FACTORIAL), '--policy-python', str(POLICY),
        '--output', str(tmp_path/'real'), '--rounds', '50', '--seed-count', '5'],
        cwd=ROOT, text=True, capture_output=True, timeout=30)
    assert p.returncode != 0
    assert 'software proof required' in p.stderr
    assert not (tmp_path/'real').exists()


def test_one_seed_software_closed_loop(tmp_path):
    output = tmp_path / 'trial'
    p = subprocess.run([sys.executable, str(ROOT/'scripts/run_et_classical_validation.py'),
        '--software', '--factorial-root', str(FACTORIAL), '--policy-python', str(POLICY),
        '--output', str(output), '--rounds', '1', '--seed-count', '1'],
        cwd=ROOT, text=True, capture_output=True, timeout=240)
    assert p.returncode == 0, p.stdout + p.stderr
    data = json.loads((output/'result.json').read_text(encoding='utf8'))
    assert data['status'] == 'completed'
    assert data['counts'] == {'DFN': 0, 'API': 0}
    assert {v['method'] for v in data['phases']} == {'parego16', 'nsga2', 'smpso'}
    assert all(v['status'] == 'completed' and v['rounds'] == 1 for v in data['phases'])
    sys.path.insert(0, str(ROOT/'scripts'))
    from analyze_et_classical_validation import audit_external, digest
    nsga = next(v for v in data['phases'] if v['method'] == 'nsga2')
    run = Path(nsga['run_directory'])
    assert audit_external(run, expected_rounds=1)['passed']
    event = run/'baseline-policy-events/000016.json'
    record = json.loads(event.read_text(encoding='utf8'))
    record['feedback']['objectives'][0] += 1
    event.write_text(json.dumps(record), encoding='utf8')
    assert not audit_external(run, expected_rounds=1)['passed']
    record['feedback']['objectives'][0] -= 1
    record['proposal']['x'][0] = 0.01
    record['content_sha256'] = digest([record['proposal'], record['feedback']])
    event.write_text(json.dumps(record), encoding='utf8')
    round_file = run/'baseline-rounds/000001.json'
    round_record = json.loads(round_file.read_text(encoding='utf8'))
    round_record['normalized_x'] = record['proposal']['x']
    round_file.write_text(json.dumps(round_record), encoding='utf8')
    assert not audit_external(run, expected_rounds=1)['passed']
