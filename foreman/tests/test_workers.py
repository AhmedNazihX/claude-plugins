"""Tests for scripts/workers.py. Stdlib only: run with `python3 -m unittest discover -s tests` from the repo root."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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

    def write_transcript(self, agent: str, tokens: int, minutes_ago: float, session: str = "s1",
                         tail: str = "") -> Path:
        """A worker transcript whose last model turn had `tokens` of context, `minutes_ago` minutes ago.

        An earlier, different turn comes first, and `tail` (raw lines) after the last turn."""
        def turn(tokens: int, minutes_ago: float) -> str:
            at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
            return json.dumps({
                "timestamp": at.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                "message": {"model": "claude-opus-5-5", "usage": {
                    "input_tokens": 1, "cache_creation_input_tokens": 999,
                    "cache_read_input_tokens": tokens - 1000, "output_tokens": 50}},
            })
        root = Path(self.tmp.name) / "projects"
        path = root / "-repo" / session / "subagents" / f"agent-{agent}.jsonl"
        path.parent.mkdir(parents=True)
        lines = ['{"type": "user"}', turn(20_000, 600), "not json", turn(tokens, minutes_ago), tail]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return root

    def context(self, sid: str, root: Path) -> str:
        result = self.run_cli("--transcripts", str(root), "context", sid)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def advice(self, tokens: int, minutes_ago: float, tail: str = "") -> str:
        self.run_cli("record", "E6", "--agent", "abc123", "--base", "abc")
        return self.context("E6", self.write_transcript("abc123", tokens, minutes_ago, tail=tail))

    def test_a_large_idle_worker_gets_a_fresh_worker(self) -> None:
        out = self.advice(tokens=240_000, minutes_ago=30)
        self.assertIn("context 240K tokens, idle 30 min", out)
        self.assertIn("fresh: story-start --continue", out)

    def test_the_cache_ttl_is_the_idle_threshold(self) -> None:
        self.assertIn("fresh:", self.advice(tokens=200_000, minutes_ago=5.2))
        self.tearDown(), self.setUp()
        self.assertIn("resume:", self.advice(tokens=200_000, minutes_ago=4.8))

    def test_150k_tokens_is_the_size_threshold(self) -> None:
        self.assertIn("fresh:", self.advice(tokens=150_000, minutes_ago=30))
        self.tearDown(), self.setUp()
        self.assertIn("resume:", self.advice(tokens=149_999, minutes_ago=30))

    def test_error_records_and_bad_lines_after_the_last_turn_are_skipped(self) -> None:
        synthetic = json.dumps({"timestamp": "2026-10-07T10:00:00.000Z", "message": {
            "model": "<synthetic>", "usage": {"input_tokens": 0, "cache_read_input_tokens": 0}}})
        naive = json.dumps({"timestamp": "2026-10-07T10:00:00", "message": {"usage": {"input_tokens": 9}}})
        odd = json.dumps({"timestamp": "yesterday", "message": {"usage": {"input_tokens": "n/a"}}})
        out = self.advice(tokens=240_000, minutes_ago=30, tail="\n".join([synthetic, naive, odd, "[1]"]))
        self.assertIn("context 240K tokens", out)
        self.assertIn("fresh:", out)

    def test_a_worker_without_a_transcript_is_resumed_as_usual(self) -> None:
        self.run_cli("record", "E6", "--agent", "nofile", "--base", "abc")
        out = self.context("E6", Path(self.tmp.name))
        self.assertIn("no transcript with usage found for agent nofile", out)

    def test_an_agent_id_with_glob_or_path_characters_is_refused(self) -> None:
        for bad in ("*", "../x", "a?b"):
            result = self.run_cli("record", "E6", "--agent", bad, "--base", "abc")
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("an agent id has only", result.stderr)
        self.assertFalse(self.registry.exists())


if __name__ == "__main__":
    unittest.main()
