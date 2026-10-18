"""S-022: finding this repo's brew runs in Claude Code's transcripts, for owl's summary (DESIGN § 3.5, § 8)."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

from accio_lib import runs

SUMMARY = ROOT / "bin" / "accio-summary"
STORY = ("---\nid: S-001\ntitle: Reset email\ntrack: story\nstatus: review\n---\n## Definition of Done\n"
         "- [ ] S-001/1 WHEN x THE SYSTEM SHALL y\n")


def workflow(folder, agents, cwd="/somewhere"):
    for number, (agent_type, label, output) in enumerate(agents):
        write(folder / f"agent-{number}.meta.json", json.dumps({"agentType": agent_type, "description": label}))
        line = {"type": "assistant", "cwd": str(cwd), "requestId": f"r{number}",
                "message": {"id": f"m{number}", "usage": {"output_tokens": output}}}
        write(folder / f"agent-{number}.jsonl", json.dumps(line) + "\n")
    return folder


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(base / "my.app")
        self.home = base / "claude-home"
        self.env = {"CLAUDE_CONFIG_DIR": str(self.home)}
        self.project = self.home / "projects" / runs.project_slug(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def brew(self, session, name, when, output=1000, cwd=None):
        folder = workflow(self.project / session / "subagents" / "workflows" / name,
                          [("accio:portkey", "load", 10), ("accio:house-elf", "S-001 implement", output)],
                          cwd or self.repo)
        os.utime(folder, (when, when))
        return folder

    def test_S_022_1_the_slug_is_the_path_with_every_other_character_a_dash(self):
        self.assertEqual(runs.project_slug(pathlib.Path("/Users/a.b/My Plugin")), "-Users-a-b-My-Plugin")

    def test_S_022_1_finds_this_repos_brew_runs_since_a_time_newest_last(self):
        old = self.brew("s1", "wf_old", 1_000)
        first = self.brew("s1", "wf_a", 2_000)
        second = self.brew("s2", "wf_b", 3_000)
        workflow(self.project / "s1" / "subagents" / "workflows" / "wf_other", [("other:agent", "load", 5)])
        workflow(self.home / "projects" / "-elsewhere" / "s9" / "subagents" / "workflows" / "wf_x",
                 [("accio:portkey", "load", 5)])
        self.assertEqual(runs.brew_runs(self.repo, since=1_500, environ=self.env), [first, second])
        self.assertEqual(runs.brew_runs(self.repo, environ=self.env), [old, first, second])

    def test_a_repo_whose_path_has_the_same_slug_is_not_counted(self):
        mine = self.brew("s1", "wf_mine", 2_000)
        self.brew("s2", "wf_twin", 2_000, cwd=self.repo.parent / "my-app")  # my.app and my-app share a slug
        self.assertEqual(runs.brew_runs(self.repo, environ=self.env), [mine])

    def test_summary_latest_refuses_while_a_build_runs(self):
        write(self.repo / ".accio" / "stories" / "S-001.md", STORY)
        write(self.repo / ".accio" / "run" / "brew.lock", "1\n")
        result = subprocess.run([sys.executable, "-I", str(SUMMARY), "--latest"], cwd=self.repo,
                                env={**os.environ, **self.env}, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("build is running", result.stderr)

    def test_S_022_1_summary_latest_takes_the_costs_from_the_runs_since_the_iteration_was_planned(self):
        accio = self.repo / ".accio"
        write(accio / "stories" / "S-001.md", STORY)
        iteration = accio / "iterations" / "1.md"
        write(iteration, "# Iteration 1\n")
        os.utime(iteration, (1_500, 1_500))
        self.brew("s1", "wf_before", 1_000, output=900_000)
        self.brew("s1", "wf_after", 2_000, output=42_000)
        result = subprocess.run([sys.executable, "-I", str(SUMMARY), "--latest"], cwd=self.repo,
                                env={**os.environ, **self.env}, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = (accio / "run" / "owl.md").read_text()
        self.assertIn("42k tokens", text)
        self.assertNotIn("942k", text)

    def test_summary_latest_with_no_run_says_the_cost_is_unknown(self):
        write(self.repo / ".accio" / "stories" / "S-001.md", STORY)
        result = subprocess.run([sys.executable, "-I", str(SUMMARY), "--latest"], cwd=self.repo,
                                env={**os.environ, **self.env}, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cost unknown", (self.repo / ".accio" / "run" / "owl.md").read_text())


if __name__ == "__main__":
    unittest.main()
