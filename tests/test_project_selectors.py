import argparse
from contextlib import redirect_stdout
import io
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


class ProjectSelectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="turnpike-selector-")
        self.old_path = bus.DB_PATH
        bus.DB_PATH = Path(self.temp.name)/"test.db"
        self.env = {**os.environ, "TURNPIKE_DB": str(bus.DB_PATH)}
        self.cli("create", "stable-slug", "--name", "Visible room", "--goal", "Tests")

    def tearDown(self):
        bus.DB_PATH = self.old_path
        self.temp.cleanup()

    def cli(self, *args):
        return subprocess.check_output([sys.executable, str(ROOT/"turnpike.py"), *args], env=self.env, encoding="utf-8")

    def board(self, selector):
        return rpc.execute({"version": 1, "request_id": str(uuid.uuid4()), "operation": "board", "params": {"project": selector}}, "codex")

    def test_local_reads_and_rpc_share_slug_name_and_id_resolution(self):
        for selector in ("stable-slug", "Visible room", "visible ROOM", "1"):
            with self.subTest(selector=selector):
                local = json.loads(self.cli("pull", selector, "--as", "codex", "--peek", "--json"))
                remote = self.board(selector)
                self.assertTrue(remote["ok"], remote)
                self.assertEqual(local["project"]["id"], remote["result"]["project"]["id"])
                self.assertEqual(local["project"]["slug"], "stable-slug")
        self.assertEqual(self.board(1)["result"]["project"]["slug"], "stable-slug")

    def test_local_mutations_accept_visible_names_without_creating_other_rooms(self):
        self.cli("post", "VISIBLE ROOM", "Correct room", "--as", "codex")
        self.cli("summary", "Visible room", "Current", "--as", "codex")
        self.cli("task-add", "Visible room", "Scoped task", "--as", "codex")
        self.cli("workdir", "Visible room", self.temp.name)
        self.cli("status", "Visible room", "paused")
        value = self.board(1)["result"]
        self.assertEqual((value["project"]["summary"], value["project"]["status"], value["project"]["workdir"]), ("Current", "paused", self.temp.name))
        self.assertEqual(value["tasks"][0]["title"], "Scoped task")
        self.assertEqual(len(json.loads(self.cli("projects", "--json"))), 1)

    def test_ambiguous_names_reject_mutations_without_changing_either_room(self):
        self.cli("create", "second-slug", "--name", "VISIBLE ROOM", "--goal", "Other")
        self.assertEqual(self.board("visible room")["error"]["code"], "ambiguous_project")
        run = subprocess.run([sys.executable, str(ROOT/"turnpike.py"), "post", "Visible room", "Do not write", "--as", "codex"],
                             env=self.env, capture_output=True, text=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("ambiguous_project", run.stderr)
        for selector in ("stable-slug", "second-slug"):
            self.assertEqual(json.loads(self.cli("log", selector, "--json")), [])

    def test_exact_slug_wins_over_other_rooms_display_names(self):
        self.cli("create", "Visible room", "--name", "Another name", "--goal", "Collision")
        value = self.board("Visible room")["result"]["project"]
        self.assertEqual(value["slug"], "Visible room")
        self.assertEqual(value["id"], 2)
        self.assertEqual(self.board("visible room")["result"]["project"]["slug"], "stable-slug")

    def test_numeric_slug_remains_compatible_and_rpc_integer_selects_id(self):
        self.cli("create", "1", "--name", "Numeric slug", "--goal", "Collision")
        self.assertEqual(self.board("1")["result"]["project"]["id"], 2)
        self.assertEqual(self.board(1)["result"]["project"]["id"], 1)
        local = json.loads(self.cli("pull", "1", "--as", "codex", "--json"))
        self.assertEqual(local["project"]["slug"], "1")

    def test_unicode_casefold_and_archived_name_collisions_are_safe(self):
        self.cli("rename", "stable-slug", "Straße", "--as", "codex")
        self.assertEqual(self.board("STRASSE")["result"]["project"]["slug"], "stable-slug")
        self.cli("create", "archived", "--name", "STRASSE", "--goal", "Other")
        self.cli("status", "archived", "archived")
        self.assertEqual(self.board("strasse")["error"]["code"], "ambiguous_project")

    def test_listing_exposes_display_name_without_changing_json_fields(self):
        listing = self.cli("projects")
        self.assertIn("stable-slug", listing)
        self.assertIn("name: Visible room", listing)
        row = json.loads(self.cli("projects", "--json"))[0]
        self.assertEqual((row["id"], row["slug"], row["name"]), (1, "stable-slug", "Visible room"))

    def test_sessions_and_restore_filters_resolve_display_name_and_id(self):
        self.cli("session-bind", "Visible room", "--as", "codex", "--provider", "codex", "--session-id", "selector-test-thread", "--cwd", self.temp.name)
        for selector in ("Visible room", "1", "stable-slug"):
            rows = json.loads(self.cli("sessions", selector, "--json"))
            self.assertEqual(len(rows), 1)
            output = io.StringIO()
            con = bus.connect()
            try:
                with patch.object(bus, "connect", return_value=con), patch.object(bus, "live_command_lines", return_value=None), redirect_stdout(output):
                    bus.cmd_restore(argparse.Namespace(project=selector, all=True, dry_run=True))
            finally:
                con.close()
            self.assertIn("selector-test-thread", output.getvalue())
            self.assertIn("would open 1 tab", output.getvalue())

    def test_invalid_and_missing_selectors_return_structured_errors(self):
        for selector in (None, True, "", "x\x00y", "x"*257, -1, 0, 2**63, "0", str(2**63)):
            with self.subTest(selector=selector):
                self.assertEqual(self.board(selector)["error"]["code"], "invalid_params")
        for selector in ("missing", "999", 999, "x' OR 1=1 --"):
            self.assertEqual(self.board(selector)["error"]["code"], "not_found")


if __name__ == "__main__":
    unittest.main()
