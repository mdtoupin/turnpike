import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import uuid
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
import turnpike
import turnpike_notes as notes

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aU1sAAAAASUVORK5CYII=")


class ImageNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="turnpike-note-test-")
        self.previous = turnpike.DB_PATH
        turnpike.DB_PATH = Path(self.temp.name)/"bus.db"
        self.env = {**os.environ, "TURNPIKE_DB": str(turnpike.DB_PATH)}
        subprocess.check_call([sys.executable, str(ROOT/"turnpike.py"), "create", "notes", "--goal", "Tests"], env=self.env, stdout=subprocess.DEVNULL)
        con = notes.connect()
        con.close()

    def tearDown(self):
        turnpike.DB_PATH = self.previous
        self.temp.cleanup()

    def asset(self):
        return notes.store_asset("notes", "image/png", base64.b64encode(PNG).decode())

    def post(self, *, kind="note", body="Review this note", assets=None, client_id=None):
        return notes.post_user_message("notes", kind, body, assets or [], client_id or str(uuid.uuid4()))

    def test_asset_is_exact_deduplicated_and_type_checked(self):
        a, b = self.asset(), self.asset()
        self.assertEqual(a, b)
        con = notes.connect()
        self.assertEqual(con.execute("SELECT data FROM note_assets").fetchone()[0], PNG)
        con.close()
        with self.assertRaises(ValueError):
            notes.store_asset("notes", "image/jpeg", base64.b64encode(PNG).decode())
        with self.assertRaises(ValueError):
            notes.store_asset("notes", "image/png", "not-base64")

    def test_note_image_and_job_are_atomic_and_idempotent(self):
        asset = self.asset()
        token = str(uuid.uuid4())
        first = self.post(body="", assets=[asset["id"]], client_id=token)
        self.assertEqual(first, self.post(body="", assets=[asset["id"]], client_id=token))
        con = notes.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM note_jobs").fetchone()[0], 1)
        rows = notes.attach_metadata(con, [dict(con.execute("SELECT * FROM messages").fetchone())])
        self.assertEqual(rows[0]["attachments"][0]["id"], asset["id"])
        self.assertEqual(rows[0]["client_id"], token)
        self.assertEqual(rows[0]["note_response"]["model"], "gpt-6.1-sol")
        self.assertEqual(rows[0]["note_response"]["effort"], "low")
        con.close()

    def test_duplicate_image_selection_is_normalized(self):
        asset = self.asset()
        self.post(assets=[asset["id"], asset["id"]])
        con = notes.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM message_assets").fetchone()[0], 1)
        con.close()

    def test_invalid_attachment_rolls_back_everything(self):
        with self.assertRaises(ValueError):
            self.post(assets=[str(uuid.uuid4())])
        con = notes.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM note_jobs").fetchone()[0], 0)
        con.close()

    def test_same_submission_id_cannot_change_content(self):
        token = str(uuid.uuid4())
        self.post(client_id=token)
        with self.assertRaises(ValueError):
            self.post(body="Different", client_id=token)

    def test_non_note_does_not_launch_response(self):
        self.assertIsNone(self.post(kind="question")["response"])
        subprocess.check_call([sys.executable, str(ROOT/"turnpike.py"), "post", "notes", "An agent note", "--kind", "note", "--as", "codex"], env=self.env, stdout=subprocess.DEVNULL)
        con = notes.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM note_jobs").fetchone()[0], 0)
        con.close()

    def test_reply_is_single_and_does_not_recurse(self):
        self.post()
        con = notes.connect()
        job = notes.claim_job(con)
        notes.finish_job(con, job, "A useful response")
        with self.assertRaises(RuntimeError):
            notes.finish_job(con, job, "A duplicate")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM messages WHERE author='codex'").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM note_jobs").fetchone()[0], 1)
        con.close()

    def test_wrong_attempt_cannot_publish(self):
        self.post()
        con = notes.connect()
        job = notes.claim_job(con)
        with self.assertRaises(RuntimeError):
            notes.finish_job(con, {**job, "owner_token": "stale"}, "Wrong owner")
        self.assertEqual(con.execute("SELECT COUNT(*) FROM messages WHERE author='codex'").fetchone()[0], 0)
        con.close()

    def test_interrupted_attempt_keeps_provider_ids_without_replay(self):
        self.post()
        con = notes.connect()
        job = notes.claim_job(con)
        notes.remember_ids(con, job, thread_id="thread", turn_id="turn")
        notes.recover_interrupted(con)
        current = con.execute("SELECT * FROM note_jobs").fetchone()
        self.assertEqual(current["state"], "needs_attention")
        self.assertEqual((current["thread_id"], current["turn_id"]), ("thread", "turn"))
        self.assertIsNone(notes.claim_job(con))
        con.close()

    def test_worker_once_processes_only_one_note(self):
        self.post(body="First")
        self.post(body="Second")
        with patch.object(notes, "respond", return_value="Test answer"):
            notes.run_worker(once=True)
        con = notes.connect()
        self.assertEqual(con.execute("SELECT COUNT(*) FROM note_jobs WHERE state='succeeded'").fetchone()[0], 1)
        self.assertEqual(con.execute("SELECT COUNT(*) FROM note_jobs WHERE state='queued'").fetchone()[0], 1)
        con.close()

    def test_uncertain_submitted_turn_is_not_retried_as_quota_failure(self):
        self.post()
        def fail(con, job):
            notes.remember_ids(con, job, thread_id="thread", turn_id="turn")
            raise RuntimeError("Rate limit after submission")
        with patch.object(notes, "respond", side_effect=fail):
            notes.run_worker(once=True)
        con = notes.connect()
        row = con.execute("SELECT * FROM note_jobs").fetchone()
        self.assertEqual(row["state"], "needs_attention")
        self.assertIsNone(row["retry_at"])
        con.close()

    def test_missing_turn_id_after_submission_never_authorizes_replay(self):
        self.post()
        def fail(con, job):
            notes.remember_ids(con, job, thread_id="thread", submission_started=1)
            raise RuntimeError("Rate limit while turn response was lost")
        with patch.object(notes, "respond", side_effect=fail):
            notes.run_worker(once=True)
        con = notes.connect()
        row = con.execute("SELECT * FROM note_jobs").fetchone()
        self.assertEqual(row["state"], "needs_attention")
        self.assertIsNone(row["turn_id"])
        self.assertIsNone(row["retry_at"])
        con.close()

    def test_enqueue_during_idle_exit_observes_released_worker_lock(self):
        released = threading.Event()
        def enqueue():
            self.assertTrue(released.wait(5))
            self.post(body="Concurrent enqueue")
            with notes.worker_lock() as available:
                return bool(available)
        with notes.worker_lock() as lease:
            release = lease.release
            def announce_release():
                released.set()
                release()
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(enqueue)
                con = notes.connect()
                with patch.object(lease, "release", side_effect=announce_release):
                    self.assertTrue(notes.release_if_idle(con, lease))
                con.close()
                self.assertTrue(future.result(timeout=5))

    def test_idle_exit_keeps_ownership_if_a_note_already_arrived(self):
        self.post()
        with notes.worker_lock() as lease:
            con = notes.connect()
            self.assertFalse(notes.release_if_idle(con, lease))
            self.assertTrue(lease)
            con.close()

    def test_worker_lock_excludes_other_processes(self):
        code = "import turnpike_notes as n\nwith n.worker_lock() as acquired: print(bool(acquired))"
        with notes.worker_lock() as acquired:
            self.assertTrue(acquired)
            result = subprocess.check_output([sys.executable, "-c", code], env=self.env, cwd=ROOT, encoding="utf-8")
            self.assertEqual(result.strip(), "False")


if __name__ == "__main__":
    unittest.main()
