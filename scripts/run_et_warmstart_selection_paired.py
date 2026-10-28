"""Source-pinned v1/v2 WarmStart selection study; dry run by default.

The live supervisor is added only after its software and provenance gates pass.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import time


WT = Path("C:/Users/aa133/.codex/worktrees/electrothermal-refactor/LLMBO_Para")
MAIN = Path("D:/Users/aa133/Desktop/LLMBO_Para")
BASE = MAIN / "bo-repair-work/20261017_et_implementation"
PROPOSAL = BASE / "warmstart-v1-v2-paired-20261027/proposal/protocol-proposal.json"
OUTPUT = MAIN / "runs/w27"
MOCK_OUTPUT = MAIN / "runs/w27mock"
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
EVIDENCE = PROPOSAL.parent.parent
RUNTIME_FILES = (
    "scripts/run_et_warmstart_selection_paired.py",
    "scripts/et_warmstart_selection_paired_worker.py",
    "scripts/analyze_et_warmstart_selection_paired.py",
    "scripts/et_three_arm_validation_worker.py",
    "scripts/run_lgbo_real_gain.py",
    "scripts/lgbo_real_gain_worker.py",
)
_ACTIVE_RELEASE: dict | None = None


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


def _seed_config(protocol: dict, seed: int) -> dict:
    item = protocol["configs"][str(seed)]
    path = Path(item["path"])
    if _sha(path) != item["sha256"]:
        raise ValueError("seed config changed")
    return json.loads(path.read_text(encoding="utf-8"))


def _phase(spec: dict, budget: PairedBudget, protocol: dict, *, root: Path,
           source_root: Path, software_fixture: bool) -> dict:
    """Run one source-pinned, owned worker with the parent's durable budget."""
    import et_three_arm_validation_worker as worker
    import run_lgbo_real_gain as helper

    validate_protocol(protocol)
    if _ACTIVE_RELEASE is not None:
        _check_release_pins(_ACTIVE_RELEASE)
    deadline = budget.deadline - 15.
    if time.monotonic() >= deadline:
        raise TimeoutError("paired deadline exhausted before phase")
    label = spec["label"]
    output = root / label
    output.mkdir(parents=True, exist_ok=False)
    override = spec.get("base_config_override")
    intent = {**{key: value for key, value in spec.items() if key != "base_config_override"},
              "output": str(output), "source_root": str(source_root),
              "source": helper.fingerprint(source_root), "deadline": deadline,
              "base_config": override if override is not None else _seed_config(protocol, spec["seed"]),
              "software_fixture": software_fixture}
    metadata = root / (label + "-owned.json")
    result = helper.supervise(worker.run_worker, intent, budget, deadline=deadline,
                              metadata=metadata,
                              integrity_check=lambda: (
                                  validate_protocol(protocol),
                                  _check_release_pins(_ACTIVE_RELEASE) if _ACTIVE_RELEASE else None))
    if json.loads(metadata.read_text(encoding="utf-8"))["owned_tree_stopped"] is not True:
        raise RuntimeError("owned worker tree remains live")
    (root / (label + "-result.json")).write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False),
        encoding="utf-8")
    return result


def _plan_configs(protocol: dict, seed: int, *, software_fixture: bool) -> dict:
    import et_three_arm_validation_worker as worker

    base = _seed_config(protocol, seed)
    v1 = worker.config_for(base, kind="warmstart_initialization",
                           arm="warmstart_only", seed=seed,
                           remaining=max(1., min(3600., CAPS["wall_clock_s"])),
                           initial_plan=None)
    if software_fixture:
        v1["model"]["provider"] = "software"
        v1["run_kind"] = "synthetic_software"
        v1["llm"]["enabled"] = False
        v1["budgets"]["max_solver_calls"] = 0
        v1["budgets"]["max_llm_requests"] = 0
    v2 = deepcopy(v1)
    v2["optimization"]["warmstart"]["selection_rule"] = "pareto_core_spacefill_v2"
    return {"v1": v1, "v2": v2}


def run_seed_pair(protocol: dict, *, seed: int, budget: PairedBudget,
                  root: Path, source_root: Path, software_fixture: bool = False) -> dict:
    """One 16-point pool, two signed plans, and two ordinary 50-round BO arms."""
    import sys
    import et_warmstart_selection_paired_worker as plans_module

    validate_protocol(protocol)
    if seed not in RUN_ORDER:
        raise ValueError("seed not in frozen run order")
    root = Path(root)
    source_root = Path(source_root)
    if source_root.resolve() != WT.resolve():
        raise ValueError("unexpected source checkout")
    source_package = str(source_root / "src")
    if source_package not in sys.path:
        sys.path.insert(0, source_package)
    pair = {"seed": seed, "status": "incomplete", "cases": {},
            "metric_space": {"objective_scales": [0.1, 1.0],
                             "hv_reference": [10.0, 10.0]}}
    try:
        budget.begin(f"pool-{seed}")
        pool = _phase({"kind": "warmstart_initialization", "arm": "warmstart_only",
                       "seed": seed, "label": f"seed-{seed}-pool",
                       "solve_cap": 0 if software_fixture else 32},
                      budget, protocol, root=root, source_root=source_root,
                      software_fixture=software_fixture)
        if (pool.get("audit_passed") is not True
                or pool.get("complete_pool_count") != 16
                or pool.get("selected_count") != 8):
            raise ValueError("shared real candidate pool incomplete")
        pair["pool"] = pool
        pair["plans"] = plans_module.derive_paired_plans(
            pool["run_directory"],
            configs=_plan_configs(protocol, seed, software_fixture=software_fixture),
            out=root / f"seed-{seed}-plans")
        budget.finish(True)
        for rule in _arm_order()[str(seed)]:
            budget.begin(f"arm-{seed}-{rule}")
            plan = pair["plans"][rule]
            initial = {"path": plan["path"], "sha256": plan["sha256"],
                       "origin_run_id": pool["run_directory"],
                       "costs": pair["plans"]["shared_costs"]}
            base = _seed_config(protocol, seed)
            base["optimization"]["warmstart"]["selection_rule"] = (
                "pareto_maximin_v1" if rule == "v1" else "pareto_core_spacefill_v2")
            row = _phase({"kind": "arm", "arm": "warmstart_only", "seed": seed,
                          "label": f"seed-{seed}-{rule}",
                          "solve_cap": 0 if software_fixture else 100,
                          "initial": initial, "base_config_override": base},
                         budget, protocol, root=root, source_root=source_root,
                         software_fixture=software_fixture)
            if (row.get("audit_passed") is not True or row.get("BO_rounds") != 50
                    or row.get("initial_file_sha") != plan["sha256"]
                    or row.get("summary", {}).get("API_calls") != 0):
                raise ValueError("formal paired arm incomplete")
            row["arm"] = rule
            pair["cases"][rule] = row
            budget.finish(True)
        pair["status"] = "completed"
        return pair
    except BaseException:
        if budget.state()["phase"] is not None:
            budget.finish(False)
        raise


def _write_json(path: Path, value: dict) -> None:
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(target)


def _check_release_pins(release: dict) -> None:
    if release is None:
        raise ValueError("software release absent")
    for name, expected in release["source_pins"].items():
        if _sha(WT / name) != expected:
            raise ValueError("released source changed: " + name)
    if _sha(EVIDENCE / "software-release.json") != release["release_sha256"]:
        raise ValueError("software release file changed")


def _live_preflight(evidence_dir: Path, output: Path) -> tuple[dict, dict]:
    if output.exists() or (evidence_dir / "budget.jsonl").exists():
        raise ValueError("live experiment already claimed")
    release_path = evidence_dir / "software-release.json"
    approval_path = evidence_dir / "approval.json"
    if not release_path.is_file() or not approval_path.is_file():
        raise ValueError("software release and local approval record required")
    protocol = load_protocol()
    release = json.loads(release_path.read_text(encoding="utf-8"))
    approval = json.loads(approval_path.read_text(encoding="utf-8"))
    if (approval.get("approved") is not True
            or approval.get("plan_commit") != PLAN_COMMIT
            or approval.get("protocol_sha256") != _sha(PROPOSAL)
            or approval.get("limits") != CAPS
            or release.get("status") != "passed"
            or release.get("protocol_sha256") != _sha(PROPOSAL)
            or release.get("limits") != CAPS
            or release.get("head") != subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=WT, text=True).strip()
            or subprocess.check_output(["git", "status", "--short"],
                                       cwd=WT, text=True).strip()
            or set(release.get("source_pins", {})) !=
            (set(SOURCE_FILES) | set(RUNTIME_FILES) |
             {path.relative_to(WT).as_posix() for path in
              (WT / "src/llmbo_para").rglob("*.py")})):
        raise ValueError("approval, source status or software release differs")
    for name, expected in release["source_pins"].items():
        if (not _hex64(expected) or _sha(WT / name) != expected
                or _sha(evidence_dir / "source-snapshot" / name) != expected):
            raise ValueError("released source pin differs")
    for gate in ("targeted", "full", "mock"):
        item = release.get("gates", {}).get(gate, {})
        path = Path(item.get("result_path", ""))
        if not path.is_file() or _sha(path) != item.get("sha256"):
            raise ValueError("released software gate missing or changed")
        result = json.loads(path.read_text(encoding="utf-8"))
        if gate == "mock":
            if (result.get("status") != "completed" or result.get("cases") != 10
                    or result.get("rounds") != 500 or result.get("API") != 0
                    or result.get("DFN") != 0):
                raise ValueError("mock rehearsal gate failed")
        else:
            counts = result.get("counts", {})
            if (result.get("exit_code") != 0 or counts.get("tests", 0) <
                    (1600 if gate == "full" else 24)
                    or any(counts.get(key) != 0 for key in ("failures", "errors", "skipped"))):
                raise ValueError("software regression gate failed")
            if gate == "full" and (result.get("source_unchanged") is not True
                                   or result.get("boundary", {}).get("network_attempts") != 0
                                   or result.get("boundary", {}).get("battery_solve_attempts") != 0):
                raise ValueError("full regression source or offline boundary differs")
    release["release_sha256"] = _sha(release_path)
    return protocol, release


def run_mock_rehearsal(*, output: Path) -> dict:
    """Run the entire frozen schedule with software fixtures and no real calls."""
    import analyze_et_warmstart_selection_paired as analyzer

    protocol = load_protocol()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    budget = PairedBudget.start(output / "budget.jsonl", protocol_sha=_sha(PROPOSAL))
    pairs = []
    for seed in RUN_ORDER:
        pair = run_seed_pair(protocol, seed=seed, budget=budget, root=output,
                             source_root=WT, software_fixture=True)
        analyzer.analyze_seed(pair, protocol)
        pairs.append(pair)
    result = {"status": "completed", "pairs": pairs, "costs": budget.counts()}
    _write_json(output / "result.json", result)
    report = analyzer.analyze_pair(output / "result.json", protocol)
    if (report["status"] != "completed" or budget.state()["closed"] is not True
            or budget.counts() != {"DFN": 0, "API": 0}):
        raise ValueError("five-seed mock closure failed")
    _write_json(output / "analysis.json", report)
    summary = {"status": "completed", "cases": 10, "rounds": 500,
               "API": 0, "DFN": 0}
    _write_json(output / "summary.json", summary)
    return summary


def execute_live(*, evidence_dir: Path = EVIDENCE, output: Path = OUTPUT) -> dict:
    """Start one approved, released live trial; never implicitly resume it."""
    global _ACTIVE_RELEASE
    import analyze_et_warmstart_selection_paired as analyzer
    import run_lgbo_real_gain as helper

    evidence_dir, output = Path(evidence_dir), Path(output)
    protocol, release = _live_preflight(evidence_dir, output)
    credential = read_credential()
    os.environ["LLMBO_OPENCODE_API_KEY"] = credential
    del credential
    output.mkdir(parents=True, exist_ok=False)
    budget = PairedBudget.start(evidence_dir / "budget.jsonl",
                                protocol_sha=_sha(PROPOSAL))
    _ACTIVE_RELEASE = release if evidence_dir == EVIDENCE else None
    result = {"status": "incomplete", "protocol_sha256": _sha(PROPOSAL),
              "release_sha256": release["release_sha256"],
              "limits": CAPS, "pairs": []}
    try:
        with helper.keep_awake(output / "wake.json"):
            for seed in RUN_ORDER:
                pair = run_seed_pair(protocol, seed=seed, budget=budget, root=output,
                                     source_root=WT)
                analyzer.analyze_seed(pair, protocol)
                result["pairs"].append(pair)
                result["costs"] = budget.counts()
                _write_json(output / "result.json", result)
                print(json.dumps({"seed": seed, "completed_pairs": len(result["pairs"]),
                                  "costs": result["costs"]}), flush=True)
            result["status"] = "completed"
            result["costs"] = budget.counts()
            _write_json(output / "result.json", result)
            report = analyzer.analyze_pair(output / "result.json", protocol)
            _write_json(output / "analysis.json", report)
            if report["status"] != "completed" or budget.state()["closed"] is not True:
                raise ValueError("final independent paired audit incomplete")
    except BaseException as exc:
        result.update(status="failed", error_type=type(exc).__name__,
                      costs=budget.counts(), finished_phases=budget.state()["finished"])
        if budget.state()["phase"] is not None:
            budget.finish(False)
        _write_json(output / "result.json", result)
    finally:
        _ACTIVE_RELEASE = None
        os.environ.pop("LLMBO_OPENCODE_API_KEY", None)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--mock-rehearsal", action="store_true")
    parser.add_argument("--mock-output", type=Path, default=MOCK_OUTPUT)
    args = parser.parse_args()
    if sum((args.dry_run, args.execute, args.mock_rehearsal)) != 1:
        parser.error("choose exactly one of --dry-run or --execute")
    result = (execute_live() if args.execute else
              run_mock_rehearsal(output=args.mock_output)
              if args.mock_rehearsal else dry_run())
    print(json.dumps({"status": result.get("status", "dry-run"),
                      "costs": result.get("costs", {"API": 0, "DFN": 0}),
                      "completed_pairs": len(result.get("pairs", []))},
                     ensure_ascii=False), flush=True)
    return 0 if args.dry_run or result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
