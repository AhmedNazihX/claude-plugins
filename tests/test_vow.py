"""S-025: accio-vow (numbering and recording decision records, DESIGN § 3.7, § 12.2)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, git, init_repo, write

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

    def test_S_025_2_record_refuses_a_record_missing_a_section_or_outside_decisions(self):
        path = self.decisions / "001-postgres.md"
        write(path, RECORD.format(number="001").replace("## Why\nMany writers at once.\n", ""))
        result = self.vow("record", path, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("## Why", result.stderr)
        write(self.repo / "README2.md", RECORD.format(number="001"))
        self.assertIn("decisions", self.vow("record", self.repo / "README2.md", check=False).stderr)
        write(self.decisions / "002-mismatch.md", RECORD.format(number="005"))
        self.assertIn("002", self.vow("record", self.decisions / "002-mismatch.md", check=False).stderr)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "accio set up")


if __name__ == "__main__":
    unittest.main()
