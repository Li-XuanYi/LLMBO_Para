"""Cold, source-pinned worker for the 5-seed/3-arm electrothermal study.

This module orchestrates existing evaluation/BO/LLM code. It contains no new
surrogate, acquisition, Region, or physical-model formula.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, replace
import json
import math
import os
from pathlib import Path
import shutil
import sys
import time


ARMS = ("bo", "warmstart_only", "full_llmbo_mo")
KINDS = ("numeric_initialization", "warmstart_initialization", "arm")
ENDPOINT = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"
ENV_NAME = "LLMBO_OPENCODE_API_KEY"


class TrialIncompleteEvaluation(RuntimeError):
    """A strict trial stops after persisting an incomplete evaluation."""


class TrialInvalidReply(RuntimeError):
    """A strict trial stops after recording a malformed WarmStart reply."""


def install_trial_failure_guard(store):
    """Persist the diagnostic and its charges before stopping the worker."""
    original = store.save_evaluation

    def checked(result, **kwargs):
        relative = original(result, **kwargs)
        if not result.complete_pair_valid:
            raise TrialIncompleteEvaluation("trial evaluation is incomplete")
        return relative

    store.save_evaluation = checked


def install_trial_reply_guard(store):
    """Record an invalid reply once and do not request another response."""
    original = store.ledger.record

    def checked(event):
        ident = original(event)
        if event.get("kind") == "screening_rejected" and event.get("reason") == "invalid_reply":
            raise TrialInvalidReply("trial WarmStart reply is invalid")
        return ident

    store.ledger.record = checked


def execution_pin(root: Path, spec: dict) -> dict:
    pin = {"source_root": str(root), "source_fingerprint": spec["source"],
           "source_commit": spec.get("source_commit")}
    if "stop_on_failure" in spec:
        if type(spec["stop_on_failure"]) is not bool:
            raise ValueError("trial failure policy must be boolean")
        pin["stop_on_failure"] = spec["stop_on_failure"]
    return pin


def make_worker_evaluator(evaluator_type, space, backend, *, fit_rates, spec):
    """Preserve older evaluator interfaces unless the strict trial is requested."""
    from inspect import signature

    strict = spec.get("stop_on_failure", False)
    if type(strict) is not bool:
        raise ValueError("trial failure policy must be boolean")
    options = {"fit_rates": fit_rates, "max_rate_attempts": 1}
    if strict:
        if "stop_on_failure" not in signature(evaluator_type).parameters:
            raise ValueError("strict trial policy is unsupported by this source")
        options["stop_on_failure"] = True
    return evaluator_type(space, backend, **options)


def config_for(base: dict, *, kind: str, arm: str, seed: int,
               remaining: float, initial_plan: dict | None) -> dict:
    """Derive an isolated worker config without changing scientific settings."""
    if kind not in KINDS or arm not in ARMS:
        raise ValueError("unknown three-arm phase or arm")
    if kind == "numeric_initialization" and arm != "bo":
        raise ValueError("numeric initialization belongs only to BO")
    if kind == "warmstart_initialization" and arm != "warmstart_only":
        raise ValueError("WarmStart initialization belongs to the shared LLM pair")
    if kind == "arm" and not initial_plan:
        raise ValueError("formal arm requires a signed initial plan")
    if kind != "arm" and initial_plan is not None:
        raise ValueError("initialization cannot import an older plan")
    if type(seed) is not int or seed < 0 or not math.isfinite(remaining) or remaining <= 0:
        raise ValueError("invalid seed or remaining time")
    config = deepcopy(base)
    opt = config["optimization"]
    opt["seed"] = seed
    opt["mode"] = "parego" if arm == "bo" else arm
    opt["total_candidate_budget"] = 58 if kind == "arm" else 8
    opt["initial_count"] = 8
    opt.pop("initial_plan", None)
    if initial_plan is not None:
        opt["initial_plan"] = deepcopy(initial_plan)
    dfn, api = {
        "numeric_initialization": (16, 0),
        "warmstart_initialization": (32, 3),
        "arm": (100, 50 if arm == "full_llmbo_mo" else 0),
    }[kind]
    config["budgets"] = {"max_solver_calls": dfn, "max_llm_requests": api,
                         "wall_clock_s": float(remaining)}
    config["llm"]["enabled"] = bool(api)
    if config["fit_rates"] != ["0.5C", "1C"]:
        raise ValueError("frozen fitting rates differ")
    return config


def _write(path, value):
    from lgbo_real_gain_worker import write
    write(path, value)


def _summarize_initial(store, prepared, plan, *, kind, count, pool_count):
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.runstore import sha256_file

    path = store.path / "initial-plan.json"
    result = {"status": "completed", "kind": kind, "selected_count": count,
              "complete_pool_count": pool_count, "plan_path": str(path),
              "plan_file_sha256": sha256_file(path), "plan_sha256": plan.plan_sha256,
              "ordered_records": [record.to_dict() for record in plan.records],
              "costs": store.ledger.summary(), "run_directory": str(store.path)}
    store.write_json("electrothermal-summary.json", result)
    store.finish("completed", result)
    audit = audit_electrothermal_run(store.path, deep=True)
    _write(store.path / "audit.json", audit)
    if not audit["passed"]:
        raise ValueError("initialization deep audit failed")
    result["audit_passed"] = True
    return result


def initialize_numeric(spec, prepared, store, budget, backend):
    """Eight preregistered Sobol points, in their original sequence."""
    from inspect import signature
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_provenance import write_initial_plan, load_initial_plan

    coordinates = spec["coordinates"]
    if len(coordinates) != 8 or len({tuple(p) for p in coordinates}) != 8:
        raise ValueError("BO initialization requires eight distinct frozen points")
    evaluator = make_worker_evaluator(ElectrothermalEvaluator, prepared.space, backend,
        fit_rates=prepared.dataset.fit_rates, spec=spec)
    records = []
    for point in coordinates:
        prepared.space.validate(point)
        budget.require_candidate(0 if spec.get("software_fixture") else 2)
        record = evaluator.evaluate(point, prepared.dataset)
        store.save_evaluation(record, phase="numeric_initialization")
        records.append(replace(record, signatures=asdict(prepared.signatures)))
    if any(not record.complete_pair_valid for record in records):
        raise ValueError("BO initialization has an incomplete real objective pair")
    path = store.path / "initial-plan.json"
    # Parego accepts a numerical plan without a WarmStart-selection claim.
    write_initial_plan(path, records, signatures=prepared.signatures)
    selection_rule = prepared.config['optimization']['warmstart'].get('selection_rule', 'pareto_maximin_v1')
    if type(selection_rule) is not str or selection_rule not in ('pareto_maximin_v1', 'pareto_core_spacefill_v2'):
        raise ValueError('invalid warmstart.selection_rule')
    plan_options = {'space': prepared.space, 'dataset': prepared.dataset,
                    'signatures': prepared.signatures}
    if 'expected_selection_rule' in signature(load_initial_plan).parameters:
        plan_options['expected_selection_rule'] = selection_rule
    elif selection_rule != 'pareto_maximin_v1':
        raise ValueError('old source only supports pareto_maximin_v1')
    plan = load_initial_plan(path, **plan_options)
    return _summarize_initial(store, prepared, plan,
                              kind="numeric_sobol", count=8, pool_count=8)


def initialize_warmstart(spec, prepared, store, budget, backend):
    """Use the production WarmStart generator and its auditable selector."""
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from lgbo_real_gain_worker import _controller

    evaluator = make_worker_evaluator(ElectrothermalEvaluator, prepared.space, backend,
        fit_rates=prepared.dataset.fit_rates, spec=spec)
    controller = _controller(prepared, budget, software_fixture=spec.get("software_fixture", False))
    if spec.get("software_fixture"):
        from llmbo_para.sobol import Sobol6

        class MockProposer:
            def post(self, payload):
                points = []
                generator = Sobol6(spec["seed"] + 1000)
                while len(points) < 16:
                    try:
                        point = prepared.space.denormalize(generator.draw(1)[0])
                    except ValueError:
                        continue
                    points.append({"parameters": dict(zip(
                        (item.name for item in prepared.space.specs), point))})
                if payload.get("warmstart_wire_format") == "candidate_only_v1":
                    return {"candidates": points}
                return {key: payload[key] for key in
                        ("schema_version", "parameter_profile", "fit_rates", "signatures")} | {
                            "candidates": points}

        controller.transport = MockProposer()
    controller.evaluator = evaluator
    controller.solver_budget = budget
    plan = controller.generate_warmstart(prepared, store=store,
                                         budgets=prepared.config["budgets"])
    selection = json.loads((store.path / "warmstart-selection.json").read_text(encoding="utf-8"))
    pool_count = sum(r["complete_pair_valid"] for r in plan.history_evidence["screening_records"])
    if not 8 <= pool_count <= 16 or len(plan.records) != 8:
        raise ValueError("insufficient or oversized WarmStart pool")
    if selection["status"] != "completed":
        raise ValueError("WarmStart selection incomplete")
    return _summarize_initial(store, prepared, plan,
                              kind="llm_warmstart", count=8, pool_count=pool_count)


def run_arm(spec, prepared, store, budget, backend):
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.mo_optimizer import MOOptimizer
    from llmbo_para.runstore import sha256_file, digest_value
    from lgbo_real_gain_worker import _controller, independent_hv, representative, read
    from run_region_transport_validation import RequestFailureStreak

    source = Path(spec["initial"]["path"])
    destination = store.path / "inputs/initial-plan.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if sha256_file(destination) != spec["initial"]["sha256"]:
        raise ValueError("copied initial plan differs")
    evaluator = make_worker_evaluator(ElectrothermalEvaluator, prepared.space, backend,
        fit_rates=prepared.dataset.fit_rates, spec=spec)
    controller = None
    streak = RequestFailureStreak(spec.get("initial_failure_streak", 0))
    if spec["arm"] == "full_llmbo_mo":
        controller = _controller(prepared, budget, software_fixture=spec.get("software_fixture", False))
        request = controller.request

        def checked(payload, **options):
            response = request(payload, **options)
            streak.observe(controller.last_request_outcome or {})
            return response

        controller.request = checked
    optimizer = MOOptimizer(prepared.space, evaluator, prepared.dataset, store,
        prepared.config["optimization"], initial_plan=prepared.initial_plan,
        llm_controller=controller, execution_budget=budget)
    result = optimizer.optimize(58)
    if result["BO_rounds"] != 50 or result["candidate_evaluations"] != 58:
        raise ValueError("formal arm did not complete 50 new rounds")
    result["initial_plan_sha256"] = prepared.initial_plan.plan_sha256
    history = prepared.initial_plan.history_evidence
    result["initialization_cost_attribution"] = {
        "origin_run_id": history["origin_run_id"] if history else None,
        "historical_costs": history["costs"] if history else None,
        "included_in_current_costs": False,
        "plan_sha256": prepared.initial_plan.plan_sha256,
        "status": "verified_history" if history else "not_applicable_or_not_supplied",
    }
    store.write_json("electrothermal-summary.json", result)
    store.finish("completed", result)
    audit = audit_electrothermal_run(store.path, deep=True)
    _write(store.path / "audit.json", audit)
    if not audit["passed"]:
        raise ValueError("formal arm deep audit failed")
    records = {r["evaluation_id"]: r for r in
               [read(p) for p in sorted((store.path / "electrothermal-evaluations").glob("*.json"))]}
    front = representative(result["pareto"], normalize=prepared.space.normalize)
    true_pairs = [r["objectives"] for r in records.values() if r["complete_pair_valid"]]
    scales = prepared.config["optimization"]["objective_scales"]
    hv = independent_hv([[u / scales[0], t / scales[1]] for u, t in true_pairs],
                        prepared.config["optimization"]["hv_reference"])
    if not math.isclose(hv, result["HV"], rel_tol=1e-12, abs_tol=1e-10):
        raise ValueError("independent HV differs")
    rounds = [read(p) for p in sorted((store.path / "mo-rounds").glob("*.json"))]
    if len(rounds) != 50:
        raise ValueError("archived round count differs")
    exported = []
    for event in rounds:
        record = records[event["evaluation_id"]]
        region = event.get("region") or {}
        exported.append({"ordinal": event["context"]["ordinal"],
                         "weight": event["context"]["scalarization"]["weights"],
                         "evaluation_id": record["evaluation_id"],
                         "objectives": record["objectives"],
                         "complete_pair_valid": record["complete_pair_valid"],
                         "cached": event["feedback"]["cached"],
                         "region": {key: region.get(key) for key in
                                    ("selection_changed", "tilt_applied", "fallback_reason", "request_outcome")},
                         "rates": [{key: row[key] for key in
                                    ("rate", "voltage", "cell_temperature", "solution_id")}
                                   for row in record["rates"]]})
    first = rounds[0]["context"]
    return {"status": "completed", "completed": True, "audit_passed": True,
            "seed": spec["seed"], "arm": spec["arm"], "BO_rounds": 50,
            "HV": hv, "F_U": front["objectives"][0], "F_T": front["objectives"][1],
            "representative": records[front["evaluation_id"]], "summary": result,
            "rounds": exported, "initial_file_sha": sha256_file(source),
            "parent_initialization_cost": spec["initial"]["costs"],
            "parent_initialization_origin": spec["initial"]["origin_run_id"],
            "first_numerical_context_sha": digest_value(
                {key: first[key] for key in ("scalarization", "gp_state", "pool")}),
            "source": prepared.signatures.source, "run_directory": str(store.path),
            "request_failure_streak": streak.count}


def _expected_chat(payload):
    from llmbo_para.electrothermal_region_wire import region_wire_payload
    wire = region_wire_payload(payload)
    compact = wire.get("region_wire_format") in ("compact_v1", "compact_action_v2")
    return {"model": MODEL,
            "messages": [
                {"role": "system", "content": wire["instructions"] +
                 "\nReturn exactly one JSON object matching the supplied response contract."},
                {"role": "user", "content": json.dumps(
                    {k: v for k, v in wire.items() if k != "instructions"},
                    ensure_ascii=False, allow_nan=False,
                    separators=(",", ":") if compact else None)}],
            "max_tokens": 8192, "stream": False,
            "response_format": {"type": "json_object"},
            "thinking": {"type": "disabled"}}


def _offline_chat_request_worker(spec, payload, run_path, connection):
    """Software-test socket leaf; never selected by a live protocol phase."""
    from unittest.mock import patch
    from llmbo_para.electrothermal_requests import _chat_request_worker

    class Reply:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, limit):
            return self.body[:limit]

    class Provider:
        def open(self, request, **kwargs):
            wire = json.loads(json.loads(request.data)["messages"][1]["content"])
            if wire.get("warmstart_wire_format") == "candidate_only_v1":
                formal = {"candidates": [{"parameters": {
                    spec["name"]: (spec["lower"] *
                        (spec["upper"] / spec["lower"]) ** (0.12 + 0.1 * i)
                        if spec["transform"] == "log10" else
                        spec["lower"] + (spec["upper"] - spec["lower"]) * (0.12 + 0.1 * i))
                    for spec in wire["parameters"]}} for i in range(8)]}
            else:
                formal = ({"request_id": wire["request_id"],
                       "region": {"kind": "region", "lb": [0.3] * 6,
                                  "ub": [0.8] * 6, "confidence": 0.65}}
                      if "request_id" in wire else {"ok": True})
            reply = Reply()
            reply.body = json.dumps({"model": MODEL, "choices": [
                {"finish_reason": "stop", "message": {"content": json.dumps(formal)}}]}).encode()
            return reply

    with patch("llmbo_para.llm.build_opener", return_value=Provider()):
        _chat_request_worker(spec, payload, run_path, connection)


def gate(spec, connection, budget):
    """One bounded actual request; historical contexts never become BO data."""
    from llmbo_para.electrothermal_requests import BoundedChatCompletionsTransport
    from llmbo_para.electrothermal_region_wire import decode_region_wire
    from llmbo_para.runstore import RunStore
    from lgbo_real_gain_worker import read
    from run_lgbo_real_gain import check_payload, digest
    from run_region_transport_validation import validate_region_effect

    kind = spec["kind"]
    prepared = None
    if kind == "gate_candidate":
        from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
        from llmbo_para.electrothermal_payloads import build_warmstart_payload
        config = deepcopy(spec["base_config"])
        if config["llm"].get("warmstart_wire_format") != "candidate_only_v1":
            raise ValueError("candidate gate needs candidate-only config")
        report, prepared = prepare_electrothermal_experiment(config,
            base_dir=Path(spec["source_root"]))
        if prepared is None:
            raise ValueError("candidate gate preparation failed: " + "; ".join(report["errors"]))
        payload = build_warmstart_payload(prepared=prepared, history=[])
        payload["artifact_task"] = "warm_start_electrothermal_request_a"
    else:
        payload = (spec["payload"] if kind == "gate_historical" else {
            "task": "warm_start_electrothermal", "artifact_task": "api_transport_minimal",
            "instructions": "This is only a transport probe. Return exactly the JSON object {\"ok\":true}.",
            "response_contract": {"type": "object", "properties": {"ok": {"const": True}},
                                  "required": ["ok"], "additionalProperties": False}})
    check_payload(payload)
    store = RunStore(spec["output"], {"kind": kind, "not_new_BO_data": True,
        "source": spec["source"], "protocol_sha256": spec["protocol_sha"]},
        command="bounded OpenCode contract and frozen Region influence gate")
    store.write_json("frozen-payload.json", payload)
    expected = _expected_chat(payload)
    store.write_json("expected-body.json", expected)
    transport = BoundedChatCompletionsTransport(
        ENDPOINT, ENV_NAME, model=MODEL, max_tokens=8192, json_mode=True,
        thinking="disabled", timeout_s=spec["timeout_s"], run_store=store)
    if spec.get("software_fixture"):
        transport._request_worker = lambda: _offline_chat_request_worker
    result = {"passed": False, "complete": False, "kind": kind,
              "run_directory": str(store.path)}
    try:
        if kind == "gate_historical":
            from llmbo_para.runstore import sha256_file
            if sha256_file(spec["round_path"]) != spec["round_sha256"]:
                raise ValueError("historical frozen GP round changed")
        budget.charge_api(spec["label"])
        formal = transport.post(payload, deadline=budget.deadline)
        task = payload.get("artifact_task", payload["task"])
        sent = read(store.path / "http" / (task + ".request.json"))
        raw = read(store.path / "http" / (task + ".response.json"))
        choice = raw["choices"][0]
        if choice["finish_reason"] != "stop":
            raise ValueError("incomplete Chat reply")
        decoded = json.loads(choice["message"]["content"])
        restored = decode_region_wire(decoded, payload)
        diagnostic = transport.last_request_diagnostic or {}
        if (sent["endpoint"] != ENDPOINT or digest(sent["body"]) != digest(expected)
                or digest(formal) != digest(restored)
                or diagnostic.get("http_status") != 200
                or diagnostic.get("http_request_started") is not True):
            raise ValueError("raw response/body/formal Region mismatch")
        if kind == "gate_minimal":
            if formal != {"ok": True}:
                raise ValueError("minimal transport contract differs")
        elif kind == "gate_candidate":
            from llmbo_para.electrothermal_warmstart_wire import (
                freeze_warmstart_request, bind_warmstart_response,
                decode_candidate_only_reply)
            request = freeze_warmstart_request(payload, run_id=store.run_id, ordinal=0)
            bound = bind_warmstart_response(request, formal, store=store,
                                             transport_status="completed")
            proposals = decode_candidate_only_reply(bound, prepared=prepared,
                                                    expected_request=request)
            names = {p.name for p in prepared.space.specs}
            unique = set()
            for proposal in proposals:
                if (type(proposal) is not dict or set(proposal) != {"parameters"}
                        or type(proposal["parameters"]) is not dict
                        or set(proposal["parameters"]) != names):
                    raise ValueError("candidate gate contains an invalid named proposal")
                point = prepared.space.validate(
                    [proposal["parameters"][p.name] for p in prepared.space.specs])
                unique.add(tuple(point))
            if len(unique) < 8:
                raise ValueError("candidate gate returned fewer than eight unique points")
            result["candidate_count"] = len(unique)
        else:
            result["effect"] = validate_region_effect(
                payload, formal, Path(spec["round_path"]))
            result["context_id"] = payload["context_id"]
        result.update(passed=True, complete=True, wire_verified=True,
                      diagnostic=diagnostic, response_model=raw.get("model"))
        store.write_json("validation-proof.json", result)
        store.finish("completed", result)
    except Exception as exc:
        result.update(error_type=type(exc).__name__,
                      diagnostic=transport.last_request_diagnostic or {})
        store.finish("failed", result)
    _write(Path(spec["output"]) / "worker-result.json", result)
    connection.send(("result", result))
    return result


def run_worker(spec, connection):
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS"):
        os.environ[name] = "1"
    os.environ["PYBAMM_DISABLE_TELEMETRY"] = "true"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    root = Path(spec["source_root"]).resolve()
    if any(name == "llmbo_para" or name.startswith("llmbo_para.") for name in sys.modules):
        raise RuntimeError("worker scientific source namespace was not cold")
    sys.path.insert(0, str(root / "src"))
    store = None
    try:
        from llmbo_para.electrothermal_provenance import source_fingerprint
        if source_fingerprint(root) != spec["source"]:
            raise ValueError("worker scientific source bytes differ")
        from lgbo_real_gain_worker import RPCBudget, _attach_api_charges
        budget = RPCBudget(connection, deadline=spec["deadline"],
                           maximum=spec["solve_cap"], prefix=spec["label"])
        if spec["kind"] in ("gate_minimal", "gate_historical", "gate_candidate"):
            gate(spec, connection, budget)
            return
        from llmbo_para.electrothermal_workflow import (
            prepare_electrothermal_experiment, make_electrothermal_backend)
        from llmbo_para.electrothermal_store import ElectrothermalRunStore

        config = config_for(spec["base_config"], kind=spec["kind"],
            arm=spec["arm"], seed=spec["seed"],
            remaining=max(.001, budget.deadline - time.monotonic()),
            initial_plan=spec.get("initial"))
        if spec.get("software_fixture"):
            config["model"]["provider"] = "software"
            config["run_kind"] = "synthetic_software"
            config["llm"]["enabled"] = False
            config["budgets"]["max_solver_calls"] = 0
            config["budgets"]["max_llm_requests"] = 0
        report, prepared = prepare_electrothermal_experiment(config, base_dir=root)
        if prepared is None:
            raise ValueError("source-specific preparation failed: " + "; ".join(report["errors"]))
        backend = make_electrothermal_backend(config, budget=budget)
        store = ElectrothermalRunStore(spec["output"], config,
            dataset=prepared.dataset, signatures=prepared.signatures,
            command="electrothermal three-arm validation")
        pin = execution_pin(root, spec)
        if spec.get("stop_on_failure", False):
            install_trial_failure_guard(store)
            install_trial_reply_guard(store)
        store.write_json("source-execution-pin.json", pin)
        _attach_api_charges(store, budget)
        if spec["kind"] == "numeric_initialization":
            result = initialize_numeric(spec, prepared, store, budget, backend)
        elif spec["kind"] == "warmstart_initialization":
            result = initialize_warmstart(spec, prepared, store, budget, backend)
        else:
            result = run_arm(spec, prepared, store, budget, backend)
        _write(Path(spec["output"]) / "worker-result.json", result)
        connection.send(("result", result))
    except Exception as exc:
        failure = {"status": "failed", "error_type": type(exc).__name__,
                   "label": spec["label"]}
        if store is not None and not (store.path / "terminal.json").exists():
            store.finish("failed", failure)
        _write(Path(spec["output"]) / "worker-failure.json", failure)
        connection.send(("error", type(exc).__name__))
    finally:
        connection.close()
