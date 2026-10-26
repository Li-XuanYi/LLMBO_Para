"""Preregistered 5-seed/3-arm electrothermal comparison; dry run by default.

All real side effects require a signed release, a dedicated credential, a
hash-chained parent budget, and cold source-pinned owned workers.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time

import run_lgbo_real_gain as helper


WT = Path("C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para")
MAIN = Path("D:/Users/aa133/Desktop/LLMBO_Para")
BASE = MAIN / "bo-repair-work/20261017_et_implementation"
PROPOSAL = BASE / "three-arm-50round-proposal-20261026"
EVIDENCE = BASE / "three-arm-50round-20261026"
OLD = BASE / "region-type-repair-20261026"
SOURCE = OLD / "s"
OUTPUT = MAIN / "runs/g26x"
CORE_FINGERPRINT = "b101a433b054dca8931c6c59c31bfce0fe2cf752d8cf0636dc88766e3459c231"
PLAN_COMMIT = "cb6ac2c6b96618d57d53c0ac8f6032d94595e241"
CANDIDATE_GATE = False
SEEDS = (376330, 633262, 789058, 609653, 362724)
ARMS = ("bo", "warmstart_only", "full_llmbo_mo")
RATES = ("0.5C", "1C")
CAPS = {"DFN": 1740, "API": 271, "wall_clock_s": 28800}
PHASES = {
    "diagnostic": {"DFN": 0, "API": 6},
    "initialization": {"DFN": 240, "API": 15},
    "main": {"DFN": 1500, "API": 250},
}
RUNTIME_FILES = (
    "run_et_three_arm_validation.py", "et_three_arm_validation_worker.py",
    "run_lgbo_real_gain.py", "lgbo_real_gain_worker.py",
    "run_region_transport_validation.py",
)


read, write, sha, digest = helper.read, helper.write, helper.sha, helper.digest


def validate_protocol(protocol: dict) -> dict:
    """Reject changed design or resource arithmetic before any live action."""
    if not isinstance(protocol, dict):
        raise ValueError("three-arm protocol must be an object")
    if protocol.get("seed_selection", {}).get("seeds") != list(SEEDS):
        raise ValueError("preselected seeds differ")
    if protocol.get("initial_count") != 8 or protocol.get("BO_rounds_per_arm") != 50:
        raise ValueError("8+50 attempt design differs")
    if protocol.get("total_candidate_budget_per_arm") != 58:
        raise ValueError("50 rounds must follow eight initial attempts")
    if protocol.get("arm_count") != 15 or protocol.get("total_BO_rounds") != 750:
        raise ValueError("case/round count differs")
    if tuple(protocol.get("fit_rates", ())) != RATES or protocol.get("duration_s") != 60:
        raise ValueError("fitting rates or duration differ")
    if protocol.get("max_rate_attempts") != 1:
        raise ValueError("rate retry rule differs")
    if protocol.get("limits") != CAPS or protocol.get("cost_breakdown") != {
        "main_DFN": 1500, "BO_initial_DFN": 80, "warmstart_pool_DFN": 160,
        "Region_API": 250, "WarmStart_API": 15, "diagnostic_API": 6}:
        raise ValueError("three-phase cap arithmetic differs")
    if (protocol.get("objective_scales") != [0.1, 1.0]
            or protocol.get("hv_reference") != [10.0, 10.0]
            or protocol.get("gp_sweeps") != 4
            or protocol.get("global_pool_size") != 512
            or protocol.get("local_pool_size") != 8
            or protocol.get("region_method") != "lgbo_v2"
            or protocol.get("region_strength_eta") != 1.0):
        raise ValueError("frozen numerical comparison differs")
    if protocol.get("provider") != {
        "endpoint": "https://opencode.ai/zen/go/v1/chat/completions",
        "model": "deepseek-v4.1-flash", "api_key_env": "LLMBO_OPENCODE_API_KEY"}:
        raise ValueError("provider differs")
    if protocol.get("timing") != {
        "single_thread": True, "Region_timeout_s": 120,
        "Region_max_tokens": 8192, "WarmStart_timeout_s": 120,
        "WarmStart_max_tokens": 8192, "transport_retries": 0}:
        raise ValueError("request control differs")
    plans = protocol.get("seed_plans")
    if not isinstance(plans, list) or len(plans) != 5:
        raise ValueError("exactly five seed plans required")
    if protocol.get("disabled_base_config_sha256") != sha(OLD / "disabled-config.json"):
        raise ValueError("disabled physical template source differs")
    source_dir = str(WT / "src")
    if source_dir not in sys.path:
        sys.path.insert(0, source_dir)
    from llmbo_para.config import parameter_space_from_config
    from llmbo_para.sobol import Sobol6
    for seed, plan in zip(SEEDS, plans):
        if plan.get("seed") != seed or sorted(plan.get("arm_order", [])) != sorted(ARMS):
            raise ValueError("seed or arm execution order differs")
        numeric = plan.get("BO_initialization", {})
        if (numeric.get("kind") != "sobol_seed_index"
                or numeric.get("start_index") != seed or numeric.get("count") != 8
                or len(numeric.get("parameters", [])) != 8
                or len({tuple(x) for x in numeric["parameters"]}) != 8):
            raise ValueError("numerical initial plan differs")
        space = parameter_space_from_config(_seed_config(seed))
        expected = [list(space.denormalize(point)) for point in Sobol6(seed).draw(8)]
        if numeric["parameters"] != expected:
            raise ValueError("Sobol seed-indexed coordinates do not reproduce")
        warm = plan.get("warmstart", {})
        if warm != {"independent_real_generation": True, "pool_target": 16,
                    "maximum_evaluations": 16, "max_requests": 3,
                    "max_candidates": 48, "minimum_complete_pool": 8,
                    "selection_count": 8,
                    "shared_between": ["warmstart_only", "full_llmbo_mo"]}:
            raise ValueError("WarmStart pool/selection contract differs")
    if protocol.get("API") != 0 or protocol.get("DFN") != 0 or protocol.get("old_budget_reopened") is not False:
        raise ValueError("draft protocol has a live or reopened cost claim")
    return protocol


def load_protocol(path=PROPOSAL / "protocol-proposal.json") -> dict:
    return validate_protocol(read(path))


def cases(protocol):
    validate_protocol(protocol)
    return [{"seed": plan["seed"], "arm": arm, "rates": list(RATES),
             "initialization": "numeric" if arm == "bo" else "warmstart"}
            for plan in protocol["seed_plans"] for arm in plan["arm_order"]]


def check_case_consistency(rows_by_arm):
    """Check paired initial state before interpreting any Region difference."""
    if not set(rows_by_arm).issubset(ARMS):
        raise ValueError("unknown comparison arm")
    available = list(rows_by_arm.values())
    weights = [[row["weight"] for row in case["rounds"]] for case in available]
    if any(sequence != weights[0] for sequence in weights[1:]):
        raise ValueError("per-seed weight schedule differs across arms")
    if {"warmstart_only", "full_llmbo_mo"}.issubset(rows_by_arm):
        warm, full = (rows_by_arm[name] for name in ("warmstart_only", "full_llmbo_mo"))
        if (warm["initial_file_sha"] != full["initial_file_sha"]
                or warm["first_numerical_context_sha"] != full["first_numerical_context_sha"]):
            raise ValueError("Region pair does not share signed initial state and numerical context")
    return True


def dry_run(path=PROPOSAL / "protocol-proposal.json", *, output=OUTPUT):
    protocol = load_protocol(path)
    # No credential lookup, output creation, HTTP or battery solve.
    return {"dry_run": True, "planned_cases": len(cases(protocol)),
            "new_rounds": protocol["total_BO_rounds"], "API": 0, "DFN": 0,
            "limits": CAPS, "output_not_created": not Path(output).exists()}


class ThreeArmBudget:
    """One durable parent writer; all charged side effects are acknowledged first."""
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def start(cls, path, *, protocol_sha):
        if not isinstance(protocol_sha, str) or len(protocol_sha) != 64:
            raise ValueError("frozen protocol SHA-256 required")
        obj = cls(path)
        event = {"type": "start", "protocol_sha": protocol_sha,
                 "limits": CAPS, "unix": time.time(),
                 "mono": time.monotonic(), "previous": None}
        event["hash"] = digest(event)
        with obj.path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        return obj

    @classmethod
    def load(cls, path):
        obj = cls(path)
        obj.state()
        return obj

    def state(self):
        content = self.path.read_text(encoding="utf-8")
        if not content.endswith("\n"):
            raise ValueError("incomplete budget journal")
        events = [json.loads(line) for line in content.splitlines()]
        if not events or events[0].get("type") != "start" or events[0].get("limits") != CAPS:
            raise ValueError("invalid budget origin")
        state = {"counts": {"DFN": 0, "API": 0}, "phase": None,
                 "closed": False, "finished": [], "ids": set(),
                 "phase_counts": {p: {"DFN": 0, "API": 0} for p in PHASES}}
        previous = None
        for i, event in enumerate(events):
            if (event.get("previous") != previous
                    or event.get("hash") != digest({k: v for k, v in event.items() if k != "hash"})):
                raise ValueError("budget hash chain differs")
            previous = event["hash"]
            if i == 0:
                continue
            if state["closed"]:
                raise ValueError("event after budget closure")
            kind = event.get("type")
            if kind == "begin":
                index = len(state["finished"])
                expected = list(PHASES)[index] if index < len(PHASES) else None
                if state["phase"] is not None or event.get("phase") != expected:
                    raise ValueError("overlapping or out-of-order budget phase")
                state["phase"] = expected
            elif kind == "charge":
                phase, item, ident = state["phase"], event.get("kind"), event.get("event_id")
                if phase is None or item not in ("DFN", "API") or ident in state["ids"]:
                    raise ValueError("unscoped or duplicate charge")
                state["ids"].add(ident)
                state["counts"][item] += 1
                state["phase_counts"][phase][item] += 1
                if (state["counts"][item] > CAPS[item]
                        or state["phase_counts"][phase][item] > PHASES[phase][item]):
                    raise ValueError("persisted charge exceeds cap")
            elif kind == "finish":
                if state["phase"] is None or type(event.get("success")) is not bool:
                    raise ValueError("invalid phase finish")
                state["finished"].append(state["phase"])
                state["phase"] = None
                state["closed"] = not event["success"]
            else:
                raise ValueError("unknown budget event")
        state.update(origin=events[0], hash=previous)
        return state

    def _append(self, event):
        event = {**event, "previous": self.state()["hash"]}
        event["hash"] = digest(event)
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    @property
    def deadline(self):
        start = self.state()["origin"]
        return min(start["mono"] + CAPS["wall_clock_s"],
                   time.monotonic() + max(0., start["unix"] + CAPS["wall_clock_s"] - time.time()))

    def counts(self):
        return self.state()["counts"].copy()

    def _open(self):
        state = self.state()
        if state["closed"] or time.monotonic() >= self.deadline:
            raise RuntimeError("budget closed or absolute deadline exhausted")
        return state

    def begin(self, phase):
        state = self._open()
        index = len(state["finished"])
        expected = list(PHASES)[index] if index < len(PHASES) else None
        if state["phase"] is not None or phase != expected:
            raise RuntimeError("repeated or out-of-order budget phase")
        self._append({"type": "begin", "phase": phase})

    def finish(self, success):
        if self.state()["phase"] is None or type(success) is not bool:
            raise RuntimeError("active phase required")
        self._append({"type": "finish", "success": success})

    def require(self, calls):
        if type(calls) is not int or calls < 0:
            raise ValueError("nonnegative integer solver reservation required")
        state = self._open()
        phase = state["phase"]
        if (phase is None or state["counts"]["DFN"] + calls > CAPS["DFN"]
                or state["phase_counts"][phase]["DFN"] + calls > PHASES[phase]["DFN"]):
            raise RuntimeError("insufficient active DFN reservation")

    def charge(self, kind, ident):
        state = self._open()
        phase = state["phase"]
        if (phase is None or kind not in ("DFN", "API")
                or not isinstance(ident, str) or not ident
                or ident in state["ids"]
                or state["counts"][kind] >= CAPS[kind]
                or state["phase_counts"][phase][kind] >= PHASES[phase][kind]):
            raise RuntimeError("duplicate, unscoped or exhausted charge")
        self._append({"type": "charge", "kind": kind, "event_id": ident})


def new_budget(path, *, protocol_sha):
    return ThreeArmBudget.start(path, protocol_sha=protocol_sha)


def read_credential():
    """Only the dedicated Windows user variable; return value only in memory."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as handle:
        value, _ = winreg.QueryValueEx(handle, "LLMBO_OPENCODE_API_KEY")
    if not isinstance(value, str) or not value or any(c.isspace() for c in value):
        raise ValueError("dedicated OpenCode credential missing")
    return value


def _input_integrity(protocol):
    for name, path in (("_launch_sha256", EVIDENCE / "live-protocol.json"),
                       ("_release_sha256", EVIDENCE / "software-release.json"),
                       ("_approval_sha256", EVIDENCE / "approval.json")):
        if name in protocol and sha(path) != protocol[name]:
            raise ValueError("active authorization or release bytes changed")
    if helper.fingerprint(WT) != CORE_FINGERPRINT or helper.fingerprint(SOURCE) != CORE_FINGERPRINT:
        raise ValueError("scientific source drift")
    for name, expected in protocol.get("pins", {}).items():
        if sha(name) != expected:
            raise ValueError("pinned runner/data input drift")


def _seed_config(seed):
    path = PROPOSAL / f"seed-{seed}.disabled-config.json"
    base = read(path)
    if (base["optimization"]["seed"] != seed
            or base["fit_rates"] != list(RATES)
            or base["budgets"]["max_solver_calls"] != 0
            or base["budgets"]["max_llm_requests"] != 0
            or base["llm"]["enabled"] is not False):
        raise ValueError("disabled seed config differs")
    return base


def _historical_contexts():
    old_protocol = read(OLD / "protocol.json")
    selected = old_protocol["contexts"][:3]
    if len(selected) != 3:
        raise ValueError("three independent historical Region contexts required")
    rows = []
    for item in selected:
        payload = Path(item["frozen_payload"])
        round_path = Path(item["round_path"])
        if sha(payload) != old_protocol["pins"][str(payload)] or sha(round_path) != old_protocol["pins"][str(round_path)]:
            raise ValueError("historical Region context bytes differ")
        rows.append({"payload": read(payload), "round_path": str(round_path),
                     "round_sha256": sha(round_path), "payload_sha256": sha(payload)})
    if len({r["payload"]["context_id"] for r in rows}) != 3:
        raise ValueError("historical contexts are not distinct")
    return rows


def _phase(spec, budget, protocol, *, worker, deadline=None):
    _input_integrity(protocol)
    deadline = min(budget.deadline - 15., deadline or budget.deadline - 15.)
    intent = {**spec, "source_root": str(SOURCE), "source": CORE_FINGERPRINT,
              "source_commit": protocol["head"],
              "protocol_sha": sha(EVIDENCE / "live-protocol.json"),
              "deadline": deadline, "output": str(OUTPUT / spec["label"])}
    if spec["kind"] not in ("gate_minimal", "gate_historical"):
        intent["base_config"] = _seed_config(spec["seed"])
    result = helper.supervise(worker, intent, budget, deadline=deadline,
        metadata=EVIDENCE / (spec["label"] + "-owned.json"),
        integrity_check=lambda: _input_integrity(protocol))
    if read(EVIDENCE / (spec["label"] + "-owned.json"))["owned_tree_stopped"] is not True:
        raise RuntimeError("owned worker tree remains live")
    write(EVIDENCE / (spec["label"] + "-result.json"), result)
    print(json.dumps({"phase": spec["label"], "status": result.get("status"),
                      "passed": result.get("passed"), "BO_rounds": result.get("BO_rounds"),
                      "costs": budget.counts()}, ensure_ascii=False), flush=True)
    return result


def execute():
    """Run only a separately frozen, software-released protocol."""
    import et_three_arm_validation_worker as worker_module

    live_path = EVIDENCE / "live-protocol.json"
    approval_path = EVIDENCE / "approval.json"
    release_path = EVIDENCE / "software-release.json"
    if not live_path.is_file() or not approval_path.is_file() or not release_path.is_file():
        raise ValueError("software release or approved frozen live protocol missing")
    protocol = load_protocol(live_path)
    approval, release = read(approval_path), read(release_path)
    protocol_sha = sha(live_path)
    targeted = release.get("targeted_counts", {})
    full = release.get("full_counts", {})
    boundary = release.get("boundary", {})
    if (approval.get("approved") is not True or approval.get("protocol_sha256") != protocol_sha
            or approval.get("limits") != CAPS or approval.get("plan_commit") != PLAN_COMMIT
            or release.get("targeted_exit_code") != 0
            or release.get("full_exit_code") != 0
            or targeted.get("tests", 0) < 16 or full.get("tests", 0) < 1600
            or any(group.get(key) != 0 for group in (targeted, full)
                   for key in ("failures", "errors", "skipped"))
            or boundary.get("network_attempts") != 0
            or boundary.get("battery_solve_attempts") != 0
            or release.get("source_unchanged_during_run") is not True
            or release.get("protected_unchanged_during_run") is not True
            or release.get("source_fingerprint") != CORE_FINGERPRINT):
        raise ValueError("approval, software release or budget differs")
    protocol = {**protocol, "_launch_sha256": protocol_sha,
                "_release_sha256": sha(release_path),
                "_approval_sha256": sha(approval_path)}
    _input_integrity(protocol)
    if OUTPUT.exists() or (EVIDENCE / "budget-journal.jsonl").exists():
        raise ValueError("live experiment already claimed; no implicit restart")
    credential = read_credential()
    os.environ["LLMBO_OPENCODE_API_KEY"] = credential
    del credential
    OUTPUT.mkdir(parents=True, exist_ok=False)
    budget = new_budget(EVIDENCE / "budget-journal.jsonl", protocol_sha=protocol_sha)
    result = {"status": "failed", "protocol_sha256": protocol_sha,
              "cases": [], "initialization": [], "gate": [], "limits": CAPS}
    try:
        with helper.keep_awake(OUTPUT / "wake.json"):
            budget.begin("diagnostic")
            diagnostic = _phase({"kind": "gate_minimal", "label": "gate-minimal",
                "solve_cap": 0, "timeout_s": 120.}, budget, protocol,
                worker=worker_module.run_worker,
                deadline=min(budget.deadline - 15., time.monotonic() + 135.))
            result["gate"].append(diagnostic)
            if not (diagnostic.get("passed") and diagnostic.get("complete")
                    and diagnostic.get("wire_verified")):
                raise RuntimeError("minimal API gate failed")
            if CANDIDATE_GATE:
                diagnostic = _phase({"kind": "gate_candidate", "seed": SEEDS[0],
                    "label": "gate-candidate", "solve_cap": 0, "timeout_s": 120.},
                    budget, protocol, worker=worker_module.run_worker,
                    deadline=min(budget.deadline - 15., time.monotonic() + 135.))
                result["gate"].append(diagnostic)
                if not (diagnostic.get("passed") and diagnostic.get("complete")
                        and diagnostic.get("wire_verified")
                        and diagnostic.get("candidate_count", 0) >= 8):
                    raise RuntimeError("candidate-only WarmStart API gate failed")
            contexts = _historical_contexts()
            for index, item in enumerate(contexts):
                diagnostic = _phase({"kind": "gate_historical", "label": f"gate-context-{index}",
                    "solve_cap": 0, "timeout_s": 120., **item}, budget, protocol,
                    worker=worker_module.run_worker,
                    deadline=min(budget.deadline - 15., time.monotonic() + 135.))
                result["gate"].append(diagnostic)
                if not (diagnostic.get("passed") and diagnostic.get("complete")
                        and diagnostic.get("wire_verified")):
                    raise RuntimeError("complete historical Region gate failed")
            if not any(row.get("effect", {}).get("tilt_applied") for row in result["gate"][1:]):
                raise RuntimeError("Region gate produced no nonzero tilt")
            budget.finish(True)

            budget.begin("initialization")
            initial = {}
            for plan in protocol["seed_plans"]:
                seed = plan["seed"]
                bo = _phase({"kind": "numeric_initialization", "arm": "bo",
                    "seed": seed, "label": f"seed-{seed}-numeric-init", "solve_cap": 16,
                    "coordinates": plan["BO_initialization"]["parameters"]},
                    budget, protocol, worker=worker_module.run_worker)
                warm = _phase({"kind": "warmstart_initialization", "arm": "warmstart_only",
                    "seed": seed, "label": f"seed-{seed}-warmstart-init", "solve_cap": 32},
                    budget, protocol, worker=worker_module.run_worker)
                for row in (bo, warm):
                    if not row.get("audit_passed") or row.get("selected_count") != 8:
                        raise RuntimeError("initialization lacks eight audited real pairs")
                initial[seed] = {"bo": bo, "warmstart": warm}
                result["initialization"].append({"seed": seed, "bo": bo, "warmstart": warm})
            budget.finish(True)

            budget.begin("main")
            failure_streak = 0
            by_seed = {seed: {} for seed in SEEDS}
            for case in cases(protocol):
                seed, arm = case["seed"], case["arm"]
                init = initial[seed]["bo" if arm == "bo" else "warmstart"]
                plan_ref = {"path": init["plan_path"], "sha256": init["plan_file_sha256"],
                            "origin_run_id": init["run_directory"], "costs": init["costs"]}
                row = _phase({"kind": "arm", "arm": arm, "seed": seed,
                    "label": f"seed-{seed}-{arm}", "solve_cap": 100,
                    "initial": plan_ref,
                    "initial_failure_streak": failure_streak if arm == "full_llmbo_mo" else 0},
                    budget, protocol, worker=worker_module.run_worker)
                if not row.get("audit_passed") or row.get("BO_rounds") != 50:
                    raise RuntimeError("formal case incomplete or audit failed")
                if arm == "full_llmbo_mo":
                    failure_streak = row["request_failure_streak"]
                by_seed[seed][arm] = row
                check_case_consistency(by_seed[seed])
                result["cases"].append(row)
            budget.finish(True)
            result["status"] = "completed"
    except Exception as exc:
        result.update(status="failed", error_type=type(exc).__name__)
        if budget.state()["phase"] is not None:
            budget.finish(False)
    result.update(ended_utc=datetime.now(timezone.utc).isoformat(),
                  costs=budget.counts(), finished_phases=budget.state()["finished"])
    write(EVIDENCE / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--protocol", default=str(PROPOSAL / "protocol-proposal.json"))
    args = parser.parse_args()
    result = execute() if args.execute else dry_run(args.protocol)
    print(json.dumps({k: v for k, v in result.items()
                      if k not in ("cases", "initialization", "gate")}, ensure_ascii=False))
    return 0 if result.get("dry_run") or result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
