"""S-025: accio-vow (numbering and recording decision records, DESIGN § 3.7, § 12.2)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, git, init_repo, write

from accio_lib import runlock

VOW = ROOT / "bin" / "accio-vow"
RECORD = """# {number} — Postgres over SQLite

Date: 2026-10-18 · Status: decided by the user

## What was decided
Which database the app uses.

## Options
| Option | What it looks like | Pros | Cons | Cost |
|---|---|---|---|---|
| Postgres | a server | concurrency | ops | $15/month |

## Decision
Postgres.

## Why
Many writers at once.
"""


class VowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.com")
        self.decisions = self.repo / ".accio" / "decisions"
        write(self.repo / ".accio" / "config.json", "{}\n")
        git(self.repo, "add", ".accio/config.json")
        git(self.repo, "commit", "-q", "-m", "accio set up")

    def tearDown(self):
        self.tmp.cleanup()

    def vow(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(VOW), *map(str, args)], cwd=self.repo,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def test_S_025_2_next_numbers_from_the_highest_record_with_a_plain_slug(self):
        self.assertEqual(self.vow("next", "Postgres over SQLite!")["path"],
                         str(self.decisions / "001-postgres-over-sqlite.md"))
        write(self.decisions / "007-old.md", "x")
        write(self.decisions / "notes.md", "x")
        reply = self.vow("next", "Use the Café API, v2")
        self.assertEqual((reply["number"], pathlib.Path(reply["path"]).name), (8, "008-use-the-cafe-api-v2.md"))

    def test_S_025_2_record_commits_a_complete_record_and_only_it(self):
        path = self.decisions / "001-postgres-over-sqlite.md"
        write(path, RECORD.format(number="001"))
        write(self.repo / "notes.txt", "mine\n")
        git(self.repo, "add", "notes.txt")
        reply = self.vow("record", path)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "docs(accio): decision 001 Postgres over SQLite")
        self.assertEqual(git(self.repo, "show", "--name-only", "--format=", "HEAD"),
                         ".accio/decisions/001-postgres-over-sqlite.md")
        self.assertEqual(reply["commit"], git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "A  notes.txt")

    def test_S_025_2_record_refuses_a_record_missing_any_section_or_outside_decisions(self):
        path = self.decisions / "001-postgres.md"
        for section in ("## What was decided", "## Options", "## Decision", "## Why"):
            with self.subTest(section):
                text = RECORD.format(number="001")
                start = text.index(section)
                end = text.find("\n## ", start + 1)
                write(path, text[:start] + (text[end + 1:] if end != -1 else ""))
                result = self.vow("record", path, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn(f"lacks {section}", result.stderr)
        fenced = "# 001 — A\n\n```\n## What was decided\n## Options\n## Decision\n## Why\n```\n"
        write(path, fenced)
        self.assertIn("lacks", self.vow("record", path, check=False).stderr)
        write(path, RECORD.format(number="001").replace("Many writers at once.\n", ""))
        self.assertIn("## Why is empty", self.vow("record", path, check=False).stderr)
        outside = self.repo / "docs" / "001-postgres.md"
        write(outside, RECORD.format(number="001"))
        self.assertIn("decisions", self.vow("record", outside, check=False).stderr)
        write(self.decisions / "002-mismatch.md", RECORD.format(number="005"))
        self.assertIn("002", self.vow("record", self.decisions / "002-mismatch.md", check=False).stderr)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "accio set up")

    def test_record_refuses_during_a_build_and_a_number_already_taken(self):
        path = self.decisions / "001-postgres.md"
        write(path, RECORD.format(number="001"))
        runlock.take(self.repo / ".accio" / "run")
        for args in (("record", path), ("next", "x")):  # nothing new in the main checkout during a build
            with self.subTest(args):
                self.assertIn("build is running", self.vow(*args, check=False).stderr)
        runlock.release(self.repo / ".accio" / "run")
        write(self.decisions / "001-other.md", RECORD.format(number="001"))
        self.assertIn("001-other.md", self.vow("record", path, check=False).stderr)

    def test_numbers_count_every_numbered_file_and_names_stay_short_and_never_empty(self):
        write(self.decisions / "005-API-Choice.md", "x")
        write(self.decisions / "006_x.md", "x")
        self.assertEqual(self.vow("next", "a")["number"], 7)
        words = pathlib.Path(self.vow("next", "one two three four five six seven eight nine ten")["path"]).name
        self.assertEqual(words, "007-one-two-three-four-five-six-seven-eight.md")
        one_long_word = pathlib.Path(self.vow("next", "x" * 300)["path"]).name
        self.assertLessEqual(len(one_long_word), 80)
        self.assertEqual(pathlib.Path(self.vow("next", "استخدام قاعدة البيانات")["path"]).name, "007-decision.md")
        self.assertEqual(pathlib.Path(self.vow("next", "!!!")["path"]).name, "007-decision.md")

    def test_recording_an_unchanged_record_reports_the_commit_that_recorded_it(self):
        path = self.decisions / "001-postgres.md"
        write(path, RECORD.format(number="001"))
        first = self.vow("record", path)["commit"]
        write(self.repo / "other.txt", "x\n")
        git(self.repo, "add", "other.txt")
        git(self.repo, "commit", "-q", "-m", "other")
        self.assertEqual(self.vow("record", path)["commit"], first)


if __name__ == "__main__":
    unittest.main()
