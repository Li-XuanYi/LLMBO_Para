"""Source-pinned v1/v2 WarmStart selection study; dry run by default.

The live supervisor is added only after its software and provenance gates pass.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import time


WT = Path("C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para")
MAIN = Path("D:/Users/aa133/Desktop/LLMBO_Para")
BASE = MAIN / "bo-repair-work/20261017_et_implementation"
PROPOSAL = BASE / "warmstart-v1-v2-paired-20261027/proposal/protocol-proposal.json"
OUTPUT = MAIN / "runs/warmstart-v1-v2-20261027"
PLAN_COMMIT = "8e69bf85f8633ae72ee8e80d047d21a27f7ea11e"
SEEDS = (260437, 152325, 947445, 235695, 299924)
RUN_ORDER = (152325, 235695, 947445, 260437, 299924)
OLD_SEEDS = (376330, 633262, 789058, 609653, 362724)
CAPS = {"DFN": 1160, "API": 15, "wall_clock_s": 28800}
SOURCE_FILES = (
    "src/llmbo_para/electrothermal_config.py",
    "src/llmbo_para/electrothermal_llm.py",
    "src/llmbo_para/electrothermal_provenance.py",
    "src/llmbo_para/electrothermal_workflow.py",
    "src/llmbo_para/electrothermal_evaluation.py",
    "src/llmbo_para/mo_optimizer.py",
    "src/llmbo_para/pybamm_adapter.py",
    "scripts/et_three_arm_validation_worker.py",
    "scripts/run_et_three_arm_validation.py",
    "scripts/analyze_et_three_arm_validation.py",
)


def _arm_order() -> dict[str, list[str]]:
    return {str(seed): (["v1", "v2"] if index % 2 == 0 else ["v2", "v1"])
            for index, seed in enumerate(RUN_ORDER)}


PHASES = {
    phase: limits
    for seed in RUN_ORDER
    for phase, limits in (
        (f"pool-{seed}", {"DFN": 32, "API": 3}),
        *((f"arm-{seed}-{arm}", {"DFN": 100, "API": 0})
          for arm in _arm_order()[str(seed)]),
    )
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _hex64(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def validate_protocol(protocol: dict) -> dict:
    if not isinstance(protocol, dict) or set(protocol) != {
        "schema_version", "status", "plan", "plan_commit", "seed_generation",
        "seeds", "seed_run_order", "arm_order_by_seed", "fit_rates", "rate_window_s",
        "candidate_pool_size", "initial_count_per_arm", "new_bo_rounds_per_arm",
        "real_api_requests_at_proposal", "real_dfn_solves_at_proposal",
        "independent_live_caps_if_released", "template", "configs", "source_files",
        "historical_seed_exclusions", "live_output",
    }:
        raise ValueError("paired protocol fields differ")
    generated = random.Random(20261027).sample(range(100000, 1000000), 5)
    order = generated.copy()
    random.Random(20261028).shuffle(order)
    if (protocol["schema_version"] != 1
            or protocol["status"] != "proposal_disabled_no_live_authorization_file"
            or protocol["plan"] != "docs/superpowers/plans/2026-10-27-warmstart-selection-paired-validation-plan.md"
            or protocol["plan_commit"] != PLAN_COMMIT
            or protocol["seed_generation"] != "random.Random(20261027).sample(range(100000,1000000),5)"
            or protocol["seeds"] != generated or tuple(generated) != SEEDS
            or protocol["seed_run_order"] != order or tuple(order) != RUN_ORDER
            or protocol["arm_order_by_seed"] != _arm_order()
            or protocol["fit_rates"] != ["0.5C", "1C"]
            or protocol["rate_window_s"] != 60
            or protocol["candidate_pool_size"] != 16
            or protocol["initial_count_per_arm"] != 8
            or protocol["new_bo_rounds_per_arm"] != 50
            or protocol["real_api_requests_at_proposal"] != 0
            or protocol["real_dfn_solves_at_proposal"] != 0
            or protocol["independent_live_caps_if_released"] != CAPS
            or protocol["historical_seed_exclusions"] != list(OLD_SEEDS)
            or protocol["live_output"] != str(OUTPUT)
            or set(generated) & set(OLD_SEEDS)):
        raise ValueError("paired protocol method, seeds, rates or cap differs")
    template = protocol["template"]
    expected_template = BASE / "three-arm-50round-eof-proposal-20261027/seed-376330.disabled-config.json"
    if (not isinstance(template, dict) or set(template) != {"path", "sha256"}
            or Path(template["path"]) != expected_template
            or not _hex64(template["sha256"])
            or _sha(expected_template) != template["sha256"]):
        raise ValueError("synthetic observation template differs")
    if not isinstance(protocol["configs"], dict) or set(protocol["configs"]) != {str(s) for s in SEEDS}:
        raise ValueError("disabled seed config set differs")
    for seed in SEEDS:
        item = protocol["configs"][str(seed)]
        expected_path = PROPOSAL.parent / f"seed-{seed}.disabled-config.json"
        if (not isinstance(item, dict) or set(item) != {"path", "sha256"}
                or Path(item["path"]) != expected_path or not _hex64(item["sha256"])
                or _sha(expected_path) != item["sha256"]):
            raise ValueError("disabled seed config pin differs")
        config = json.loads(expected_path.read_text(encoding="utf-8"))
        opt = config["optimization"]
        if (config["fit_rates"] != ["0.5C", "1C"]
                or config["run_kind"] != "synthetic_dfn"
                or config["budgets"] != {"max_solver_calls": 0, "max_llm_requests": 0, "wall_clock_s": 28800}
                or config["llm"]["enabled"] is not False
                or opt["seed"] != seed or opt["mode"] != "warmstart_only"
                or opt["initial_count"] != 8 or opt["total_candidate_budget"] != 58
                or opt["warmstart"] != {
                    "count": 8, "pool_size": 16, "max_requests": 3,
                    "max_candidates": 48, "max_evaluations": 16,
                    "selection_rule": "pareto_maximin_v1",
                }):
            raise ValueError("disabled seed configuration semantics differ")
    sources = protocol["source_files"]
    if not isinstance(sources, dict) or set(sources) != set(SOURCE_FILES):
        raise ValueError("source pin set differs")
    for name, expected in sources.items():
        if not _hex64(expected) or _sha(WT / name) != expected:
            raise ValueError("pinned source bytes differ")
    return protocol


def load_protocol(path: Path = PROPOSAL) -> dict:
    return validate_protocol(json.loads(Path(path).read_text(encoding="utf-8")))


def cases(protocol: dict) -> list[dict]:
    validate_protocol(protocol)
    return [{"seed": seed, "arm": arm, "kind": "arm"}
            for seed in RUN_ORDER for arm in _arm_order()[str(seed)]]


def dry_run(path: Path = PROPOSAL, *, output: Path = OUTPUT) -> dict:
    protocol = load_protocol(path)
    return {"dry_run": True, "planned_cases": len(cases(protocol)),
            "new_rounds": len(cases(protocol)) * 50,
            "API": 0, "DFN": 0, "limits": CAPS,
            "output_not_created": not Path(output).exists()}


class PairedBudget:
    """Durable parent-only hash-chain ledger with fixed per-phase ceilings."""

    def __init__(self, path: Path):
        self.path = Path(path)

    @classmethod
    def start(cls, path: Path, *, protocol_sha: str) -> "PairedBudget":
        if not _hex64(protocol_sha):
            raise ValueError("frozen protocol SHA-256 required")
        obj = cls(path)
        event = {"type": "start", "protocol_sha": protocol_sha, "limits": CAPS,
                 "unix": time.time(), "mono": time.monotonic(), "previous": None}
        event["hash"] = _digest(event)
        with obj.path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return obj

    def state(self) -> dict:
        content = self.path.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            raise ValueError("incomplete parent budget journal")
        events = [json.loads(line) for line in content.splitlines()]
        if not events or events[0].get("type") != "start" or events[0].get("limits") != CAPS:
            raise ValueError("invalid parent budget origin")
        state = {"counts": {"DFN": 0, "API": 0}, "phase": None,
                 "closed": False, "finished": [], "ids": set(),
                 "phase_counts": {phase: {"DFN": 0, "API": 0} for phase in PHASES}}
        previous = None
        for index, event in enumerate(events):
            if (event.get("previous") != previous
                    or event.get("hash") != _digest({k: v for k, v in event.items() if k != "hash"})):
                raise ValueError("parent budget hash chain differs")
            previous = event["hash"]
            if index == 0:
                continue
            if state["closed"]:
                raise ValueError("event after budget closure")
            kind = event.get("type")
            if kind == "begin":
                next_index = len(state["finished"])
                expected = list(PHASES)[next_index] if next_index < len(PHASES) else None
                if state["phase"] is not None or event.get("phase") != expected:
                    raise ValueError("overlapping or out-of-order phase")
                state["phase"] = expected
            elif kind == "charge":
                phase, item, ident = state["phase"], event.get("kind"), event.get("event_id")
                if phase is None or item not in ("DFN", "API") or not isinstance(ident, str) or not ident or ident in state["ids"]:
                    raise ValueError("unscoped or duplicate budget charge")
                state["ids"].add(ident)
                state["counts"][item] += 1
                state["phase_counts"][phase][item] += 1
                if (state["counts"][item] > CAPS[item]
                        or state["phase_counts"][phase][item] > PHASES[phase][item]):
                    raise ValueError("persisted budget charge exceeds cap")
            elif kind == "finish":
                if state["phase"] is None or type(event.get("success")) is not bool:
                    raise ValueError("invalid phase completion")
                state["finished"].append(state["phase"])
                state["phase"] = None
                state["closed"] = not event["success"] or len(state["finished"]) == len(PHASES)
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
        start = self.state()["origin"]
        return min(start["mono"] + CAPS["wall_clock_s"],
                   time.monotonic() + max(0., start["unix"] + CAPS["wall_clock_s"] - time.time()))

    def counts(self) -> dict:
        return self.state()["counts"].copy()

    def _open(self) -> dict:
        state = self.state()
        if state["closed"] or time.monotonic() >= self.deadline:
            raise RuntimeError("parent budget closed or deadline exhausted")
        return state

    def begin(self, phase: str) -> None:
        state = self._open()
        next_index = len(state["finished"])
        expected = list(PHASES)[next_index] if next_index < len(PHASES) else None
        if state["phase"] is not None or phase != expected:
            raise RuntimeError("repeated or out-of-order budget phase")
        self._append({"type": "begin", "phase": phase})

    def finish(self, success: bool) -> None:
        if self.state()["phase"] is None or type(success) is not bool:
            raise RuntimeError("active phase required")
        self._append({"type": "finish", "success": success})

    def require(self, calls: int) -> None:
        if type(calls) is not int or calls < 0:
            raise ValueError("nonnegative integer solver reservation required")
        state = self._open()
        phase = state["phase"]
        if (phase is None or state["counts"]["DFN"] + calls > CAPS["DFN"]
                or state["phase_counts"][phase]["DFN"] + calls > PHASES[phase]["DFN"]):
            raise RuntimeError("insufficient active DFN reservation")

    def charge(self, kind: str, ident: str) -> None:
        state = self._open()
        phase = state["phase"]
        if (phase is None or kind not in ("DFN", "API")
                or not isinstance(ident, str) or not ident or ident in state["ids"]
                or state["counts"][kind] >= CAPS[kind]
                or state["phase_counts"][phase][kind] >= PHASES[phase][kind]):
            raise RuntimeError("duplicate, unscoped or exhausted budget charge")
        self._append({"type": "charge", "kind": kind, "event_id": ident})


def read_credential() -> str:
    """Read the dedicated key only into memory after a live software release."""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
        value, _ = winreg.QueryValueEx(handle, "LLMBO_OPENCODE_API_KEY")
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError("dedicated OpenCode credential missing")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run:
        parser.error("live execution is unavailable before software release")
    print(json.dumps(dry_run(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
