"""Upload only audited project files and the explicit workbook to a new release."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tarfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--prepare-only", action="store_true", help="Build and inspect the local bundle without any connection or upload")
parser.add_argument("--transfer-approved", action="store_true", help="Use only after explicit user authorization to upload source and the workbook")
args = parser.parse_args()
if not args.prepare_only and not args.transfer_approved:
    parser.error("Explicit workbook/source transfer authorization is pending; --prepare-only is available")
tag = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
archive = root / "runs/deployment-previews" / tag
archive.mkdir(parents=True, exist_ok=False)
bundle = archive / ("release-" + tag + ".tar.gz")
files = []
for folder in ("src", "scripts", "tests", "configs", "docs"):
    files.extend(file for file in (root / folder).rglob("*") if file.is_file() and "__pycache__" not in file.parts)
files.extend(root / name for name in ("README.md", "pyproject.toml", "requirements-py312.lock", ".gitignore"))
files.append(root / "data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx")
with tarfile.open(bundle, "x:gz") as package:
    for file in files:
        package.add(file, arcname=str(file.relative_to(root)), recursive=False)
digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
with (archive / ("release-" + tag + "-file-index.json")).open("x", encoding="utf-8") as stream:
    json.dump({str(file.relative_to(root)): hashlib.sha256(file.read_bytes()).hexdigest() for file in files}, stream, indent=2)
remote_code = '''
import hashlib,io,json,sys,tarfile
from pathlib import Path
root=Path('/home/yqt/XuanyiLi/LLMBO')
blob=sys.stdin.buffer.read()
assert hashlib.sha256(blob).hexdigest()==EXPECTED
release=root/'releases'/TAG
release.mkdir(parents=True,exist_ok=False)
transfer=root/'transfers'
transfer.mkdir(exist_ok=True)
with (transfer/(TAG+'.tar.gz')).open('xb') as stream: stream.write(blob)
with tarfile.open(fileobj=io.BytesIO(blob),mode='r:gz') as package:
    for member in package.getmembers():
        target=(release/member.name).resolve()
        assert target.is_relative_to(release) and not member.issym() and not member.islnk()
    package.extractall(release,filter='data')
config=json.loads((release/'configs/21700-feasible-ablation.json').read_text())
config['data']['path']=str(release/'data/raw/6c796b3f08156229636b033d3e6ff036ad8ae143525e86c5de16983e5a1483a7/true_data.xlsx')
config['llm']['max_tokens']=4096
config['status']='zju_paired_ablation_8_valid_initial_25_bo_with_full_screening_cost'
with (release/'configs/ablation-zju.json').open('x') as stream: json.dump(config,stream,indent=2)
result={'release_directory':str(release),'bundle_sha256':EXPECTED,'file_count':len(list(release.rglob('*'))),'config':str(release/'configs/ablation-zju.json')}
with (release/'deployment.json').open('x') as stream: json.dump(result,stream,indent=2)
print(json.dumps(result),flush=True)
'''.replace("EXPECTED", repr(digest)).replace("TAG", repr(tag))
command = ["wsl.exe", "-d", "Ubuntu", "--exec", "ssh", "-T", "-o", "ControlMaster=no", "-o", "ControlPath=none",
    "-o", "BatchMode=yes", "-o", "ConnectTimeout=15", "-o", "StrictHostKeyChecking=yes", "zju",
    "python3 -c " + shlex.quote(remote_code)]
with (archive / ("deploy-" + tag + "-command.json")).open("x", encoding="utf-8") as stream:
    json.dump({"command": command, "bundle": str(bundle), "bundle_sha256": digest}, stream, indent=2)
if args.prepare_only:
    preview = {"state": "prepared_locally_no_connection_or_transfer", "local_bundle": str(bundle), "bundle_sha256": digest,
        "bundle_bytes": bundle.stat().st_size, "file_count": len(files), "remote_root": "/home/yqt/XuanyiLi/LLMBO",
        "contains": "audited project source/config/tests/docs and the canonical measured XLSX; excludes credentials, environments, Reference, and historical runs",
        "permission": "pending explicit source/workbook transfer consent"}
    with (archive / "preview.json").open("x", encoding="utf-8") as stream: json.dump(preview,stream,indent=2)
    print(json.dumps(preview),flush=True)
    raise SystemExit(0)
result = subprocess.run(command, input=bundle.read_bytes(), capture_output=True)
with (archive / ("deploy-" + tag + "-stdout.txt")).open("xb") as stream: stream.write(result.stdout)
with (archive / ("deploy-" + tag + "-stderr.txt")).open("xb") as stream: stream.write(result.stderr)
print(result.stdout.decode("utf-8", errors="replace"), flush=True)
print(json.dumps({"exit_code": result.returncode, "local_bundle": str(bundle)}), flush=True)
raise SystemExit(result.returncode)
