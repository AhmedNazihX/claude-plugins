"""Tests for scripts/workers.py. Stdlib only: run with `python3 -m unittest discover -s tests` from the repo root."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "workers.py"


class WorkersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = Path(self.tmp.name) / "workers.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--registry", str(self.registry), *args],
            capture_output=True, text=True, input=stdin, cwd=self.tmp.name,
        )

    def entries(self) -> dict[str, dict[str, object]]:
        return json.loads(self.registry.read_text(encoding="utf-8"))

    def test_a_recorded_worker_keeps_its_agent_base_and_brief(self) -> None:
        result = self.run_cli(
            "record", "C9", "--agent", "a2e9c9", "--base", "d80be7fe9c27",
            "--worktree", "/repo/.claude/worktrees/agent-a2e9c9", "--brief", "-",
            stdin="STORY: C9\nSLUG: obligation-texts\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        c9 = self.entries()["C9"]
        self.assertEqual(c9["agent_id"], "a2e9c9")
        self.assertEqual(c9["base_sha"], "d80be7fe9c27")
        self.assertEqual(c9["state"], "running")
        self.assertEqual(c9["branch"], "story/C9-*")
        self.assertIn("SLUG: obligation-texts", str(c9["brief"]))

    def test_record_needs_the_agent_and_the_base(self) -> None:
        result = self.run_cli("record", "C9", "--agent", "a2e9c9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--base", result.stderr)
        self.assertFalse(self.registry.exists())

    def test_set_changes_the_state_and_keeps_a_note(self) -> None:
        self.run_cli("record", "E11", "--agent", "aa6c72", "--base", "abc")
        result = self.run_cli("set", "E11", "waiting-user", "--note", "recording approved")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.entries()["E11"]["state"], "waiting-user")
        self.assertEqual(self.entries()["E11"]["note"], "recording approved")

    def test_an_unknown_state_is_refused(self) -> None:
        self.run_cli("record", "E11", "--agent", "aa6c72", "--base", "abc")
        result = self.run_cli("set", "E11", "sleeping")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.entries()["E11"]["state"], "running")

    def test_list_flags_a_worktree_that_is_gone(self) -> None:
        present = Path(self.tmp.name) / "agent-present"
        present.mkdir()
        self.run_cli("record", "P5", "--agent", "a83612", "--base", "abc", "--worktree", str(present))
        self.run_cli("record", "V7", "--agent", "a096fa", "--base", "abc", "--worktree", "/nowhere/agent-gone")
        out = self.run_cli("list").stdout
        self.assertIn("P5: running, agent a83612", out)
        self.assertIn("worktree present", out)
        self.assertIn("V7: running, agent a096fa", out)
        self.assertIn("worktree GONE", out)

    def test_show_prints_the_brief_and_forget_removes_the_entry(self) -> None:
        self.run_cli("record", "C9", "--agent", "a2e9c9", "--base", "abc", "--brief", "-", stdin="the brief")
        self.assertIn("the brief", self.run_cli("show", "C9").stdout)
        self.assertEqual(self.run_cli("forget", "C9").returncode, 0)
        self.assertEqual(self.entries(), {})
        self.assertNotEqual(self.run_cli("show", "C9").returncode, 0)

    def test_an_empty_registry_lists_no_workers(self) -> None:
        self.assertIn("No workers recorded.", self.run_cli("list").stdout)


if __name__ == "__main__":
    unittest.main()
