import json
import hashlib
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path('D:/Users/aa133/Desktop/LLMBO_Para/runs/f1101/template.json')
POLICY = Path('D:/Users/aa133/Desktop/LLMBO_Para/bo-repair-work/environments/baselines312-20261102/Scripts/python.exe')


def test_cold_software_trial_covers_fresh_pools_and_three_methods(tmp_path):
    if not TEMPLATE.is_file() or not POLICY.is_file():
        pytest.skip('local synthetic template and stock policy environment required')
    out = tmp_path/'trial'
    design = tmp_path/'design.json'
    design.write_text(json.dumps({'seeds':[131469], 'template_sha256':hashlib.sha256(TEMPLATE.read_bytes()).hexdigest(),
        'arm_order_by_seed':{'131469':['smpso','LLMBO','nsga2']}}),encoding='utf8')
    p = subprocess.run([sys.executable,str(ROOT/'scripts/run_fresh_comparison.py'),
        '--software','--design',str(design),'--template',str(TEMPLATE),'--policy-python',str(POLICY),
        '--output',str(out),'--rounds','1','--seed-count','1'],cwd=ROOT,capture_output=True,text=True,timeout=240)
    assert p.returncode==0,p.stdout+p.stderr
    result=json.loads((out/'result.json').read_text(encoding='utf8'))
    assert result['status']=='completed'
    assert result['counts']=={'DFN':0,'API':0}
    assert set(result['seeds'][0]['pools'])=={'numeric','llm_v3'}
    assert set(result['seeds'][0]['arms'])=={'LLMBO','nsga2','smpso'}
    assert all(x['status']=='completed' for x in result['seeds'][0]['arms'].values())
