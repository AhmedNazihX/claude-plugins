"""S-011: setup proposes check commands (accio_lib.checkfinder)."""
import json
import pathlib
import tempfile
import unittest

from support import write

from accio_lib import checkfinder, config


def commands(repo):
    return [p["command"] for p in checkfinder.propose(pathlib.Path(repo))]


class CheckFinderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = pathlib.Path(self._tmp.name)

    def test_S_011_1_workflow_run_lines_with_a_keyword(self):
        write(self.repo / ".github/workflows/ci.yml", (
            "jobs:\n  t:\n    steps:\n"
            "      - run: npm ci\n"
            "      - run: npm run build\n"
            "      - name: x\n        run: |\n          make lint\n          echo hi\n          pytest -q\n"
            "      - run: python3 -m unittest discover\n"
            "      - run: ruff check .\n"
        ))
        self.assertEqual(commands(self.repo), [
            "npm run build", "make lint", "pytest -q", "python3 -m unittest discover", "ruff check ."])

    def test_S_011_1_proposals_fit_the_config_checks_shape(self):
        write(self.repo / ".github/workflows/ci.yml", "steps:\n  - run: make test\n")
        proposals = checkfinder.propose(self.repo)
        self.assertEqual(proposals, [{"command": "make test", "glob": "**"}])
        self.assertIsNone(config._check_checks(proposals))

    def test_S_011_2_package_json_test_and_lint_scripts(self):
        write(self.repo / "package.json", json.dumps({"scripts": {"test": "jest", "lint": "eslint .", "start": "x"}}))
        self.assertEqual(commands(self.repo), ["npm test", "npm run lint"])

    def test_S_011_2_package_json_without_scripts(self):
        write(self.repo / "package.json", "{}")
        self.assertEqual(commands(self.repo), [])

    def test_S_011_2_bad_package_json_is_ignored(self):
        write(self.repo / "package.json", "{nope")
        self.assertEqual(commands(self.repo), [])

    def test_S_011_3_pytest_folder(self):
        write(self.repo / "tests/test_a.py", "def test_a(): pass\n")
        self.assertEqual(commands(self.repo), ["python3 -m pytest tests"])

    def test_S_011_3_empty_tests_folder_is_not_pytest(self):
        write(self.repo / "tests/data.txt", "x")
        self.assertEqual(commands(self.repo), [])

    def test_S_011_4_nothing_found_says_so(self):
        self.assertEqual(checkfinder.propose(self.repo), [])
        self.assertIn("no check commands", checkfinder.describe([]).lower())

    def test_S_011_1_duplicates_are_proposed_once(self):
        write(self.repo / ".github/workflows/a.yml", "steps:\n  - run: npm test\n")
        write(self.repo / "package.json", json.dumps({"scripts": {"test": "jest"}}))
        self.assertEqual(commands(self.repo), ["npm test"])


if __name__ == "__main__":
    unittest.main()
