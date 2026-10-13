"""Compact DFN WarmStart prompt contract and injection smoke."""
from importlib import resources

from llmbo_para.config import parameter_space_from_config
from llmbo_para.llm import LLMClient
from llmbo_para.synthetic import synthetic_config


def test_compact_prompt_contains_mechanisms_history_and_output_contract():
    prompt = resources.files("llmbo_para").joinpath("prompts/warm_start.txt").read_text(encoding="utf-8")
    assert prompt.startswith("You are an expert in lithium-ion battery electrochemistry")
    assert 180 <= len(prompt.split()) <= 300
    for required in ("DFN/P2D", "0.5C", "1C", "2C", "3C", "RMSE", "Capacity balance",
                     "diffusion", "conductivity", "evaluation_feedback",
                     "requested_count", "parameter_order", "candidates"):
        assert required in prompt
    for unwanted in ("仅作软先验", "不得虚构", "不能替代仿真", "不要强行规定"):
        assert unwanted not in prompt


def test_compact_prompt_is_sent_with_real_context_and_strict_vector_contract():
    space = parameter_space_from_config(synthetic_config())
    proposal = list(space.denormalize((0.5,) * 6))
    context = {"initialization_recovery": {"evaluation_feedback": {
        "schema_version": 1, "records": [], "total_evaluated": 0,
        "necessary_conditions_only": True}}}
    class Transport:
        def post(self, payload):
            self.payload = payload
            return {"candidates": [{"parameters": proposal}]}
    transport = Transport()
    result = LLMClient(transport, context=context).warm_start(space, 1)
    assert result == (tuple(proposal),)
    assert transport.payload["context"] == context
    assert "evaluation_feedback" in transport.payload["instructions"]
    assert transport.payload["requested_count"] == 1
    assert len(transport.payload["bounds"]) == len(result[0]) == 6
