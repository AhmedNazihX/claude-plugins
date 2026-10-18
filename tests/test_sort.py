"""S-023: the scripts behind `sort` (`accio-score --apply`, `accio-board record`; DESIGN § 3.2, § 5.1).

The skill's DoD lines are checked by hand and by its evals; these tests pin what the skill leans on: tracks set from
the score, split flags, and a commit of exactly the stories, only when every story is sound.
"""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, git, init_repo, write

from accio_lib import runlock, story

SCORE = ROOT / "bin" / "accio-score"
BOARD = ROOT / "bin" / "accio-board"


def story_text(story_id, files, deps=(), track="story"):
    dep_list = f"deps: [{', '.join(deps)}]\n" if deps else ""
    return (f"---\nid: {story_id}\ntitle: Story {story_id}\ntrack: {track}  # quill's guess\nstatus: backlog\n"
            f"files: [{', '.join(files)}]\n{dep_list}---\n## Context\nWhy.\n## Definition of Done\n"
            f"- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n")


class SortScriptsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        git(self.repo, "config", "user.name", "t")
        git(self.repo, "config", "user.email", "t@example.com")
        self.accio = self.repo / ".accio"
        write(self.accio / "config.json", "{}\n")
        git(self.repo, "add", ".accio/config.json")
        git(self.repo, "commit", "-q", "-m", "accio set up")

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, story_id, files, **extra):
        path = self.accio / "stories" / f"{story_id}.md"
        write(path, story_text(story_id, files, **extra))
        return path

    def run_script(self, script, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(script), *map(str, args)], cwd=self.repo,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def test_S_023_2_apply_sets_each_track_from_the_score_and_flags_what_to_split(self):
        small = self.add("S-001", ["src/a.py"])
        big = self.add("S-002", [f"src/m{n}.py" for n in range(12)])
        reply = self.run_script(SCORE, "--apply", "--json", small, big)
        self.assertEqual([(item["id"], item["track"], item["split"]) for item in reply],
                         [("S-001", "quick", False), ("S-002", "feature", True)])
        self.assertEqual(story.parse(small).meta["track"], "quick")
        self.assertIn("track: quick  # quill's guess\n", small.read_text())
        self.assertEqual(story.parse(big).meta["track"], "feature")

    def test_apply_writes_nothing_when_one_file_is_bad(self):
        good = self.add("S-001", ["src/a.py"])
        bad = self.accio / "stories" / "S-002.md"
        write(bad, "---\nid: S-002\n---\n")
        result = self.run_script(SCORE, "--apply", "--json", good, bad, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-002.md", result.stderr)
        self.assertEqual(story.parse(good).meta["track"], "story")

    def test_S_023_1_record_commits_exactly_the_stories_and_the_board_when_all_are_sound(self):
        first = self.add("S-001", ["src/a.py"])
        second = self.add("S-002", ["src/b.py"], deps=["S-001"])
        self.add("S-003", ["src/c.py"])  # sound, but not given: it stays out of the commit
        write(self.repo / "notes.txt", "mine\n")
        git(self.repo, "add", "notes.txt")
        reply = self.run_script(BOARD, "record", first, second)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "chore(accio): sort 2 stories")
        self.assertEqual(reply["commit"], git(self.repo, "rev-parse", "HEAD"))
        committed = set(git(self.repo, "show", "--name-only", "--format=", "HEAD").splitlines())
        self.assertEqual(committed, {".accio/stories/S-001.md", ".accio/stories/S-002.md", ".accio/board.md"})
        self.assertIn("S-002 Story S-002", (self.accio / "board.md").read_text())
        self.assertEqual(git(self.repo, "status", "--porcelain").splitlines(),
                         ["A  notes.txt", "?? .accio/stories/S-003.md"])

    def test_S_023_1_record_refuses_unsound_stories_and_commits_nothing(self):
        first = self.add("S-001", ["src/a.py"], deps=["S-009"])
        result = self.run_script(BOARD, "record", first, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-009", result.stderr)
        self.add("S-001", ["src/a.py"])
        self.add("S-002", ["src/b.py"], deps=["S-003"])
        self.add("S-003", ["src/c.py"], deps=["S-002"])
        result = self.run_script(BOARD, "record", first, check=False)
        self.assertIn("cycle", result.stderr)
        self.assertEqual(git(self.repo, "log", "-1", "--format=%s"), "accio set up")

    def test_record_takes_only_story_files_and_never_during_a_build(self):
        first = self.add("S-001", ["src/a.py"])
        write(self.repo / "src.py", "x = 1\n")
        self.assertIn("story files", self.run_script(BOARD, "record", self.repo / "src.py", check=False).stderr)
        runlock.take(self.accio / "run")
        for args in (("record", first), ("new",)):  # sort's first command stops it before quill writes anything
            with self.subTest(args):
                self.assertIn("build is running", self.run_script(BOARD, *args, check=False).stderr)


if __name__ == "__main__":
    unittest.main()
