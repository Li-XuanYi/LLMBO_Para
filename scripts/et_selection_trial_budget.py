"""Durable, parent-owned budget for a source-pinned selection trial."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import time


def _digest(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _validate_limits(caps: dict, phases: dict) -> None:
    if (not isinstance(caps, dict) or set(caps) != {"DFN", "API", "wall_clock_s"}
            or any(type(caps[k]) is not int or caps[k] < 0 for k in caps)
            or caps["wall_clock_s"] <= 0 or not isinstance(phases, dict) or not phases):
        raise ValueError("invalid budget limits")
    for name, limit in phases.items():
        if (not isinstance(name, str) or not name or not isinstance(limit, dict)
                or set(limit) != {"DFN", "API"}
                or any(type(limit[k]) is not int or limit[k] < 0 for k in limit)):
            raise ValueError("invalid phase limits")
    if any(sum(limit[k] for limit in phases.values()) > caps[k] for k in ("DFN", "API")):
        raise ValueError("phase limits exceed total")


class SelectionTrialBudget:
    """One writer; every API request or solve is charged before execution."""

    def __init__(self, path: Path, *, caps: dict, phases: dict):
        _validate_limits(caps, phases)
        self.path = Path(path)
        self.caps = dict(caps)
        self.phases = {name: dict(limit) for name, limit in phases.items()}

    @classmethod
    def start(cls, path: Path, *, protocol_sha: str, caps: dict, phases: dict):
        if (not isinstance(protocol_sha, str) or len(protocol_sha) != 64
                or any(c not in "0123456789abcdef" for c in protocol_sha)):
            raise ValueError("protocol SHA-256 required")
        obj = cls(path, caps=caps, phases=phases)
        event = {"type": "start", "protocol_sha": protocol_sha, "limits": obj.caps,
                 "phases": obj.phases, "unix": time.time(), "mono": time.monotonic(),
                 "previous": None}
        event["hash"] = _digest(event)
        with obj.path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return obj

    def state(self) -> dict:
        content = self.path.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            raise ValueError("incomplete budget journal")
        events = [json.loads(line) for line in content.splitlines()]
        if (not events or events[0].get("type") != "start"
                or events[0].get("limits") != self.caps
                or events[0].get("phases") != self.phases):
            raise ValueError("invalid budget origin")
        state = {"counts": {"DFN": 0, "API": 0}, "phase": None,
                 "closed": False, "finished": [], "ids": set(),
                 "phase_counts": {name: {"DFN": 0, "API": 0} for name in self.phases}}
        previous = None
        for index, event in enumerate(events):
            if (event.get("previous") != previous
                    or event.get("hash") != _digest({k: v for k, v in event.items() if k != "hash"})):
                raise ValueError("budget hash chain differs")
            previous = event["hash"]
            if index == 0:
                continue
            if state["closed"]:
                raise ValueError("event after budget closure")
            kind = event.get("type")
            if kind == "begin":
                idx = len(state["finished"])
                expected = list(self.phases)[idx] if idx < len(self.phases) else None
                if state["phase"] is not None or event.get("phase") != expected:
                    raise ValueError("overlapping or out-of-order phase")
                state["phase"] = expected
            elif kind == "charge":
                phase, item, ident = state["phase"], event.get("kind"), event.get("event_id")
                if phase is None or item not in ("DFN", "API") or not isinstance(ident, str) or not ident or ident in state["ids"]:
                    raise ValueError("unscoped or duplicate charge")
                state["ids"].add(ident)
                state["counts"][item] += 1
                state["phase_counts"][phase][item] += 1
                if (state["counts"][item] > self.caps[item]
                        or state["phase_counts"][phase][item] > self.phases[phase][item]):
                    raise ValueError("persisted charge exceeds cap")
            elif kind == "finish":
                if state["phase"] is None or type(event.get("success")) is not bool:
                    raise ValueError("invalid phase completion")
                state["finished"].append(state["phase"])
                state["phase"] = None
                state["closed"] = not event["success"] or len(state["finished"]) == len(self.phases)
            elif kind == "abort":
                if state["phase"] is not None:
                    raise ValueError("abort requires no active phase")
                state["closed"] = True
            else:
                raise ValueError("unknown budget event")
        state.update(origin=events[0], hash=previous)
        return state

    def _append(self, event: dict) -> None:
        event = {**event, "previous": self.state()["hash"]}
        event["hash"] = _digest(event)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @property
    def deadline(self) -> float:
        origin = self.state()["origin"]
        return min(origin["mono"] + self.caps["wall_clock_s"],
                   time.monotonic() + max(0., origin["unix"] + self.caps["wall_clock_s"] - time.time()))

    def counts(self) -> dict:
        return self.state()["counts"].copy()

    def _open(self) -> dict:
        state = self.state()
        if state["closed"] or time.monotonic() >= self.deadline:
            raise RuntimeError("budget closed or deadline exhausted")
        return state

    def begin(self, phase: str) -> None:
        state = self._open()
        idx = len(state["finished"])
        expected = list(self.phases)[idx] if idx < len(self.phases) else None
        if state["phase"] is not None or phase != expected:
            raise RuntimeError("repeated or out-of-order phase")
        self._append({"type": "begin", "phase": phase})

    def finish(self, success: bool) -> None:
        if self.state()["phase"] is None or type(success) is not bool:
            raise RuntimeError("active phase required")
        self._append({"type": "finish", "success": success})

    def abort(self) -> None:
        state = self.state()
        if state["closed"] or state["phase"] is not None:
            raise RuntimeError("open budget without active phase required")
        self._append({"type": "abort"})

    def require(self, calls: int) -> None:
        if type(calls) is not int or calls < 0:
            raise ValueError("nonnegative solver reservation required")
        state = self._open()
        phase = state["phase"]
        if (phase is None or state["counts"]["DFN"] + calls > self.caps["DFN"]
                or state["phase_counts"][phase]["DFN"] + calls > self.phases[phase]["DFN"]):
            raise RuntimeError("insufficient solver reservation")

    def charge(self, kind: str, ident: str) -> None:
        state = self._open()
        phase = state["phase"]
        if (phase is None or kind not in ("DFN", "API") or not isinstance(ident, str)
                or not ident or ident in state["ids"] or state["counts"][kind] >= self.caps[kind]
                or state["phase_counts"][phase][kind] >= self.phases[phase][kind]):
            raise RuntimeError("duplicate, unscoped or exhausted budget charge")
        self._append({"type": "charge", "kind": kind, "event_id": ident})
