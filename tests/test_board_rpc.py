from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
import io
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
import turnpike
import turnpike_rpc as rpc


class BoardRpcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="turnpike-rpc-test-")
        self.old_path = turnpike.DB_PATH
        turnpike.DB_PATH = Path(self.temp.name)/"bus.db"
        self.env = {**os.environ, "TURNPIKE_DB": str(turnpike.DB_PATH)}
        self.cli("create", "stable-slug", "--name", "Crimson-master", "--goal", "Test")

    def tearDown(self):
        turnpike.DB_PATH = self.old_path
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.check_output([sys.executable, str(ROOT/"turnpike.py"), *args], env=self.env, encoding="utf-8")

    def request(self, operation, **params):
        return {"version": 1, "request_id": str(uuid.uuid4()), "operation": operation, "params": params}

    def run_rpc(self, request):
        result = subprocess.run([sys.executable, str(ROOT/"turnpike.py"), "rpc", "--as", "codex"],
                                input=json.dumps(request, ensure_ascii=False)+"\n", capture_output=True,
                                text=True, encoding="utf-8", env=self.env, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def execute(self, operation, **params):
        return rpc.execute(self.request(operation, **params), "codex")

    def messages(self):
        return self.execute("messages", project="stable-slug")["result"]["messages"]

    def test_display_name_slug_and_id_resolve_to_same_room(self):
        for selector in ("stable-slug", "Crimson-master", "crimson-MASTER", 1):
            reply = self.execute("board", project=selector)
            self.assertTrue(reply["ok"], reply)
            self.assertEqual(reply["result"]["project"]["id"], 1)

    def test_ambiguous_display_names_require_stable_selector(self):
        self.cli("create", "other", "--name", "Crimson-master", "--goal", "Test")
        reply = self.execute("board", project="Crimson-master")
        self.assertEqual(reply["error"]["code"], "ambiguous_project")
        self.assertTrue(self.execute("board", project="stable-slug")["ok"])

    def test_lost_reply_retry_is_exact_and_does_not_duplicate_post(self):
        request = self.request("post", project="stable-slug", body="A note 🐇 with `shell` and $(text)")
        first = self.run_rpc(request)
        second = self.run_rpc(request)
        self.assertEqual(first, second)
        self.assertEqual(len(self.messages()), 1)
        self.assertIn("🐇", self.messages()[0]["body"])

    def test_concurrent_duplicate_posts_commit_once(self):
        request = self.request("post", project="stable-slug", body="One effect")
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(self.run_rpc, [request, request]))
        self.assertEqual(replies[0], replies[1])
        self.assertEqual(len(self.messages()), 1)

    def test_request_id_cannot_be_reused_for_different_content(self):
        request = self.request("post", project="stable-slug", body="First")
        self.assertTrue(rpc.execute(request, "codex")["ok"])
        request["params"]["body"] = "Changed"
        reply = rpc.execute(request, "codex")
        self.assertEqual(reply["error"]["code"], "idempotency_conflict")
        self.assertEqual(len(self.messages()), 1)

    def test_failed_dispatch_rolls_back_message_and_receipt(self):
        from unittest.mock import patch
        request = self.request("post", project="stable-slug", body="Rollback")
        original = rpc.dispatch
        def fail(con, actor, operation, params):
            original(con, actor, operation, params)
            raise rpc.RequestError("injected_failure", "Fail before commit")
        with patch.object(rpc, "dispatch", side_effect=fail):
            self.assertFalse(rpc.execute(request, "codex")["ok"])
        self.assertEqual(self.messages(), [])
        self.assertTrue(rpc.execute(request, "codex")["ok"])
        self.assertEqual(len(self.messages()), 1)

    def test_worker_inboxes_and_acknowledgments_are_independent(self):
        self.execute("post", project="stable-slug", body="Read me")
        a = self.execute("inbox", project="stable-slug", worker_id="worker-a")["result"]
        b = self.execute("inbox", project="stable-slug", worker_id="worker-b")["result"]
        self.assertEqual(a["messages"], b["messages"])
        self.assertEqual(a["acknowledged_id"], 0)
        self.assertTrue(self.execute("ack", project="stable-slug", worker_id="worker-a", through_id=a["delivered_id"])["ok"])
        self.assertEqual(self.execute("inbox", project="stable-slug", worker_id="worker-a")["result"]["messages"], [])
        self.assertEqual(len(self.execute("inbox", project="stable-slug", worker_id="worker-b")["result"]["messages"]), 1)
        denied = self.execute("ack", project="stable-slug", worker_id="worker-b", through_id=99999)
        self.assertEqual(denied["error"]["code"], "invalid_ack")

    def test_post_does_not_advance_legacy_or_worker_cursor(self):
        self.cli("pull", "stable-slug", "--as", "codex")
        con = turnpike.connect()
        before = [tuple(r) for r in con.execute("SELECT * FROM cursors")]
        con.close()
        self.execute("post", project="stable-slug", body="New independent delivery")
        con = turnpike.connect()
        self.assertEqual(before, [tuple(r) for r in con.execute("SELECT * FROM cursors")])
        con.close()

    def test_task_revision_detects_legacy_cli_edits(self):
        task = self.execute("task.create", project="stable-slug", title="New task")["result"]["task"]
        self.cli("task-update", str(task["id"]), "--detail", "Changed elsewhere", "--as", "codex")
        denied = self.execute("task.update", task_id=task["id"], expected_revision=task["revision"], changes={"status": "done"})
        self.assertEqual(denied["error"]["code"], "revision_conflict")

    def test_same_second_aba_cannot_restore_an_old_revision(self):
        with patch.object(turnpike, "now", return_value="2026-11-01T12:00:00Z"):
            original = self.execute("task.create", project="stable-slug", title="Stable")["result"]["task"]
            b = self.execute("task.update", task_id=original["id"], expected_revision=original["revision"], changes={"detail": "B"})["result"]["task"]
            a = self.execute("task.update", task_id=b["id"], expected_revision=b["revision"], changes={"detail": ""})["result"]["task"]
            self.assertEqual({k:v for k,v in a.items() if k!="revision"}, {k:v for k,v in original.items() if k!="revision"})
            denied = self.execute("task.update", task_id=a["id"], expected_revision=original["revision"], changes={"status": "done"})
            self.assertEqual(denied["error"]["code"], "revision_conflict")

    def test_numeric_project_ids_are_bounded_without_killing_session(self):
        for value in (-1, 2**63, 10**100):
            reply = self.run_rpc(self.request("board", project=value))
            self.assertEqual(reply["error"]["code"], "invalid_params")

    def test_truncated_reply_after_commit_retains_same_id_recovery(self):
        spec = importlib.util.spec_from_file_location("remote", ROOT/"tools"/"turnpike_remote.py")
        remote = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(remote)
        request = self.request("post", project="stable-slug", body="Accepted before output was lost")
        path = Path(self.temp.name)/"request.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        real_run = subprocess.run
        def transport(*args, **kwargs):
            accepted = real_run([sys.executable, str(ROOT/"turnpike.py"), "rpc", "--as", "codex"],
                                input=kwargs["input"], capture_output=True, text=True, encoding="utf-8", env=self.env)
            self.assertEqual(accepted.returncode, 0)
            return subprocess.CompletedProcess(args[0], 0, stdout='{"version":1,', stderr="")
        stdout = io.StringIO()
        with patch.object(sys, "argv", ["remote", "--host", "workstation", "--as", "codex", "--request", str(path)]), \
             patch.object(remote.subprocess, "run", side_effect=transport), redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            self.assertEqual(remote.main(), 3)
        reply = json.loads(stdout.getvalue())
        self.assertEqual(reply["request_id"], request["request_id"])
        self.assertEqual(reply["error"]["code"], "ssh_unknown_outcome")
        self.assertTrue(reply["error"]["retryable"])
        self.assertTrue(self.run_rpc(request)["ok"])
        self.assertEqual(len(self.messages()), 1)

    @unittest.skipUnless(os.name == "nt", "Windows installer")
    def test_installer_rejects_unicode_paths_before_copying(self):
        destination = Path(self.temp.name)/"cli-é"
        result = subprocess.run(["powershell", "-NoProfile", "-File", str(ROOT/"install-cli.ps1"),
                                 "-Destination", str(destination), "-PythonExecutable", sys.executable], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires ASCII paths", result.stderr)
        self.assertFalse(destination.exists())

    def test_task_update_status_and_history(self):
        task = self.execute("task.create", project="stable-slug", title="New task")["result"]["task"]
        updated = self.execute("task.update", task_id=task["id"], expected_revision=task["revision"], changes={"status": "doing"})
        self.assertTrue(updated["ok"], updated)
        self.assertEqual(updated["result"]["task"]["assignee"], "codex")
        self.assertNotEqual(updated["result"]["task"]["revision"], task["revision"])

    def test_does_not_edit_other_agents_running_task(self):
        self.cli("task-add", "stable-slug", "Other work", "--as", "codex", "--assignee", "claude")
        self.cli("task-update", "1", "--status", "doing", "--as", "codex")
        task = self.execute("board", project="stable-slug")["result"]["tasks"][0]
        reply = self.execute("task.update", task_id=1, expected_revision=task["revision"], changes={"detail": "No"})
        self.assertEqual(reply["error"]["code"], "task_owned")

    def test_rejects_commands_identity_spoofing_and_bad_schema(self):
        for request in (self.request("shell", command="anything"), self.request("projects", actor="user"),
                        {**self.request("projects"), "version": True}, {**self.request("projects"), "request_id": "bad"}):
            self.assertFalse(rpc.execute(request, "codex")["ok"])
        self.assertFalse(self.execute("post", project="stable-slug", kind="directive", body="No")["ok"])


if __name__ == "__main__":
    unittest.main()
