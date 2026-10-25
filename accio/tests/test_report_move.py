"""S-082 follow-up: every `accio-brief` call moves the reports an older accio left in `.accio/run/<folder>/` to their
place in `<worktree root>/.reports/`, so the run folder, which a search from the main checkout passes over, never
holds one (security review of S-082, 2026-10-25). A report already in the new place is kept; the old one goes beside
it as `earlier-build-report.md`.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, remove_tmp, write

from accio_lib import paths

BRIEF = ROOT / "bin" / "accio-brief"


class MoveOldReportsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.run_dir = self.repo / ".accio" / "run"
        write(self.repo / ".accio" / "config.json", json.dumps({"checks": [{"command": "true", "glob": "**"}]}))
        self.reports = paths.reports_dir(self.repo)

    def tearDown(self):
        remove_tmp(self.tmp)

    def test_old_reports_in_any_case_move_to_their_place(self):
        write(self.run_dir / "S-001" / "build-report.md", "one\n")
        write(self.run_dir / "fix-typo" / "BUILD-REPORT.md", "two\n")
        write(self.run_dir / "S-001" / "examiner-findings.md", "kept\n")
        moved = paths.move_old_reports(self.repo)
        self.assertEqual(moved, [self.reports / "S-001" / "build-report.md", self.reports / "fix-typo" / "build-report.md"])
        self.assertEqual((self.reports / "S-001" / "build-report.md").read_text(), "one\n")
        self.assertEqual((self.reports / "fix-typo" / "build-report.md").read_text(), "two\n")
        self.assertEqual([p.name for p in self.run_dir.rglob("*") if p.is_file()], ["examiner-findings.md"])

    def test_a_report_already_in_the_new_place_is_kept_and_the_old_one_goes_beside_it(self):
        write(self.reports / "S-001" / "build-report.md", "new\n")
        write(self.run_dir / "S-001" / "build-report.md", "old\n")
        paths.move_old_reports(self.repo)
        self.assertEqual((self.reports / "S-001" / "build-report.md").read_text(), "new\n")
        self.assertEqual((self.reports / "S-001" / paths.EARLIER_REPORT_NAME).read_text(), "old\n")
        self.assertFalse((self.run_dir / "S-001" / "build-report.md").exists())

    def test_no_run_folder_or_no_old_report_moves_nothing(self):
        self.assertEqual(paths.move_old_reports(self.repo), [])
        write(self.run_dir / "S-001" / "brief.md", "x\n")
        self.assertEqual(paths.move_old_reports(self.repo), [])
        self.assertFalse(self.reports.exists())

    def test_accio_brief_moves_them_before_anything_else(self):
        write(self.run_dir / "S-003" / "build-report.md", "old\n")
        result = subprocess.run([sys.executable, "-I", str(BRIEF), "S-999"], cwd=self.repo, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 1)  # no story S-999, but the move ran first
        self.assertIn("there is no story S-999", result.stderr)
        self.assertTrue((self.reports / "S-003" / "build-report.md").is_file())
        self.assertFalse((self.run_dir / "S-003" / "build-report.md").exists())

    def test_a_move_that_fails_is_a_plain_error(self):
        write(self.run_dir / "S-004" / "build-report.md", "old\n")
        write(paths.worktree_root(self.repo), "a file where the worktree root should be\n")
        result = subprocess.run([sys.executable, "-I", str(BRIEF), "S-999"], cwd=self.repo, capture_output=True,
                                text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("accio-brief: could not move an older build's report", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
