"""S-041: accio-break try and verify (a repro against a story's head and base)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import breaker, config, paths

BREAK = ROOT / "bin" / "accio-break"
STORY = """---
id: S-001
title: Reset link
track: story
status: doing
files: [src/a.py]
---
## Definition of Done
- [ ] S-001/1 WHEN a user asks THE SYSTEM SHALL send a link
"""
COMMAND = "PYTHONPATH=. python3 {file}"
HEADER = "# claim: the value stays 1\n# source: S-001/1\n"
KEEPS_VALUE = HEADER + "from src.a import value\nassert value == 1, 'value changed'\n"


class BreakerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.scratch = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.scratch / "app")
        write(self.repo / ".gitignore", ".accio/run/\n")
        write(self.repo / "src" / "a.py", "value = 1\n")
        self.accio = self.repo / ".accio"
        self.configure({"command": COMMAND})
        write(self.accio / "stories" / "S-001.md", STORY)
        commit_all(self.repo)
        self.worktree = paths.worktree_root(self.repo) / "S-001"
        git(self.repo, "worktree", "add", "-q", str(self.worktree), "-b", "story/S-001")
        self.change("value = 2\n")
        self.boggart = self.accio / "run" / "S-001" / "boggart"

    def tearDown(self):
        self.tmp.cleanup()

    def configure(self, breaker_settings):
        settings = {} if breaker_settings is None else {"breaker": breaker_settings}
        write(self.accio / "config.json", json.dumps(settings))

    def change(self, text):
        write(self.worktree / "src" / "a.py", text)
        commit_all(self.worktree, "story work")

    def repro(self, name, text):
        path = self.scratch / name
        write(path, text)
        return path

    def run_break(self, *args):
        result = subprocess.run([sys.executable, "-I", str(BREAK), "S-001", *args], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def try_repro(self, name, text):
        return self.run_break("try", str(self.repro(name, text)))["repros"][0]

    def test_S_041_1_assertion_on_head_passing_on_base_is_kept_with_its_claim(self):
        entry = self.try_repro("repro_a.py", KEEPS_VALUE)
        self.assertEqual(entry["verdict"], "kept")
        self.assertEqual(entry["claim"], "the value stays 1")
        self.assertEqual(entry["source"], "S-001/1")
        self.assertTrue(entry["in_dod"])

    def test_S_041_1_a_source_that_is_not_a_dod_id_is_not_in_dod(self):
        text = "# claim: stays 1\n# source: src/a.py:1\nfrom src.a import value\nassert value == 1\n"
        entry = self.try_repro("repro_b.py", text)
        self.assertEqual((entry["verdict"], entry["in_dod"]), ("kept", False))

    def test_S_041_2_crash_in_a_changed_file_twice_is_kept(self):
        self.change("raise RuntimeError('boom')\n")
        entry = self.try_repro("repro_c.py", HEADER + "from src.a import value\n")
        self.assertEqual(entry["verdict"], "kept")
        self.assertIn("src/a.py", entry["reason"])

    def test_S_041_3_setup_error_is_dropped(self):
        entry = self.try_repro("repro_d.py", HEADER + "import no_such_module_anywhere\n")
        self.assertEqual(entry["verdict"], "dropped")
        self.assertIn("setup error", entry["reason"])

    def test_S_041_3_every_marker_counts_as_a_setup_error(self):
        for text in ("raise ModuleNotFoundError('x')", "raise SyntaxError('x')", "raise IndentationError('x')",
                     "raise RuntimeError(\"fixture 'db' not found\")", "raise RuntimeError('zzz: command not found')"):
            with self.subTest(text=text):
                self.assertEqual(self.try_repro("repro_e.py", HEADER + text + "\n")["verdict"], "dropped")

    def test_S_041_4_a_pass_on_head_is_dropped(self):
        entry = self.try_repro("repro_f.py", HEADER + "from src.a import value\nassert value == 2\n")
        self.assertEqual((entry["verdict"], entry["reason"]), ("dropped", "passed on head"))

    def test_S_041_5_failing_in_only_one_of_two_runs_is_dropped(self):
        counter = self.scratch / "count"
        text = HEADER + (f"import os\nif not os.path.exists({str(counter)!r}):\n"
                         f"    open({str(counter)!r}, 'w').close()\n    raise AssertionError('first run')\n")
        entry = self.try_repro("repro_g.py", text)
        self.assertEqual(entry["verdict"], "dropped")
        self.assertIn("1 of 2", entry["reason"])

    def test_S_041_6_failing_on_base_too_is_pre_existing(self):
        entry = self.try_repro("repro_h.py", HEADER + "assert False, 'always'\n")
        self.assertEqual(entry["verdict"], "pre-existing")
        self.assertIn("out of scope", entry["reason"])

    def add_module(self):
        write(self.worktree / "src" / "b.py", "count = 5\n")
        commit_all(self.worktree, "story adds b")

    def test_S_055_1_a_setup_error_on_base_means_the_code_is_new_so_the_break_is_kept(self):
        self.add_module()
        entry = self.try_repro("repro_n.py", HEADER + "from src.b import count\nassert count == 1, 'count'\n")
        self.assertEqual(entry["verdict"], "kept")
        self.assertIn("isn't on base", entry["reason"])

    def test_S_055_1_a_crash_on_head_with_a_setup_error_on_base_is_kept(self):
        self.add_module()
        write(self.worktree / "src" / "b.py", "raise RuntimeError('boom')\n")
        commit_all(self.worktree, "story breaks b")
        entry = self.try_repro("repro_o.py", HEADER + "import src.b\n")
        self.assertEqual(entry["verdict"], "kept")
        self.assertIn("isn't on base", entry["reason"])

    def test_S_055_2_a_failure_on_base_without_a_setup_error_is_still_pre_existing(self):
        self.add_module()
        entry = self.try_repro("repro_p.py", HEADER + "from src.a import value\nassert value == 99, 'never'\n")
        self.assertEqual(entry["verdict"], "pre-existing")
        self.assertIn("out of scope", entry["reason"])

    def test_S_055_3_a_repro_importing_a_new_module_that_fails_an_assertion_is_kept_end_to_end(self):
        self.add_module()
        result = self.run_break("try", str(self.repro("repro_r.py", HEADER + "from src.b import count\nassert count == 1\n")))
        self.assertEqual(result["repros"][0]["verdict"], "kept")

    def test_S_041_7_a_missing_or_empty_claim_is_dropped(self):
        for header in ("# source: S-001/1\n", "# claim:\n# source: S-001/1\n", "# claim: a claim\n",
                       "# claim: a claim\n# source:\n"):
            with self.subTest(header=header):
                entry = self.try_repro("repro_i.py", header + "from src.a import value\nassert value == 1\n")
                self.assertEqual(entry["verdict"], "dropped")
                self.assertIn("no written claim", entry["reason"])

    def test_S_041_8_no_breaker_command_skips_and_logs(self):
        self.configure(None)
        reply = self.run_break("try", str(self.repro("repro_j.py", KEEPS_VALUE)))
        self.assertTrue(reply["skipped"])
        self.assertIn("no `breaker` command", (self.boggart / "log.txt").read_text())
        self.assertTrue(self.run_break("verify")["skipped"])
        self.assertFalse((self.boggart / "verdicts.json").exists())

    def test_S_041_9_verify_records_a_pass_after_a_fix_round_as_fixed(self):
        self.try_repro("repro_k.py", KEEPS_VALUE)
        self.try_repro("repro_l.py", HEADER + "import no_such_module_anywhere\n")
        first = {entry["file"]: entry for entry in self.run_break("verify")["repros"]}
        self.assertEqual(first["repro_k.py"]["verdict"], "kept")
        self.assertEqual(first["repro_l.py"]["verdict"], "dropped")
        self.assertEqual(json.loads((self.boggart / "verdicts.json").read_text())["repros"][0]["file"], "repro_k.py")
        self.change("value = 1\n")
        second = {entry["file"]: entry for entry in self.run_break("verify")["repros"]}
        self.assertEqual(second["repro_k.py"]["verdict"], "fixed")
        self.assertEqual(second["repro_k.py"]["claim"], "the value stays 1")

    def test_S_041_9_a_kept_repro_that_still_fails_stays_kept(self):
        self.try_repro("repro_m.py", KEEPS_VALUE)
        self.run_break("verify")
        self.change("value = 3\n")
        self.assertEqual(self.run_break("verify")["repros"][0]["verdict"], "kept")

    def verdicts_by_file(self):
        return {entry["file"]: entry for entry in self.run_break("verify")["repros"]}

    def test_S_052_1_a_fixed_repro_that_fails_again_is_kept_again(self):
        self.try_repro("repro_n.py", KEEPS_VALUE)
        self.verdicts_by_file()
        self.change("value = 1\n")
        self.assertEqual(self.verdicts_by_file()["repro_n.py"]["verdict"], "fixed")
        self.change("value = 5\n")
        self.assertEqual(self.verdicts_by_file()["repro_n.py"]["verdict"], "kept")

    def test_S_052_1_a_fixed_verdict_forged_in_verdicts_json_is_not_trusted(self):
        self.try_repro("repro_o.py", KEEPS_VALUE)
        self.run_break("verify")
        path = self.boggart / "verdicts.json"
        data = json.loads(path.read_text())
        path.write_text(json.dumps({"repros": [{**data["repros"][0], "verdict": "fixed"}]}))
        self.assertEqual(self.verdicts_by_file()["repro_o.py"]["verdict"], "kept")

    def test_S_052_1_a_setup_error_on_head_keeps_an_earlier_kept_or_fixed_repro_kept(self):
        self.try_repro("repro_r.py", KEEPS_VALUE)
        self.verdicts_by_file()
        self.change("other = 1\n")  # `from src.a import value` now raises ImportError
        self.assertEqual(self.verdicts_by_file()["repro_r.py"]["verdict"], "kept")
        self.change("value = 1\n")
        self.assertEqual(self.verdicts_by_file()["repro_r.py"]["verdict"], "fixed")
        self.change("other = 1\n")
        self.assertEqual(self.verdicts_by_file()["repro_r.py"]["verdict"], "kept")

    def test_S_043_8_cant_load_is_set_only_when_head_failed_with_a_setup_error(self):
        self.try_repro("repro_c.py", KEEPS_VALUE)
        first = self.verdicts_by_file()["repro_c.py"]
        self.assertEqual((first["verdict"], first["cant_load"]), ("kept", False))  # an assertion, base has a setup error
        self.change("other = 1\n")  # the import now fails on head
        stuck = self.verdicts_by_file()["repro_c.py"]
        self.assertEqual((stuck["verdict"], stuck["cant_load"]), ("kept", True))
        self.change("value = 1\n")
        fixed = self.verdicts_by_file()["repro_c.py"]
        self.assertEqual((fixed["verdict"], fixed["cant_load"]), ("fixed", False))

    def test_S_043_8_a_new_module_break_whose_reason_says_setup_error_on_base_is_not_cant_load(self):
        write(self.worktree / "src" / "b.py", "value = 2\n")
        commit_all(self.worktree, "new module")
        text = HEADER + "from src.b import value\nassert value == 1, 'value changed'\n"
        entry = self.try_repro("repro_n.py", text)
        self.assertEqual(entry["verdict"], "kept")
        self.assertIn("setup error", entry["reason"])
        self.assertFalse(entry["cant_load"])

    def test_S_052_1_a_crash_outside_the_changed_files_keeps_an_earlier_repro_kept(self):
        self.try_repro("repro_s.py", KEEPS_VALUE)
        self.verdicts_by_file()
        write(self.worktree / "src" / "a.py", "value = 1\n")
        commit_all(self.worktree, "fix")
        self.assertEqual(self.verdicts_by_file()["repro_s.py"]["verdict"], "fixed")
        write(self.boggart / "repros" / "repro_s.py", HEADER + "raise RuntimeError('elsewhere')\n")
        self.assertEqual(self.verdicts_by_file()["repro_s.py"]["verdict"], "kept")

    def test_S_052_2_a_fixed_repro_that_passes_stays_fixed(self):
        self.try_repro("repro_p.py", KEEPS_VALUE)
        self.verdicts_by_file()
        self.change("value = 1\n")
        self.assertEqual(self.verdicts_by_file()["repro_p.py"]["verdict"], "fixed")
        self.assertEqual(self.verdicts_by_file()["repro_p.py"]["verdict"], "fixed")

    def test_S_052_3_a_pre_existing_repro_is_run_on_base_again(self):
        self.try_repro("repro_q.py", HEADER + "assert False, 'always'\n")
        self.assertEqual(self.verdicts_by_file()["repro_q.py"]["verdict"], "pre-existing")
        # the repro file now passes on base, so the old verdict must not be copied
        write(self.boggart / "repros" / "repro_q.py", HEADER + "from src.a import value\nassert value == 1\n")
        self.assertEqual(self.verdicts_by_file()["repro_q.py"]["verdict"], "kept")

    def test_S_041_8_config_needs_a_file_placeholder(self):
        for bad in ({"command": "pytest"}, {"cmd": "x {file}"}, "pytest {file}"):
            self.configure(bad)
            with self.assertRaises(config.ConfigError):
                config.load(self.accio)
        self.configure({"command": "pytest {file}"})
        self.assertEqual(config.load(self.accio)["breaker"]["command"], "pytest {file}")

    def test_read_field_takes_comment_styles(self):
        self.assertEqual(breaker.read_field("// claim: a b\n", "claim"), "a b")
        self.assertEqual(breaker.read_field("x = 1\n", "claim"), "")


if __name__ == "__main__":
    unittest.main()
