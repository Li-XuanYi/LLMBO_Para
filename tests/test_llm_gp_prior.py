import json
import math
import pytest
from llmbo_para.llm_gp_prior import make_prior, validate_response, BASE_MU, request_priors
from llmbo_para.metrics import RATE_ORDER
from llmbo_para.llm import LLMClient
from llmbo_para.llm_gp_prior import build_payload
from test_bo_repair import setup_problem


def response():
    return {"priors": {r: {"log_lengthscale_shifts": [0.] * 6, "rationale": "Insufficient evidence.",
                          "evidence_ids": ["initial-0"], "uncertainty": "high"} for r in RATE_ORDER}}


def test_neutral_prior_equivalent_and_explicit():
    result = validate_response(response(), {"initial-0"})
    assert all(not row["informative"] for row in result.values())
    assert all(row["lengthscale_prior"] == make_prior() for row in result.values())
    assert make_prior()["mu"] == [BASE_MU] * 6


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), math.log(2) + 1e-8, "0"])
def test_reject_invalid_or_excessive_shift(bad):
    value = response(); value["priors"]["3C"]["log_lengthscale_shifts"][0] = bad
    with pytest.raises(ValueError):
        validate_response(value, {"initial-0"})


def test_reject_missing_dimension_rate_and_unknown_evidence():
    for mutation in (lambda d: d["priors"].pop("2C"),
                     lambda d: d["priors"]["1C"]["log_lengthscale_shifts"].pop(),
                     lambda d: d["priors"]["3C"].update(evidence_ids=["future-8"])):
        value = response(); mutation(value)
        with pytest.raises(ValueError):
            validate_response(value, {"initial-0"})


def test_nonzero_prior_is_bounded_location_change_only():
    value = response(); value["priors"]["3C"]["log_lengthscale_shifts"][0] = -math.log(2)
    row = validate_response(value, {"initial-0"})["3C"]
    assert row["informative"]
    assert row["lengthscale_prior"]["sigma"] == make_prior()["sigma"]
    assert math.exp(row["lengthscale_prior"]["mu"][0] - BASE_MU) == pytest.approx(.5)


def sample_records(space):
    return [("initial-0", {"parameters": space.denormalize([.5]*6), "valid": True,
        "arbitrary_private_field": "PRIVATE_CANARY", "rates": [{"rate": r, "valid": True, "rmse_v": .05,
          "simulation_time_s": [123], "aligned_voltage_v": [456],
          "residual_summary": {"rmse_v": .05, "private": "PRIVATE_CANARY"}} for r in RATE_ORDER]})]


def test_summary_whitelist_excludes_curves_and_unapproved_fields():
    _, space, _ = setup_problem()
    payload = build_payload(space, sample_records(space))
    wire = json.dumps(payload)
    assert "PRIVATE_CANARY" not in wire
    assert "simulation_time_s" not in wire and "aligned_voltage_v" not in wire
    assert payload["training_summary"]["valid_count_by_rate"] == dict.fromkeys(RATE_ORDER, 1)


def test_neutral_is_accepted_without_extra_request_and_bad_schema_repairs_once():
    _, space, _ = setup_problem()
    class Fake:
        def __init__(self, bad=False): self.calls = []; self.bad = bad
        def post(self, payload):
            self.calls.append(payload)
            return {} if self.bad and len(self.calls) == 1 else response()
    for bad, expected in ((False, 1), (True, 2)):
        transport = Fake(bad)
        result = request_priors(LLMClient(transport), space, sample_records(space))
        assert len(transport.calls) == expected
        assert all(not row["informative"] for row in result.values())
        assert all("instructions" in p for p in transport.calls)
