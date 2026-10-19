"""S-005: one what's-next rule, `accio_lib/nextstep.py`, run by `accio-board next` and read by session-start."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, init_repo, write

from accio_lib import nextstep, runlock

BOARD = ROOT / "bin" / "accio-board"


def story_text(story_id, status):
    return (f"---\nid: {story_id}\ntitle: Story {story_id}\ntrack: story\nstatus: {status}\n---\n"
            f"## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n")


class NextStepTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.accio = self.repo / ".accio"
        write(self.repo / ".gitignore", ".accio/run/\n")
        write(self.accio / "config.json", "{}\n")
        write(self.accio / "design.md", "# Design\n")
        commit_all(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, story_id, status):
        write(self.accio / "stories" / f"{story_id}.md", story_text(story_id, status))

    def run_next(self, *flags):
        result = subprocess.run([sys.executable, str(BOARD), "next", *flags], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def check(self, step, auto):
        reply = json.loads(self.run_next("--json"))
        self.assertEqual((reply["step"], reply["auto"]), (step, auto), reply)

    def test_S_005_1_json_has_step_auto_and_the_sentence(self):
        self.add("S-001", "ready")
        reply = json.loads(self.run_next("--json"))
        self.assertEqual(set(reply), {"step", "auto", "sentence"})
        self.assertIn("/accio:brew", reply["sentence"])
        self.assertEqual(self.run_next().strip(), reply["sentence"])

    def test_S_005_2_every_state_gives_its_step_and_auto(self):
        (self.accio / "design.md").unlink()
        self.check("wand", False)
        write(self.accio / "design.md", "# Design\n")
        self.check("sort", True)
        self.add("S-001", "done")
        self.check("done", False)
        self.add("S-002", "backlog")
        self.check("prophecy", True)
        self.add("S-003", "ready")
        self.check("brew", True)
        self.add("S-004", "blocked")
        self.check("owl", False)
        self.add("S-004", "review")
        self.check("owl", True)
        self.add("S-005", "doing")
        self.check("brew", True)
        runlock.take(self.accio / "run")
        self.check("wait", False)

    def test_S_008_1_prophecy_is_auto_when_the_plan_has_no_dropped_dep(self):
        self.add("S-001", "done")
        self.add("S-002", "backlog")
        self.check("prophecy", True)

    def test_S_008_2_prophecy_is_not_auto_when_the_plan_has_a_dropped_dep(self):
        self.add("S-001", "dropped")
        write(self.accio / "stories" / "S-002.md",
              story_text("S-002", "backlog").replace("track: story\n", "track: story\ndeps: [S-001]\n"))
        self.check("prophecy", False)

    def test_S_008_3_owl_is_auto_when_the_review_has_only_ready_stories(self):
        self.add("S-001", "review")
        self.add("S-002", "review")
        self.check("owl", True)

    def test_S_008_4_owl_is_not_auto_when_the_review_holds_a_blocked_story(self):
        self.add("S-001", "review")
        self.add("S-002", "blocked")
        self.check("owl", False)

    def test_S_005_2_workflows_off_changes_the_sentence_not_the_step(self):
        reply = nextstep.next_step(self.accio, {"S-001": "ready"}, True)
        self.assertEqual((reply["step"], reply["auto"]), ("brew", True))
        self.assertIn("once workflows are on", reply["sentence"])

    def test_S_005_3_session_start_uses_nextstep_and_holds_no_copy(self):
        text = (ROOT / "hooks" / "session_start.py").read_text(encoding="utf-8")
        self.assertIn("nextstep", text)
        self.assertNotIn("def next_step", text)
        self.assertNotIn("/accio:sort", text)
        self.assertNotIn("/accio:prophecy", text)

    def test_S_005_4_map_runs_accio_board_next_and_holds_no_rule_list(self):
        text = (ROOT / "skills" / "map" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("accio-board next", text)
        for command in ("/accio:sort", "/accio:prophecy", "/accio:wand", "/accio:brew"):
            self.assertNotIn(command, text)


if __name__ == "__main__":
    unittest.main()
