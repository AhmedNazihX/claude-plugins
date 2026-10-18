"""S-024: the scripts behind `wand` (`accio-board init`, `accio-board record-design`; DESIGN § 3.1, § 12.1)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, git, init_repo, write

from accio_lib import runlock

BOARD = ROOT / "bin" / "accio-board"


class WandScriptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.com")
        self.accio = self.repo / ".accio"

    def tearDown(self):
        self.tmp.cleanup()

    def board(self, *args, check=True, cwd=None):
        result = subprocess.run([sys.executable, "-I", str(BOARD), *args], cwd=cwd or self.repo,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def test_S_024_4_init_sets_accio_up_once_and_keeps_the_run_folder_out_of_git(self):
        write(self.repo / ".gitignore", "node_modules/\n")
        reply = self.board("init")
        self.assertEqual(json.loads((self.accio / "config.json").read_text()), {})
        self.assertTrue((self.accio / "stories").is_dir())
        self.assertEqual((self.repo / ".gitignore").read_text(), "node_modules/\n.accio/run/\n")
        self.assertTrue(reply["created"])
        write(self.accio / "config.json", '{"base_branch": "trunk"}\n')
        again = self.board("init")
        self.assertFalse(again["created"])
        self.assertEqual((self.repo / ".gitignore").read_text().count(".accio/run/"), 1)
        self.assertEqual(json.loads((self.accio / "config.json").read_text()), {"base_branch": "trunk"})

    def test_init_works_from_a_subfolder_and_refuses_outside_a_repo(self):
        (self.repo / "src").mkdir()
        self.board("init", cwd=self.repo / "src")
        self.assertTrue((self.accio / "config.json").exists())
        outside = pathlib.Path(self.tmp.name) / "plain"
        outside.mkdir()
        self.assertIn("git repo", self.board("init", check=False, cwd=outside).stderr)

    def test_S_024_4_record_design_commits_the_design_and_setup_only(self):
        self.board("init")
        write(self.accio / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n")
        write(self.repo / "notes.txt", "mine\n")
        git(self.repo, "add", "notes.txt")
        reply = self.board("record-design")
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "docs(accio): design")
        committed = set(git(self.repo, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(committed, {".accio/design.md", ".accio/config.json", ".gitignore"})
        self.assertEqual(reply["commit"], git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "A  notes.txt")

    def test_record_design_needs_a_design_with_an_outcome_and_no_build(self):
        self.board("init")
        self.assertIn("design.md", self.board("record-design", check=False).stderr)
        write(self.accio / "design.md", "# Design: x\n\nNo outcome here.\n")
        self.assertIn("## Outcome", self.board("record-design", check=False).stderr)
        write(self.accio / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n")
        runlock.take(self.accio / "run")
        self.assertIn("build is running", self.board("record-design", check=False).stderr)


if __name__ == "__main__":
    unittest.main()
