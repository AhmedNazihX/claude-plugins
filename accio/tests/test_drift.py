"""S-083: accio-board drift (a done story's testable DoD line that no test carries any more)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

BOARD = ROOT / "bin" / "accio-board"
CONFIG = json.dumps({"checks": [{"command": "python3 -m unittest", "glob": "**/*.py"}]})


def story_text(story_id, status, title, lines):
    dod = "".join(f"- [x] {story_id}/{n} {text}\n" for n, text in lines)
    return f"---\nid: {story_id}\ntitle: {title}\ntrack: story\nstatus: {status}\n---\n## Definition of Done\n{dod}"


class DriftTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        write(self.repo / ".accio" / "config.json", CONFIG)

    def tearDown(self):
        self.tmp.cleanup()

    def story(self, story_id, status="done", title="Login", lines=((1, "WHEN a THE SYSTEM SHALL b"),
                                                                    (2, "WHEN c THE SYSTEM SHALL d"))):
        write(self.repo / ".accio" / "stories" / f"{story_id}.md", story_text(story_id, status, title, lines))

    def write_test(self, text):
        write(self.repo / "tests" / "test_login.py", text)

    def drift(self, *args):
        commit_all(self.repo)
        result = subprocess.run([sys.executable, "-I", str(BOARD), "drift", *args], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_S_083_1_a_done_story_line_without_a_tagged_test_is_listed(self):
        self.story("S-012")
        self.write_test("def test_S_012_1_works(): pass\n")
        self.assertEqual(self.drift().strip(), "S-012/2 · Login")

    def test_S_083_1_several_lost_lines_share_one_line_per_story(self):
        self.story("S-012")
        self.assertEqual(self.drift().strip(), "S-012/1 S-012/2 · Login")

    def test_S_083_2_nothing_is_listed_when_every_line_is_tagged(self):
        self.story("S-012")
        self.write_test("# S-012/1\n# S-012/2\n")
        self.assertEqual(self.drift().strip(), "no drift")

    def test_S_083_2_no_test_lines_and_stories_not_done_are_not_listed(self):
        self.story("S-012", lines=((1, "(no test) checks pass"),))
        self.story("S-013", status="ready")
        self.story("S-014", status="blocked")
        self.assertEqual(self.drift().strip(), "no drift")

    def test_S_083_2_a_tag_in_a_fixture_does_not_count(self):
        self.story("S-012", lines=((1, "WHEN a THE SYSTEM SHALL b"),))
        write(self.repo / "tests" / "fixtures" / "data.txt", "S-012/1\n")
        self.assertEqual(self.drift().strip(), "S-012/1 · Login")

    def test_S_083_3_json_gives_id_title_and_lines_and_writes_nothing(self):
        self.story("S-012")
        self.write_test("# S-012/1\n")
        out = self.drift("--json")
        self.assertEqual(json.loads(out), {"drift": [{"id": "S-012", "title": "Login", "lines": ["S-012/2"]}]})
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")

    def test_S_083_3_json_with_no_drift_is_an_empty_list(self):
        self.assertEqual(json.loads(self.drift("--json")), {"drift": []})

    def test_S_083_4_map_runs_drift_and_names_the_ways_to_fix_it(self):
        text = (ROOT / "skills" / "map" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("accio-board drift", text)
        self.assertIn("Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board drift)", text)
        self.assertIn("direct fix", text)


if __name__ == "__main__":
    unittest.main()
