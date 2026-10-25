"""S-024: the scripts behind `wand` (`accio-board init`, `accio-board record-design`; DESIGN § 3.1, § 12.1)."""
import json
import os
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

    def test_init_keeps_line_endings_and_bytes_and_asks_git_what_it_ignores(self):
        (self.repo / ".gitignore").write_bytes(b"node_modules/\r\ncaf\xe9/\r\n")
        self.board("init")
        self.assertEqual((self.repo / ".gitignore").read_bytes(), b"node_modules/\r\ncaf\xe9/\r\n.accio/run/\r\n")
        (self.repo / ".gitignore").write_text("/.accio/run/\n")
        self.board("init")
        self.assertEqual((self.repo / ".gitignore").read_text(), "/.accio/run/\n")  # already ignored: no second line
        (self.repo / ".gitignore").write_text(".accio/run/\n!.accio/run/\n")
        self.board("init")
        self.assertIn(".accio/run/", git(self.repo, "check-ignore", ".accio/run/x"))

    def test_init_refuses_a_setup_file_that_points_outside_the_repo(self):
        outside = pathlib.Path(self.tmp.name) / "dotfiles-gitignore"
        outside.write_text("*.log\n")
        os.symlink(outside, self.repo / ".gitignore")
        result = self.board("init", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn(".gitignore", result.stderr)
        self.assertEqual(outside.read_text(), "*.log\n")
        os.unlink(self.repo / ".gitignore")
        (self.accio).mkdir()
        os.symlink(pathlib.Path(self.tmp.name) / "nowhere.json", self.accio / "config.json")
        self.assertIn("config.json", self.board("init", check=False).stderr)
        self.assertFalse((pathlib.Path(self.tmp.name) / "nowhere.json").exists())

    def test_init_gives_a_plain_error_for_a_gitignore_it_cannot_read(self):
        (self.repo / ".gitignore").mkdir()
        result = self.board("init", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("Traceback", result.stderr)

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

    def test_a_later_design_note_commits_the_design_and_config_not_the_users_other_edits(self):
        self.board("init")
        write(self.accio / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n")
        first = self.board("record-design")
        with (self.repo / ".gitignore").open("a") as stream:
            stream.write("secret-wip/\n")
        write(self.accio / "config.json", '{"base_branch": "trunk"}\n')  # S-089: a changed config goes in too
        write(self.accio / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n\n## Export\nCSV.\n")
        self.board("record-design")
        self.assertEqual(set(git(self.repo, "show", "--name-only", "--format=", "HEAD").splitlines()),
                         {".accio/design.md", ".accio/config.json"})
        self.assertIn("secret-wip/", git(self.repo, "diff", "--", ".gitignore"))
        self.assertEqual(self.board("record-design")["commit"], git(self.repo, "rev-parse", "HEAD"))
        self.assertNotEqual(first["commit"], git(self.repo, "rev-parse", "HEAD"))

    def test_record_design_needs_a_design_with_an_outcome_and_no_build(self):
        self.board("init")
        self.assertIn("design.md", self.board("record-design", check=False).stderr)
        for text in ("# Design: x\n\nNo outcome here.\n", "# Design: x\n\n```\n## Outcome\nok\n```\n",
                     "# Design: x\n\n## Outcome\n## Who\nus\n",
                     "# Design: x\n\n## Outcome\nAfter this ships, <what should be true>, and we'd know.\n"):
            with self.subTest(text):
                write(self.accio / "design.md", text)
                self.assertIn("## Outcome", self.board("record-design", check=False).stderr)
        write(self.accio / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n")
        runlock.take(self.accio / "run")
        self.assertIn("build is running", self.board("record-design", check=False).stderr)


    def test_S_090_1_wand_reset_removes_the_helpers_notes_and_refuses_during_a_build(self):
        self.board("init")
        wand = self.accio / "run" / "wand"
        write(wand / "seeker-notes.md", "old\n")
        write(wand / "first-year-notes.md", "old\n")
        result = self.board("wand-reset", check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(wand.iterdir()), [])
        self.assertEqual(self.board("wand-reset", check=False).returncode, 0)  # nothing there is fine
        write(wand / "seeker-notes.md", "old\n")
        runlock.take(self.accio / "run")
        refused = self.board("wand-reset", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("build is running", refused.stderr)
        self.assertTrue((wand / "seeker-notes.md").exists())

    def test_S_090_1_wand_reset_never_deletes_through_a_link(self):
        self.board("init")
        elsewhere = self.accio.parent.parent / "elsewhere"
        write(elsewhere / "keep.md", "not wand's\n")
        run = self.accio / "run"
        run.mkdir(exist_ok=True)
        os.symlink(elsewhere, run / "wand")  # run/wand is a link to a folder outside the run folder
        refused = self.board("wand-reset", check=False)
        self.assertEqual(refused.returncode, 1)
        self.assertIn("is a link", refused.stderr)
        self.assertTrue((elsewhere / "keep.md").exists())
        (run / "wand").unlink()
        write(run / "wand" / "seeker-notes.md", "old\n")
        os.symlink(elsewhere / "keep.md", run / "wand" / "notes-link.md")  # a link inside is removed, not followed
        self.assertEqual(self.board("wand-reset", check=False).returncode, 0)
        self.assertEqual(list((run / "wand").iterdir()), [])
        self.assertTrue((elsewhere / "keep.md").exists())


class WandAsksFirstTest(unittest.TestCase):
    def step_1(self):
        text = (ROOT / "skills" / "wand" / "SKILL.md").read_text(encoding="utf-8")
        return " ".join(text.split("## 1. Set up", 1)[1].split("**Check commands.**", 1)[0].split())

    def test_S_030_2_step_1_asks_once_before_setting_up_unless_the_user_typed_the_command(self):
        text = self.step_1()
        init_at = text.index("accio-board init")
        before = text[:init_at]
        for phrase in ("no `.accio/`", "/accio:wand", "/accio", "ask once", "hooks"):
            with self.subTest(phrase):
                self.assertIn(phrase, before)
        self.assertIn("no", before.lower())


def skill_flat():
    return " ".join((ROOT / "skills" / "wand" / "SKILL.md").read_text(encoding="utf-8").split())


def section(text, start, end):
    return text.split(start, 1)[1].split(end, 1)[0]


class FreshReaderTest(unittest.TestCase):
    """S-081/3: wand calls first-year once, after writing the design and before record-design."""

    def step_6(self):
        return section(skill_flat(), "## 6. Record and write", "End:")

    def test_S_081_3_first_year_runs_after_the_design_is_written_and_before_record_design(self):
        text = self.step_6()
        written, reader = text.index("Write `.accio/design.md`"), text.index("`accio:first-year`")
        self.assertLess(written, reader)
        self.assertLess(reader, text.index("accio-board record-design"))

    def test_S_081_3_called_once_with_only_the_design_path(self):
        text = self.step_6()
        for words in ("once", "only the design's path", "the note's heading", "never call it twice in a run",
                      ".accio/run/wand/first-year-notes.md"):
            with self.subTest(words):
                self.assertIn(words, text)

    def test_S_081_3_points_are_asked_one_at_a_time_and_written_into_the_design(self):
        text = self.step_6()
        for words in ("drop a point the interview already settled", "one at a time", "interview.md",
                      "write each answer into the design with Edit", "With `driven`", "still asked",
                      "the fresh reader found nothing"):
            with self.subTest(words):
                self.assertIn(words, text)


class HelpersDidntRunTest(unittest.TestCase):
    """S-090/2 and /3: a helper that did not run is said, never "found nothing"."""

    def test_S_090_2_wand_resets_first_and_names_the_didnt_run_wording(self):
        text = skill_flat()
        self.assertIn("Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board wand-reset)", text.split("---")[1])
        step_1 = section(text, "## 1. Set up", "**Check commands.**")
        self.assertIn("accio-board wand-reset", step_1)
        self.assertLess(step_1.index("accio-board init"), step_1.index("wand-reset"))  # .accio/ must exist first
        for start, end in (("## 3. Check the facts", "## 4."), ("## 4. Get options", "## 5."),
                           ("3. **Fresh reader.**", "4. Run")):
            with self.subTest(start):
                part = section(text, start, end)
                for words in ("didn't run", "reply", "is not there"):
                    self.assertIn(words, part)
        self.assertIn("never \"found nothing\"", section(text, "3. **Fresh reader.**", "End:"))
        self.assertIn("incomplete", section(text, "3. **Fresh reader.**", "4. Run"))
        self.assertIn("the fresh reader didn't run", text)

    def test_S_090_3_first_year_replies_incomplete_with_the_path_when_it_cannot_read_the_design(self):
        text = " ".join((ROOT / "agents" / "first-year.md").read_text(encoding="utf-8").split())
        self.assertIn("notes: none · incomplete: <path>", text)
        self.assertIn("cannot read the design", text)


class DecisionClashTest(unittest.TestCase):
    """S-081/4: wand reads the recorded decisions and asks about a clash: replace the decision or change the note."""

    def check(self, text):
        for words in (".accio/decisions/", "replace the decision", "change the note", "Replaces decision NNN",
                      "vow"):
            with self.subTest(words):
                self.assertIn(words, text)

    def test_S_081_4_wand_step_2_reads_the_decisions_and_asks_on_a_clash(self):
        self.check(section(skill_flat(), "## 2. Interview", "## 3. Check the facts"))

    def test_S_081_4_the_interview_guide_asks_on_a_clash(self):
        self.check(" ".join((ROOT / "skills" / "wand" / "references" / "interview.md").read_text(
            encoding="utf-8").split()))


if __name__ == "__main__":
    unittest.main()
