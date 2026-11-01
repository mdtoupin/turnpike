import collections
import importlib.util
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("probe", Path(__file__).parents[1]/"tools"/"probe_providers.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class ContractTests(unittest.TestCase):
    def test_exact_versions(self):
        probe.validate_version("codex", "codex-cli 0.166.0")
        probe.validate_version("claude", "2.1.295 (Claude Code)")
        for provider, bad in (("codex", "codex-cli 0.166.01"), ("claude", "2.1.2950 (Claude Code)"),
                              ("codex", "unrelated 0.166.0"), ("claude", "")):
            with self.subTest(bad=bad), self.assertRaises(probe.ContractError):
                probe.validate_version(provider, bad)

    def test_subscription_environment_omits_paid_and_custom_overrides(self):
        with patch.dict(os.environ, {key: "must-not-inherit" for key in probe.API_ENV}):
            env = probe.subscription_env()
        self.assertTrue(all(key not in env for key in probe.API_ENV))

    def test_custom_codex_routes_are_rejected(self):
        probe.validate_codex_route({"chatgpt_base_url": "https://chatgpt.com/backend-api/"})
        for config in ({"model_provider": "custom"}, {"model_providers": {"openai": {"env_key": "PAID_KEY"}}},
                       {"chatgpt_base_url": "https://chatgpt.com.example.test/"},
                       {"chatgpt_base_url": "https://chatgpt.com/backend-api/?token=secret"}):
            with self.subTest(config=config), self.assertRaises(probe.ContractError):
                probe.validate_codex_route(config)

    def test_failures_are_diagnostic_not_retry_authorization(self):
        self.assertEqual(probe.error_kind({"code": 429}), "waiting_for_quota")
        self.assertEqual(probe.error_kind("token expired"), "waiting_for_auth")
        self.assertEqual(probe.error_kind("model_not_found"), "incompatible_provider")
        self.assertEqual(probe.error_kind("unknown"), "needs_attention")

    def test_claude_stream_invariants(self):
        model = "claude-opus-5-5"
        init = {"type": "system", "subtype": "init", "session_id": "one", "model": model,
                "apiKeySource": "none", "tools": []}
        final = {"type": "result", "session_id": "one", "modelUsage": {model: {}}}
        probe.validate_claude_stream([init, final], model)
        cases = ([init, final, final], [init, final, {"type": "late"}],
                 [init, {**final, "session_id": "two"}], [init, {**final, "modelUsage": {"other": {}}}],
                 [{**init, "apiKeySource": "env"}, final], [{**init, "tools": ["Bash"]}, final])
        for messages in cases:
            with self.subTest(messages=messages), self.assertRaises(probe.ContractError):
                probe.validate_claude_stream(messages, model)

    def test_expired_deadline_rejects_even_when_queue_has_events(self):
        rpc = probe.Rpc.__new__(probe.Rpc)
        rpc.queue = probe.queue.Queue()
        rpc.queue.put({"method": "noise"})
        with self.assertRaises(TimeoutError):
            rpc.receive(time.monotonic()-1)

    def test_flood_is_bounded(self):
        code = 'import json,sys\nfor line in sys.stdin:\n while True: print(json.dumps({"method":"unrelated"}),flush=True)'
        rpc = probe.Rpc([sys.executable, "-u", "-c", code], timeout=0.15)
        start = time.monotonic()
        try:
            with self.assertRaises((TimeoutError, probe.ContractError)):
                rpc.request("never-replies", {})
            self.assertLessEqual(len(rpc.pending), 4096)
        finally:
            rpc.close()
        self.assertLess(time.monotonic()-start, 12)

    def test_unsolicited_approval_is_denied_without_losing_response(self):
        code = '''import json,sys
r=json.loads(sys.stdin.readline())
print(json.dumps({"id":91,"method":"permission/request","params":{}}),flush=True)
denied=json.loads(sys.stdin.readline())
print(json.dumps({"id":r["id"],"result":{"denied":denied["id"]==91 and "error" in denied}}),flush=True)
'''
        rpc = probe.Rpc([sys.executable, "-u", "-c", code])
        try:
            self.assertEqual(rpc.request("check", {}), {"denied": True})
        finally:
            rpc.close()

    def test_malformed_provider_stdout_fails(self):
        rpc = probe.Rpc([sys.executable, "-u", "-c", 'import sys;sys.stdin.readline();print("not json",flush=True)'])
        try:
            with self.assertRaises(probe.ContractError):
                rpc.request("check", {})
        finally:
            rpc.close()

    def test_tool_activity_cannot_pass_inference_probe(self):
        class Fake:
            def notification(self, *args, **kwargs):
                return {"turn": {"id": "turn", "status": "completed"}}
            def request(self, *args):
                return {"thread": {"turns": [{"id": "turn", "items": [{"type": "commandExecution"}]}]}}
        with self.assertRaises(probe.ContractError):
            probe.wait_turn(Fake(), "thread", "turn")

    def test_interrupted_turn_items_are_inspected(self):
        class Fake:
            def request(self, *args):
                return {"thread": {"turns": [{"id": "turn", "status": "interrupted", "items": [{"type": "commandExecution"}]}]}}
        with self.assertRaises(probe.ContractError):
            probe.inspect_turn(Fake(), "thread", "turn")

    def test_submitted_turn_keeps_unknown_outcome_and_known_ids(self):
        observations = {}
        class Fake:
            def request(self, *args):
                return {"turn": {"id": "turn"}}
        probe.start_turn(Fake(), observations, {"threadId": "thread"})
        self.assertEqual(observations["inflight"], {"operation": "turn/start", "thread_id": "thread", "turn_id": "turn", "outcome": "unknown"})

    def test_claude_resume_failure_keeps_session_and_unknown_outcome(self):
        auth = SimpleNamespace(returncode=0, stdout='{"loggedIn":true,"authMethod":"claude.ai"}')
        nonce = "TP_0123456789ab"
        with patch.object(probe, "command", return_value=auth), patch.object(probe.uuid, "uuid4", return_value=SimpleNamespace(hex="0123456789ab")), \
             patch.object(probe, "claude_turn", side_effect=[({"session_id": "session"}, {"session_id": "session", "result": nonce}), TimeoutError("lost connection")]):
            with self.assertRaises(TimeoutError) as caught:
                probe.probe_claude(True, ".")
        self.assertEqual(caught.exception.observations["session_id"], "session")
        self.assertEqual(caught.exception.observations["inflight"]["operation"], "claude/resume")
        self.assertEqual(caught.exception.observations["inflight"]["outcome"], "unknown")


if __name__ == "__main__":
    unittest.main()
