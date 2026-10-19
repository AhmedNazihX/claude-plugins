"""S-002: the plugin manifest, CI config and plugin validation."""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))

    def test_manifest_names_accio_with_a_version_and_description(self):
        self.assertEqual(self.manifest["name"], "accio")
        self.assertRegex(self.manifest["version"], SEMVER)
        self.assertTrue(self.manifest["description"].strip())
        self.assertTrue(self.manifest["author"]["name"].strip())

    @unittest.skipUnless(shutil.which("claude"), "the claude CLI is not installed (e.g. in CI)")
    def test_S_002_1_claude_plugin_validate_passes(self):
        result = subprocess.run(
            ["claude", "plugin", "validate", str(ROOT)], capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


class CiConfigTest(unittest.TestCase):
    def test_S_002_2_ci_runs_both_test_suites_on_macos_and_linux(self):
        text = (ROOT.parent / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")  # the marketplace's CI
        self.assertIn("working-directory: accio", text)
        lines = text.splitlines()
        runs = [line.strip() for line in lines if line.strip().startswith("run:")]
        matrix = [line.strip() for line in lines if line.strip().startswith("os:")]
        self.assertEqual(matrix, ["os: [ubuntu-latest, macos-latest]"])
        for command in ("python3 tests/run_tests.py", "node --test 'tests/workflow/**/*.test.mjs'"):
            self.assertTrue(any(command in run for run in runs), f"no run: step runs {command}")


if __name__ == "__main__":
    unittest.main()
