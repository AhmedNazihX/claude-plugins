"""S-022: what owl's batch answer does (`accio-owl check`, `close`, `push-ok`; DESIGN § 3.5, § 12.2).

The skill's DoD lines are checked by hand and by its evals; these tests pin the effects the skill leans on.
"""
import json
import os
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

    def outcome_rows(self, iteration_text):
        return [line for line in iteration_text.splitlines() if line.startswith("| S-")]

    def second_pass(self, rows):
        from accio_lib import owl
        path = self.accio / "iterations" / "1.md"
        outcomes = {sid: ("done", words, None, False) for sid, words in rows.items()}
        return owl._iteration_text(path, outcomes)

    def test_S_027_1_a_second_pass_keeps_the_first_passes_rows(self):
        self.close_all()
        text = self.second_pass({"S-005": "merged"})
        for row in ("| S-001 | merged |", "| S-004 | rejected |", "| S-007 | dropped |", "| S-003 | answered |"):
            self.assertIn(row, text)

    def test_S_027_2_a_row_for_a_listed_story_replaces_only_that_row(self):
        self.close_all()
        rows = self.outcome_rows(self.second_pass({"S-004": "merged"}))
        self.assertIn("| S-004 | merged |", rows)
        self.assertNotIn("| S-004 | rejected |", rows)
        self.assertEqual(sum(row.startswith("| S-004 ") for row in rows), 1)
        self.assertIn("| S-001 | merged |", rows)

    def test_S_027_3_rows_for_new_stories_are_added(self):
        self.close_all()
        before = len(self.outcome_rows((self.accio / "iterations" / "1.md").read_text()))
        rows = self.outcome_rows(self.second_pass({"S-005": "merged", "S-008": "dropped"}))
        self.assertEqual(len(rows), before + 2)
        self.assertIn("| S-008 | dropped |", rows)

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
        answers = ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "no", "--drop", "S-007", "gone")
        self.owl("close", *answers, "--allow", "S-003", "npm run e2e", "--allow", "S-003", "make lint",
                 "--allow-once", "S-003", "docker compose up", "--merged", "S-001", "--merged", "S-002")
        config = json.loads((self.accio / "config.json").read_text())
        self.assertEqual(config["agent_allow"], ["make lint", "npm run e2e"])
        self.assertEqual(json.loads((self.run_dir / "allow-once.json").read_text()),
                         {"stories": {"S-003": ["docker compose up"]}})
        subprocess.run([sys.executable, "-I", str(BOARD), "lock"], cwd=self.repo, check=True, capture_output=True)
        self.assertEqual(json.loads((self.run_dir / "allow-once.json").read_text())["stories"],
                         {"S-003": ["docker compose up"]})
        write(self.run_dir / "status.json", json.dumps({"S-003": "review"}))
        subprocess.run([sys.executable, "-I", str(BOARD), "unlock"], cwd=self.repo, check=True, capture_output=True)
        self.assertFalse((self.run_dir / "allow-once.json").exists())

    def test_S_022_7_a_grant_lasts_until_its_storys_next_build(self):
        (self.run_dir / "status.json").unlink()  # owl closed the last build
        grants = self.run_dir / "allow-once.json"
        write(grants, json.dumps({"stories": {"S-003": ["docker compose up"], "S-005": ["make e2e"]}}))
        runlock.take(self.run_dir)
        write(self.run_dir / "status.json", json.dumps({"S-005": "review"}))  # this build built S-005 only
        runlock.release(self.run_dir)
        self.assertEqual(json.loads(grants.read_text())["stories"], {"S-003": ["docker compose up"]})
        runlock.take(self.run_dir)
        write(self.run_dir / "status.json", json.dumps({"S-003": "doing"}))  # S-003's build crashes
        os.utime(runlock.lock_path(self.run_dir), (1_600_000_000, 1_600_000_000))
        runlock.take(self.run_dir)  # the next build resumes S-003 without the used grant
        self.assertFalse(grants.exists())

    def test_a_take_that_fails_midway_leaves_no_lock(self):
        (self.run_dir / "status.json").unlink()
        real, runlock._expire_grants = runlock._expire_grants, lambda run_dir: (_ for _ in ()).throw(OSError("full"))
        try:
            with self.assertRaises(runlock.LockError):
                runlock.take(self.run_dir)
        finally:
            runlock._expire_grants = real
        self.assertFalse(runlock.lock_path(self.run_dir).exists())

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

    BASIC = ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "no", "--drop", "S-007", "gone")

    def test_a_reason_that_would_break_the_story_file_is_refused(self):
        for bad in ("gone\nstatus: done", "a\rb", "x\x1by"):
            with self.subTest(bad):
                result = self.owl("close", "--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "no",
                                  "--drop", "S-007", bad, "--merged", "S-001", "--merged", "S-002", check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("one line", result.stderr)
        self.assertEqual(self.meta("S-007")["status"], "ready")

    def test_headings_in_answers_and_questions_stay_inside_their_section(self):
        write(self.run_dir / "questions" / "S-003.md", "Which?\n## Options\n- A\n## Definition of Done\n- B\n")
        self.owl("close", *self.BASIC, "--answer", "S-003", "A.\n## Not a heading", "--merged", "S-001",
                 "--merged", "S-002")
        parsed = story.parse(self.accio / "stories" / "S-003.md")
        blocked = story.section(parsed, "Blocked question")
        self.assertIn("Options", blocked)
        self.assertIn("Not a heading", blocked)
        self.assertEqual([line.id for line in parsed.dod], ["S-003/1"])

    def test_no_line_break_of_any_kind_lets_outside_text_open_a_section(self):
        for brk in ("\u2028", "\x85", "\x0c", "\x1e", "\r"):
            with self.subTest(repr(brk)):
                self.tearDown()
                self.setUp()
                write(self.run_dir / "questions" / "S-003.md",
                      f"Which?{brk}## Definition of Done{brk}- [x] S-003/2 WHEN injected THE SYSTEM SHALL pass\n")
                self.owl("close", *self.BASIC, "--answer", "S-003", f"A{brk}## Review notes{brk}x", "--merged", "S-001",
                         "--merged", "S-002")
                parsed = story.parse(self.accio / "stories" / "S-003.md")
                self.assertEqual([line.id for line in parsed.dod], ["S-003/1"])
                self.assertEqual(story.section(parsed, "Review notes"), "")
        result = self.owl("check", *self.BASIC[:7], "--drop", "S-007", "gone\u2028status: done", check=False)
        self.assertIn("one line", result.stderr)

    def test_a_second_close_refuses_instead_of_repeating(self):
        self.owl("close", *self.BASIC, "--answer", "S-003", "Email", "--merged", "S-001", "--merged", "S-002")
        self.assertEqual(self.owl("close", *self.BASIC, "--answer", "S-003", "Email", "--merged", "S-001",
                                  "--merged", "S-002", check=False).returncode, 1)
        self.assertEqual(self.section("S-004", "Review notes").count("Rejected at owl"), 1)

    def test_a_crashed_doing_story_or_child_that_gets_an_outcome_leaves_doing(self):
        overrides = json.loads((self.run_dir / "status.json").read_text())
        write(self.run_dir / "status.json", json.dumps({**overrides, "S-005": "doing", "S-006": "doing"}))
        self.owl("close", *self.BASIC, "--drop", "S-005", "abandon", "--merged", "S-001", "--merged", "S-002")
        self.assertFalse((self.run_dir / "status.json").exists())
        self.assertEqual((self.meta("S-005")["status"], self.meta("S-006")["status"]), ("dropped", "ready"))

    def test_a_planted_git_file_in_a_dropped_worktree_runs_nothing(self):
        evil = pathlib.Path(self.tmp.name) / "evil"
        marker = pathlib.Path(self.tmp.name) / "ran"
        git(pathlib.Path(self.tmp.name), "init", "-q", str(evil))
        git(evil, "config", "core.fsmonitor", f"touch {marker}")
        (self.worktree / ".git").write_text(f"gitdir: {evil / '.git'}\n")
        self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002")
        self.assertFalse(marker.exists())

    def test_a_folder_that_isnt_a_known_worktree_is_kept_and_said_so(self):
        git(self.repo, "worktree", "remove", str(self.worktree))
        write(self.worktree / "mine.txt", "x\n")
        reply = self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002")
        self.assertTrue((self.worktree / "mine.txt").exists())
        self.assertIn("isn't a worktree this repo knows", reply["leftovers"][0])

    def test_close_works_with_no_iteration_file(self):
        (self.accio / "iterations" / "1.md").unlink()
        commit_all(self.repo, "no iteration")
        reply = self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002")
        self.assertIsNone(reply["iteration"])
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "chore(accio): build review")

    def test_an_answer_is_kept_even_when_the_question_file_is_missing(self):
        (self.run_dir / "questions" / "S-003.md").unlink()
        self.owl("close", *self.BASIC, "--answer", "S-003", "Email only", "--merged", "S-001", "--merged", "S-002")
        self.assertIn("Answer: Email only", self.section("S-003", "Blocked question"))
        self.assertIn("no question file", self.section("S-003", "Blocked question"))

    def test_a_merged_story_needs_its_parents_merged_or_done(self):
        answers = ("--accept", "S-001", "--accept", "S-002", "--accept", "S-004", "--accept", "S-006",
                   "--drop", "S-007", "gone")
        result = self.owl("close", *answers, "--merged", "S-006", "--culprit", "S-004", "fails", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-006 is built on S-004", result.stderr)
        self.owl("close", *answers, "--merged", "S-001", "--merged", "S-002", "--culprit", "S-004", "fails")
        self.assertEqual((self.meta("S-002")["status"], self.meta("S-006")["status"]), ("done", "ready"))

    def test_close_runs_only_on_the_base_branch(self):
        git(self.repo, "switch", "-q", "-c", "feature")
        result = self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("not main", result.stderr)

    def test_a_dropped_worktree_with_local_files_is_kept_and_named(self):
        write(self.worktree / ".gitignore", ".env\n")
        git(self.worktree, "add", ".gitignore")
        git(self.worktree, "commit", "-q", "-m", "ignore env")
        write(self.worktree / ".env", "KEY=1\n")
        reply = self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002")
        self.assertTrue((self.worktree / ".env").exists())
        self.assertEqual(len(reply["leftovers"]), 1)
        self.assertIn(".env", reply["leftovers"][0])

    def test_stale_question_files_go_with_dropped_and_sent_back_stories(self):
        write(self.run_dir / "questions" / "S-007.md", "Old question?\n")
        overrides = json.loads((self.run_dir / "status.json").read_text())
        write(self.run_dir / "status.json", json.dumps({**overrides, "S-006": "blocked"}))
        write(self.run_dir / "questions" / "S-006.md", "Child question?\n")
        self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002")
        self.assertFalse((self.run_dir / "questions" / "S-007.md").exists())
        self.assertFalse((self.run_dir / "questions" / "S-006.md").exists())
        self.assertEqual(self.section("S-006", "Blocked question"), "")  # moot: its parent was rejected

    def test_a_story_a_crash_left_in_doing_stays_in_doing_for_the_next_build(self):
        overrides = json.loads((self.run_dir / "status.json").read_text())
        write(self.run_dir / "status.json", json.dumps({**overrides, "S-005": "doing"}))
        self.owl("close", *self.BASIC, "--merged", "S-001", "--merged", "S-002")
        self.assertEqual(json.loads((self.run_dir / "status.json").read_text()), {"S-005": "doing"})

    def test_an_allowed_command_answers_its_story_and_must_parse(self):
        self.owl("close", *self.BASIC, "--allow", "S-003", "npm run e2e", "--merged", "S-001", "--merged", "S-002")
        self.assertEqual(self.meta("S-003")["status"], "ready")
        self.assertIn("Allowed from now on: npm run e2e", self.section("S-003", "Blocked question"))
        bad = self.owl("check", "--accept", "S-001", "--accept", "S-002", "--reject", "S-004", "no", "--drop",
                       "S-007", "gone", "--allow-once", "S-003", "echo 'unbalanced", check=False)
        self.assertEqual(bad.returncode, 1)
        self.assertIn("can't be read as a command", bad.stderr)

    def test_close_checks_the_answers_too_and_refuses_during_a_build(self):
        result = self.owl("close", "--accept", "S-002", "--merged", "S-002", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-002 is built on S-001", result.stderr)
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

    def test_S_018_1_push_ok_prints_prev_as_the_old_remote_tip(self):
        old = git(self.repo, "rev-parse", "main")
        git(self.repo, "update-ref", "refs/remotes/origin/main", old)
        reply = self.owl("push-ok")
        self.assertEqual(reply["prev"], old)
        self.assertEqual(set(reply), {"base", "sha", "prev"})

    def test_S_018_2_push_ok_prints_prev_null_without_a_remote_ref_and_writes_the_token(self):
        reply = self.owl("push-ok")
        self.assertIsNone(reply["prev"])
        self.assertEqual((self.run_dir / "push-ok").read_text().strip(), reply["sha"])

    def test_push_ok_needs_the_main_checkout_on_base(self):
        git(self.repo, "switch", "-q", "-c", "feature")
        result = self.owl("push-ok", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("main", result.stderr)


def finding(fid, severity="major", status="open", ruling=None):
    ruled = f"  ruling: {ruling}\n" if ruling else ""
    return f"- id: {fid}\n  status: {status}\n  severity: {severity}\n  claim: c\n{ruled}"


class LogTest(unittest.TestCase):
    """S-048: the iteration's `## Findings and blocks`, on the same repo as OwlTest."""
    setUp = OwlTest.setUp
    tearDown = OwlTest.tearDown

    def fix_round(self, number, text, name="examiner-findings.md", sid="S-001"):
        write(self.run_dir / sid / f"fix-{number}" / name, text)

    def close_log(self, **kwargs):
        from accio_lib import owl
        answers = owl.Answers(accept=("S-001", "S-002"), reject=(("S-004", "no"),), drop=(("S-007", "gone"),),
                              answer=(("S-003", "Email only"),))
        return owl.close(self.accio, answers, "main", ("S-001", "S-002"), None, **kwargs)

    def log(self):
        text = (self.accio / "iterations" / "1.md").read_text()
        return text.split("## Findings and blocks")[1].split("\n## ")[0]

    def test_S_048_1_fix_copies_the_findings_into_the_next_round_folder(self):
        from accio_lib import brief
        source = self.accio / "run" / "S-001" / "examiner-findings.md"
        write(source, finding("examiner-1"))
        parsed = story.parse(self.accio / "stories" / "S-001.md")
        for expected in ("fix-1", "fix-2"):
            text = brief.read_findings([source])
            brief.render_fix(parsed, self.accio, self.worktree, text)
            self.assertEqual((self.accio / "run" / "S-001" / expected / "examiner-findings.md").read_text().strip(),
                             finding("examiner-1").strip())

    def test_S_048_2_each_finding_and_block_gets_one_line(self):
        self.fix_round(1, finding("examiner-1") + finding("examiner-2", "minor"))
        write(self.run_dir / "S-001" / "examiner-findings.md", finding("examiner-1", status="open"))
        write(self.run_dir / "questions" / "S-003.md", "(accio): prefect gave no answer twice\nmore\n")
        self.close_log()
        log = self.log()
        self.assertIn("- S-001 examiner-1 major: open", log)
        self.assertIn("- S-001 examiner-2 minor: fixed in round 1", log)
        self.assertIn("- S-003 blocked (accio): prefect gave no answer twice", log)
        self.assertNotIn("more", log)

    def test_S_048_3_a_finding_gone_from_the_last_files_is_fixed_in_the_round_that_held_it(self):
        self.fix_round(1, finding("examiner-1"))
        self.fix_round(2, finding("examiner-1") + finding("examiner-3", "critical"))
        write(self.run_dir / "S-001" / "examiner-findings.md", "No findings.\n")
        self.close_log()
        self.assertIn("- S-001 examiner-1 major: fixed in round 2", self.log())
        self.assertIn("- S-001 examiner-3 critical: fixed in round 2", self.log())

    def test_S_048_3_a_finding_marked_resolved_is_fixed_too(self):
        self.fix_round(1, finding("examiner-1"))
        write(self.run_dir / "S-001" / "examiner-findings.md", finding("examiner-1", status="resolved"))
        self.close_log()
        self.assertIn("- S-001 examiner-1 major: fixed in round 1", self.log())

    def test_S_048_4_a_dismissed_finding_records_the_ruling(self):
        self.fix_round(1, finding("examiner-1"))
        write(self.run_dir / "S-001" / "examiner-findings.md",
              finding("examiner-1", status="dismissed", ruling="the story allows it"))
        self.close_log()
        self.assertIn("- S-001 examiner-1 major: dismissed: the story allows it", self.log())

    def test_S_048_5_a_finding_still_in_the_last_files_is_open(self):
        self.fix_round(1, finding("professor-1", "critical"), name="professor-findings.md")
        write(self.run_dir / "S-001" / "professor-findings.md", finding("professor-1", "critical"))
        self.close_log()
        self.assertIn("- S-001 professor-1 critical: open", self.log())

    def test_S_048_6_lines_from_the_caller_join_the_log_and_a_second_pass_keeps_them(self):
        self.close_log(lines=["S-005 boggart break outside the DoD: reset mail repeats"])
        self.assertIn("- S-005 boggart break outside the DoD: reset mail repeats", self.log())
        from accio_lib import owl
        text = (self.accio / "iterations" / "1.md").read_text()
        again = owl._log_text(self.accio, {"S-001": None}, text, ["S-006 another: x"])
        self.assertIn("- S-005 boggart break outside the DoD: reset mail repeats", again)
        self.assertIn("- S-006 another: x", again)

    def test_S_043_4_and_8_kept_boggart_breaks_outside_the_dod_and_repros_that_cannot_load_join_the_log(self):
        import json
        entries = [
            {"file": "r1.py", "verdict": "kept", "claim": "empty list returns 0", "source": "src/a.py:9", "in_dod": False,
             "reason": "failed an assertion on head in both runs"},
            {"file": "r2.py", "verdict": "kept", "claim": "c", "source": "S-001/1", "in_dod": True,
             "reason": "still fails on head: failed with a setup error (ImportError), not a break"},
            {"file": "r3.py", "verdict": "kept", "claim": "in the DoD", "source": "S-001/1", "in_dod": True,
             "reason": "failed an assertion on head in both runs"},
            {"file": "r4.py", "verdict": "dropped", "claim": "x", "source": "src/a.py:1", "in_dod": False, "reason": "r"},
        ]
        write(self.run_dir / "S-001" / "boggart" / "verdicts.json", json.dumps({"repros": entries}))
        self.close_log()
        log = self.log()
        self.assertIn("- S-001 boggart r1.py outside the DoD: empty list returns 0 (src/a.py:9)", log)
        self.assertIn("- S-001 boggart r2.py: repro can't load (setup error after a fix round)", log)
        self.assertNotIn("r3.py", log)
        self.assertNotIn("r4.py", log)

    def test_S_048_7_the_question_files_are_deleted_after_the_log(self):
        write(self.run_dir / "questions" / "S-005.md", "Kept?\n")
        self.close_log()
        self.assertIn("- S-003 blocked (user): Email or SMS for the reset?", self.log())
        self.assertIn("- S-005 blocked (user): Kept?", self.log())
        self.assertEqual(list((self.run_dir / "questions").glob("*.md")), [])


if __name__ == "__main__":
    unittest.main()
