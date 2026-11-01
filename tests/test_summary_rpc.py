from concurrent.futures import ThreadPoolExecutor
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
import turnpike as bus
import turnpike_rpc as rpc


class SummaryRpcTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="turnpike-summary-")
        self.old_path = bus.DB_PATH
        bus.DB_PATH = Path(self.temp.name)/"test.db"
        self.env = {**os.environ, "TURNPIKE_DB": str(bus.DB_PATH)}
        self.cli("create", "room", "--name", "Visible room", "--goal", "Tests")

    def tearDown(self):
        bus.DB_PATH = self.old_path
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.check_output([sys.executable, str(ROOT/"turnpike.py"), *args], env=self.env, encoding="utf-8")

    def request(self, operation, **params):
        return {"version": 1, "request_id": str(uuid.uuid4()), "operation": operation, "params": params}

    def execute(self, operation, **params):
        return rpc.execute(self.request(operation, **params), "codex")

    def current(self):
        reply = self.execute("summary.get", project="room")
        self.assertTrue(reply["ok"], reply)
        return reply["result"]

    def update(self, body):
        return self.execute("summary.update", project="room", expected_revision=self.current()["revision"], summary=body)

    def history(self, **params):
        return self.execute("summary.history", project="room", **params)["result"]

    def process_request(self, request):
        run = subprocess.run([sys.executable, str(ROOT/"turnpike.py"), "rpc", "--as", "codex"],
                             input=json.dumps(request)+"\n", env=self.env, text=True,
                             encoding="utf-8", capture_output=True, timeout=20, check=True)
        return json.loads(run.stdout)

    def test_update_records_author_before_after_and_timeline_without_acknowledging(self):
        self.cli("pull", "room", "--as", "codex")
        con = bus.connect()
        cursors = [tuple(r) for r in con.execute("SELECT * FROM cursors")]
        con.close()
        original = self.current()
        reply = self.update("Ship from learn-live; preserve the current release.")
        self.assertTrue(reply["ok"], reply)
        self.assertTrue(reply["result"]["changed"])
        self.assertNotEqual(reply["result"]["revision"], original["revision"])
        history = self.history()["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual((history[0]["previous_summary"], history[0]["actor"], history[0]["source"]), ("", "codex", "rpc"))
        self.assertEqual(history[0]["summary"], reply["result"]["summary"])
        con = bus.connect()
        self.assertEqual(cursors, [tuple(r) for r in con.execute("SELECT * FROM cursors")])
        self.assertEqual(con.execute("SELECT body FROM messages WHERE id=?", (reply["result"]["message_id"],)).fetchone()[0], "Updated the living summary (revision 1).")
        con.close()

    def test_same_id_retry_after_newer_update_returns_receipt_without_reverting(self):
        request = self.request("summary.update", project="room", expected_revision=self.current()["revision"], summary="First")
        first = self.process_request(request)
        self.assertTrue(first["ok"], first)
        self.assertTrue(self.update("Newer")["ok"])
        self.assertEqual(self.process_request(request), first)
        self.assertEqual(self.current()["summary"], "Newer")
        self.assertEqual(len(self.history()["history"]), 2)

    def test_concurrent_writers_cannot_overwrite_each_other(self):
        revision = self.current()["revision"]
        requests = [self.request("summary.update", project="room", expected_revision=revision, summary=body) for body in ("A", "B")]
        with ThreadPoolExecutor(max_workers=2) as pool:
            replies = list(pool.map(self.process_request, requests))
        self.assertEqual(sum(r["ok"] for r in replies), 1)
        self.assertEqual([r["error"]["code"] for r in replies if not r["ok"]], ["revision_conflict"])
        self.assertEqual(len(self.history()["history"]), 1)

    def test_legacy_writer_aba_invalidates_old_token_even_in_one_second(self):
        self.update("A")
        original = self.current()
        con = bus.connect()
        for value in ("B", "A"):
            con.execute("UPDATE projects SET summary=?,updated_at='2026-11-01T00:00:00Z' WHERE slug='room'", (value,))
        con.commit()
        con.close()
        denied = self.execute("summary.update", project="room", expected_revision=original["revision"], summary="Lost update")
        self.assertEqual(denied["error"]["code"], "revision_conflict")
        history = self.history()["history"]
        self.assertEqual([(r["actor"], r["source"]) for r in history[1:]], [("unknown", "legacy"), ("unknown", "legacy")])

    def test_local_summary_writes_share_the_audit_and_keep_old_calls_working(self):
        self.cli("summary", "room", "Known author", "--as", "codex")
        self.cli("summary", "room", "Old syntax")
        history = self.history()["history"]
        self.assertEqual([(r["actor"], r["source"]) for r in history], [("codex", "cli"), ("unknown", "cli")])
        self.assertEqual(history[1]["previous_summary"], "Known author")

    def test_unrelated_changes_and_identical_summary_do_not_invalidate_token(self):
        original = self.current()
        self.execute("post", project="room", kind="update", body="Unrelated")
        self.execute("task.create", project="room", title="Unrelated task")
        self.assertEqual(self.current()["revision"], original["revision"])
        reply = self.update("")
        self.assertFalse(reply["result"]["changed"])
        self.assertEqual(reply["result"]["revision"], original["revision"])
        self.assertEqual(self.history()["history"], [])

    def test_history_pagination_is_room_scoped(self):
        self.cli("create", "other", "--goal", "Other")
        for text in ("One", "Two", "Three"):
            self.update(text)
        first = self.history(limit=2)
        second = self.history(after_revision=first["last_revision"], limit=2)
        self.assertEqual([r["revision"] for r in first["history"]+second["history"]], [1, 2, 3])
        self.assertEqual(self.execute("summary.history", project="other")["result"]["history"], [])

    def test_summary_token_cannot_be_used_for_another_room(self):
        self.cli("create", "other", "--goal", "Other")
        reply = self.execute("summary.update", project="other", expected_revision=self.current()["revision"], summary="Wrong target")
        self.assertEqual(reply["error"]["code"], "revision_conflict")

    def test_dispatch_failure_rolls_back_summary_history_message_and_receipt(self):
        before = self.current()
        request = self.request("summary.update", project="room", expected_revision=before["revision"], summary="Rollback")
        original = rpc.dispatch
        def fail(*args):
            original(*args)
            raise rpc.RequestError("injected_failure", "Stop before commit")
        with patch.object(rpc, "dispatch", side_effect=fail):
            self.assertFalse(rpc.execute(request, "codex")["ok"])
        self.assertEqual(self.current(), before)
        self.assertEqual(self.history()["history"], [])
        self.assertEqual(self.execute("messages", project="room")["result"]["messages"], [])
        self.assertTrue(rpc.execute(request, "codex")["ok"])

    def test_invalid_body_and_history_bounds_do_not_change_summary(self):
        before = self.current()
        for body in (None, True, "\x00", "x"*100001):
            denied = self.execute("summary.update", project="room", expected_revision=before["revision"], summary=body)
            self.assertEqual(denied["error"]["code"], "invalid_params")
        for params in ({"limit": 0}, {"limit": 201}, {"after_revision": -1}):
            self.assertEqual(self.execute("summary.history", project="room", **params)["error"]["code"], "invalid_params")
        self.assertEqual(self.current(), before)

    def test_display_name_and_id_return_the_same_summary(self):
        self.assertEqual(self.execute("summary.get", project="Visible room")["result"], self.current())
        self.assertEqual(self.execute("summary.get", project=1)["result"], self.current())


if __name__ == "__main__":
    unittest.main()
