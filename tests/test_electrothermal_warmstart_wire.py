import json
from dataclasses import replace

import pytest

from electrothermal_fixtures import et_config


def _prepared(tmp_path):
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    cfg = et_config()
    cfg["llm"]["warmstart_wire_format"] = "candidate_only_v1"
    report, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    assert report["ready"]
    return cfg, prepared


def _candidate(prepared):
    return {
        "parameters": dict(
            zip(
                (spec.name for spec in prepared.space.specs),
                prepared.space.denormalize([0.5] * 6),
            )
        )
    }


def test_candidate_only_payload_and_config_signature_are_explicit(tmp_path):
    from llmbo_para.electrothermal_payloads import build_warmstart_payload
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment

    old_cfg = et_config()
    _, old = prepare_electrothermal_experiment(old_cfg, base_dir=tmp_path)
    cfg, prepared = _prepared(tmp_path)
    payload = build_warmstart_payload(prepared=prepared, history=[])
    assert set(payload["response_contract"]["required"]) == {"candidates"}
    assert "signatures" in payload
    assert "exact task signatures" not in payload["instructions"]
    assert old.signatures.config != prepared.signatures.config
    assert "warmstart_wire_format" not in old_cfg["llm"]
    bad = et_config()
    bad["llm"]["warmstart_wire_format"] = "arbitrary"
    report, rejected = prepare_electrothermal_experiment(bad, base_dir=tmp_path)
    assert rejected is None and not report["ready"]


def test_bound_candidate_reply_rejects_stale_or_tampered_identity(tmp_path):
    from llmbo_para.electrothermal_payloads import build_warmstart_payload
    from llmbo_para.electrothermal_warmstart_wire import (
        freeze_warmstart_request,
        bind_warmstart_response,
        decode_candidate_only_reply,
    )
    from llmbo_para.electrothermal_store import ElectrothermalRunStore

    cfg, prepared = _prepared(tmp_path)
    store = ElectrothermalRunStore(
        tmp_path, cfg, dataset=prepared.dataset, signatures=prepared.signatures,
        command="candidate wire test"
    )
    payload = build_warmstart_payload(prepared=prepared, history=[])
    payload["artifact_task"] = "warm_start_electrothermal_request_a"
    frozen = freeze_warmstart_request(payload, run_id=store.run_id, ordinal=0)
    response = {"candidates": [_candidate(prepared)]}
    bound = bind_warmstart_response(
        frozen, response, store=store, transport_status="mock"
    )
    assert decode_candidate_only_reply(
        bound, prepared=prepared, expected_request=frozen
    ) == response["candidates"]

    with pytest.raises(ValueError):
        decode_candidate_only_reply(
            replace(bound, response={"candidates": []}),
            prepared=prepared, expected_request=frozen
        )
    other = freeze_warmstart_request(payload, run_id="different-run", ordinal=0)
    with pytest.raises(ValueError):
        decode_candidate_only_reply(bound, prepared=prepared, expected_request=other)
    with pytest.raises(ValueError):
        decode_candidate_only_reply(
            replace(bound, response={"candidates": [[1, 2, 3, 4, 5, 6]]}),
            prepared=prepared, expected_request=frozen
        )


def test_candidate_only_reply_obeys_configured_count_limit(tmp_path):
    from llmbo_para.electrothermal_payloads import build_warmstart_payload
    from llmbo_para.electrothermal_warmstart_wire import (
        freeze_warmstart_request, bind_warmstart_response,
        decode_candidate_only_reply,
    )
    from llmbo_para.electrothermal_store import ElectrothermalRunStore

    cfg, prepared = _prepared(tmp_path)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
                                   signatures=prepared.signatures, command="count test")
    payload = build_warmstart_payload(prepared=prepared, history=[])
    payload["artifact_task"] = "warm_start_electrothermal_request_a"
    request = freeze_warmstart_request(payload, run_id=store.run_id, ordinal=0)
    response = {"candidates": [_candidate(prepared)] *
                (cfg["optimization"]["warmstart"]["max_candidates"] + 1)}
    bound = bind_warmstart_response(request, response, store=store,
                                    transport_status="mock")
    with pytest.raises(ValueError, match="candidate"):
        decode_candidate_only_reply(bound, prepared=prepared,
                                    expected_request=request)


def test_completed_reply_must_match_archived_http_envelope(tmp_path):
    from llmbo_para.electrothermal_payloads import build_warmstart_payload
    from llmbo_para.electrothermal_warmstart_wire import (
        freeze_warmstart_request, bind_warmstart_response,
        decode_candidate_only_reply,
    )
    from llmbo_para.electrothermal_store import ElectrothermalRunStore

    cfg, prepared = _prepared(tmp_path)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
                                   signatures=prepared.signatures, command="http binding test")
    payload = build_warmstart_payload(prepared=prepared, history=[])
    payload["artifact_task"] = "warm_start_electrothermal_request_a"
    request = freeze_warmstart_request(payload, run_id=store.run_id, ordinal=0)
    response = {"candidates": [_candidate(prepared)]}
    with pytest.raises(ValueError, match="envelope missing"):
        bind_warmstart_response(request, response, store=store,
                                transport_status="completed")
    store.write_json("http/warm_start_electrothermal_request_a.response.json",
                     {"choices": [{"message": {"content": json.dumps(response)}}]})
    bound = bind_warmstart_response(request, response, store=store,
                                    transport_status="completed")
    assert decode_candidate_only_reply(bound, prepared=prepared,
                                       expected_request=request) == response["candidates"]


def test_legacy_full_reply_still_requires_exact_signatures(tmp_path):
    from llmbo_para.electrothermal_llm import validate_warmstart_response
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    from dataclasses import asdict

    _, prepared = prepare_electrothermal_experiment(et_config(), base_dir=tmp_path)
    valid = {
        "schema_version": 2,
        "parameter_profile": prepared.space.profile,
        "fit_rates": list(prepared.dataset.fit_rates),
        "signatures": asdict(prepared.signatures),
        "candidates": [_candidate(prepared)],
    }
    assert len(validate_warmstart_response(valid, prepared=prepared)) == 1
    bad = json.loads(json.dumps(valid))
    bad["signatures"]["data"] = "0" * 64
    with pytest.raises(ValueError, match="stale or mismatched"):
        validate_warmstart_response(bad, prepared=prepared)


def test_candidate_only_controller_generates_signed_initial_plan(tmp_path):
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_evaluation import ElectrothermalEvaluator
    from llmbo_para.electrothermal_store import ElectrothermalRunStore
    from llmbo_para.electrothermal_synthetic import SyntheticElectrothermalSimulator

    cfg, prepared = _prepared(tmp_path)
    cfg["optimization"]["warmstart"].update(pool_size=2, max_requests=1,
                                                 max_evaluations=2)
    # Re-prepare after the explicit budget change so signatures stay current.
    from llmbo_para.electrothermal_workflow import prepare_electrothermal_experiment
    _, prepared = prepare_electrothermal_experiment(cfg, base_dir=tmp_path)
    store = ElectrothermalRunStore(tmp_path, cfg, dataset=prepared.dataset,
                                   signatures=prepared.signatures, command="candidate test")

    class CandidateTransport:
        def post(self, payload):
            assert payload["warmstart_wire_format"] == "candidate_only_v1"
            return {"candidates": [
                {"parameters": dict(zip((s.name for s in prepared.space.specs),
                                         prepared.space.denormalize([x] * 6)))}
                for x in (0.25, 0.75)]}

    controller = ElectrothermalLLMController(
        transport=CandidateTransport(), is_mock=True,
        evaluator=ElectrothermalEvaluator(prepared.space,
                                          SyntheticElectrothermalSimulator(),
                                          fit_rates=prepared.dataset.fit_rates))
    plan = controller.generate_warmstart(prepared, store=store, budgets=cfg["budgets"])
    assert len(plan.records) == 2
    assert (store.path / "llm/000000.warmstart-binding.json").is_file()


def test_deep_audit_detects_bound_reply_mutation(tmp_path):
    from pathlib import Path
    from llmbo_para.electrothermal_audit import audit_electrothermal_run
    from llmbo_para.electrothermal_llm import ElectrothermalLLMController
    from llmbo_para.electrothermal_workflow import run_electrothermal_experiment

    cfg, prepared = _prepared(tmp_path)
    cfg["optimization"]["mode"] = "warmstart_only"

    class CandidateTransport:
        def post(self, payload):
            return {"candidates": [
                {"parameters": dict(zip((s.name for s in prepared.space.specs),
                                         prepared.space.denormalize([x] * 6)))}
                for x in (0.2, 0.4, 0.6, 0.8)]}

    result = run_electrothermal_experiment(
        cfg, tmp_path, base_dir=tmp_path,
        llm_controller=ElectrothermalLLMController(
            transport=CandidateTransport(), is_mock=True))
    root = Path(result["run_directory"])
    assert audit_electrothermal_run(root, deep=True)["passed"]
    receipt = root / "llm/000000.warmstart-binding.json"
    value = json.loads(receipt.read_text(encoding="utf8"))
    value["response_sha256"] = "0" * 64
    receipt.write_text(json.dumps(value), encoding="utf8")
    assert not audit_electrothermal_run(root, deep=True)["passed"]
