"""S-068: `ui_evidence` in config, and `accio-preview <ID> evidence` (screenshots of a native app's real window)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from support import ROOT, git, init_repo, write

from accio_lib import config, paths, preview

PREVIEW = ROOT / "bin" / "accio-preview"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16  # the PNG signature, then filler: enough for the count
# The project's walk: copies the steps it was given, notes where it ran, and saves one window screenshot.
WALK_SCRIPT = """import os, pathlib, sys
steps, folder = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
(folder / "steps-seen.txt").write_text(steps.read_text())
(folder / "cwd.txt").write_text(os.getcwd())
(folder / "main-light.png").write_bytes(bytes.fromhex(sys.argv[3]))
"""

GOOD = {"command": "app --ui-walk {steps} --out {folder}", "steps_doc": "docs/ui-walk.md", "takes_over_screen": False}


class EvidenceConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.accio = pathlib.Path(self.tmp.name).resolve() / ".accio"

    def tearDown(self):
        self.tmp.cleanup()

    def load(self, data):
        write(self.accio / "config.json", json.dumps(data))
        return config.load(self.accio)

    def refused(self, data):
        with self.assertRaises(config.ConfigError) as caught:
            self.load(data)
        return str(caught.exception)

    def test_S_068_8_a_good_ui_evidence_loads_and_defaults_to_none(self):
        self.assertIsNone(self.load({})["ui_evidence"])
        settings = self.load({"ui_evidence": {**GOOD, "themes": ["light", "dark"], "timeout": 120}})["ui_evidence"]
        self.assertEqual(settings["command"], GOOD["command"])
        self.assertEqual(list(settings["themes"]), ["light", "dark"])

    def test_S_068_8_preview_and_ui_evidence_together_are_refused_with_set_one(self):
        preview = {"command": "npm start", "url": "http://localhost:3000", "test_data": True}
        message = self.refused({"preview": preview, "ui_evidence": GOOD})
        self.assertIn("set one", message)
        self.assertIn("preview", message)
        self.assertIn("ui_evidence", message)

    def test_S_068_8_a_missing_required_key_is_named(self):
        for key in ("command", "steps_doc", "takes_over_screen"):
            with self.subTest(key=key):
                data = {name: value for name, value in GOOD.items() if name != key}
                message = self.refused({"ui_evidence": data})
                self.assertIn("ui_evidence", message)
                self.assertIn(key, message)

    def test_S_068_8_a_command_without_steps_or_folder_is_named(self):
        for command, missing in (("app --out {folder}", "{steps}"), ("app {steps}", "{folder}"), ("", "{steps}")):
            with self.subTest(command=command):
                message = self.refused({"ui_evidence": {**GOOD, "command": command}})
                self.assertIn(missing, message)

    def test_S_068_8_bad_values_are_refused(self):
        bad = ({"takes_over_screen": "no"}, {"steps_doc": ""}, {"steps_doc": "/abs/ui-walk.md"},
               {"steps_doc": "../outside.md"}, {"themes": "dark"}, {"themes": ["light", ""]}, {"timeout": 0},
               {"timeout": True}, {"unknown": 1})
        for extra in bad:
            with self.subTest(extra=extra):
                self.assertIn("ui_evidence", self.refused({"ui_evidence": {**GOOD, **extra}}))
        self.assertIn("ui_evidence", self.refused({"ui_evidence": "app"}))


class EvidenceRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name).resolve()
        self.root = init_repo(base / "my repo")  # a space: the filled-in paths must be quoted
        self.accio = self.root / ".accio"
        self.run_dir = self.accio / "run"
        self.worktree = init_repo(paths.worktree_root(self.root) / "S-001")
        self.head = git(self.worktree, "rev-parse", "HEAD")
        self.walk = base / "walk.py"
        self.walk.write_text(WALK_SCRIPT)
        write(self.run_dir / "S-001" / preview.STEPS_NAME, "open main\nresize 800x600\nminimize\nrestore\n")
        self.folder = self.run_dir / "S-001" / preview.EVIDENCE_FOLDER

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, command=None, **extra):
        command = command or f"{sys.executable} {self.walk} {{steps}} {{folder}} {PNG.hex()}"
        return {"command": command, "steps_doc": "docs/ui-walk.md", "takes_over_screen": False, **extra}

    def run_evidence(self, settings, head=None):
        return preview.evidence(self.run_dir, self.worktree, "S-001", settings, head or self.head)

    def stamp(self):
        return (self.run_dir / "S-001" / preview.STAMP_NAME).read_text(encoding="utf-8").strip()

    def test_S_068_1_the_command_runs_in_the_worktree_with_the_steps_file_and_folder_filled_in(self):
        result = self.run_evidence(self.settings())
        self.assertEqual(result, {"ok": True, "folder": str(self.folder), "head": self.head, "screenshots": 1})
        self.assertEqual((self.folder / "cwd.txt").read_text(), str(self.worktree))
        self.assertEqual((self.folder / "steps-seen.txt").read_text(), "open main\nresize 800x600\nminimize\nrestore\n")
        self.assertEqual(self.stamp(), self.head)

    def test_S_068_1_the_folder_is_emptied_first_so_nothing_left_there_counts(self):
        write(self.folder / "old.png", "")
        (self.folder / "old.png").write_bytes(PNG)
        write(self.folder / "dark" / "older.png", "")
        result = self.run_evidence(self.settings(command="true {steps} {folder}"))
        self.assertTrue(result["skipped"])
        self.assertFalse((self.folder / "old.png").exists())
        self.assertFalse((self.folder / "dark").exists())

    def test_S_068_1_screenshots_in_theme_subfolders_count(self):
        script = (f"{sys.executable} -c \"import pathlib,sys; d=pathlib.Path(sys.argv[2]); "
                  f"[(d/t).mkdir() for t in ('light','dark')]; "
                  f"[(d/t/'main.png').write_bytes(bytes.fromhex('{PNG.hex()}')) for t in ('light','dark')]\" "
                  "{steps} {folder}")
        self.assertEqual(self.run_evidence(self.settings(command=script))["screenshots"], 2)

    def test_S_068_1_the_cli_prints_the_result_as_json(self):
        write(self.accio / "config.json", json.dumps({"ui_evidence": self.settings()}))
        result = subprocess.run([sys.executable, str(PREVIEW), "S-001", "evidence", "--head", self.head],
                                cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["screenshots"], 1)
        plan = subprocess.run([sys.executable, str(PREVIEW), "S-001", "evidence-plan"],
                              cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(json.loads(plan.stdout), {"ui_evidence": True, "takes_over_screen": False,
                                                   "steps_doc": "docs/ui-walk.md", "themes": []})

    def test_S_068_1_the_plan_without_ui_evidence_says_so(self):
        self.assertEqual(preview.evidence_plan(None), {"ui_evidence": False})
        plan = preview.evidence_plan(self.settings(themes=["light", "dark"], takes_over_screen=True))
        self.assertEqual(plan["themes"], ["light", "dark"])
        self.assertTrue(plan["takes_over_screen"])

    def test_S_068_2_a_failing_command_is_a_skip_that_says_it_failed(self):
        result = self.run_evidence(self.settings(command="echo broken-walk {steps} {folder}; exit 3"))
        self.assertTrue(result["skipped"])
        self.assertIn("exited with 3", result["reason"])
        self.assertIn(preview.EVIDENCE_LOG, result["reason"])
        self.assertIn("broken-walk", (self.run_dir / "S-001" / preview.EVIDENCE_LOG).read_text())
        self.assertFalse((self.run_dir / "S-001" / preview.STAMP_NAME).exists())

    def test_S_068_2_a_command_past_its_timeout_is_stopped_and_skipped(self):
        started = time.monotonic()
        result = self.run_evidence(self.settings(command="sleep 30; echo {steps} {folder}", timeout=1))
        self.assertLess(time.monotonic() - started, 20)
        self.assertTrue(result["skipped"])
        self.assertIn("timeout of 1s", result["reason"])

    def test_S_068_2_a_folder_with_no_png_screenshots_is_skipped(self):
        fake = "touch {folder}/main.png {folder}/dump.txt {steps}"  # an empty main.png is no screenshot
        result = self.run_evidence(self.settings(command=fake))
        self.assertTrue(result["skipped"])
        self.assertIn("no PNG screenshots", result["reason"])
        self.assertFalse((self.run_dir / "S-001" / preview.STAMP_NAME).exists())

    def test_S_068_2_a_missing_steps_file_is_skipped(self):
        (self.run_dir / "S-001" / preview.STEPS_NAME).unlink()
        result = self.run_evidence(self.settings())
        self.assertTrue(result["skipped"])
        self.assertIn(preview.STEPS_NAME, result["reason"])

    def test_S_068_5_a_stamp_for_another_commit_is_refused_naming_both(self):
        other = "1" * 40
        result = self.run_evidence(self.settings(), head=other)
        self.assertTrue(result["skipped"])
        self.assertIn(self.head[:12], result["reason"])
        self.assertIn(other[:12], result["reason"])

    def test_S_068_5_stamp_problem_refuses_a_missing_or_different_stamp(self):
        self.assertIn("missing", preview.stamp_problem(self.run_dir, "S-001", self.head))
        self.assertIn(self.head[:12], preview.stamp_problem(self.run_dir, "S-001", self.head))
        write(self.run_dir / "S-001" / preview.STAMP_NAME, "2" * 40 + "\n")
        problem = preview.stamp_problem(self.run_dir, "S-001", self.head)
        self.assertIn("2" * 12, problem)
        self.assertIn(self.head[:12], problem)
        write(self.run_dir / "S-001" / preview.STAMP_NAME, self.head + "\n")
        self.assertEqual(preview.stamp_problem(self.run_dir, "S-001", self.head), "")

    def test_S_068_5_a_new_run_removes_the_old_stamp_first(self):
        write(self.run_dir / "S-001" / preview.STAMP_NAME, self.head + "\n")
        self.run_evidence(self.settings(command="false {steps} {folder}"))
        self.assertFalse((self.run_dir / "S-001" / preview.STAMP_NAME).exists())

    def test_S_068_7_a_command_that_takes_over_the_screen_never_runs(self):
        marker = pathlib.Path(self.tmp.name) / "ran"
        result = self.run_evidence(self.settings(command=f"touch {marker} {{steps}} {{folder}}", takes_over_screen=True))
        self.assertTrue(result["skipped"])
        self.assertIn("takes over the screen", result["reason"])
        self.assertIn("unattended", result["reason"])
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
