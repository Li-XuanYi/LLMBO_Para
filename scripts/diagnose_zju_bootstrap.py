import json
from pathlib import Path
import subprocess
root=Path('/home/yqt/XuanyiLi/LLMBO/environment/20261011T055906Z')
print(json.dumps({'venv_error':(root/'create-venv-output.txt').read_text(),
    'known_other_python_paths':{str(path):path.exists() for path in (Path('/home/yqt/miniconda3/bin/python'),Path('/home/yqt/anaconda3/bin/python'))},
    'system_pip':subprocess.run(['python3','-m','pip','--version'],capture_output=True,text=True).stdout}),flush=True)
