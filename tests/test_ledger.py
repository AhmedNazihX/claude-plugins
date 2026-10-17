"""S-006: accio-ledger (verdict keys from the exact diff, check/record/clear)."""
import concurrent.futures
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import ledger, story

LEDGER = ROOT / "bin" / "accio-ledger"
DOD = "## Definition of Done\n- [ ] S-001/1 WHEN x THE SYSTEM SHALL y\n"


def story_file(path, dod=DOD):
    write(path, "---\nid: S-001\ntitle: x\ntrack: story\nstatus: ready\n---\n" + dod)
    return story.parse(path)


class KeyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")
        self.story = story_file(self.base / "S-001.md")

    def tearDown(self):
        self.tmp.cleanup()

    def branch(self, name, start="main"):
        worktree = self.base / name.replace("/", "-")
        git(self.repo, "worktree", "add", "-q", str(worktree), "-b", name, start)
        return worktree

    def change(self, worktree, files):
        for name, text in files.items():
            write(worktree / name, text)
        commit_all(worktree)

    def key(self, worktree, checks=(), panel="spec+quality", parent=None, parsed=None):
        start = ledger.diff_base(worktree, "main", parent)
        return ledger.key(ledger.work_digest(worktree, start), checks, panel, parsed or self.story)

    def test_S_006_1_each_input_changes_the_key(self):
        worktree = self.branch("story/S-001")
        self.change(worktree, {"a.txt": "one\n"})
        first = self.key(worktree)
        self.assertNotEqual(first, self.key(worktree, checks=({"command": "make test", "glob": "**"},)))
        self.assertNotEqual(first, self.key(worktree, panel="spec+quality+security"))
        other_dod = story_file(self.base / "other" / "S-001.md", DOD.replace("SHALL y", "SHALL z"))
        self.assertNotEqual(first, self.key(worktree, parsed=other_dod))
        self.change(worktree, {"a.txt": "two\n"})
        self.assertNotEqual(first, self.key(worktree))

    def test_S_006_2_same_patch_in_a_different_commit_layout_gives_the_same_key(self):
        stepwise = self.branch("story/S-001")
        self.change(stepwise, {"a.txt": "one\n"})
        self.change(stepwise, {"b.txt": "two\n"})
        squashed = self.branch("story/S-001-squashed")
        self.change(squashed, {"a.txt": "one\n", "b.txt": "two\n"})
        self.assertEqual(self.key(stepwise), self.key(squashed))

    def test_S_006_3_a_stacked_child_diffs_from_its_parent_head(self):
        parent = self.branch("story/S-001")
        self.change(parent, {"parent.txt": "parent\n"})
        child = self.branch("story/S-002", start="story/S-001")
        self.change(child, {"child.txt": "child\n"})
        self.assertEqual(ledger.diff_base(child, "main", "story/S-001"), git(self.repo, "rev-parse", "story/S-001"))
        self.assertNotEqual(self.key(child, parent="story/S-001"), self.key(child))
        relayout = self.branch("story/S-002-relayout", start="story/S-001")
        self.change(relayout, {"child.txt": "chi"})
        self.change(relayout, {"child.txt": "child\n"})
        self.assertEqual(self.key(child, parent="story/S-001"), self.key(relayout, parent="story/S-001"))

    def test_whitespace_only_differences_give_different_keys(self):
        write(self.repo / "a.py", "if x:\n    a()\nb()\n")
        commit_all(self.repo)
        keys = set()
        for name, text in (("ws1", "if x:\n    a()\n    b()\n"), ("ws2", "if x:\n    a()\n        b()\n"),
                           ("ws3", "if x:\n    a()\nb()  \n")):
            worktree = self.branch(f"story/{name}")
            self.change(worktree, {"a.py": text})
            keys.add(self.key(worktree))
        self.assertEqual(len(keys), 3)

    def test_binary_and_mode_changes_give_different_keys(self):
        first = self.branch("story/bin1")
        (first / "img.bin").write_bytes(bytes(range(256)))
        commit_all(first)
        second = self.branch("story/bin2")
        (second / "img.bin").write_bytes(bytes(reversed(range(256))))
        commit_all(second)
        self.assertNotEqual(self.key(first), self.key(second))
        moded = self.branch("story/mode")
        (moded / "README.md").chmod(0o755)
        commit_all(moded)
        self.assertNotEqual(self.key(moded), self.key(self.branch("story/plain")))

    def test_the_users_git_display_settings_do_not_change_the_key(self):
        worktree = self.branch("story/S-001")
        self.change(worktree, {"a.txt": "one\n"})
        plain = self.key(worktree)
        git(self.repo, "config", "color.ui", "always")
        git(self.repo, "config", "diff.external", "false")
        self.assertEqual(self.key(worktree), plain)

    def test_a_moved_base_changes_the_key(self):
        worktree = self.branch("story/S-001")
        self.change(worktree, {"a.txt": "one\n"})
        before = self.key(worktree)
        write(self.repo / "other.txt", "main moved\n")
        commit_all(self.repo)
        git(worktree, "rebase", "-q", "main")
        self.assertNotEqual(self.key(worktree), before)

    def test_files_in_any_encoding_and_line_ending_are_keyed(self):
        latin = self.branch("story/latin")
        (latin / "legacy.txt").write_bytes(b"caf\xe9\n")
        commit_all(latin)
        crlf = self.branch("story/crlf")
        (crlf / "legacy.txt").write_bytes(b"cafe\r\n")
        commit_all(crlf)
        lf = self.branch("story/lf")
        (lf / "legacy.txt").write_bytes(b"cafe\n")
        commit_all(lf)
        self.assertEqual(len({self.key(latin), self.key(crlf), self.key(lf)}), 3)

    def test_an_edited_tracked_file_is_refused_too(self):
        worktree = self.branch("story/S-001")
        self.change(worktree, {"a.txt": "one\n"})
        write(worktree / "a.txt", "edited\n")
        with self.assertRaisesRegex(ledger.LedgerError, "uncommitted"):
            self.key(worktree)

    def test_uncommitted_or_untracked_work_is_refused(self):
        worktree = self.branch("story/S-001")
        self.change(worktree, {"a.txt": "one\n"})
        write(worktree / "new.txt", "untracked\n")
        with self.assertRaisesRegex(ledger.LedgerError, "uncommitted"):
            self.key(worktree)

    def test_an_empty_diff_has_a_stable_key(self):
        worktree = self.branch("story/S-001")
        self.assertEqual(self.key(worktree), self.key(worktree))

    def test_an_unknown_parent_is_a_plain_error(self):
        worktree = self.branch("story/S-001")
        with self.assertRaisesRegex(ledger.LedgerError, "story/S-404"):
            ledger.diff_base(worktree, "main", "story/S-404")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.run = pathlib.Path(self.tmp.name) / "run"

    def tearDown(self):
        self.tmp.cleanup()

    def test_S_006_4_a_recorded_pass_for_the_key_is_a_skip(self):
        self.assertFalse(ledger.has_pass(self.run, "S-001", "k1"))
        ledger.record(self.run, "S-001", "k1", "pass")
        self.assertTrue(ledger.has_pass(self.run, "S-001", "k1"))
        self.assertFalse(ledger.has_pass(self.run, "S-001", "k2"))
        self.assertFalse(ledger.has_pass(self.run, "S-002", "k1"))

    def test_a_later_fail_for_the_same_key_cancels_the_pass(self):
        ledger.record(self.run, "S-001", "k1", "pass")
        ledger.record(self.run, "S-001", "k1", "fail")
        self.assertFalse(ledger.has_pass(self.run, "S-001", "k1"))

    def test_S_006_5_clear_deletes_only_that_story(self):
        ledger.record(self.run, "S-001", "k1", "pass")
        ledger.record(self.run, "S-002", "k2", "pass")
        ledger.clear(self.run, "S-001")
        self.assertFalse(ledger.has_pass(self.run, "S-001", "k1"))
        self.assertTrue(ledger.has_pass(self.run, "S-002", "k2"))

    def test_bad_ids_and_verdicts_are_refused(self):
        with self.assertRaises(ledger.LedgerError):
            ledger.record(self.run, "S-001\tx", "k", "pass")
        with self.assertRaises(ledger.LedgerError):
            ledger.record(self.run, "S-001", "k", "maybe")

    def test_quick_fix_ids_are_accepted(self):
        ledger.record(self.run, "Q-3", "k", "pass")
        self.assertTrue(ledger.has_pass(self.run, "Q-3", "k"))

    def test_parallel_records_keep_every_line(self):
        ids = [f"S-00{n}" for n in range(1, 9)]
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda sid: ledger.record(self.run, sid, "k", "pass"), ids))
        self.assertTrue(all(ledger.has_pass(self.run, sid, "k") for sid in ids))

    def test_a_corrupt_line_is_a_plain_error(self):
        write(self.run / ledger.LEDGER_NAME, "garbage\n")
        with self.assertRaisesRegex(ledger.LedgerError, "ledger.tsv:1"):
            ledger.has_pass(self.run, "S-001", "k")


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")
        (self.repo / ".accio" / "stories").mkdir(parents=True)
        self.story_path = self.repo / ".accio" / "stories" / "S-001.md"
        story_file(self.story_path)
        self.worktree = self.base / "wt"
        git(self.repo, "worktree", "add", "-q", str(self.worktree), "-b", "story/S-001")
        write(self.worktree / "a.txt", "one\n")
        commit_all(self.worktree)

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(LEDGER), *args], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_key_check_record_clear_round_trip(self):
        key = self.cli("key", str(self.story_path), "--worktree", str(self.worktree), "--panel", "spec").stdout.strip()
        self.assertRegex(key, r"^[0-9a-f]{64}$")
        self.assertEqual(self.cli("check", "S-001", key).stdout.strip(), "run")
        self.cli("record", "S-001", key, "pass")
        self.assertEqual(self.cli("check", "S-001", key).stdout.strip(), "skip")
        self.cli("clear", "S-001")
        self.assertEqual(self.cli("check", "S-001", key).stdout.strip(), "run")

    def test_errors_are_plain(self):
        result = self.cli("record", "S-001", "k", "maybe", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("pass", result.stderr)


if __name__ == "__main__":
    unittest.main()
