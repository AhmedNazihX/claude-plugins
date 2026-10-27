"""S-091: accio asks about the mutation check once per repo, and owl says when tests weren't checked."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

from accio_lib import config, mutationfinder, summary

FINDER = ROOT / "bin" / "accio_lib" / "mutationfinder.py"
WAND = ROOT / "skills" / "wand" / "SKILL.md"
NOTE = "Tests not checked for weak spots: the mutation check is off."


class MutationFinderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name)

    def tools(self):
        return mutationfinder.find(self.repo)

    def test_S_091_1_each_marker_names_its_tool(self):
        for marker, tool in (("pyproject.toml", "mutmut"), ("setup.py", "mutmut"), ("package.json", "Stryker"),
                             ("Cargo.toml", "cargo-mutants"), ("Package.swift", "Muter")):
            with self.subTest(marker=marker):
                folder = self.repo / marker.replace(".", "_")
                write(folder / marker, "x")
                self.assertEqual(mutationfinder.find(folder), [tool])

    def test_S_091_1_py_file_and_xcodeproj(self):
        write(self.repo / "src" / "a.py", "x = 1\n")
        self.assertEqual(self.tools(), ["mutmut"])
        (self.repo / "App.xcodeproj").mkdir()
        self.assertEqual(self.tools(), ["mutmut", "Muter"])

    def test_S_091_1_more_than_one_language_names_each(self):
        write(self.repo / "package.json", "{}")
        write(self.repo / "Cargo.toml", "x")
        write(self.repo / "setup.py", "x")
        self.assertEqual(self.tools(), ["mutmut", "Stryker", "cargo-mutants"])
        self.assertEqual(mutationfinder.describe(self.tools()), "mutmut, Stryker, cargo-mutants")

    def test_S_091_1_none_known_and_nothing_written(self):
        self.assertEqual(mutationfinder.describe(self.tools()), "none known")
        result = subprocess.run([sys.executable, "-I", str(FINDER), str(self.repo)], capture_output=True, text=True)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, "none known"))
        self.assertEqual(list(self.repo.iterdir()), [])

    def test_S_091_1_run_as_a_script_prints_the_tool(self):
        write(self.repo / "Cargo.toml", "x")
        result = subprocess.run([sys.executable, "-I", str(FINDER), str(self.repo)], capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), "cargo-mutants")


class WandSkillTest(unittest.TestCase):
    def setUp(self):
        text = WAND.read_text(encoding="utf-8")
        self.head = text.split("---", 2)[1]
        self.step = " ".join(text.split("**Check commands.**", 1)[1].split("**New design or design note.**", 1)[0].split())

    def test_S_091_2_wand_may_run_the_finder(self):
        self.assertIn("Bash(python3 ${CLAUDE_PLUGIN_ROOT}/bin/accio_lib/mutationfinder.py)", self.head)

    def test_S_091_2_question_is_asked_once_only_when_the_key_is_missing_and_a_tool_is_named(self):
        self.assertIn("mutationfinder.py", self.step)
        self.assertIn("has no `mutation` key", self.step)
        self.assertIn("Your tests aren't checked for weak spots. Turn on the mutation check with", self.step)
        self.assertIn("its own message", self.step)
        self.assertIn("none known", self.step)
        self.assertIn("don't ask", self.step)

    def test_S_091_2_no_writes_false_and_yes_gives_steps(self):
        self.assertIn('`"mutation": false`', self.step)
        self.assertIn("dev dependency", self.step)
        self.assertIn("{diff}", self.step)
        self.assertIn("`file:line`", self.step)


class ConfigMutationTest(unittest.TestCase):
    def load(self, data):
        with tempfile.TemporaryDirectory() as tmp:
            write(pathlib.Path(tmp) / "config.json", json.dumps(data))
            return config.load(pathlib.Path(tmp))

    def test_S_091_3_false_is_accepted_and_means_not_audited(self):
        self.assertIs(self.load({"mutation": False})["mutation"], False)
        self.assertFalse(self.load({"mutation": False})["mutation"])

    def test_S_091_3_true_and_other_values_are_still_refused(self):
        for bad in (True, "mutmut", 3, {"command": "x"}):
            with self.subTest(bad=bad), self.assertRaises(config.ConfigError):
                self.load({"mutation": bad})

    def test_S_091_3_a_command_still_works(self):
        self.assertEqual(self.load({"mutation": {"command": "m {diff}"}})["mutation"]["command"], "m {diff}")


class OwlNoteTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.accio = pathlib.Path(self._tmp.name) / ".accio"
        self.accio.mkdir()

    def summarise(self, data):
        if data is not None:
            write(self.accio / "config.json", json.dumps(data))
        return summary.render({}, {}, self.accio / "run", {})

    def test_S_091_4_missing_key_starts_owl_with_the_note(self):
        for data in (None, {}, {"wip": 2}):
            with self.subTest(data=data):
                text = self.summarise(data)
                self.assertTrue(text.startswith(NOTE), text)
                self.assertIn('Set `mutation.command` in .accio/config.json, or `"mutation": false` to stop this '
                              "note.", text.splitlines()[0])

    def test_S_091_4_false_or_a_command_leaves_it_out(self):
        for data in ({"mutation": False}, {"mutation": {"command": "m {diff}"}}):
            with self.subTest(data=data):
                self.assertNotIn("Tests not checked", self.summarise(data))
                self.assertTrue(self.summarise(data).startswith("# Review"))

    def test_S_091_4_accio_summary_writes_it(self):
        repo = init_repo(pathlib.Path(self._tmp.name) / "app")
        (repo / ".accio").mkdir()
        result = subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "accio-summary"), "--latest"],
                                cwd=repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((repo / ".accio" / "run" / "owl.md").read_text().startswith(NOTE))
        write(repo / ".accio" / "config.json", json.dumps({"mutation": False}))
        subprocess.run([sys.executable, "-I", str(ROOT / "bin" / "accio-summary"), "--latest"],
                       cwd=repo, capture_output=True, text=True)
        self.assertNotIn("Tests not checked", (repo / ".accio" / "run" / "owl.md").read_text())


if __name__ == "__main__":
    unittest.main()
