"""S-075: an owl answer that names a file outside its story's `files:` is caught at check, and `--widen` adds it."""
import unittest

from support import git, write

import test_owl
from accio_lib import storyfiles


class WidenTest(unittest.TestCase):
    """The S-022 setup, with S-004 (in review) and S-003 (blocked) given `files:`."""

    setUp = test_owl.OwlTest.setUp
    tearDown = test_owl.OwlTest.tearDown
    owl = test_owl.OwlTest.owl
    meta = test_owl.OwlTest.meta

    def give_files(self, sid, value):
        path = self.accio / "stories" / f"{sid}.md"
        write(path, storyfiles.with_fields(path, {"files": value}))
        write(self.repo / "src" / "pane.py", "x = 1\n")
        write(self.repo / "tests" / "keep.txt", "k\n")
        git(self.repo, "add", "src", "tests", ".accio/stories")
        git(self.repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "files")

    def base(self, reject_text="no", answer_text="Email only"):
        return ("--accept", "S-001", "--accept", "S-002", "--reject", "S-004", reject_text,
                "--drop", "S-007", "gone", "--answer", "S-003", answer_text)

    def test_S_075_1_a_reject_reason_naming_a_path_outside_files_is_refused(self):
        self.give_files("S-004", "[docs/]")
        result = self.owl("check", *self.base("add accessors to `src/pane.py` and src/new.py"), check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-004", result.stderr)
        self.assertIn("src/pane.py", result.stderr)
        self.assertIn("src/new.py", result.stderr)  # a path that doesn't exist yet counts: its folder does
        self.assertIn("--widen S-004", result.stderr)

    def test_S_075_1_an_answer_naming_a_path_outside_files_is_refused_too(self):
        self.give_files("S-003", "[docs/]")
        result = self.owl("check", *self.base(answer_text="edit src/pane.py"), check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-003", result.stderr)
        self.assertIn("src/pane.py", result.stderr)

    def test_S_075_2_a_folder_entry_covers_what_is_under_it(self):
        self.give_files("S-004", "[src/]")
        result = self.owl("check", *self.base("see src/pane.py"))
        self.assertEqual(result["accept"], ["S-001", "S-002"])

    def test_S_075_2_text_with_no_path_is_accepted_as_today(self):
        self.give_files("S-004", "[docs/]")
        self.owl("check", *self.base("use and/or, e.g. the link, v1.2 or Email/SMS"))

    def test_S_075_2_a_test_file_is_not_outside(self):
        self.give_files("S-004", "[docs/]")
        self.owl("check", *self.base("fix tests/keep.txt"))

    def test_S_075_3_widen_lets_check_pass_and_close_adds_the_path_and_commits_it(self):
        self.give_files("S-004", "[docs/]  # keep")
        answers = (*self.base("add accessors to src/pane.py"), "--widen", "S-004", "src/pane.py")
        self.owl("check", *answers)
        self.owl("close", *answers, "--merged", "S-001", "--merged", "S-002")
        self.assertEqual(self.meta("S-004")["files"], ("docs/", "src/pane.py"))
        text = (self.accio / "stories" / "S-004.md").read_text()
        self.assertIn("files: [docs/, src/pane.py]  # keep", text)
        shown = git(self.repo, "show", "--name-only", "--format=%s", "HEAD")
        self.assertIn(".accio/stories/S-004.md", shown)
        self.assertIn("review", shown)

    def test_S_075_3_widen_works_for_a_blocked_story_with_an_answer(self):
        self.give_files("S-003", "[docs/]")
        answers = (*self.base(answer_text="edit src/pane.py"), "--widen", "S-003", "src/pane.py")
        self.owl("close", *answers, "--merged", "S-001", "--merged", "S-002")
        self.assertEqual(self.meta("S-003")["files"], ("docs/", "src/pane.py"))

    def test_S_075_4_widen_for_an_accepted_dropped_or_unreviewed_story_is_refused(self):
        self.give_files("S-004", "[docs/]")
        for sid in ("S-001", "S-007", "S-005", "S-099"):
            with self.subTest(sid):
                result = self.owl("check", *self.base(), "--widen", sid, "src/pane.py", check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn(sid, result.stderr)
                self.assertIn("--widen", result.stderr)


if __name__ == "__main__":
    unittest.main()
