"""S-068: `ui_evidence` in config, and `accio-preview <ID> evidence` (screenshots of a native app's real window)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from support import ROOT, commit_all, git, init_repo, write

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

STEPS_TEXT = "open main\nresize 800x600\nminimize\nrestore\n"
GOOD = {"command": "app --ui-walk {steps} --out {folder}", "steps_doc": "docs/ui-walk.md", "takes_over_screen": False,
        "evidence_globs": []}


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
        for key in ("command", "steps_doc", "takes_over_screen", "evidence_globs"):
            with self.subTest(key=key):
                data = {name: value for name, value in GOOD.items() if name != key}
                message = self.refused({"ui_evidence": data})
                self.assertIn("ui_evidence", message)
                self.assertIn(key, message)

    def test_S_069_1_ui_evidence_without_evidence_globs_is_refused_naming_the_key(self):
        data = {name: value for name, value in GOOD.items() if name != "evidence_globs"}
        message = self.refused({"ui_evidence": data})
        self.assertIn("ui_evidence", message)
        self.assertIn("evidence_globs", message)

    def test_S_069_1_evidence_globs_must_be_a_list_of_globs_and_may_be_empty(self):
        for bad in ("src/**", [""], [1], None, {"a": "b"}):
            with self.subTest(bad=bad):
                message = self.refused({"ui_evidence": {**GOOD, "evidence_globs": bad}})
                self.assertIn("evidence_globs", message)
        loaded = self.load({"ui_evidence": {**GOOD, "evidence_globs": ["app/Walk*.swift"]}})["ui_evidence"]
        self.assertEqual(list(loaded["evidence_globs"]), ["app/Walk*.swift"])
        self.assertEqual(list(self.load({"ui_evidence": GOOD})["ui_evidence"]["evidence_globs"]), [])

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

    def test_S_070_5_a_timeout_above_540_is_refused_naming_prefects_600_second_limit(self):
        for timeout in (541, 600, 3600):
            with self.subTest(timeout=timeout):
                message = self.refused({"ui_evidence": {**GOOD, "timeout": timeout}})
                self.assertIn("ui_evidence", message)
                self.assertIn("540", message)
                self.assertIn("600", message)
        self.assertEqual(self.load({"ui_evidence": {**GOOD, "timeout": 540}})["ui_evidence"]["timeout"], 540)

    def test_S_070_5_without_a_timeout_the_evidence_command_gets_540_seconds(self):
        self.assertEqual(preview.DEFAULT_EVIDENCE_TIMEOUT, 540)
        self.assertEqual(config.EVIDENCE_TIMEOUT_MAX, 540)
        self.assertEqual(preview.evidence_timeout(self.load({"ui_evidence": GOOD})["ui_evidence"]), 540)
        self.assertEqual(preview.evidence_timeout({**GOOD, "timeout": 30}), 30)


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
        write(self.run_dir / "S-001" / preview.STEPS_NAME, STEPS_TEXT)
        self.folder = self.run_dir / "S-001" / preview.EVIDENCE_FOLDER

    def tearDown(self):
        self.tmp.cleanup()

    def settings(self, command=None, **extra):
        command = command or f"{sys.executable} {self.walk} {{steps}} {{folder}} {PNG.hex()}"
        return {"command": command, "steps_doc": "docs/ui-walk.md", "takes_over_screen": False,
                "evidence_globs": [], **extra}

    def run_evidence(self, settings, head=None, steps_sum=None):
        return preview.evidence(self.run_dir, self.worktree, "S-001", settings, head or self.head, steps_sum)

    def stamp(self):
        return (self.run_dir / "S-001" / preview.STAMP_NAME).read_text(encoding="utf-8").strip()

    def test_S_068_1_the_command_runs_in_the_worktree_with_the_steps_file_and_folder_filled_in(self):
        result = self.run_evidence(self.settings(fresh_checkout=False))  # S-073: the live worktree, by choice
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
        other = "1" * 40  # in the live worktree (S-073): a fresh checkout of an unknown commit can't even start
        result = self.run_evidence(self.settings(fresh_checkout=False), head=other)
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

    def test_S_070_4_steps_sum_is_32_bit_fnv_1a_over_the_texts_code_points(self):
        for text, expected in (("", "811c9dc5"), ("a", "e40c292c"), ("foobar", "bf9cf968")):
            with self.subTest(text=text):
                self.assertEqual(preview.steps_sum(text), expected)
        self.assertNotEqual(preview.steps_sum("open main\n"), preview.steps_sum("open main"))
        self.assertRegex(preview.steps_sum("café ☕ \U0001F600"), r"^[0-9a-f]{8}$")

    def test_S_070_4_a_matching_steps_file_runs_the_command(self):
        result = self.run_evidence(self.settings(), steps_sum=preview.steps_sum(STEPS_TEXT))
        self.assertTrue(result.get("ok"), result)

    def test_S_070_4_a_changed_steps_file_never_runs_the_command_and_says_it_was_changed(self):
        marker = pathlib.Path(self.tmp.name) / "ran"
        settings = self.settings(command=f"touch {marker} {{steps}} {{folder}}")
        write(self.folder / "old.png", "")
        for changed in (STEPS_TEXT + "\n", STEPS_TEXT.rstrip("\n"), STEPS_TEXT.replace("main", "Main"), ""):
            with self.subTest(changed=changed):
                write(self.run_dir / "S-001" / preview.STEPS_NAME, changed)
                result = self.run_evidence(settings, steps_sum=preview.steps_sum(STEPS_TEXT))
                self.assertTrue(result["skipped"])
                self.assertIn(f"{preview.STEPS_NAME} was changed", result["reason"])
                self.assertIn("did not run", result["reason"])
                self.assertFalse(marker.exists())
                self.assertTrue((self.folder / "old.png").exists(), "the old evidence is left alone")

    def test_S_070_4_a_steps_file_that_is_not_utf8_counts_as_changed(self):
        (self.run_dir / "S-001" / preview.STEPS_NAME).write_bytes(b"\xff\xfe open")
        result = self.run_evidence(self.settings(), steps_sum=preview.steps_sum(STEPS_TEXT))
        self.assertTrue(result["skipped"])
        self.assertIn("was changed", result["reason"])

    def test_S_070_4_the_cli_takes_steps_sum_and_refuses_a_changed_file(self):
        write(self.accio / "config.json", json.dumps({"ui_evidence": self.settings()}))
        base = [sys.executable, str(PREVIEW), "S-001", "evidence", "--head", self.head, "--steps-sum"]
        good = subprocess.run(base + [preview.steps_sum(STEPS_TEXT)], cwd=self.root, capture_output=True, text=True,
                              timeout=60)
        self.assertEqual(json.loads(good.stdout).get("screenshots"), 1, good.stderr)
        bad = subprocess.run(base + ["00000000"], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(bad.returncode, 0, bad.stderr)
        self.assertIn("was changed", json.loads(bad.stdout)["reason"])
        odd = subprocess.run(base + ["not-hex"], cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertEqual(odd.returncode, 1)
        self.assertIn("--steps-sum", odd.stderr)

    def story_changes(self, *names):
        """The worktree's repo leaves main with one commit that adds `names`; returns the new head."""
        git(self.worktree, "checkout", "-q", "-b", "story/S-001")
        for name in names:
            write(self.worktree / name, "changed\n")
        commit_all(self.worktree, "story")
        return git(self.worktree, "rev-parse", "HEAD")

    def globbed(self, **extra):
        return self.settings(evidence_globs=["app/Walk*.swift", "scripts/capture.*"], **extra)

    def test_S_069_2_a_diff_touching_an_evidence_glob_never_runs_the_command_and_names_the_files(self):
        head = self.story_changes("app/WalkMode.swift", "app/View.swift", "scripts/capture.sh")
        marker = pathlib.Path(self.tmp.name) / "ran"
        result = self.run_evidence(self.globbed(command=f"touch {marker} {{steps}} {{folder}}"), head=head,
                                   )
        self.assertTrue(result["skipped"])
        self.assertIn("app/WalkMode.swift, scripts/capture.sh", result["reason"])
        self.assertNotIn("View.swift", result["reason"])
        self.assertIn("a person should look", result["reason"])
        self.assertFalse(marker.exists())

    def test_S_069_2_when_git_cannot_say_the_evidence_is_not_trusted(self):
        files, problem = preview.evidence_files(self.run_dir, self.worktree, "S-001", self.globbed(), "no-such-branch")
        self.assertEqual(files, [])
        self.assertIn("can't be trusted", problem)
        write(self.accio / "config.json", json.dumps({"base_branch": "no-such-branch"}))
        result = self.run_evidence(self.globbed())
        self.assertTrue(result["skipped"])
        self.assertIn("can't be trusted", result["reason"])

    def test_S_069_3_a_diff_touching_no_evidence_glob_runs_the_evidence_step_as_before(self):
        head = self.story_changes("app/View.swift")
        result = self.run_evidence(self.globbed(), head=head)
        self.assertEqual(result, {"ok": True, "folder": str(self.folder), "head": head, "screenshots": 1})
        files, problem = preview.evidence_files(self.run_dir, self.worktree, "S-001", self.globbed(), "main")
        self.assertEqual((files, problem), ([], ""))

    def test_S_069_2_the_cli_run_sees_the_touched_files(self):
        head = self.story_changes("scripts/capture.sh")
        write(self.accio / "config.json", json.dumps({"ui_evidence": self.globbed()}))
        ran = subprocess.run([sys.executable, str(PREVIEW), "S-001", "evidence", "--head", head],
                             cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertIn("scripts/capture.sh", json.loads(ran.stdout)["reason"], ran.stderr)

    def test_S_077_3_only_a_full_lowercase_commit_id_is_taken_as_head(self):
        head = self.story_changes("app/View.swift")
        write(self.accio / "config.json", json.dumps({"ui_evidence": self.settings()}))
        for bad in (head[:7], head[:12], head[:39], head.upper(), head + "0", "zz" * 20):
            ran = subprocess.run([sys.executable, str(PREVIEW), "S-001", "evidence", "--head", bad],
                                 cwd=self.root, capture_output=True, text=True, timeout=60)
            self.assertEqual(ran.returncode, 1, bad)
            self.assertIn("40", ran.stderr)
            self.assertEqual(ran.stdout, "")

    def marked(self, **extra):
        """Settings whose command leaves a marker file, and the marker's path."""
        marker = pathlib.Path(self.tmp.name) / "ran"
        return self.settings(command=f"touch {marker} {{steps}} {{folder}}", **extra), marker

    def assert_skipped_naming(self, result, marker, *names):
        self.assertTrue(result.get("skipped"), result)
        self.assertIn("not committed", result["reason"])
        for name in names:
            self.assertIn(name, result["reason"])
        self.assertFalse(marker.exists(), "the evidence command must not run")

    def test_S_071_2_a_changed_tracked_file_never_runs_the_command_and_names_it(self):
        write(self.worktree / "README.md", "changed, not committed\n")
        settings, marker = self.marked()
        self.assert_skipped_naming(self.run_evidence(settings), marker, "README.md")

    def test_S_071_2_a_staged_file_never_runs_the_command_and_names_it(self):
        write(self.worktree / "app" / "Staged.swift", "staged\n")
        git(self.worktree, "add", "app/Staged.swift")
        settings, marker = self.marked()
        self.assert_skipped_naming(self.run_evidence(settings), marker, "app/Staged.swift")

    def test_S_071_2_an_untracked_file_never_runs_the_command_and_names_it_even_inside_a_new_folder(self):
        write(self.worktree / "app" / "walk" / "Hidden.swift", "untracked\n")
        write(self.worktree / "notes.txt", "untracked\n")
        settings, marker = self.marked(evidence_globs=["app/Walk*.swift"])
        self.assert_skipped_naming(self.run_evidence(settings), marker, "app/walk/Hidden.swift", "notes.txt")

    def test_S_071_2_a_long_list_of_files_is_cut_short_with_a_count(self):
        for index in range(preview.MAX_NAMED_FILES + 5):
            write(self.worktree / f"extra-{index:03}.txt", "x\n")
        settings, marker = self.marked()
        result = self.run_evidence(settings)
        self.assert_skipped_naming(result, marker, "extra-000.txt", "and 5 more")
        self.assertNotIn(f"extra-{preview.MAX_NAMED_FILES:03}.txt", result["reason"])

    def test_S_071_2_ignored_files_do_not_count_and_a_clean_worktree_runs_as_before(self):
        write(self.worktree / ".gitignore", "build/\n")
        commit_all(self.worktree, "ignore build")
        write(self.worktree / "build" / "App.o", "built\n")
        head = git(self.worktree, "rev-parse", "HEAD")
        self.assertEqual(preview.worktree_changes(self.worktree), ([], ""))
        result = self.run_evidence(self.settings(), head=head)
        self.assertEqual(result, {"ok": True, "folder": str(self.folder), "head": head, "screenshots": 1})

    def test_S_071_2_when_git_cannot_say_the_command_never_runs(self):
        plain = pathlib.Path(self.tmp.name) / "not-a-repo"
        plain.mkdir()
        files, problem = preview.worktree_changes(plain)
        self.assertEqual(files, [])
        self.assertIn("can't tell", problem)
        settings, marker = self.marked()
        result = preview.evidence(self.run_dir, plain, "S-001", settings, self.head)
        self.assertTrue(result["skipped"])
        self.assertIn("can't tell", result["reason"])
        self.assertFalse(marker.exists())

    def test_S_071_2_the_cli_run_names_the_uncommitted_files(self):
        write(self.worktree / "scripts" / "capture.sh", "untracked\n")
        write(self.accio / "config.json", json.dumps({"ui_evidence": self.settings()}))
        ran = subprocess.run([sys.executable, str(PREVIEW), "S-001", "evidence", "--head", self.head],
                             cwd=self.root, capture_output=True, text=True, timeout=60)
        self.assertIn("scripts/capture.sh", json.loads(ran.stdout)["reason"], ran.stderr)

    def test_S_071_3_a_path_matching_an_evidence_glob_apart_from_letter_case_counts_as_touching_it(self):
        head = self.story_changes("APP/walkmode.SWIFT", "Scripts/Capture.sh", "app/View.swift")
        settings, marker = self.marked(evidence_globs=["app/Walk*.swift", "scripts/capture.*"])
        files, problem = preview.evidence_files(self.run_dir, self.worktree, "S-001", settings, "main")
        self.assertEqual((files, problem), (["APP/walkmode.SWIFT", "Scripts/Capture.sh"], ""))
        result = self.run_evidence(settings, head=head)
        self.assertTrue(result["skipped"])
        self.assertIn("APP/walkmode.SWIFT, Scripts/Capture.sh", result["reason"])
        self.assertFalse(marker.exists())

    def test_S_071_3_an_upper_case_glob_matches_a_lower_case_path_too(self):
        self.story_changes("sources/uiwalk/x.swift")
        files, _ = preview.evidence_files(self.run_dir, self.worktree, "S-001",
                                          self.settings(evidence_globs=["Sources/UIWalk/**"]), "main")
        self.assertEqual(files, ["sources/uiwalk/x.swift"])

    def test_S_068_7_a_command_that_takes_over_the_screen_never_runs(self):
        marker = pathlib.Path(self.tmp.name) / "ran"
        result = self.run_evidence(self.settings(command=f"touch {marker} {{steps}} {{folder}}", takes_over_screen=True))
        self.assertTrue(result["skipped"])
        self.assertIn("takes over the screen", result["reason"])
        self.assertIn("unattended", result["reason"])
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
