"""Append-only run manifest, command record and one immutable file per attempt."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib import metadata
import hashlib
import json
from pathlib import Path
import platform
import sys
import uuid
import shutil
import os

import numpy as np


def canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest_value(value) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def reject_inline_secrets(value, location: str = "config") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in {"api_key", "token", "access_token", "authorization", "password", "secret"}:
                raise ValueError(f"{location}: inline credentials are forbidden; use an environment-variable name")
            reject_inline_secrets(child, location + "." + str(key))
    elif isinstance(value, (tuple, list)):
        for child in value:
            reject_inline_secrets(child, location)


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"cannot serialize {type(value).__name__}")


class RunStore:
    def __init__(
        self,
        root: str | Path,
        config: dict,
        *,
        data_hashes: dict[str, str] | None = None,
        command: str,
        source_revision: str | None = None,
    ):
        reject_inline_secrets(config)
        self.root = Path(root).resolve()
        self.config = config
        self.config_hash = digest_value(config)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.run_id = f"{stamp}_{self.config_hash[:12]}_{uuid.uuid4().hex[:8]}"
        self.path = self.root / self.run_id
        self.path.mkdir(parents=True, exist_ok=False)
        (self.path / "attempts").mkdir()
        self.events_path = self.path / "events.jsonl"
        manifest = {
            "schema_version": 1,
            "run_id": self.run_id,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "machine": platform.node(),
            "platform": platform.platform(),
            "python": sys.version,
            "python_executable": sys.executable,
            "process_id": os.getpid(),
            "logical_cpu_count": os.cpu_count(),
            "numerical_thread_environment": {name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS")},
            "working_directory": str(Path.cwd().resolve()),
            "output_directory": str(self.path),
            "argv": sys.argv,
            "dependencies": {
                name: self._package_version(name)
                for name in ("numpy", "openpyxl", "et_xmlfile", "pybamm", "casadi", "torch")
            },
            "config_sha256": self.config_hash,
            "config": config,
            "data_sha256": data_hashes or {},
            "command": command,
            "source_revision": source_revision,
            "status": "created",
        }
        self._create_json(self.path / "manifest.json", manifest)
        self.append_event({"type": "run_created", "run_id": self.run_id})
        self.snapshot_sources()

    @staticmethod
    def _package_version(name: str) -> str | None:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            return None

    def write_json(self, relative_path: str, value) -> Path:
        path = (self.path / relative_path).resolve()
        if not path.is_relative_to(self.path) or path == self.path:
            raise ValueError("artifact paths must stay inside the run directory")
        path.parent.mkdir(parents=True, exist_ok=True)
        self._create_json(path, value)
        return path

    def snapshot_sources(self) -> None:
        root = Path(__file__).resolve().parents[2]
        hashes = {}
        files = []
        if (root / "pyproject.toml").is_file() and (root / "src" / "llmbo_para" / "runstore.py").resolve() == Path(__file__).resolve():
            for folder in ("src", "configs", "scripts", "tests", "docs"):
                files.extend(p for p in (root / folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
            files.extend(root / name for name in ("pyproject.toml", "requirements-py312.lock", "README.md", ".gitignore"))
        else:
            # A non-editable wheel has no repository beside it; still archive
            # the actual imported package rather than silently saving no code.
            package = Path(__file__).resolve().parent
            for file in package.rglob("*"):
                if not file.is_file() or "__pycache__" in file.parts:
                    continue
                relative = Path("src/llmbo_para") / file.relative_to(package)
                target = self.path / "source" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, target)
                hashes[str(relative)] = sha256_file(target)
        for file in files:
            if not file.is_file():
                continue
            relative = file.relative_to(root)
            target = self.path / "source" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
            hashes[str(relative)] = sha256_file(target)
        self.write_json("source-sha256.json", hashes)

    def finish(self, status: str, summary: dict) -> None:
        if status not in {"completed", "completed_with_failures", "failed", "interrupted", "preflight_failed"}:
            raise ValueError("invalid terminal run status")
        self.write_json("terminal.json", {"status": status, "finished_utc": datetime.now(timezone.utc).isoformat(), "summary": summary})
        self.append_event({"type": "run_finished", "status": status, "summary": summary})

    @staticmethod
    def _create_json(path: Path, value: dict) -> None:
        serialized = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False, default=_json_default)
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(serialized + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def append_event(self, event: dict) -> None:
        row = dict(event)
        row.setdefault("timestamp_utc", datetime.now(timezone.utc).isoformat())
        with self.events_path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(canonical_json(row).decode("utf-8") + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def save_attempt(self, candidate_id: int, attempt: int, record: dict) -> Path:
        if candidate_id < 0 or attempt < 1:
            raise ValueError("candidate_id must be non-negative and attempt must be positive")
        path = self.path / "attempts" / f"candidate-{candidate_id:06d}-attempt-{attempt:03d}.json"
        self._create_json(path, record)
        self.append_event({
            "type": "candidate_attempt",
            "candidate_id": candidate_id,
            "attempt": attempt,
            "valid": bool(record.get("valid", False)),
            "objective_v": record.get("objective_v"),
            "record": path.name,
        })
        return path

