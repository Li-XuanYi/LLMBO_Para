"""Exercise the actual chat wire contract without making HTTP requests."""
from importlib import resources
from io import BytesIO
import json
from urllib.error import HTTPError

from llmbo_para.llm import ChatCompletionsTransport


class ChatResponse:
    status = 200

    def read(self, count):
        content = {"region": {"kind": "none", "coordinate_space": "normalized",
                              "confidence": 0.0, "reason": "insufficient evidence"}}
        wire = {"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(content)}}]}
        return json.dumps(wire).encode("utf8")[:count]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def region_payload():
    return {
        "task": "region_preference_electrothermal",
        "instructions": resources.files("llmbo_para").joinpath(
            "prompts/region_preference_electrothermal.txt").read_text(encoding="utf8"),
        "context": {"weights": [.8, .2], "objective_scales": [.1, 1.]},
    }


def install_provider_boundary(monkeypatch):
    """Model the provider's documented rejection at the network boundary only."""
    sent = []

    class Provider:
        def open(self, request, **kwargs):
            wire = json.loads(request.data)
            sent.append(wire)
            if (wire.get("response_format") == {"type": "json_object"}
                    and not any("json" in row["content"].lower()
                                for row in wire["messages"])):
                error = {"error": {"message": "messages must contain the word json "
                                  "to use response_format json_object"}}
                raise HTTPError(request.full_url, 400, "invalid JSON-mode messages", {},
                                BytesIO(json.dumps(error).encode("utf8")))
            return ChatResponse()

    monkeypatch.setenv("LLMBO_REGION_WIRE_TEST_CREDENTIAL", "test-region-wire-credential")
    monkeypatch.setattr("llmbo_para.llm.build_opener", lambda *args: Provider())
    return sent


def test_real_region_prompt_is_accepted_by_json_object_provider(monkeypatch):
    sent = install_provider_boundary(monkeypatch)
    transport = ChatCompletionsTransport(
        "https://provider.example.test/v1/chat/completions",
        "LLMBO_REGION_WIRE_TEST_CREDENTIAL", model="test-model", max_tokens=512,
        json_mode=True, timeout_s=1.)

    result = transport.post(region_payload())

    assert result["region"]["kind"] == "none"
    assert len(sent) == 1
    assert sent[0]["response_format"] == {"type": "json_object"}
    assert any("json" in row["content"].lower() for row in sent[0]["messages"])


def test_json_mode_off_preserves_legacy_wire_without_response_format(monkeypatch):
    sent = install_provider_boundary(monkeypatch)
    payload = region_payload()
    transport = ChatCompletionsTransport(
        "https://provider.example.test/v1/chat/completions",
        "LLMBO_REGION_WIRE_TEST_CREDENTIAL", model="test-model", max_tokens=512,
        json_mode=False, timeout_s=1.)

    result = transport.post(payload)

    assert result["region"]["kind"] == "none"
    assert len(sent) == 1
    assert "response_format" not in sent[0]
    assert sent[0]["messages"][0]["content"] == payload["instructions"]
