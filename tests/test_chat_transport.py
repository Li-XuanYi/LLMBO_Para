from __future__ import annotations

from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from llmbo_para.llm import ChatCompletionsTransport, HttpJsonTransport, NoRedirect, LLMClient
from llmbo_para.config import parameter_space_from_config
from llmbo_para.runstore import RunStore
from llmbo_para.synthetic import synthetic_config
from llmbo_para.workflow import run_experiment


class Response:
    status = 200
    def __init__(self, content, *, finish="stop"):
        self.body = json.dumps({"model": "reported-test-model", "choices": [{"finish_reason": finish, "message": {"content": content}}],
                                "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode()
    def read(self, count):
        return self.body[:count]
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class ChatTransportTests(unittest.TestCase):
    endpoint = "https://api.example.test/v1/chat/completions"
    environment = {"LLMBO_TEST_API_KEY": "test-credential-do-not-persist", "OPENBLAS_NUM_THREADS": "1",
                   "MKL_NUM_THREADS": "1", "OMP_NUM_THREADS": "1"}

    def transport(self, **kwargs):
        return ChatCompletionsTransport(self.endpoint, "LLMBO_TEST_API_KEY", model="requested-test-model",
                                        max_tokens=512, json_mode=True, **kwargs)

    def test_messages_decoding_and_bounded_request(self):
        sent = []
        class Opener:
            def open(self, request, **kwargs):
                sent.append(request)
                return Response('{"candidates":[]}')
        with patch.dict("os.environ", self.environment), patch("llmbo_para.llm.build_opener", return_value=Opener()):
            result = self.transport().post({"task": "warm_start", "instructions": "Return JSON only", "bounds": [[0, 1]]})
        self.assertEqual(result, {"candidates": []})
        wire = json.loads(sent[0].data)
        self.assertEqual(wire["model"], "requested-test-model")
        self.assertEqual([row["role"] for row in wire["messages"]], ["system", "user"])
        self.assertEqual(wire["max_tokens"], 512)
        self.assertEqual(wire["response_format"], {"type": "json_object"})
        self.assertFalse(wire["stream"])
        self.assertEqual(sent[0].get_header("User-agent"), "LLMBO-Para/1")
        self.assertNotIn("test-credential", sent[0].data.decode())

    def test_opencode_session_identifies_archived_run_without_archiving_authentication(self):
        sent = []
        class Opener:
            def open(self, request, **kwargs):
                sent.append(request)
                return Response('{"candidates":[]}')
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder, patch.dict("os.environ", self.environment), \
             patch("llmbo_para.llm.build_opener", return_value=Opener()):
            store = RunStore(Path(folder), {"run_kind": "test"}, command="OpenCode session regression")
            transport = ChatCompletionsTransport("https://opencode.ai/zen/go/v1/chat/completions", "LLMBO_TEST_API_KEY",
                model="deepseek-v4.1-flash", max_tokens=512, json_mode=True, run_store=store)
            transport.post({"task": "warm_start", "instructions": "Return JSON"})
            expected = "llmbo-para-" + store.path.name
            self.assertEqual(sent[0].get_header("X-opencode-session"), expected)
            archived = json.loads((store.path/"http/warm_start.request.json").read_text())
            self.assertEqual(archived["headers"]["x-opencode-session"], expected)
            self.assertNotIn("test-credential-do-not-persist", json.dumps(archived))

    def test_truncated_and_non_object_output_are_rejected(self):
        for response in (Response('{"candidates":[]}', finish="length"), Response("[]"), Response("not JSON")):
            class Opener:
                def open(self, *args, **kwargs):
                    return response
            with self.subTest(response=response), patch.dict("os.environ", self.environment), patch("llmbo_para.llm.build_opener", return_value=Opener()):
                with self.assertRaisesRegex(ValueError, "strict JSON"):
                    self.transport().post({"task": "warm_start", "instructions": "Return JSON"})

    def test_http_error_is_archived_without_authentication_value(self):
        class Opener:
            def open(self, *args, **kwargs):
                raise HTTPError(ChatTransportTests.endpoint, 503, "unavailable", {},
                                BytesIO(b'{"error":{"code":"model_not_found","message":"test-credential-do-not-persist"}}'))
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = RunStore(Path(folder), {"run_kind": "test"}, command="mock HTTP privacy test")
            with patch.dict("os.environ", self.environment), patch("llmbo_para.llm.build_opener", return_value=Opener()):
                with self.assertRaisesRegex(RuntimeError, "503"):
                    self.transport(run_store=store).post({"task": "warm_start", "instructions": "Return JSON"})
            error = json.loads((store.path/"http/warm_start.error.json").read_text())
            self.assertEqual(error["provider_response"]["error"]["code"], "model_not_found")
            self.assertEqual(error["provider_response"]["error"]["message"], "[REDACTED]")
            for file in (store.path/"http").glob("*.json"):
                self.assertNotIn("test-credential-do-not-persist", file.read_text())

    def test_redirects_and_inline_authentication_are_refused(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example"))
        with self.assertRaises(ValueError):
            self.transport().post({"task": "warm_start", "instructions": "Return JSON", "api_key": "placeholder"})

    def test_unsupported_settings_fail_before_request(self):
        with self.assertRaises(ValueError):
            ChatCompletionsTransport(self.endpoint, "ENV", model="x", max_tokens=0, json_mode=True)
        with self.assertRaises(ValueError):
            ChatCompletionsTransport("https://api.example.test/", "ENV", model="x", max_tokens=32, json_mode=True)

    def test_invalid_group_fallback_has_explicit_rejection_diagnostics(self):
        space = parameter_space_from_config(synthetic_config(5))
        names = [spec.name for spec in space.specs]
        sent = []
        class GroupTransport:
            def post(self, payload):
                sent.append(payload)
                return {"groups": {"0.5C": [], "1C": names, "2C": ["unknown parameter"], "3C": [names[2]]}}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = RunStore(Path(folder), {"run_kind": "test"}, command="group rejection diagnostics regression")
            groups = LLMClient(GroupTransport(), run_store=store).parameter_groups(space, [])
            self.assertEqual(groups["1C"], ())
            self.assertEqual(groups["2C"], ())
            self.assertEqual(groups["3C"], (names[2],))
            diagnostic = json.loads((store.path/"llm/rate_parameter_groups.validation.json").read_text())
            self.assertFalse(diagnostic["valid_response"])
            self.assertEqual(diagnostic["invalid_rates"], ["1C", "2C"])
            self.assertEqual(diagnostic["rates"]["1C"]["reason"], "all_six_parameters_not_a_subset")
            self.assertEqual(diagnostic["rates"]["0.5C"]["status"], "abstained")
        self.assertEqual(sent[0]["group_constraints"]["maximum_nonempty_group_size"], 5)
        self.assertTrue(sent[0]["group_constraints"]["allow_empty_abstention"])

    def test_explicit_empty_groups_are_valid_abstentions(self):
        space = parameter_space_from_config(synthetic_config(5))
        class GroupTransport:
            def post(self, payload):
                return {"groups": {rate: [] for rate in payload["rates"]}}
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            store = RunStore(Path(folder), {"run_kind": "test"}, command="valid group abstention regression")
            groups = LLMClient(GroupTransport(), run_store=store).parameter_groups(space, [])
            self.assertTrue(all(group == () for group in groups.values()))
            diagnostic = json.loads((store.path/"llm/rate_parameter_groups.validation.json").read_text())
            self.assertTrue(diagnostic["valid_response"])
            self.assertEqual(diagnostic["invalid_rates"], [])
            self.assertTrue(all(item["status"] == "abstained" for item in diagnostic["rates"].values()))

    def test_full_workflow_uses_exactly_two_chat_calls_without_raw_series(self):
        calls = []
        first = [0.35, 0.55, 1e-15, 1e-14, 40, 70]
        second = [0.65, 0.30, 1e-13, 1e-15, 150, 20]
        class Opener:
            def open(self, request, **kwargs):
                wire = json.loads(request.data)
                task = json.loads(wire["messages"][1]["content"])
                calls.append(task)
                if task["task"] == "warm_start":
                    return Response(json.dumps({"candidates": [{"parameters": first}, {"parameters": second}]}))
                return Response(json.dumps({"groups": {r: [task["parameter_order"][2]] for r in task["rates"]}}))
        config = synthetic_config(5)
        config["optimization"].update(warm_start_llm_points=2, sobol_points=2, llm_enabled=True,
                                      candidate_pool_size=8, composite_ei_draws=8, gp_sweeps=1)
        config["llm"].update(transport="openai_chat_completions", endpoint=self.endpoint, model="requested-test-model",
                             api_key_env="LLMBO_TEST_API_KEY", max_tokens=512, json_mode=True)
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder, patch.dict("os.environ", self.environment), patch("llmbo_para.llm.build_opener", return_value=Opener()):
            result = run_experiment(config, Path(folder))
            self.assertTrue(result["audit_passed"])
            self.assertEqual(result["candidate_completed"], 5)
            self.assertEqual(result["rate_solve_attempts"], 20)
            run = Path(result["run_directory"])
            self.assertEqual(json.loads((run/"initial-set.json").read_text())["sources"][:2], ["llm", "llm"])
            self.assertEqual(len(list((run/"http").glob("*.response.json"))), 2)
            self.assertEqual(len(list((run/"http").glob("*.request.json"))), 2)
            diagnostic = json.loads((run/"llm/rate_parameter_groups.validation.json").read_text())
            self.assertTrue(diagnostic["valid_response"])
        self.assertEqual([row["task"] for row in calls], ["warm_start", "rate_parameter_groups"])
        self.assertNotIn("input-series", json.dumps(calls))
        self.assertNotIn("voltage_v", json.dumps(calls))


if __name__ == "__main__":
    unittest.main()
