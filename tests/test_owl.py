"""S-022: what owl's batch answer does (`accio-owl check`, `close`, `push-ok`; DESIGN § 3.5, § 12.2).

The skill's DoD lines are checked by hand and by its evals; these tests pin the effects the skill leans on.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import paths, runlock, story

OWL = ROOT / "bin" / "accio-owl"
BOARD = ROOT / "bin" / "accio-board"


def story_text(story_id, deps=(), status="ready"):
    dep_list = f"deps: [{', '.join(deps)}]\n" if deps else ""
    return (f"---\nid: {story_id}\ntitle: Story {story_id}\ntrack: story\nstatus: {status}\n{dep_list}---\n"
            f"## Context\nWhy.\n## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n"
            "## Review notes\n## Blocked question\n")


class OwlTest(unittest.TestCase):
    """After a build: S-001 and its child S-002 in review, S-003 blocked with a question, S-004 in review with its
    child S-006, S-007 in review with a worktree, S-005 untouched in Ready."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.com")
        self.accio = self.repo / ".accio"
        deps = {"S-002": ["S-001"], "S-006": ["S-004"]}
        for number in (1, 2, 3, 4, 5, 6, 7):
            sid = f"S-{number:03d}"
            write(self.accio / "stories" / f"{sid}.md", story_text(sid, deps.get(sid, ())))
        write(self.accio / "config.json", json.dumps({"agent_allow": ["make lint"]}, indent=2) + "\n")
        write(self.accio / "iterations" / "1.md", "# Iteration 1\n\n| Story | Title | Track | Stacked on |\n"
              "|---|---|---|---|\n| S-001 | Story S-001 | story | — |\n\n## Outcome\n\nWritten by `/accio:owl`.\n")
        commit_all(self.repo, "planned")
        self.run_dir = self.accio / "run"
        overrides = {"S-001": "review", "S-002": "review", "S-003": "blocked", "S-004": "review", "S-006": "review",
                     "S-007": "review"}
        write(self.run_dir / "status.json", json.dumps(overrides))
        write(self.run_dir / "questions" / "S-003.md", "Email or SMS for the reset?\n")
        write(self.run_dir / "ledger.tsv", "S-004\tk4\tpass\nS-006\tk6\tpass\nS-001\tk1\tpass\n")
        self.worktree = paths.worktree_root(self.repo) / "S-007"
        git(self.repo, "worktree", "add", "-q", str(self.worktree), "-b", "story/S-007")

    def tearDown(self):
        self.tmp.cleanup()

    def owl(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(OWL), *args], cwd=self.repo, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def meta(self, story_id):
        return story.parse(self.accio / "stories" / f"{story_id}.md").meta

    def section(self, story_id, heading):
        return story.section(story.parse(self.accio / "stories" / f"{story_id}.md"), heading)

    ANSWERS = ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "the reset link expires too soon",
               "--accept", "S-006", "--drop", "S-007", "we use the provider's page", "--answer", "S-003", "Email only")

    def test_S_022_2_accepting_a_child_without_its_parent_is_refused_in_plain_words(self):
        result = self.owl("check", "--accept", "S-002", "--reject", "S-001", "no", "--reject", "S-004", "no",
                          "--reject", "S-006", "no", "--reject", "S-007", "no", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-002 is built on S-001", result.stderr)
        self.assertIn("accept S-001 too", result.stderr)

    def test_S_022_2_a_child_of_a_rejected_parent_cant_be_accepted_either(self):
        result = self.owl("check", *self.ANSWERS, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-006 is built on S-004", result.stderr)

    def test_S_022_1_every_story_in_review_needs_a_verdict_and_only_one(self):
        result = self.owl("check", "--accept", "S-001", check=False)
        self.assertEqual(result.returncode, 1)
        for sid in ("S-002", "S-004", "S-006", "S-007"):
            self.assertIn(sid, result.stderr)
        twice = self.owl("check", "--accept", "S-001", "--drop", "S-001", "x", check=False)
        self.assertIn("S-001 has two answers", twice.stderr)

    def test_S_022_1_only_review_stories_get_verdicts_and_only_blocked_ones_answers(self):
        for args, words in ((("--reject", "S-003", "no"), "S-003 is blocked"), (("--answer", "S-001", "x"), "S-001 is in review"),
                            (("--accept", "S-005"), "S-005 is ready")):
            with self.subTest(args):
                result = self.owl("check", *args, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn(words, result.stderr)

    def test_S_022_1_check_returns_the_accepted_stories_in_merge_order(self):
        answers = ("--accept", "S-002", "--accept", "S-001", "--reject", "S-004", "no", "--reject", "S-006", "no",
                   "--drop", "S-007", "gone")
        self.assertEqual(self.owl("check", *answers)["accept"], ["S-001", "S-002"])

    def close_all(self, *extra):
        # S-006 is stacked on S-004, which is rejected: it goes back to Ready with no verdict of its own
        answers = ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "the link expires too soon",
                   "--drop", "S-007", "we use the provider's page", "--answer", "S-003", "Email only")
        return self.owl("close", *answers, "--merged", "S-001", "--merged", "S-002", *extra)

    def test_S_022_3_reject_writes_the_notes_clears_the_ledger_and_sends_the_story_and_its_children_back(self):
        self.close_all()
        self.assertEqual(self.meta("S-004")["status"], "ready")
        self.assertIn("the link expires too soon", self.section("S-004", "Review notes"))
        self.assertEqual(self.meta("S-006")["status"], "ready")
        self.assertIn("S-004 was rejected", self.section("S-006", "Review notes"))
        ledger = (self.run_dir / "ledger.tsv").read_text()
        self.assertNotIn("S-004\t", ledger)
        self.assertNotIn("S-006\t", ledger)
        self.assertIn("S-001\tk1", ledger)

    def test_S_022_4_drop_sets_dropped_with_the_reason_and_removes_the_worktree_keeping_the_branch(self):
        reply = self.close_all()
        self.assertEqual((self.meta("S-007")["status"], self.meta("S-007")["dropped"]),
                         ("dropped", "we use the provider's page"))
        self.assertFalse(self.worktree.exists())
        self.assertEqual(git(self.repo, "branch", "--list", "story/S-007").strip(), "story/S-007")
        self.assertEqual(reply["leftovers"], [])

    def test_S_022_1_answers_go_into_the_story_and_the_story_back_to_ready(self):
        self.close_all()
        self.assertEqual(self.meta("S-003")["status"], "ready")
        blocked = self.section("S-003", "Blocked question")
        self.assertIn("Email or SMS for the reset?", blocked)
        self.assertIn("Answer: Email only", blocked)
        self.assertFalse((self.run_dir / "questions" / "S-003.md").exists())

    def test_S_022_5_close_folds_the_statuses_writes_the_outcome_and_makes_one_commit(self):
        reply = self.close_all()
        self.assertEqual((self.meta("S-001")["status"], self.meta("S-002")["status"]), ("done", "done"))
        self.assertEqual(self.meta("S-005")["status"], "ready")
        self.assertFalse((self.run_dir / "status.json").exists())
        outcome = (self.accio / "iterations" / "1.md").read_text()
        self.assertNotIn("Written by `/accio:owl`.", outcome)
        for row in ("| S-001 | merged |", "| S-004 | rejected |", "| S-006 | back to Ready (S-004 was rejected) |",
                    "| S-007 | dropped |", "| S-003 | answered |"):
            self.assertIn(row, outcome)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "chore(accio): iteration 1 review")
        self.assertEqual(reply["commit"], git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(git(self.repo, "status", "--porcelain", "--", ".accio/stories", ".accio/iterations",
                             ".accio/board.md"), "")

    def test_S_022_5_a_merge_culprit_goes_back_with_the_failure_and_unmerged_stories_carry_over(self):
        answers = ("--accept", "S-001", "--accept", "S-002", "--accept", "S-004", "--accept", "S-006",
                   "--drop", "S-007", "gone", "--answer", "S-003", "Email")
        self.owl("close", *answers, "--merged", "S-001", "--culprit", "S-004", "npm test fails after the merge")
        self.assertEqual(self.meta("S-001")["status"], "done")
        self.assertEqual(self.meta("S-004")["status"], "ready")
        self.assertIn("npm test fails after the merge", self.section("S-004", "Review notes"))
        self.assertEqual(self.meta("S-006")["status"], "ready")
        self.assertEqual(self.meta("S-002")["status"], "review")

    def test_S_022_7_allow_from_now_on_goes_to_agent_allow_and_allow_once_to_the_next_build_only(self):
        self.close_all("--allow", "npm run e2e", "--allow", "make lint", "--allow-once", "docker compose up")
        config = json.loads((self.accio / "config.json").read_text())
        self.assertEqual(config["agent_allow"], ["make lint", "npm run e2e"])
        self.assertEqual(json.loads((self.run_dir / "allow-once.json").read_text()), ["docker compose up"])
        subprocess.run([sys.executable, "-I", str(BOARD), "lock"], cwd=self.repo, check=True, capture_output=True)
        subprocess.run([sys.executable, "-I", str(BOARD), "unlock"], cwd=self.repo, check=True, capture_output=True)
        self.assertFalse((self.run_dir / "allow-once.json").exists())

    def test_S_022_1_an_unanswered_blocked_story_keeps_its_question_in_the_story_file(self):
        answers = ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "no", "--drop", "S-007", "gone")
        self.owl("close", *answers, "--merged", "S-001", "--merged", "S-002")
        self.assertEqual(self.meta("S-003")["status"], "blocked")
        self.assertIn("Email or SMS for the reset?", self.section("S-003", "Blocked question"))

    def test_close_takes_only_accepted_stories_as_merged_or_culprit(self):
        answers = ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "no", "--drop", "S-007", "gone")
        for extra in (("--merged", "S-004"), ("--culprit", "S-007", "it broke")):
            with self.subTest(extra):
                result = self.owl("close", *answers, *extra, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("only accepted stories", result.stderr)
        self.assertEqual(self.meta("S-004")["status"], "ready")  # the story file: nothing was written
        self.assertTrue((self.run_dir / "status.json").exists())

    def test_close_checks_the_answers_too_and_refuses_during_a_build(self):
        result = self.owl("close", "--accept", "S-002", "--merged", "S-002", check=False)
        self.assertEqual(result.returncode, 1)
        runlock.take(self.run_dir)
        result = self.owl("close", *self.ANSWERS[:4], check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("build is running", result.stderr)
        self.assertEqual(self.meta("S-001")["status"], "ready")

    def test_S_022_5_push_ok_names_base_head_only_after_the_build(self):
        sha = git(self.repo, "rev-parse", "main")
        self.assertEqual(self.owl("push-ok")["sha"], sha)
        self.assertEqual((self.run_dir / "push-ok").read_text().strip(), sha)
        (self.run_dir / "push-ok").unlink()
        runlock.take(self.run_dir)
        result = self.owl("push-ok", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("build is running", result.stderr)
        self.assertFalse((self.run_dir / "push-ok").exists())

    def test_push_ok_needs_the_main_checkout_on_base(self):
        git(self.repo, "switch", "-q", "-c", "feature")
        result = self.owl("push-ok", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("main", result.stderr)


if __name__ == "__main__":
    unittest.main()
