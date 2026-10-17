"""S-008: accio-merge (integration branch, full checks, culprit, fast-forward, cleanup)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

MERGE = ROOT / "bin" / "accio-merge"
CHECK = "import pathlib, sys\nsys.exit(1 if any('BROKEN' in p.read_text() for p in pathlib.Path('src').glob('*.py')) else 0)\n"


def story_text(story_id, deps=(), story_type="feat", status="review"):
    dep_line = f"deps: [{', '.join(deps)}]\n" if deps else ""
    return (f"---\nid: {story_id}\ntitle: Story {story_id}\ntype: {story_type}\ntrack: story\nstatus: {status}\n"
            f"{dep_line}---\n## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n")


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")
        write(self.repo / "check.py", CHECK)
        write(self.repo / "src" / "app.py", "value = 1\n")
        write(self.repo / ".gitignore", ".accio/run/\n")
        commit_all(self.repo, "base")
        self.accio = self.repo / ".accio"
        write(self.accio / "config.json", json.dumps({"checks": [{"command": "python3 check.py", "glob": "**/*.py"}]}))
        self.wt_root = self.base / ".app-accio-wt"

    def tearDown(self):
        self.tmp.cleanup()

    def story(self, story_id, files, deps=(), parent=None, story_type="feat"):
        write(self.accio / "stories" / f"{story_id}.md", story_text(story_id, deps, story_type))
        worktree = self.wt_root / story_id
        git(self.repo, "worktree", "add", "-q", str(worktree), "-b", f"story/{story_id}", parent or "main")
        for name, text in files.items():
            write(worktree / name, text)
        commit_all(worktree, f"work on {story_id}")
        return worktree

    def use_checks(self, *commands):
        write(self.accio / "config.json", json.dumps({"checks": [{"command": c, "glob": "**/*.py"} for c in commands]}))

    def merge(self, number, *ids, check=True):
        result = subprocess.run([sys.executable, "-I", str(MERGE), str(number), *ids], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def first_parent_subjects(self):
        return git(self.repo, "log", "--first-parent", "--format=%s", "main").splitlines()

    # S-008/1 and /2
    def test_S_008_1_merges_no_ff_in_dependency_order_with_conventional_messages(self):
        self.story("S-001", {"src/one.py": "one = 1\n"}, story_type="fix")
        self.story("S-002", {"src/two.py": "two = 2\n"}, deps=("S-001",), parent="story/S-001")
        old_main = git(self.repo, "rev-parse", "main")
        reply = self.merge(1, "S-002", "S-001")
        self.assertEqual(reply["result"], "merged")
        self.assertEqual(reply["merged"], ["S-001", "S-002"])
        self.assertEqual(self.first_parent_subjects()[:2], ["feat(S-002): Story S-002", "fix(S-001): Story S-001"])
        merge_parents = git(self.repo, "log", "-1", "--format=%p", "main").split()
        self.assertEqual(len(merge_parents), 2)
        self.assertEqual(git(self.repo, "merge-base", "--is-ancestor", old_main, "main"), "")
        self.assertEqual(reply["main"], git(self.repo, "rev-parse", "main"))

    # S-008/3
    def test_S_008_3_failing_checks_leave_main_alone_and_name_the_culprit(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        self.story("S-002", {"src/two.py": "two = 'BROKEN'\n"})
        self.story("S-003", {"src/three.py": "three = 3\n"})
        old_main = git(self.repo, "rev-parse", "main")
        reply = self.merge(1, "S-001", "S-002", "S-003")
        self.assertEqual(reply["result"], "checks_failed")
        self.assertEqual(reply["culprit"], "S-002")
        self.assertEqual(reply["failing"], ["python3 check.py"])
        self.assertEqual(git(self.repo, "rev-parse", "main"), old_main)
        self.assertTrue((self.wt_root / "S-001").is_dir())
        self.assertNotIn("accio/integrate-1", git(self.repo, "branch", "--list", "accio/*"))

    # S-008/4
    def test_S_008_4_uncommitted_changes_in_the_same_files_stop_with_a_question(self):
        self.story("S-001", {"src/app.py": "value = 2\n"})
        write(self.repo / "src" / "app.py", "value = 99  # my local edit\n")
        old_main = git(self.repo, "rev-parse", "main")
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "needs_user")
        self.assertIn("src/app.py", reply["question"])
        self.assertEqual(git(self.repo, "rev-parse", "main"), old_main)
        self.assertEqual((self.repo / "src" / "app.py").read_text(), "value = 99  # my local edit\n")

    def test_uncommitted_changes_in_other_files_are_kept_and_the_merge_goes_on(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        write(self.repo / "notes.txt", "my notes\n")
        self.assertEqual(self.merge(1, "S-001")["result"], "merged")
        self.assertEqual((self.repo / "notes.txt").read_text(), "my notes\n")
        self.assertTrue((self.repo / "src" / "one.py").is_file())

    def test_main_checked_out_elsewhere_than_the_main_checkout_still_fast_forwards(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        git(self.repo, "switch", "-q", "-c", "side")
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "merged")
        self.assertEqual(git(self.repo, "rev-parse", "main"), reply["main"])

    # S-008/5
    def test_S_008_5_success_removes_worktrees_and_branches(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        self.merge(1, "S-001")
        self.assertFalse((self.wt_root / "S-001").exists())
        self.assertFalse((self.wt_root / "integrate-1").exists())
        self.assertEqual(git(self.repo, "branch", "--list", "story/*", "accio/*"), "")

    # S-008/6
    def test_S_008_6_a_leftover_integration_branch_is_rebuilt(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        git(self.repo, "worktree", "add", "-q", str(self.wt_root / "integrate-1"), "-b", "accio/integrate-1", "main")
        write(self.wt_root / "integrate-1" / "junk.txt", "half done\n")
        commit_all(self.wt_root / "integrate-1", "crashed midway")
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "merged")
        self.assertNotIn("crashed midway", git(self.repo, "log", "--format=%s", "main"))

    def test_work_left_in_a_story_worktree_survives_and_is_reported(self):
        worktree = self.story("S-001", {"src/one.py": "one = 1\n"})
        write(worktree / "notes-untracked.txt", "keep me\n")
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "merged")
        self.assertEqual((worktree / "notes-untracked.txt").read_text(), "keep me\n")
        self.assertIn("story/S-001", git(self.repo, "branch", "--list", "story/*"))
        self.assertIn(str(worktree), reply["leftovers"])

    def test_a_check_that_leaves_files_behind_does_not_fail_a_finished_merge(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        self.use_checks("python3 check.py", "python3 -c \"open('coverage.txt', 'w').write('x')\"")
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "merged")
        self.assertFalse((self.wt_root / "integrate-1").exists())

    def test_an_ignored_local_file_the_merge_would_overwrite_stops_with_a_question(self):
        write(self.repo / ".gitignore", ".accio/run/\nlocal.cfg\n")
        commit_all(self.repo, "ignore local.cfg")
        write(self.repo / "local.cfg", "my secret settings\n")
        self.story("S-001", {".gitignore": ".accio/run/\n", "local.cfg": "shared = 1\n"})
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "needs_user")
        self.assertIn("local.cfg", reply["question"])
        self.assertEqual((self.repo / "local.cfg").read_text(), "my secret settings\n")

    def test_renames_untracked_folders_and_spaces_are_seen_as_overlaps(self):
        self.story("S-001", {"src/my file.py": "x = 1\n", "src/newdir/f.py": "y = 1\n"})
        git(self.wt_root / "S-001", "mv", "src/app.py", "src/main.py")
        commit_all(self.wt_root / "S-001", "rename")
        write(self.repo / "src" / "app.py", "value = 5  # local\n")
        write(self.repo / "src" / "newdir" / "f.py", "mine\n")
        write(self.repo / "src" / "my file.py", "mine too\n")
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "needs_user")
        for path in ("src/app.py", "src/newdir/f.py", "src/my file.py"):
            self.assertIn(path, reply["question"])

    def test_the_culprit_search_survives_a_check_that_edits_files(self):
        write(self.repo / "mutating_check.py", CHECK.replace("import pathlib, sys\n",
              "import pathlib, sys\npathlib.Path('src/one.py').write_text('edited by the check\\n')\n"
              "pathlib.Path('src/two.py').write_text(pathlib.Path('src/two.py').read_text() if "
              "pathlib.Path('src/two.py').exists() else 'created by the check\\n')\n"))
        commit_all(self.repo, "a check that edits a tracked file")
        self.use_checks("python3 mutating_check.py")
        self.story("S-001", {"src/one.py": "one = 1\n"})
        self.story("S-002", {"src/two.py": "two = 'BROKEN'\n"})
        reply = self.merge(1, "S-001", "S-002")
        self.assertEqual((reply["result"], reply["culprit"]), ("checks_failed", "S-002"))

    def test_a_check_already_failing_on_base_blames_no_story(self):
        write(self.repo / "src" / "old.py", "old = 'BROKEN'\n")
        commit_all(self.repo, "base already broken")
        self.story("S-001", {"src/one.py": "one = 1\n"})
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "checks_failed")
        self.assertIsNone(reply["culprit"])
        self.assertTrue(reply["base_failing"])

    def test_a_story_breaking_another_check_is_blamed_even_when_base_fails_one(self):
        write(self.repo / "src" / "old.py", "old = 'BROKEN'\n")
        write(self.repo / "two_check.py", "import pathlib, sys\nsys.exit(1 if pathlib.Path('src/two.py').exists() else 0)\n")
        commit_all(self.repo, "base fails check.py; two_check.py passes")
        self.use_checks("python3 check.py", "python3 two_check.py")
        self.story("S-001", {"src/one.py": "one = 1\n"})
        self.story("S-002", {"src/two.py": "two = 2\n"})
        reply = self.merge(1, "S-001", "S-002")
        self.assertEqual((reply["culprit"], reply["base_failing"]), ("S-002", True))

    def test_the_culprit_is_found_cumulatively(self):
        write(self.repo / "pair_check.py", "import pathlib, sys\n"
              "sys.exit(1 if all(pathlib.Path(f'src/{n}.py').exists() for n in ('a_part', 'b_part')) else 0)\n")
        commit_all(self.repo, "pair check")
        self.use_checks("python3 pair_check.py")
        self.story("S-001", {"src/a_part.py": "a = 1\n"})
        self.story("S-002", {"src/b_part.py": "b = 1\n"})
        self.assertEqual(self.merge(1, "S-001", "S-002")["culprit"], "S-002")

    def test_a_merge_refused_by_a_hook_is_not_called_a_conflict(self):
        hook = pathlib.Path(git(self.repo, "rev-parse", "--git-common-dir")) / "hooks" / "pre-merge-commit"
        if not hook.is_absolute():
            hook = self.repo / hook
        write(hook, "#!/bin/sh\necho 'merges are frozen' >&2\nexit 1\n")
        hook.chmod(0o755)
        self.story("S-001", {"src/one.py": "one = 1\n"})
        result = self.merge(1, "S-001", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("merges are frozen", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn("accio/integrate-1", git(self.repo, "branch", "--list", "accio/*"))

    def test_check_output_that_is_not_utf8_is_kept_without_a_crash(self):
        self.use_checks("printf 'bad \\377 byte\\n'; exit 1")
        self.story("S-001", {"src/one.py": "one = 1\n"})
        reply = self.merge(1, "S-001")
        self.assertEqual(reply["result"], "checks_failed")
        self.assertIn("bad", reply["failure_output"][reply["failing"][0]])

    def test_a_conflict_between_stories_names_the_story(self):
        self.story("S-001", {"src/app.py": "value = 2\n"})
        self.story("S-002", {"src/app.py": "value = 3\n"})
        old_main = git(self.repo, "rev-parse", "main")
        reply = self.merge(1, "S-001", "S-002")
        self.assertEqual(reply["result"], "conflict")
        self.assertEqual(reply["culprit"], "S-002")
        self.assertEqual(git(self.repo, "rev-parse", "main"), old_main)

    def test_a_child_without_its_parent_is_refused(self):
        self.story("S-001", {"src/one.py": "one = 1\n"})
        self.story("S-002", {"src/two.py": "two = 2\n"}, deps=("S-001",), parent="story/S-001")
        result = self.merge(1, "S-002", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S-001", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_story_without_a_branch_is_a_plain_error(self):
        write(self.accio / "stories" / "S-009.md", story_text("S-009"))
        result = self.merge(1, "S-009", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("story/S-009", result.stderr)


if __name__ == "__main__":
    unittest.main()
