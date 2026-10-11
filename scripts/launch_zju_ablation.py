"""Launch the approved remote study; credential travels only through SSH stdin."""
import argparse
import getpass
import json
from pathlib import Path
import shlex
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("--release", required=True)
parser.add_argument("--python", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
archive = root / "runs/ablation-preparation/20261011T054928Z_3b7b86e5a827_0f76dcff"
remote_code = '''
from datetime import datetime,timezone
import json,os,subprocess,sys
from pathlib import Path
release=Path(RELEASE)
python=PYTHON
assert release.is_relative_to('/home/yqt/XuanyiLi/LLMBO/releases') and release.is_dir()
key=sys.stdin.readline().strip()
assert key and not any(char.isspace() for char in key)
stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
job=Path('/home/yqt/XuanyiLi/LLMBO/jobs')/stamp
job.mkdir(parents=True,exist_ok=False)
env=dict(os.environ)
env.update(LLMBO_NEWAPI_API_KEY=key,PYBAMM_DISABLE_TELEMETRY='true',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',OMP_NUM_THREADS='1')
command=[python,'-u','-X','utf8','-B',str(release/'scripts/run_ablation_suite.py'),str(release/'configs/ablation-zju.json'),'--bo-iterations','25','--output',str(release/'runs/ablations')]
supervisor_code="""
from datetime import datetime,timezone
import json,subprocess,sys,time,traceback
from pathlib import Path
job=Path(sys.argv[1])
started=time.perf_counter()
record={'started_utc':datetime.now(timezone.utc).isoformat()}
try:
    child=subprocess.Popen(sys.argv[2:],stdin=subprocess.DEVNULL)
    with (job/'worker.json').open('x') as stream: json.dump({'pid':child.pid},stream)
    record['exit_code']=child.wait()
except Exception as exc:
    record.update(exit_code=1,error_type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
record.update(finished_utc=datetime.now(timezone.utc).isoformat(),elapsed_s=time.perf_counter()-started)
with (job/'exit.json').open('x') as stream: json.dump(record,stream,indent=2)
sys.exit(0 if record['exit_code']==0 else 1)
"""
supervisor_command=[python,'-u','-c',supervisor_code,str(job),*command]
with (job/'console.log').open('x') as log:
    process=subprocess.Popen(supervisor_command,cwd=release,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
result={'job_directory':str(job),'pid':process.pid,'pid_role':'supervisor','command':command,'release_directory':str(release),'python':python,'credential_persisted':False,'workers':1,'initial_count_per_arm':8,'bo_iterations_per_arm':25,'worker_record':str(job/'worker.json'),'exit_record':str(job/'exit.json')}
with (job/'launch.json').open('x') as stream: json.dump(result,stream,indent=2)
print(json.dumps(result),flush=True)
'''.replace("RELEASE", repr(args.release)).replace("PYTHON", repr(args.python))
command = ["wsl.exe", "-d", "Ubuntu", "--exec", "ssh", "-T", "-o", "ControlMaster=no", "-o", "ControlPath=none",
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=yes", "zju",
    "python3 -c " + shlex.quote(remote_code)]
with (archive / "approved-study-launch-command.json").open("x", encoding="utf-8") as stream:
    json.dump({"command": command, "credential_transport": "hidden input then SSH stdin; not archived"}, stream, indent=2)
key = getpass.getpass("Temporary API credential for zju study (hidden): ")
result = subprocess.run(command, input=(key + "\n").encode(), capture_output=True)
key = None
with (archive / "approved-study-launch-stdout.txt").open("xb") as stream: stream.write(result.stdout)
with (archive / "approved-study-launch-stderr.txt").open("xb") as stream: stream.write(result.stderr)
with (archive / "approved-study-launch-exit.json").open("x", encoding="utf-8") as stream:
    json.dump({"ssh_launch_exit_code": result.returncode}, stream)
print(result.stdout.decode("utf-8", errors="replace"), flush=True)
raise SystemExit(result.returncode)
