"""Tests for scripts/workers.py. Stdlib only: run with `python3 -m unittest discover -s tests` from the repo root."""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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

    def test_20_concurrent_records_keep_all_20_entries(self) -> None:
        ids = [f"C{n}" for n in range(20)]
        procs = [
            subprocess.Popen(
                [sys.executable, str(SCRIPT), "--registry", str(self.registry),
                 "record", sid, "--agent", f"a{n}", "--base", "abc"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=self.tmp.name,
            )
            for n, sid in enumerate(ids)
        ]
        for proc in procs:
            _, err = proc.communicate(timeout=60)
            self.assertEqual(proc.returncode, 0, err)
        self.assertEqual(sorted(self.entries()), sorted(ids))
        leftovers = [p.name for p in Path(self.tmp.name).iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_a_launching_entry_without_an_agent_id_is_listed_as_launching(self) -> None:
        result = self.run_cli("record", "Q1", "--launching", "--base", "657b3500bc85", "--brief", "-",
                              stdin="STORY: Q1\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        q1 = self.entries()["Q1"]
        self.assertEqual(q1["state"], "launching")
        self.assertEqual(q1["agent_id"], "")
        out = self.run_cli("list").stdout
        self.assertIn("Q1: launching, no agent id yet, story/Q1-*", out)

    def test_record_with_an_agent_fills_a_launching_entry_and_keeps_its_base_and_brief(self) -> None:
        self.run_cli("record", "Q1", "--launching", "--base", "657b3500bc85", "--brief", "-", stdin="the brief")
        launched = self.entries()["Q1"]["launched"]
        result = self.run_cli("record", "Q1", "--agent", "af2d76", "--worktree", "/repo/.claude/worktrees/agent-af2d76")
        self.assertEqual(result.returncode, 0, result.stderr)
        q1 = self.entries()["Q1"]
        self.assertEqual(q1["agent_id"], "af2d76")
        self.assertEqual(q1["state"], "running")
        self.assertEqual(q1["base_sha"], "657b3500bc85")
        self.assertEqual(q1["brief"], "the brief")
        self.assertEqual(q1["worktree"], "/repo/.claude/worktrees/agent-af2d76")
        self.assertEqual(q1["launched"], launched)
        self.assertIn("Q1: running, agent af2d76", self.run_cli("list").stdout)

    def test_launching_needs_a_base_and_refuses_an_agent(self) -> None:
        self.assertNotEqual(self.run_cli("record", "Q1", "--launching").returncode, 0)
        result = self.run_cli("record", "Q1", "--launching", "--base", "abc", "--agent", "a1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no --agent", result.stderr)
        self.assertFalse(self.registry.exists())

    def test_record_without_a_base_needs_a_launching_entry(self) -> None:
        self.run_cli("record", "Q1", "--agent", "a1", "--base", "abc")
        self.run_cli("set", "Q1", "reported")
        result = self.run_cli("record", "Q1", "--agent", "a2")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no `launching` entry", result.stderr)
        self.assertEqual(self.entries()["Q1"]["agent_id"], "a1")

    def test_context_of_a_launching_entry_says_there_is_no_agent_yet(self) -> None:
        self.run_cli("record", "Q1", "--launching", "--base", "abc")
        result = self.run_cli("--transcripts", self.tmp.name, "context", "Q1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("no agent id recorded yet", result.stderr)

    def test_launching_over_a_live_entry_is_refused_without_replace(self) -> None:
        self.run_cli("record", "Q1", "--agent", "a1", "--base", "abc", "--worktree", "/wt/agent-a1")
        self.run_cli("set", "Q1", "reported")
        result = self.run_cli("record", "Q1", "--launching", "--base", "def")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--replace", result.stderr)
        q1 = self.entries()["Q1"]
        self.assertEqual((q1["agent_id"], q1["worktree"], q1["state"]), ("a1", "/wt/agent-a1", "reported"))

    def test_launching_with_replace_or_over_a_merged_entry_starts_a_new_entry(self) -> None:
        self.run_cli("record", "Q1", "--agent", "a1", "--base", "abc")
        result = self.run_cli("record", "Q1", "--launching", "--replace", "--base", "def")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.entries()["Q1"]["state"], self.entries()["Q1"]["agent_id"]), ("launching", ""))
        self.run_cli("record", "Q2", "--agent", "a2", "--base", "abc")
        self.run_cli("set", "Q2", "merged")
        self.assertEqual(self.run_cli("record", "Q2", "--launching", "--base", "def").returncode, 0)
        self.assertEqual(self.entries()["Q2"]["state"], "launching")

    def test_set_refuses_a_launching_entry(self) -> None:
        self.run_cli("record", "Q1", "--launching", "--base", "abc")
        result = self.run_cli("set", "Q1", "running")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("record Q1 --agent", result.stderr)
        self.assertEqual(self.entries()["Q1"]["state"], "launching")

    def test_a_failed_save_keeps_the_old_registry_and_leaves_no_temp_file(self) -> None:
        self.run_cli("record", "Q1", "--agent", "a1", "--base", "abc")
        before = self.registry.read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location("workers_under_test", SCRIPT)
        workers = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(workers)
        with mock.patch.object(workers.os, "replace", side_effect=OSError("disk full")) as replace:
            with self.assertRaises(OSError):
                workers.save(self.registry, {"Q9": {"story": "Q9"}})
        replace.assert_called_once()
        self.assertEqual(self.registry.read_text(encoding="utf-8"), before)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir() if p.name.endswith(".tmp")], [])

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


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "handoffs"
REVIEWER = ("--reviewer", "foreman:diff-reviewer", "--round", "1")


class ReportTest(unittest.TestCase):
    """`report` and `handoff-path`, against the synthetic reports in fixtures/handoffs (story Z7)."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.handoffs = Path(self.tmp.name) / "handoffs"
        shutil.copytree(FIXTURES, self.handoffs)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--handoffs", str(self.handoffs), *args],
            capture_output=True, text=True, cwd=self.tmp.name,
        )

    def field(self, field: str, *extra: str) -> str:
        result = self.run_cli("report", "Z7", *extra, "--field", field)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def drop_line(self, name: str, prefix: str) -> None:
        path = self.handoffs / name
        kept = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.startswith(prefix)]
        path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    def test_handoff_path_names_the_worker_and_reviewer_files(self) -> None:
        self.assertEqual(self.run_cli("handoff-path", "Z7").stdout.strip(), str(self.handoffs / "Z7.md"))
        self.assertEqual(self.run_cli("handoff-path", "Z7", *REVIEWER).stdout.strip(),
                         str(self.handoffs / "Z7-foreman-diff-reviewer-r1.md"))

    def test_handoff_path_refuses_names_that_leave_the_folder(self) -> None:
        for args in (("../Z7",), ("Z7.x",), ("Z7", "--reviewer", "../x", "--round", "1"),
                     ("Z7", "--reviewer", "a", "--round", "0"), ("Z7", "--reviewer", "a")):
            result = self.run_cli("handoff-path", *args)
            self.assertEqual(result.returncode, 1, args)
            self.assertEqual(result.stdout, "", args)

    def test_status_is_the_workers_outcome(self) -> None:
        self.assertEqual(self.field("status"), "NEEDS USER\n")

    def test_status_of_a_reviewer_report_is_its_verdict(self) -> None:
        self.assertEqual(self.field("status", *REVIEWER), "CHANGES\n")

    def test_evidence_is_the_dod_evidence_section(self) -> None:
        self.assertEqual(self.field("evidence"), (
            "DoD evidence\n"
            "- parser reads every sample row: test_parser_reads_rows passes\n"
            "- bad rows are reported: test_bad_row_is_reported passes\n"))

    def test_needs_user_keeps_its_continuation_lines_and_stops_at_the_next_label(self) -> None:
        self.assertEqual(self.field("needs-user"), (
            "Needs user (if any): choose the default date format; I recommend ISO 8601.\n"
            "                      ! python3 scripts/sample.py --dry-run\n"))

    def test_checks_stops_at_the_next_label(self) -> None:
        self.assertEqual(self.field("checks"), "Checks: python3 -m unittest -q: pass, 12 tests\n  lint: pass\n")

    def test_no_field_prints_the_whole_report(self) -> None:
        result = self.run_cli("report", "Z7")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, (self.handoffs / "Z7.md").read_text(encoding="utf-8"))

    def test_markdown_headings_are_section_labels(self) -> None:
        path = self.handoffs / "Z7.md"
        path.write_text(path.read_text(encoding="utf-8").replace("DoD evidence", "## DoD evidence"),
                        encoding="utf-8")
        self.assertTrue(self.field("evidence").startswith("## DoD evidence\n- parser reads"))

    def test_a_missing_section_exits_1(self) -> None:
        self.drop_line("Z7.md", "Checks:")
        self.drop_line("Z7.md", "  lint:")
        result = self.run_cli("report", "Z7", "--field", "checks")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no checks section", result.stderr)

    def test_each_missing_worker_header_line_exits_2(self) -> None:
        for key in ("Story:", "Branch:", "Head:", "Agent:", "Time:"):
            with self.subTest(key=key):
                self.tearDown(), self.setUp()
                # The body repeats `Branch:`; only the header counts, so drop the first one alone.
                path = self.handoffs / "Z7.md"
                lines = path.read_text(encoding="utf-8").splitlines()
                lines.remove(next(line for line in lines if line.startswith(key)))
                path.write_text("\n".join(lines) + "\n", encoding="utf-8")
                result = self.run_cli("report", "Z7", "--field", "status")
                self.assertEqual(result.returncode, 2, key)
                self.assertIn(f"header line missing or empty: {key[:-1]}", result.stderr)
                self.assertEqual(result.stdout, "")

    def test_each_missing_reviewer_header_line_exits_2(self) -> None:
        for key in ("Reviewer:", "Range:", "Verdict:"):
            with self.subTest(key=key):
                self.tearDown(), self.setUp()
                self.drop_line("Z7-foreman-diff-reviewer-r1.md", key)
                result = self.run_cli("report", "Z7", *REVIEWER, "--field", "status")
                self.assertEqual(result.returncode, 2, key)
                self.assertIn(f"header line missing or empty: {key[:-1]}", result.stderr)

    def test_an_empty_header_value_or_a_wrong_story_or_head_exits_2(self) -> None:
        path = self.handoffs / "Z7.md"
        original = path.read_text(encoding="utf-8")
        for old, new, message in (("Agent: a0f1e2d3c4b5", "Agent:", "missing or empty: Agent"),
                                  ("Story: Z7", "Story: Z8", "expected Z7"),
                                  ("Head: 3f9c2ab71d04", "Head: main", "isn't a commit sha")):
            with self.subTest(old=old):
                path.write_text(original.replace(old, new, 1), encoding="utf-8")
                result = self.run_cli("report", "Z7")
                self.assertEqual(result.returncode, 2, old)
                self.assertIn(message, result.stderr)

    def test_a_reviewer_report_for_another_reviewer_exits_2(self) -> None:
        source = self.handoffs / "Z7-foreman-diff-reviewer-r1.md"
        target = self.handoffs / "Z7-foreman-security-reviewer-r1.md"
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        result = self.run_cli("report", "Z7", "--reviewer", "foreman:security-reviewer", "--round", "1")
        self.assertEqual(result.returncode, 2)
        self.assertIn("expected foreman:security-reviewer", result.stderr)

    def test_a_missing_file_exits_2(self) -> None:
        for args in (("Z9",), ("Z7", "--reviewer", "foreman:diff-reviewer", "--round", "2")):
            result = self.run_cli("report", *args, "--field", "status")
            self.assertEqual(result.returncode, 2, args)
            self.assertIn("no report file", result.stderr)

    def test_an_unknown_field_is_refused(self) -> None:
        result = self.run_cli("report", "Z7", "--field", "cost")
        self.assertEqual(result.returncode, 1)
        self.assertIn("one of status, evidence, needs-user, checks", result.stderr)

    def test_a_reviewer_range_that_isnt_two_shas_exits_2(self) -> None:
        path = self.handoffs / "Z7-foreman-diff-reviewer-r1.md"
        original = path.read_text(encoding="utf-8")
        for bad in ("main..HEAD", "1a2b3c4", "1a2b3c4...3f9c2ab"):
            with self.subTest(bad=bad):
                path.write_text(original.replace("1a2b3c4..3f9c2ab", bad, 1), encoding="utf-8")
                result = self.run_cli("report", "Z7", *REVIEWER, "--field", "status")
                self.assertEqual(result.returncode, 2, bad)
                self.assertIn("isn't <sha>..<sha>", result.stderr)


# A git that reads no user or system config, so commit signing, hooks and aliases can't change the test repo.
GIT_ENV = {
    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
}
REVIEWERS = "foreman:diff-reviewer,foreman:security-reviewer"


class VerdictTest(unittest.TestCase):
    """`verdict` and `verdicts`, in a throwaway repo: main, and a story branch Z7 off it."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        self.ledger = Path(self.tmp.name) / "ledger.tsv"
        self.env = {**os.environ, **GIT_ENV}
        self.git("init", "-q", "-b", "main")
        self.commit("base.txt", "base\n")
        self.git("switch", "-q", "-c", "story/Z7-sample")
        self.commit("story.txt", "story\n")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def git(self, *args: str) -> str:
        return subprocess.run(["git", *args], cwd=self.repo, env=self.env, capture_output=True, text=True,
                              check=True).stdout.strip()

    def commit(self, name: str, text: str) -> str:
        (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", name)
        self.git("commit", "-q", "-m", f"add {name}")
        return self.git("rev-parse", "HEAD")

    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--ledger", str(self.ledger), *args],
            capture_output=True, text=True, cwd=self.repo, env=self.env,
        )

    def verdict(self, reviewer: str, sha: str, verdict: str = "pass", level: str = "test-verified",
                evidence: str = "handoffs/Z7-r1.md") -> None:
        result = self.run_cli("verdict", "Z7", reviewer, sha, verdict, "--level", level, "--evidence", evidence)
        self.assertEqual(result.returncode, 0, result.stderr)

    def verdicts(self, head: str, reviewers: str = REVIEWERS) -> subprocess.CompletedProcess[str]:
        return self.run_cli("verdicts", "Z7", "--head", head, "--reviewers", reviewers)

    def rows(self) -> list[list[str]]:
        return [line.split("\t") for line in self.ledger.read_text(encoding="utf-8").splitlines()]

    def test_a_pass_from_every_reviewer_on_the_head_exits_0(self) -> None:
        head = self.git("rev-parse", "HEAD")
        self.verdict("foreman:diff-reviewer", head[:7], level="static-only")
        self.verdict("foreman:security-reviewer", head)
        result = self.verdicts(head[:10])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("passed " + head[:12], result.stdout)
        self.assertEqual(self.rows()[0], ["ts", "story", "reviewer", "sha", "verdict", "level", "evidence"])
        self.assertEqual(self.rows()[1][1:], ["Z7", "foreman:diff-reviewer", head, "pass", "static-only",
                                              "handoffs/Z7-r1.md"])

    def test_a_missing_reviewer_exits_2_and_is_named(self) -> None:
        head = self.git("rev-parse", "HEAD")
        self.verdict("foreman:diff-reviewer", head)
        result = self.verdicts(head)
        self.assertEqual(result.returncode, 2)
        self.assertIn("foreman:security-reviewer: no verdict", result.stderr)
        self.assertNotIn("foreman:diff-reviewer:", result.stderr)

    def test_a_later_fail_voids_an_earlier_pass(self) -> None:
        head = self.git("rev-parse", "HEAD")
        self.verdict("foreman:diff-reviewer", head)
        self.verdict("foreman:security-reviewer", head)
        self.verdict("foreman:security-reviewer", head, verdict="fail", level="live-verified")
        result = self.verdicts(head)
        self.assertEqual(result.returncode, 2)
        self.assertIn("foreman:security-reviewer: latest verdict is fail (live-verified)", result.stderr)

    def test_a_new_head_voids_a_pass(self) -> None:
        old = self.git("rev-parse", "HEAD")
        self.verdict("foreman:diff-reviewer", old)
        self.verdict("foreman:security-reviewer", old)
        new = self.commit("fix.txt", "fix\n")
        result = self.verdicts(new)
        self.assertEqual(result.returncode, 2)
        self.assertIn("foreman:diff-reviewer: no verdict", result.stderr)
        self.assertIn("foreman:security-reviewer: no verdict", result.stderr)

    def test_a_pass_survives_a_rebase_with_the_same_patch_id(self) -> None:
        old = self.git("rev-parse", "HEAD")
        self.verdict("foreman:diff-reviewer", old)
        self.verdict("foreman:security-reviewer", old)
        self.git("switch", "-q", "main")
        self.commit("other.txt", "another story\n")
        self.git("switch", "-q", "story/Z7-sample")
        self.git("rebase", "-q", "main")
        rebased = self.git("rev-parse", "HEAD")
        self.assertNotEqual(rebased, old)
        result = self.verdicts(rebased)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_another_storys_verdicts_dont_count(self) -> None:
        head = self.git("rev-parse", "HEAD")
        for reviewer in REVIEWERS.split(","):
            result = self.run_cli("verdict", "Z8", reviewer, head, "pass", "--level", "test-verified",
                                  "--evidence", "x")
            self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.verdicts(head).returncode, 2)

    def test_cells_lose_tabs_and_line_breaks_and_formulas_are_quoted(self) -> None:
        head = self.git("rev-parse", "HEAD")
        for evidence in ("=HYPERLINK(\"x\")\tsecond\r\nthird", "+1", "-1", "@SUM(A1)", "plain/path.md"):
            self.verdict("foreman:diff-reviewer", head, evidence=evidence)
        cells = [row[-1] for row in self.rows()[1:]]
        self.assertEqual(cells, ["'=HYPERLINK(\"x\") second third", "'+1", "'-1", "'@SUM(A1)", "plain/path.md"])
        self.assertTrue(all(len(row) == 7 for row in self.rows()))

    def test_bad_verdicts_are_refused_and_not_written(self) -> None:
        head = self.git("rev-parse", "HEAD")
        for args, message in (
            (("Z7", "a", head, "maybe", "--level", "static-only"), "one of pass, fail"),
            (("Z7", "a", head, "pass", "--level", "quick"), "one of live-verified"),
            (("Z7", "a", head, "pass", "--level", "blocked"), "a pass can't be blocked"),
            (("Z7", "a", "main", "pass", "--level", "static-only"), "isn't a commit"),
            (("Z7", "a", "0" * 40, "pass", "--level", "static-only"), "isn't a commit"),
            (("../Z7", "a", head, "pass", "--level", "static-only"), "an ID has only"),
            (("Z7", "a\tb", head, "pass", "--level", "static-only"), "a reviewer name has only"),
        ):
            with self.subTest(args=args):
                result = self.run_cli("verdict", *args, "--evidence", "x")
                self.assertEqual(result.returncode, 1, args)
                self.assertIn(message, result.stderr)
        self.assertFalse(self.ledger.exists())


if __name__ == "__main__":
    unittest.main()
