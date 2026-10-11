"""Execute an archived Python maintenance script via the user's WSL SSH alias."""
import argparse
import json
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser()
parser.add_argument("script", type=Path)
parser.add_argument("--label", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
archive = root / "runs/ablation-preparation/20261011T054928Z_3b7b86e5a827_0f76dcff"
command = ["wsl.exe", "-d", "Ubuntu", "--exec", "ssh", "-T", "-o", "ControlMaster=no", "-o", "ControlPath=none", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
           "-o", "StrictHostKeyChecking=yes", "zju", "python3", "-"]
script = args.script.read_bytes()
with (archive / (args.label + "-command.json")).open("x", encoding="utf-8") as stream:
    json.dump({"command": command, "stdin_script_path": str(args.script.resolve())}, stream, indent=2)
with (archive / (args.label + "-script.py")).open("xb") as stream:
    stream.write(script)
with (archive / (args.label + "-stdout.txt")).open("xb") as output, (archive / (args.label + "-stderr.txt")).open("xb") as error:
    result = subprocess.run(command, input=script, stdout=output, stderr=error)
with (archive / (args.label + "-exit.json")).open("x", encoding="utf-8") as stream:
    json.dump({"exit_code": result.returncode}, stream)
print((archive / (args.label + "-stdout.txt")).read_text(encoding="utf-8", errors="replace"), flush=True)
print(json.dumps({"exit_code": result.returncode, "archive_directory": str(archive)}), flush=True)
raise SystemExit(result.returncode)
