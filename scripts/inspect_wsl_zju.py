"""Read-only inventory of the requested WSL SSH target; never read credentials."""
import json
from pathlib import Path
import subprocess
import sys

workspace = Path(__file__).resolve().parents[1]
archive = workspace / "runs/ablation-preparation/20261011T054928Z_3b7b86e5a827_0f76dcff"
wsl_code = r'''
import json,os,platform,subprocess
result=subprocess.run(['ssh','-G','zju'],capture_output=True,text=True)
fields={}
for line in result.stdout.splitlines():
    key, _, value=line.partition(' ')
    if key in {'hostname','user','port','identityfile','proxyjump','proxycommand'}:
        fields.setdefault(key,[]).append(value)
print(json.dumps({'wsl_user':os.getlogin() if os.isatty(0) else os.environ.get('USER'),'wsl_home':os.path.expanduser('~'),'platform':platform.platform(),'ssh_config_exit_code':result.returncode,'ssh_target_fields':fields,'ssh_stderr':result.stderr}))
'''
remote_code = r'''
import json,os,platform,shutil,subprocess,sys
from pathlib import Path
target=Path('/home/yqt/XuanyiLi/LLMBO')
parents=[Path('/home/yqt'),Path('/home/yqt/XuanyiLi'),target]
paths=[]
for item in parents:
    paths.append({'path':str(item),'exists':item.exists(),'is_directory':item.is_dir(),'writable':os.access(item,os.W_OK)})
contents=[{'name':item.name,'is_directory':item.is_dir()} for item in sorted(target.iterdir())[:80] if not item.name.startswith('.')] if target.is_dir() else []
commands={}
for label, command in {'memory':['free','-b'],'disk':['df','-B1','/home/yqt'],'cpu':['getconf','_NPROCESSORS_ONLN'],'gpu':['nvidia-smi','--query-gpu=name,memory.total,memory.used,utilization.gpu','--format=csv,noheader'],'python312':['python3.12','--version'],'uv':['uv','--version']}.items():
    try:
        result=subprocess.run(command,capture_output=True,text=True,timeout=12)
        commands[label]={'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr}
    except (OSError,subprocess.TimeoutExpired) as exc:
        commands[label]={'error_type':type(exc).__name__,'message':str(exc)}
print(json.dumps({'hostname':platform.node(),'platform':platform.platform(),'user_uid':os.getuid(),'home':str(Path.home()),'cwd':str(Path.cwd()),'python':sys.version,'python_executable':sys.executable,'paths':paths,'existing_target_contents':contents,'commands':commands}))
'''


def call(label, command, source=None):
    result = subprocess.run(command, input=source, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    evidence = {"command": command, "remote_stdin_script": source, "exit_code": result.returncode,
                "stdout": result.stdout, "stderr": result.stderr}
    with (archive / (label + ".json")).open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, indent=2)
    print(json.dumps({"stage": label, **evidence}, ensure_ascii=False), flush=True)
    return result


first = call("wsl-ssh-config", ["wsl.exe", "-d", "Ubuntu", "--exec", "python3", "-c", wsl_code])
if first.returncode:
    raise SystemExit(first.returncode)
second = call("remote-readonly-inventory", ["wsl.exe", "-d", "Ubuntu", "--exec", "ssh", "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=yes", "zju", "python3", "-"], remote_code)
raise SystemExit(second.returncode)
