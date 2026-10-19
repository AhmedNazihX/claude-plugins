"""S-004: accio-board (IDs, moves, the ready list with stacking, board.md, the run lock)."""
import concurrent.futures
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import paths, runlock

BOARD = ROOT / "bin" / "accio-board"
CHECKS = [{"command": "python3 -m unittest", "glob": "**/*.py"}]


def story_text(story_id, status="ready", deps=(), title=None, track="story", extra=""):
    dep_list = f"deps: [{', '.join(deps)}]\n" if deps else ""
    return (f"---\nid: {story_id}\ntitle: {title or 'Story ' + story_id}\ntrack: {track}\nstatus: {status}\n"
            f"{dep_list}{extra}---\n## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n")


class BoardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.accio = self.repo / ".accio"
        (self.accio / "stories").mkdir(parents=True)
        self.config()

    def config(self, **settings):
        write(self.accio / "config.json", json.dumps({"checks": CHECKS, **settings}))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, story_id, **fields):
        write(self.accio / "stories" / f"{story_id}.md", story_text(story_id, **fields))

    def board(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(BOARD), *args], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def ready(self):
        return json.loads(self.board("ready", "--json").stdout)

    def test_S_010_1_ready_refuses_without_checks_and_names_config_json_with_an_example(self):
        for text in (None, "{}", json.dumps({"checks": []})):
            if text is None:
                (self.accio / "config.json").unlink()
            else:
                write(self.accio / "config.json", text)
            result = self.board("ready", "--json", check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("config.json", result.stderr)
            self.assertIn('"checks"', result.stderr)
            self.assertIn('"command"', result.stderr)
            self.assertEqual(result.stdout, "")

    def test_S_010_2_a_refused_ready_changes_nothing_on_the_board(self):
        self.add("S-001")
        write(self.accio / "config.json", "{}")
        commit_all(self.repo)
        before = sorted(str(p) for p in self.accio.rglob("*"))
        self.assertEqual(self.board("ready", "--resume", check=False).returncode, 1)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        self.assertEqual(before, sorted(str(p) for p in self.accio.rglob("*")))

    def test_S_010_3_ready_behaves_as_today_when_checks_are_set(self):
        self.add("S-001")
        self.assertEqual([item["id"] for item in self.ready()], ["S-001"])

    # S-004/1
    def test_S_004_1_new_returns_the_next_free_id(self):
        self.assertEqual(self.board("new").stdout.strip(), "S-001")
        self.add("S-001")
        self.add("S-009")
        self.assertEqual(self.board("new").stdout.strip(), "S-010")

    def test_S_004_1_new_goes_past_three_digits(self):
        self.add("S-999")
        self.assertEqual(self.board("new").stdout.strip(), "S-1000")

    # S-004/2 and S-004/7
    def test_S_004_2_move_during_a_build_writes_only_status_json(self):
        self.add("S-001")
        before = (self.accio / "stories" / "S-001.md").read_text(encoding="utf-8")
        self.board("lock")
        self.board("move", "S-001", "doing")
        self.assertEqual((self.accio / "stories" / "S-001.md").read_text(encoding="utf-8"), before)
        status = json.loads((self.accio / "run" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status, {"S-001": "doing"})

    def test_move_rejects_an_unknown_story_or_status(self):
        self.add("S-001")
        self.board("lock")
        self.assertIn("S-404", self.board("move", "S-404", "doing", check=False).stderr)
        self.assertIn("finished", self.board("move", "S-001", "finished", check=False).stderr)

    def test_S_004_7_lock_move_and_unlock_create_refresh_and_remove_the_lock(self):
        self.add("S-001")
        lock = self.accio / "run" / "brew.lock"
        self.board("lock")
        self.assertTrue(lock.is_file())
        old = time.time() - 600
        os.utime(lock, (old, old))
        self.board("move", "S-001", "doing")
        self.assertGreater(lock.stat().st_mtime, old + 300)
        self.board("unlock")
        self.assertFalse(lock.exists())

    def test_S_004_7_move_during_a_long_quiet_build_revives_a_stale_lock(self):
        self.add("S-001")
        self.board("lock")
        lock = self.accio / "run" / "brew.lock"
        old = time.time() - runlock.STALE_SECONDS - 60
        os.utime(lock, (old, old))
        self.board("move", "S-001", "review")
        self.assertGreater(lock.stat().st_mtime, old + runlock.STALE_SECONDS)
        status = json.loads((self.accio / "run" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status, {"S-001": "review"})

    def test_S_004_7_refresh_keeps_the_lock_fresh(self):
        self.board("lock")
        lock = self.accio / "run" / "brew.lock"
        old = time.time() - 600
        os.utime(lock, (old, old))
        self.board("refresh")
        self.assertGreater(lock.stat().st_mtime, old + 300)

    def test_move_outside_a_build_is_refused(self):
        self.add("S-001")
        result = self.board("move", "S-001", "doing", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("during a build", result.stderr)
        self.assertFalse((self.accio / "run" / "status.json").exists())

    def test_S_004_2_parallel_moves_keep_every_update(self):
        ids = [f"S-00{n}" for n in range(1, 7)]
        for story_id in ids:
            self.add(story_id)
        self.board("lock")
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(ids)) as pool:
            results = list(pool.map(lambda sid: self.board("move", sid, "doing", check=False), ids))
        self.assertEqual([r.returncode for r in results], [0] * len(ids), [r.stderr for r in results])
        status = json.loads((self.accio / "run" / "status.json").read_text(encoding="utf-8"))
        self.assertEqual(status, {sid: "doing" for sid in ids})

    def test_S_004_7_parallel_locks_let_exactly_one_win(self):
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: self.board("lock", check=False), range(4)))
        self.assertEqual(sorted(r.returncode for r in results), [0, 1, 1, 1])

    def test_S_004_7_second_lock_is_refused_while_the_first_is_fresh(self):
        self.board("lock")
        result = self.board("lock", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already running", result.stderr)

    def test_S_004_7_stale_lock_is_taken_over_and_says_so(self):
        self.board("lock")
        lock = self.accio / "run" / "brew.lock"
        old = time.time() - runlock.STALE_SECONDS - 60
        os.utime(lock, (old, old))
        result = self.board("lock")
        self.assertIn("stale", result.stdout + result.stderr)

    def test_lock_clears_old_worktree_claims(self):
        write(self.accio / "run" / "claims.json", json.dumps({"agent-1": "/old/wt"}))
        self.board("lock")
        self.assertFalse((self.accio / "run" / "claims.json").exists())

    # S-004/3, /4, /6
    def test_S_004_3_ready_lists_dependency_order_with_stacked_children(self):
        self.add("S-001", status="done")
        self.add("S-002", deps=("S-001",))
        self.add("S-003", deps=("S-002",))
        self.add("S-004")
        ids = [item["id"] for item in self.ready()]
        self.assertEqual(ids, ["S-002", "S-004", "S-003"])
        by_id = {item["id"]: item for item in self.ready()}
        self.assertEqual(by_id["S-003"]["parents"], ["S-002"])
        self.assertEqual(by_id["S-003"]["level"], 2)
        self.assertEqual(by_id["S-002"]["parents"], [])

    def test_S_004_3_a_chain_deeper_than_stack_depth_waits(self):
        self.add("S-001")
        self.add("S-002", deps=("S-001",))
        self.add("S-003", deps=("S-002",))
        self.assertEqual([item["id"] for item in self.ready()], ["S-001", "S-002"])

    def test_S_004_3_stack_depth_comes_from_config(self):
        self.config(stack_depth=1)
        self.add("S-001")
        self.add("S-002", deps=("S-001",))
        self.assertEqual([item["id"] for item in self.ready()], ["S-001"])

    def test_S_004_3_a_dep_in_backlog_keeps_the_story_out(self):
        self.add("S-001", status="backlog")
        self.add("S-002", deps=("S-001",))
        self.assertEqual(self.ready(), [])

    def test_S_004_3_child_stays_listed_while_its_parent_is_doing_or_in_review(self):
        self.add("S-001")
        self.add("S-002", deps=("S-001",))
        self.board("lock")
        for parent_status in ("doing", "review"):
            self.board("move", "S-001", parent_status)
            items = {item["id"]: item for item in self.ready()}
            self.assertEqual(list(items), ["S-002"], parent_status)
            self.assertEqual(items["S-002"]["parents"], ["S-001"])
            self.assertEqual(items["S-002"]["level"], 2)

    def test_S_004_4_parent_blocked_in_this_run_leaves_the_child_out(self):
        self.add("S-001")
        self.add("S-002", deps=("S-001",))
        self.board("lock")
        self.board("move", "S-001", "blocked")
        self.assertEqual(self.ready(), [])

    def test_S_004_6_dropped_is_never_ready_and_holds_its_children(self):
        self.add("S-001", status="dropped", extra="dropped: not needed\n")
        self.add("S-002", deps=("S-001",))
        self.assertEqual(self.ready(), [])

    def test_S_019_6_a_story_a_crash_left_in_doing_is_listed_with_where_to_resume(self):
        self.add("S-001", status="doing")
        self.add("S-002", status="doing")
        self.add("S-003", status="ready")
        commit_all(self.repo, "stories")
        git(self.repo, "branch", "story/S-002")
        git(self.repo, "checkout", "-q", "story/S-002")
        write(self.repo / "work.py", "x = 1\n")
        commit_all(self.repo, "S-002 work")
        git(self.repo, "checkout", "-q", "main")
        listed = json.loads(self.board("ready", "--json", "--resume").stdout)
        self.assertEqual({item["id"]: item["resume"] for item in listed},
                         {"S-001": "prepare", "S-002": "check", "S-003": None})
        self.assertEqual([item["id"] for item in listed][:2], ["S-001", "S-002"])
        self.assertEqual([item["id"] for item in self.ready()], ["S-003"])

    def test_S_019_6_a_stacked_child_resumes_from_its_own_base_not_its_parents(self):
        self.add("S-001", status="doing")
        self.add("S-002", status="doing", deps=("S-001",))
        commit_all(self.repo, "stories")
        git(self.repo, "branch", "story/S-001")
        git(self.repo, "checkout", "-q", "story/S-001")
        write(self.repo / "parent.py", "x = 1\n")
        commit_all(self.repo, "S-001 work")
        git(self.repo, "checkout", "-q", "main")
        worktree = paths.worktree_root(self.repo) / "S-002"
        git(self.repo, "worktree", "add", "-q", str(worktree), "-b", "story/S-002", "story/S-001")
        write(self.accio / "run" / "S-002" / "base", git(self.repo, "rev-parse", "story/S-001") + "\n")
        listed = {item["id"]: item for item in json.loads(self.board("ready", "--json", "--resume").stdout)}
        self.assertEqual((listed["S-001"]["resume"], listed["S-002"]["resume"]), ("check", "prepare"))
        self.assertEqual(listed["S-002"]["worktree"], str(worktree))

    def test_a_dependency_cycle_is_reported(self):
        self.add("S-001", deps=("S-002",))
        self.add("S-002", deps=("S-001",))
        result = self.board("ready", "--json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cycle", result.stderr)

    def test_a_dep_on_a_missing_story_is_reported(self):
        self.add("S-001", deps=("S-404",))
        result = self.board("ready", "--json", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S-404", result.stderr)

    # S-004/5
    def test_S_004_5_board_has_six_columns_and_a_dropped_line(self):
        self.add("S-001", status="done", title="Login page")
        self.add("S-002", status="ready")
        self.add("S-003", status="dropped", extra="dropped: covered by S-002\n")
        self.add("S-004", status="backlog")
        self.board("board")
        text = (self.accio / "board.md").read_text(encoding="utf-8")
        self.assertIn("| Backlog | Ready | Doing | Review | Done | Blocked |", text)
        self.assertIn("| S-004 Story S-004 | S-002 Story S-002 |  |  | S-001 Login page |  |", text)
        self.assertIn("S-001 Login page", text)
        self.assertIn("Dropped: S-003 (covered by S-002)", text)
        self.assertIn("never hand-edit", text)

    def test_status_summarises_the_columns(self):
        self.add("S-001", status="done")
        self.add("S-002", status="ready")
        self.add("S-003", status="ready")
        self.assertIn("ready 2", self.board("status").stdout)

    def test_outside_an_accio_repo_it_says_so(self):
        (self.accio / "stories" / ".keep").touch()
        os.rename(self.accio, self.repo / "elsewhere")
        result = self.board("status", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(".accio", result.stderr)

    def test_a_bad_status_override_names_the_file_and_story(self):
        self.add("S-001")
        write(self.accio / "run" / "status.json", json.dumps({"S-001": "finished"}))
        result = self.board("status", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("status.json", result.stderr)
        self.assertIn("S-001", result.stderr)

    def test_an_unwritable_run_folder_gives_a_plain_message(self):
        self.add("S-001")
        self.board("lock")
        run = self.accio / "run"
        run.chmod(0o500)
        try:
            result = self.board("move", "S-001", "doing", check=False)
        finally:
            run.chmod(0o755)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cannot write", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_malformed_story_names_its_file(self):
        write(self.accio / "stories" / "S-001.md", "---\nid: S-001\n")
        result = self.board("status", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S-001.md", result.stderr)


if __name__ == "__main__":
    unittest.main()
