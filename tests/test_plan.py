"""S-021: the iteration plan behind `prophecy` (`accio-board plan`, `accio-board go`; DESIGN § 3.3).

The skill's DoD lines are checked by hand and by its evals; these tests pin the rules the skill leans on: which
stories are eligible, the cap, stacking, dropped deps, and what "go" writes.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, git, init_repo, write

from accio_lib import story, storyfiles

BOARD = ROOT / "bin" / "accio-board"


def story_text(story_id, status="backlog", deps=(), track="story", extra=""):
    dep_list = f"deps: [{', '.join(deps)}]  # parents\n" if deps else ""
    return (f"---\nid: {story_id}\ntitle: Story {story_id}\ntrack: {track}  # from accio-score\nstatus: {status}\n"
            f"{dep_list}{extra}---\n## Context\nWhy.\n## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM "
            "SHALL y\n")


class PlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.accio = self.repo / ".accio"
        (self.accio / "stories").mkdir(parents=True)
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.com")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, story_id, **fields):
        write(self.accio / "stories" / f"{story_id}.md", story_text(story_id, **fields))

    def board(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(BOARD), *args], cwd=self.repo, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def plan(self):
        return json.loads(self.board("plan", "--json").stdout)

    def proposed(self):
        return [item["id"] for item in self.plan()["proposed"]]

    def test_S_021_1_proposes_at_most_iteration_max_eligible_stories_in_dependency_order(self):
        for number in range(1, 11):
            self.add(f"S-{number:03d}")
        write(self.accio / "config.json", json.dumps({"iteration_max": 8}))
        plan = self.plan()
        self.assertEqual([item["id"] for item in plan["proposed"]], [f"S-{n:03d}" for n in range(1, 9)])
        self.assertEqual([item["id"] for item in plan["held"]], ["S-009", "S-010"])
        self.assertIn("at most 8", plan["held"][0]["why"])

    def test_S_021_1_a_story_is_eligible_when_its_deps_are_done_or_it_stacks_within_2_levels(self):
        self.add("S-001", status="done")
        self.add("S-002", deps=["S-001"])
        self.add("S-003", deps=["S-002"])
        self.add("S-004", deps=["S-003"])
        self.add("S-005", status="review")
        self.add("S-006", deps=["S-005"])
        plan = self.plan()
        levels = {item["id"]: item["level"] for item in plan["proposed"]}
        self.assertEqual(levels, {"S-002": 1, "S-003": 2})
        self.assertEqual({item["id"] for item in plan["proposed"]} & {"S-004", "S-006"}, set())
        self.assertEqual(plan["held"], [])  # not eligible at all: a dep in review is not done, nor in the iteration

    def test_S_021_1_a_parent_comes_before_its_child_whatever_their_ids(self):
        self.add("S-001", deps=["S-003"])
        self.add("S-003")
        self.assertEqual(self.proposed(), ["S-003", "S-001"])

    def test_S_021_1_a_child_of_a_held_story_is_held_too(self):
        self.add("S-001")
        self.add("S-002")
        self.add("S-003", deps=["S-001", "S-002"])
        self.add("S-004", deps=["S-003"])
        write(self.accio / "config.json", json.dumps({"stack_depth": 3}))
        plan = self.plan()
        self.assertEqual([item["id"] for item in plan["proposed"]], ["S-001", "S-002"])
        self.assertEqual([entry["id"] for entry in plan["held"]], ["S-003", "S-004"])
        self.assertEqual(plan["held"][1]["why"], "it stacks on S-003, which can't go in this iteration")

    def test_S_021_1_dropped_stories_are_never_proposed_and_done_ones_never_again(self):
        self.add("S-001", status="dropped", extra="dropped: not needed\n")
        self.add("S-002", status="done")
        self.add("S-003", status="ready")
        self.assertEqual(self.proposed(), ["S-003"])

    def test_S_021_1_a_child_whose_parent_misses_the_cap_waits_too(self):
        self.add("S-001")
        self.add("S-002", deps=["S-001"])
        self.add("S-003")
        write(self.accio / "config.json", json.dumps({"iteration_max": 1}))
        self.assertEqual(self.proposed(), ["S-001"])

    def test_S_021_1_a_child_with_two_parents_in_the_iteration_waits_for_the_next(self):
        self.add("S-001")
        self.add("S-002")
        self.add("S-003", deps=["S-001", "S-002"])
        plan = self.plan()
        self.assertEqual([item["id"] for item in plan["proposed"]], ["S-001", "S-002"])
        self.assertEqual(plan["held"], [{"id": "S-003", "why": "it stacks on 2 stories of this iteration; it can "
                                                               "go in the next one"}])

    def test_S_021_3_stories_whose_dependency_was_dropped_are_listed_for_a_question(self):
        self.add("S-001", status="dropped")
        self.add("S-002", deps=["S-001"])
        plan = self.plan()
        self.assertEqual(plan["proposed"], [])
        self.assertEqual(plan["dropped_deps"], [{"id": "S-002", "dropped": ["S-001"]}])

    def test_S_021_4_go_moves_the_stories_to_ready_writes_the_iteration_and_the_board(self):
        self.add("S-001")
        self.add("S-002", deps=["S-001"])
        write(self.accio / "iterations" / "1.md", "# Iteration 1\n")
        reply = json.loads(self.board("go", "S-001", "S-002", "--track", "S-002=quick").stdout)
        self.assertEqual(reply["iteration"], 2)
        for story_id, track in (("S-001", "story"), ("S-002", "quick")):
            parsed = story.parse(self.accio / "stories" / f"{story_id}.md")
            self.assertEqual((parsed.meta["status"], parsed.meta["track"]), ("ready", track))
        text = (self.accio / "stories" / "S-002.md").read_text()
        self.assertIn("deps: [S-001]  # parents\n", text)
        self.assertIn("track: quick  # from accio-score\n", text)
        iteration = pathlib.Path(reply["path"]).read_text()
        self.assertEqual(pathlib.Path(reply["path"]), self.accio / "iterations" / "2.md")
        self.assertIn("| S-002 | Story S-002 | quick | S-001 |", iteration)
        self.assertEqual(self.column_of("S-001"), "Ready")
        self.assertEqual(sorted(reply["files"]), sorted([str(self.accio / "stories" / "S-001.md"),
                                                         str(self.accio / "stories" / "S-002.md"),
                                                         reply["path"], str(self.accio / "board.md")]))

    def column_of(self, story_id):
        rows = (self.accio / "board.md").read_text().splitlines()
        header = [cell.strip() for cell in rows[rows.index(next(r for r in rows if r.startswith("| Backlog")))].split("|")]
        for row in rows:
            cells = [cell.strip() for cell in row.split("|")]
            for index, cell in enumerate(cells):
                if cell.startswith(f"{story_id} "):
                    return header[index]
        return None

    def go(self, *args):
        return json.loads(self.board("go", *args).stdout)

    def test_S_021_4_go_commits_its_files_and_the_story_files_passed_with_also_only(self):
        self.add("S-001")
        self.add("S-004")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "backlog")
        edited = self.accio / "stories" / "S-004.md"
        edited.write_text(edited.read_text().replace("status: backlog", "status: dropped\ndropped: not needed"))
        write(self.repo / "notes.txt", "mine\n")
        git(self.repo, "add", "notes.txt")
        write(self.repo / "scratch.txt", "untracked\n")
        reply = self.go("S-001", "--also", ".accio/stories/S-004.md")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "chore(accio): plan iteration 1")
        self.assertEqual(reply["commit"], git(self.repo, "rev-parse", "HEAD"))
        committed = set(git(self.repo, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(committed, {".accio/stories/S-001.md", ".accio/stories/S-004.md", ".accio/iterations/1.md",
                                     ".accio/board.md"})
        self.assertEqual(git(self.repo, "status", "--porcelain").splitlines(), ["A  notes.txt", "?? scratch.txt"])

    def test_S_021_4_planning_the_same_set_again_is_not_a_commit_error(self):
        self.add("S-001")
        first = self.go("S-001")
        again = self.go("S-001")
        self.assertEqual((again["commit"], again["commit_error"]), (first["commit"], None))

    def test_S_021_4_a_refused_commit_leaves_nothing_staged(self):
        self.add("S-001")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        self.go("S-001")
        self.assertEqual(git(self.repo, "diff", "--cached", "--name-only"), "")

    def test_a_failed_write_leaves_no_temp_file(self):
        self.add("S-001")
        self.add("S-002")
        real_chmod, calls = storyfiles.os.chmod, []

        def failing_chmod(path, mode):
            calls.append(path)
            if len(calls) == 2:
                raise OSError("disk full")
            real_chmod(path, mode)

        storyfiles.os.chmod = failing_chmod
        try:
            with self.assertRaises(storyfiles.WriteError):
                storyfiles.write_all({self.accio / "stories" / "S-001.md": "a", self.accio / "stories" / "S-002.md": "b"})
        finally:
            storyfiles.os.chmod = real_chmod
        self.assertEqual(sorted(path.name for path in (self.accio / "stories").iterdir()), ["S-001.md", "S-002.md"])

    def test_S_021_4_also_takes_only_story_files(self):
        self.add("S-001")
        write(self.repo / "src.py", "x = 1\n")
        for path in ("src.py", ".accio/config.json", ".accio/stories/S-009.md", "../outside.md"):
            with self.subTest(path):
                result = self.board("go", "S-001", "--also", path, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("--also", result.stderr)
        self.assertFalse((self.accio / "iterations").exists())

    def test_S_021_4_a_commit_a_hook_refuses_leaves_the_plan_written_and_says_why(self):
        self.add("S-001")
        hook = self.repo / ".git" / "hooks" / "pre-commit"
        write(hook, "#!/bin/sh\necho 'secret found' >&2\nexit 1\n")
        hook.chmod(0o755)
        reply = self.go("S-001")
        self.assertIsNone(reply["commit"])
        self.assertIn("secret found", reply["commit_error"])
        self.assertTrue((self.accio / "iterations" / "1.md").exists())

    def test_S_021_4_a_ready_story_left_out_goes_back_to_the_backlog(self):
        self.add("S-001", status="ready")
        self.add("S-002")
        reply = self.go("S-002")
        self.assertEqual(reply["returned"], ["S-001"])
        self.assertEqual(story.parse(self.accio / "stories" / "S-001.md").meta["status"], "backlog")
        self.assertIn(str(self.accio / "stories" / "S-001.md"), reply["files"])
        self.assertEqual([item["id"] for item in json.loads(self.board("ready", "--json").stdout)], ["S-002"])

    def test_S_021_4_an_iteration_planned_but_not_built_is_planned_again_in_place(self):
        self.add("S-001")
        self.add("S-002")
        self.assertEqual(self.go("S-001")["iteration"], 1)
        self.assertEqual(json.loads(self.board("plan", "--json").stdout)["open_iteration"], 1)
        reply = self.go("S-002")
        self.assertEqual((reply["iteration"], reply["returned"]), (1, ["S-001"]))
        self.assertNotIn("S-001", (self.accio / "iterations" / "1.md").read_text())

    def test_S_021_4_an_iteration_already_building_is_never_overwritten(self):
        self.add("S-001")
        self.add("S-002")
        self.go("S-001")
        path = self.accio / "stories" / "S-001.md"
        path.write_text(path.read_text().replace("status: ready", "status: review"))
        self.assertIsNone(json.loads(self.board("plan", "--json").stdout)["open_iteration"])
        self.assertEqual(self.go("S-002")["iteration"], 2)

    def test_S_021_4_a_failed_go_changes_nothing(self):
        self.add("S-001")
        (self.accio / "iterations").mkdir()
        before = (self.accio / "stories" / "S-001.md").read_text()
        (self.accio / "iterations").chmod(0o500)
        try:
            result = self.board("go", "S-001", check=False)
        finally:
            (self.accio / "iterations").chmod(0o700)
        self.assertEqual(result.returncode, 1)
        self.assertIn("nothing was changed", result.stderr)
        self.assertEqual((self.accio / "stories" / "S-001.md").read_text(), before)
        self.assertFalse((self.accio / "board.md").exists())

    def test_go_keeps_comments_line_endings_and_file_modes(self):
        path = self.accio / "stories" / "S-001.md"
        write(path, story_text("S-001").replace("status: backlog", "status: backlog  # was triaged").replace("\n", "\r\n"))
        path.chmod(0o644)
        self.go("S-001", "--track", "S-001=quick")
        text = path.read_bytes().decode()
        self.assertIn("status: ready  # was triaged\r\n", text)
        self.assertIn("track: quick  # from accio-score\r\n", text)
        self.assertNotIn("\n", text.replace("\r\n", ""))
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_a_title_with_a_pipe_keeps_the_iteration_table_whole(self):
        path = self.accio / "stories" / "S-001.md"
        write(path, story_text("S-001").replace("title: Story S-001", "title: Login | logout"))
        reply = self.go("S-001")
        self.assertIn("| S-001 | Login \\| logout | story | — |", pathlib.Path(reply["path"]).read_text())

    def test_S_021_1_stories_waiting_on_unfinished_work_are_listed_with_what_they_wait_for(self):
        self.add("S-005", status="review")
        self.add("S-006", deps=["S-005"])
        plan = self.plan()
        self.assertEqual(plan["waiting"], [{"id": "S-006", "waits_on": ["S-005 (review)"]}])
        self.assertIn("S-006 waits on S-005 (review)", self.board("plan").stdout)

    def test_S_021_4_go_refuses_an_ineligible_set_and_changes_nothing(self):
        self.add("S-001")
        self.add("S-002", deps=["S-001"])
        self.add("S-003", status="dropped")
        before = {path.name: path.read_text() for path in (self.accio / "stories").iterdir()}
        for args, words in ((["S-002"], "S-002"), (["S-003"], "S-003"), (["S-009"], "S-009"),
                            (["S-001", "--track", "S-001=huge"], "huge"), (["S-001", "--track", "S-002=quick"], "S-002")):
            with self.subTest(args):
                result = self.board("go", *args, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn(words, result.stderr)
        self.assertEqual({path.name: path.read_text() for path in (self.accio / "stories").iterdir()}, before)
        self.assertFalse((self.accio / "iterations").exists())

    def test_go_refuses_during_a_build(self):
        self.add("S-001")
        self.board("lock")
        result = self.board("go", "S-001", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("build is running", result.stderr)

    def test_a_stale_lock_from_a_crash_does_not_block_planning(self):
        self.add("S-001")
        self.board("lock")
        lock = self.accio / "run" / "brew.lock"
        os.utime(lock, (1_600_000_000, 1_600_000_000))
        self.assertEqual(self.go("S-001")["stories"], ["S-001"])


if __name__ == "__main__":
    unittest.main()
