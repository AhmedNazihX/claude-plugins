"""S-073: the evidence command runs in a fresh detached checkout of the story's head, removed afterwards."""
import json
import pathlib
import sys
import tempfile
import time
import unittest

from support import commit_all, git, init_repo, write

from accio_lib import config, paths, preview

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
# The walk notes the commit and folder it ran in, and what it found in each file named after the PNG bytes.
WALK_SCRIPT = """import os, pathlib, subprocess, sys
steps, folder = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
head = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
(folder / "head.txt").write_text(head)
(folder / "cwd.txt").write_text(os.getcwd())
for name in sys.argv[4:]:
    path = pathlib.Path(name)
    (folder / (name.replace("/", "_") + ".seen")).write_text(path.read_text() if path.exists() else "absent")
(folder / "main.png").write_bytes(bytes.fromhex(sys.argv[3]))
"""
GOOD = {"command": "app --ui-walk {steps} --out {folder}", "steps_doc": "docs/ui-walk.md", "takes_over_screen": False,
        "evidence_globs": []}
WALK_FILE = "app/WalkMode.swift"
COMMITTED = "committed walk\n"


class FreshCheckoutConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.accio = pathlib.Path(self.tmp.name).resolve() / ".accio"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, data):
        write(self.accio / "config.json", json.dumps(data))
        return config.load(self.accio)

    def test_S_073_3_fresh_checkout_takes_true_or_false(self):
        for value in (True, False):
            with self.subTest(value=value):
                self.assertIs(self.load({"ui_evidence": {**GOOD, "fresh_checkout": value}})["ui_evidence"]
                              ["fresh_checkout"], value)

    def test_S_073_3_any_other_fresh_checkout_value_is_refused_naming_the_key(self):
        for bad in ("true", "no", 1, 0, None, [], {}):
            with self.subTest(bad=bad):
                with self.assertRaises(config.ConfigError) as caught:
                    self.load({"ui_evidence": {**GOOD, "fresh_checkout": bad}})
                self.assertIn("fresh_checkout", str(caught.exception))
                self.assertIn("true or false", str(caught.exception))


class FreshCheckoutRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name).resolve()
        self.base = base
        self.root = init_repo(base / "my repo")
        self.run_dir = self.root / ".accio" / "run"
        self.worktree = init_repo(paths.worktree_root(self.root) / "S-001")
        write(self.worktree / WALK_FILE, COMMITTED)
        write(self.worktree / ".gitignore", "*.local.swift\n")
        commit_all(self.worktree, "walk mode")
        self.head = git(self.worktree, "rev-parse", "HEAD")
        self.walk = base / "walk.py"
        self.walk.write_text(WALK_SCRIPT)
        write(self.run_dir / "S-001" / preview.STEPS_NAME, "open main\n")
        self.folder = self.run_dir / "S-001" / preview.EVIDENCE_FOLDER

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, command=None, files=(), **extra):
        command = command or f"{sys.executable} {self.walk} {{steps}} {{folder}} {PNG.hex()} {' '.join(files)}"
        return {**GOOD, "command": command, "evidence_globs": ["app/Walk*.swift"], **extra}

    def run_evidence(self, settings, head=None):
        return preview.evidence(self.run_dir, self.worktree, "S-001", settings, head or self.head)

    def worktrees(self):
        listed = git(self.worktree, "worktree", "list", "--porcelain")
        return [line for line in listed.splitlines() if line.startswith("worktree ")]

    def assert_checkout_removed(self, ran_in):
        self.assertNotEqual(ran_in.resolve(), self.worktree.resolve())
        self.assertFalse(ran_in.exists(), "the checkout must be removed")
        self.assertFalse(ran_in.parent.exists(), "its temporary folder must be removed")
        self.assertEqual(len(self.worktrees()), 1, "git must not keep the checkout registered")

    def test_S_073_1_the_command_runs_in_a_detached_checkout_of_the_head_and_it_is_removed(self):
        write(self.worktree / "README.md", "moved on\n")
        commit_all(self.worktree, "a later commit the head is not")
        result = self.run_evidence(self.settings())
        self.assertEqual(result, {"ok": True, "folder": str(self.folder), "head": self.head, "screenshots": 1})
        self.assertEqual((self.folder / "head.txt").read_text(), self.head)
        self.assert_checkout_removed(pathlib.Path((self.folder / "cwd.txt").read_text()))
        self.assertEqual((self.run_dir / "S-001" / preview.STAMP_NAME).read_text().strip(), self.head)

    def where_it_ran(self, marker):
        return pathlib.Path(marker.read_text().strip())

    def test_S_073_1_the_checkout_is_removed_when_the_command_fails(self):
        marker = self.base / "ran-in"
        result = self.run_evidence(self.settings(command=f"pwd > '{marker}'; echo {{steps}} {{folder}}; exit 3"))
        self.assertTrue(result["skipped"])
        self.assertIn("exited with 3", result["reason"])
        self.assert_checkout_removed(self.where_it_ran(marker))

    def test_S_073_1_the_checkout_is_removed_when_the_command_times_out(self):
        marker = self.base / "ran-in"
        started = time.monotonic()
        result = self.run_evidence(self.settings(command=f"pwd > '{marker}'; sleep 30; echo {{steps}} {{folder}}",
                                                 timeout=1))
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn("timeout of 1s", result["reason"])
        self.assert_checkout_removed(self.where_it_ran(marker))

    def test_S_073_1_a_head_git_cannot_check_out_is_a_skip_and_leaves_nothing(self):
        marker = self.base / "ran"
        other = "1" * 40
        result = self.run_evidence(self.settings(command=f"touch '{marker}' {{steps}} {{folder}}",
                                                 evidence_globs=[]), head=other)
        self.assertTrue(result["skipped"])
        self.assertIn(other[:12], result["reason"])
        self.assertIn("did not run", result["reason"])
        self.assertFalse(marker.exists())
        self.assertEqual(len(self.worktrees()), 1)
        self.assertFalse((self.run_dir / "S-001" / preview.STAMP_NAME).exists())

    def test_S_073_2_ignored_and_index_hidden_changes_to_an_evidence_glob_file_never_reach_the_evidence(self):
        write(self.worktree / "app" / "WalkExtra.local.swift", "ignored walk\n")
        write(self.worktree / "app" / "WalkSkip.swift", "committed skip\n")
        commit_all(self.worktree, "a second walk file")
        self.head = git(self.worktree, "rev-parse", "HEAD")
        git(self.worktree, "update-index", "--assume-unchanged", WALK_FILE)
        git(self.worktree, "update-index", "--skip-worktree", "app/WalkSkip.swift")
        write(self.worktree / WALK_FILE, "hidden walk\n")
        write(self.worktree / "app" / "WalkSkip.swift", "hidden skip\n")
        self.assertEqual(preview.worktree_changes(self.worktree), ([], ""), "git status can't see them")
        files = (WALK_FILE, "app/WalkSkip.swift", "app/WalkExtra.local.swift")
        result = self.run_evidence(self.settings(files=files))
        self.assertTrue(result.get("ok"), result)
        self.assertEqual((self.folder / "app_WalkMode.swift.seen").read_text(), COMMITTED)
        self.assertEqual((self.folder / "app_WalkSkip.swift.seen").read_text(), "committed skip\n")
        self.assertEqual((self.folder / "app_WalkExtra.local.swift.seen").read_text(), "absent")

    def test_S_073_3_fresh_checkout_false_runs_in_the_live_worktree_as_before(self):
        write(self.worktree / "app" / "WalkExtra.local.swift", "ignored walk\n")
        result = self.run_evidence(self.settings(files=("app/WalkExtra.local.swift",), fresh_checkout=False))
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(pathlib.Path((self.folder / "cwd.txt").read_text()).resolve(), self.worktree.resolve())
        self.assertEqual((self.folder / "app_WalkExtra.local.swift.seen").read_text(), "ignored walk\n")
        self.assertEqual(len(self.worktrees()), 1)

    def test_S_073_3_without_fresh_checkout_it_runs_in_a_fresh_checkout(self):
        settings = self.settings()
        self.assertNotIn("fresh_checkout", settings)
        result = self.run_evidence({**settings, "fresh_checkout": True})
        self.assertTrue(result.get("ok"), result)
        self.assert_checkout_removed(pathlib.Path((self.folder / "cwd.txt").read_text()))
        result = self.run_evidence(settings)
        self.assertTrue(result.get("ok"), result)
        self.assert_checkout_removed(pathlib.Path((self.folder / "cwd.txt").read_text()))


if __name__ == "__main__":
    unittest.main()
