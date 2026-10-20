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


class HooksFailClosedTest(unittest.TestCase):
    def setUp(self):
        data = json.loads((ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
        self.entries = [
            (event, hook)
            for event, groups in data["hooks"].items()
            for group in groups
            for hook in group["hooks"]
        ]

    def _find(self, script):
        return [(e, h) for e, h in self.entries if h["command"].endswith(f'/hooks/{script}"')]

    def test_S_028_1_guards_and_curfew_block_on_failure(self):
        for script, count in (("protego.py", 1), ("fidelius.py", 1), ("curfew.py", 2)):
            found = self._find(script)
            self.assertEqual(len(found), count, script)
            for event, hook in found:
                self.assertEqual(hook.get("onFailure"), "block", f"{script} in {event}")
        self.assertEqual({e for e, _ in self._find("curfew.py")}, {"PreToolUse", "PermissionRequest"})

    def test_S_028_2_doc_size_and_session_start_have_no_on_failure(self):
        for script in ("doc_size.py", "session_start.py"):
            found = self._find(script)
            self.assertTrue(found, script)
            for _, hook in found:
                self.assertNotIn("onFailure", hook, script)


if __name__ == "__main__":
    unittest.main()
