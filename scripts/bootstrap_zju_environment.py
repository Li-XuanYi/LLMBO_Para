"""Executed on zju by zju_exec; creates an isolated archived Linux runtime."""
import datetime
import email
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
    os.environ[name] = "1"

root = Path("/home/yqt/XuanyiLi/LLMBO")
assert root.is_dir() and root.resolve() == root
if shutil.disk_usage(root).free < 5 * 1024**3:
    raise RuntimeError("less than 5 GiB disk available; environment setup deferred")
stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
archive = root / "environment" / stamp
archive.mkdir(parents=True, exist_ok=False)
venv = archive / "venv"
wheelhouse = archive / "wheelhouse"
wheelhouse.mkdir()
requirements = archive / "requested-requirements.txt"
requirements.write_text("pip==24.0\npybamm==25.10.2\nnumpy==2.5.3\nscipy==1.18.1\nopenpyxl==3.1.5\nmatplotlib==3.11.2\n", encoding="utf-8")


def run(label, command):
    with (archive / (label + "-command.json")).open("x", encoding="utf-8") as stream:
        json.dump(command, stream, indent=2)
    with (archive / (label + "-output.txt")).open("x", encoding="utf-8") as stream:
        result = subprocess.run(command, stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, cwd=root)
    (archive / (label + "-exit-code.txt")).write_text(str(result.returncode), encoding="utf-8")
    print(json.dumps({"stage": label, "exit_code": result.returncode, "environment_archive": str(archive)}), flush=True)
    if result.returncode:
        raise RuntimeError(label + " failed; see " + str(archive / (label + "-output.txt")))


run("create-venv", [sys.executable, "-m", "venv", "--without-pip", str(venv)])
python = str(venv / "bin/python")
bootstrap_pip = [sys.executable, "-m", "pip", "--python", python]
run("download", bootstrap_pip + ["download", "--index-url", "https://pypi.org/simple", "--timeout", "20",
    "--retries", "0", "--only-binary=:all:", "--cache-dir", str(archive / "pip-cache"),
    "--dest", str(wheelhouse), "-r", str(requirements)])
locked = []
for wheel in sorted(wheelhouse.glob("*.whl")):
    with zipfile.ZipFile(wheel) as package:
        metadata = next(name for name in package.namelist() if name.endswith(".dist-info/METADATA"))
        parsed = email.message_from_bytes(package.read(metadata))
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    locked.append(f"{parsed['Name']}=={parsed['Version']} --hash=sha256:{digest}")
(archive / "resolved-requirements.lock").write_text("\n".join(locked) + "\n", encoding="utf-8")
run("install-offline", bootstrap_pip + ["install", "--no-index", "--find-links", str(wheelhouse),
    "--require-hashes", "-r", str(archive / "resolved-requirements.lock"), "--report", str(archive / "installation-report.json")])
run("pip-check", [python, "-m", "pip", "check"])
run("freeze", [python, "-m", "pip", "freeze"])
run("runtime", [python, "-c", "import sys,numpy,scipy,pybamm,casadi,openpyxl; print(sys.version); print(numpy.__version__,scipy.__version__,pybamm.__version__,casadi.__version__,openpyxl.__version__)"])
result = {"python": python, "environment_archive": str(archive), "wheel_count": len(locked), "disk_free_after": shutil.disk_usage(root).free}
(archive / "environment-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
print(json.dumps(result), flush=True)
