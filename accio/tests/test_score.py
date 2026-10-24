"""S-005: accio-score (complexity score → track and split flag), plus the shared glob matcher."""
import json
import pathlib
from unittest import mock
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

from accio_lib import globs, score

SCORE = ROOT / "bin" / "accio-score"
RISKY = ("**/auth/**", ".github/workflows/**", "**/*secret*")


def story_text(files=(), risk=None, track="story"):
    lines = ["---", "id: S-001", "title: x", f"track: {track}", "status: ready"]
    if files:
        lines.append(f"files: [{', '.join(files)}]")
    if risk:
        lines.append(f"risk: {risk}")
    return "\n".join([*lines, "---", "## Definition of Done", "- [ ] S-001/1 WHEN x THE SYSTEM SHALL y", ""])


class GlobTest(unittest.TestCase):
    def test_double_star_matches_any_depth_including_none(self):
        self.assertTrue(globs.match("src/auth/reset.ts", "**/auth/**"))
        self.assertTrue(globs.match("auth/reset.ts", "**/auth/**"))
        self.assertTrue(globs.match(".github/workflows/ci.yml", ".github/workflows/**"))
        self.assertTrue(globs.match("config/db_secret.json", "**/*secret*"))

    def test_question_mark_and_special_characters_are_literal_enough(self):
        self.assertTrue(globs.match("src/a1.ts", "src/a?.ts"))
        self.assertFalse(globs.match("src/a/1.ts", "src/a?.ts"))
        self.assertFalse(globs.match("src/a/b", "src/a?b"))
        self.assertFalse(globs.match("src/aXts", "src/a.ts"))
        self.assertTrue(globs.match("lib/c++(x)[1].h", "lib/c++(x)[1].h"))

    def test_double_star_in_the_middle(self):
        self.assertTrue(globs.match("a/c", "a/**/c"))
        self.assertTrue(globs.match("a/b/b2/c", "a/**/c"))

    def test_a_folder_match_covers_everything_inside_it(self):
        self.assertTrue(globs.match("config/secrets/prod.env", "**/*secret*"))
        self.assertTrue(globs.match("infra/main.tf", "infra"))
        self.assertTrue(globs.match("infra/main.tf", "infra/"))
        self.assertFalse(globs.match("infrastructure/main.tf", "infra"))

    def test_dot_slash_paths_are_normalised(self):
        self.assertTrue(globs.match("./.github/workflows/ci.yml", ".github/workflows/**"))
        self.assertTrue(globs.match("src//auth/./x.ts", "**/auth/**"))

    def test_absolute_paths_are_refused(self):
        with self.assertRaises(globs.GlobError):
            globs.match("/Users/me/repo/.github/workflows/ci.yml", ".github/workflows/**")

    def test_S_071_3_letter_case_counts_unless_the_caller_asks_to_ignore_it(self):
        self.assertFalse(globs.match("Infra/main.tf", "infra"))
        self.assertFalse(globs.matches_any("SRC/Auth/x.ts", ["src/auth/**"]))
        self.assertTrue(globs.match("Infra/main.tf", "infra", ignore_case=True))
        self.assertTrue(globs.matches_any("SRC/Auth/x.ts", ["src/auth/**"], ignore_case=True))
        self.assertTrue(globs.matches_any("sources/uiwalk/x.swift", ["Sources/UIWalk/**"], ignore_case=True))
        self.assertFalse(globs.matches_any("sources/uiwalker/x.swift", ["Sources/UIWalk/*.swift"], ignore_case=True))
        self.assertTrue(globs.match("src/a1.TS", "src/A?.ts", ignore_case=True))

    def test_S_071_3_risky_paths_keep_matching_with_letter_case(self):
        self.assertFalse(globs.matches_any("SRC/AUTH/x.ts", RISKY))
        self.assertEqual(score.assess(["SRC/AUTH/x.ts"], None, RISKY), score.assess(["src/x.ts"], None, RISKY))
        self.assertNotEqual(score.assess(["src/auth/x.ts"], None, RISKY), score.assess(["src/x.ts"], None, RISKY))

    def test_a_newline_in_a_folder_name_cannot_dodge_a_pattern(self):
        self.assertTrue(globs.match("src/a\nb/auth/x.ts", "**/auth/**"))

    def test_single_star_stays_inside_one_folder(self):
        self.assertTrue(globs.match("src/a.ts", "src/*.ts"))
        self.assertFalse(globs.match("src/deep/a.ts", "src/*.ts"))
        self.assertFalse(globs.match("src/authors/x.ts", "**/auth/**"))


class ScoreTest(unittest.TestCase):
    def assess(self, files=(), risk=None):
        return score.assess(files=files, risk=risk, risky_paths=RISKY)

    def test_a_small_safe_change_is_quick(self):
        result = self.assess(files=("README.md",))
        self.assertEqual(result["track"], "quick")
        self.assertFalse(result["split"])

    def test_S_005_1_a_risky_path_forces_story_whatever_the_size(self):
        with mock.patch.object(score, "RISK_WEIGHT", 0):
            result = self.assess(files=("src/auth/reset.ts",))
        self.assertLessEqual(result["score"], score.QUICK_MAX_SCORE)
        self.assertEqual(result["track"], "story")
        self.assertEqual(result["parts"]["risky_files"], ["src/auth/reset.ts"])

    def test_S_005_1_a_risk_field_forces_story_too(self):
        result = self.assess(risk="payments")
        self.assertLessEqual(result["score"], score.QUICK_MAX_SCORE)
        self.assertEqual(result["track"], "story")

    def test_S_005_2_above_the_story_threshold_it_flags_a_split(self):
        files = tuple(f"src/f{n}.ts" for n in range(score.STORY_MAX_SCORE + 1))
        result = self.assess(files=files)
        self.assertGreater(result["score"], score.STORY_MAX_SCORE)
        self.assertEqual(result["track"], "feature")
        self.assertTrue(result["split"])

    def test_S_005_2_at_the_threshold_it_does_not_split(self):
        files = tuple(f"src/f{n}.ts" for n in range(score.STORY_MAX_SCORE))
        result = self.assess(files=files)
        self.assertEqual(result["score"], score.STORY_MAX_SCORE)
        self.assertFalse(result["split"])

    def test_a_dependency_manifest_counts_as_a_new_dependency(self):
        result = self.assess(files=("package.json", "src/a.ts"))
        self.assertEqual(result["parts"]["dependency_files"], ["package.json"])
        self.assertEqual(result["score"], 2 * score.FILE_WEIGHT + score.DEPENDENCY_WEIGHT)

    def test_a_new_dependency_rules_out_quick_whatever_the_score(self):
        with mock.patch.object(score, "DEPENDENCY_WEIGHT", 0):
            result = self.assess(files=("package.json",))
        self.assertLessEqual(result["score"], score.QUICK_MAX_SCORE)
        self.assertEqual(result["track"], "story")

    def test_an_absolute_path_in_a_story_is_a_plain_error(self):
        with self.assertRaises(globs.GlobError):
            self.assess(files=("/etc/passwd",))

    def test_a_tests_only_story_with_no_files_listed_is_quick(self):
        self.assertEqual(self.assess()["track"], "quick")


class ScoreCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        (self.repo / ".accio").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_score(self, *args):
        return subprocess.run([sys.executable, "-I", str(SCORE), *args], cwd=self.repo,
                              capture_output=True, text=True, check=False)

    def test_S_005_3_prints_the_parts_it_used(self):
        path = self.repo / ".accio" / "stories" / "S-001.md"
        write(path, story_text(files=("src/auth/reset.ts", "package.json"), risk="auth"))
        result = self.run_score(str(path))
        self.assertEqual(result.returncode, 0, result.stderr)
        for expected in ("files 2", "src/auth/reset.ts", "package.json", "risk auth", "track story"):
            self.assertIn(expected, result.stdout)

    def test_json_output_uses_the_project_risky_paths(self):
        write(self.repo / ".accio" / "config.json", json.dumps({"risky_paths": ["billing/**"]}))
        path = self.repo / ".accio" / "stories" / "S-001.md"
        write(path, story_text(files=("billing/invoice.py",)))
        data = json.loads(self.run_score(str(path), "--json").stdout)
        self.assertEqual(data["track"], "story")
        self.assertEqual(data["parts"]["risky_files"], ["billing/invoice.py"])

    def test_an_absolute_path_gives_a_plain_message(self):
        path = self.repo / ".accio" / "stories" / "S-001.md"
        write(path, story_text(files=("/etc/hosts",)))
        result = self.run_score(str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("repo-relative", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_a_bad_story_file_gives_a_plain_message(self):
        path = self.repo / ".accio" / "stories" / "S-001.md"
        write(path, "---\nid: S-001\n")
        result = self.run_score(str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S-001.md", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
