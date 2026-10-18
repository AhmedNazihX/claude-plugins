"""S-014: fidelius, the PreToolUse Write/Edit guard (DESIGN § 4.4, § 6). Payloads are piped in as Claude Code sends
them; a block is exit 2 with the reason on stderr and never the secret, a pass is exit 0 and silent.

Every fake key is built at runtime by concatenation (S-011/6), so no key-shaped string sits in this file.
"""
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from support import ROOT, git, init_repo, write

FIDELIUS = ROOT / "hooks" / "fidelius.py"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"


def stripe_key():
    return "sk" + "_live_" + "Ab3dE5gH7jK9mN1pQ3sT5vX7"


class FideliusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        (self.repo / ".accio").mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, tool, tool_input, cwd=None):
        payload = json.dumps({"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
                              "cwd": str(cwd or self.repo)})
        return subprocess.run([sys.executable, "-I", str(FIDELIUS)], input=payload, capture_output=True, text=True,
                              check=False)

    def assert_blocked(self, tool, tool_input):
        result = self.check(tool, tool_input)
        self.assertEqual(result.returncode, 2, f"{tool} was not blocked")
        self.assertIn("Stripe secret key", result.stderr)
        self.assertNotIn(stripe_key(), result.stderr)
        self.assertNotIn(stripe_key(), result.stdout)
        return result

    def assert_allowed(self, tool, tool_input, cwd=None):
        result = self.check(tool, tool_input, cwd)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""), tool)

    def test_S_014_1_a_secret_in_any_write_or_edit_is_blocked_without_the_value(self):
        target = str(self.repo / "config.py")
        line = f"KEY = '{stripe_key()}'\n"
        for tool, tool_input in (
                ("Write", {"file_path": target, "content": line}),
                ("Edit", {"file_path": target, "old_string": "KEY = None", "new_string": line}),
                ("MultiEdit", {"file_path": target, "edits": [{"old_string": "a", "new_string": "b"},
                                                              {"old_string": "c", "new_string": line}]}),
                ("NotebookEdit", {"notebook_path": str(self.repo / "nb.ipynb"), "new_source": line})):
            with self.subTest(tool):
                result = self.assert_blocked(tool, tool_input)
                self.assertIn("config.py" if tool != "NotebookEdit" else "nb.ipynb", result.stderr)
                self.assertIn("environment variable", result.stderr)

    def test_S_014_1_an_edit_that_removes_a_secret_is_allowed(self):
        self.assert_allowed("Edit", {"file_path": str(self.repo / "config.py"),
                                     "old_string": f"KEY = '{stripe_key()}'", "new_string": "KEY = os.environ['KEY']"})

    def test_S_014_1_a_real_env_file_may_hold_the_secret_but_a_template_may_not(self):
        write(self.repo / ".gitignore", ".env*\n!.env.example\n")
        self.assert_allowed("Write", {"file_path": str(self.repo / ".env.local"), "content": f"KEY={stripe_key()}\n"})
        self.assert_blocked("Write", {"file_path": str(self.repo / ".env.example"), "content": f"KEY={stripe_key()}\n"})

    def test_S_014_1_only_a_gitignored_untracked_env_file_is_exempt(self):
        write(self.repo / ".gitignore", ".env*\n*.env\n!.env.example\n")
        line = f"KEY={stripe_key()}\n"
        for name in ("config.env.ts", "app.env.js", ".env.example.bak", ".env.sample"):
            with self.subTest(name):
                self.assert_blocked("Write", {"file_path": str(self.repo / name), "content": line})
        for name in (".env.production.local", ".env_local", ".env-prod", "prod.env", "newdir/.env"):
            with self.subTest(name):
                self.assert_allowed("Write", {"file_path": str(self.repo / name), "content": line})
        (self.repo / ".env.local").symlink_to(self.repo / "config.py")
        self.assert_blocked("Write", {"file_path": str(self.repo / ".env.local"), "content": line})
        write(self.repo / ".gitignore", "")
        self.assert_blocked("Write", {"file_path": str(self.repo / ".env"), "content": line})
        write(self.repo / ".gitignore", ".env*\n")
        write(self.repo / ".env.prod", "")
        git(self.repo, "add", "-f", ".env.prod")
        self.assert_blocked("Write", {"file_path": str(self.repo / ".env.prod"), "content": line})

    def test_S_014_1_a_key_split_across_edits_or_finished_by_an_edit_is_blocked(self):
        key = stripe_key()
        target = self.repo / "config.py"
        self.assert_blocked("MultiEdit", {"file_path": str(target), "edits": [
            {"old_string": "", "new_string": f"KEY = '{key[:12]}"}, {"old_string": "x", "new_string": f"{key[12:]}'"}]})
        write(target, f"KEY = '{key[:12]}PLACEHOLDER'\n")
        self.assert_blocked("Edit", {"file_path": str(target), "old_string": "PLACEHOLDER", "new_string": key[12:]})

    def test_S_014_1_a_secret_already_in_the_file_does_not_block_other_edits(self):
        target = self.repo / "config.py"
        write(target, f"KEY = '{stripe_key()}'\nDEBUG = False\n")
        self.assert_allowed("Edit", {"file_path": str(target), "old_string": "DEBUG = False", "new_string": "DEBUG = 1"})
        other = "sk" + "_live_" + "Zz9yX8wV7uT6sR5qP4oN3mL2"
        result = self.check("Edit", {"file_path": str(target), "old_string": stripe_key(), "new_string": other})
        self.assertEqual(result.returncode, 2)
        self.assertNotIn(other, result.stderr)

    def test_S_014_1_a_second_private_key_under_the_same_header_is_blocked(self):
        header = "-----BEGIN " + "PRIVATE KEY-----"
        target = self.repo / "keys.py"
        write(target, f'A = """{header}\nMIIEvQ\n"""\n')
        result = self.check("Edit", {"file_path": str(target), "old_string": 'MIIEvQ\n"""\n',
                                     "new_string": f'MIIEvQ\n"""\nB = """{header}\nMIIEvA\n"""\n'})
        self.assertEqual(result.returncode, 2)
        self.assertIn("line 4", result.stderr)

    def test_S_014_1_a_new_body_under_an_existing_private_key_header_is_blocked(self):
        begin, end = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"
        target = self.repo / "keys.py"
        write(target, f'A = """{begin}\nMIIEvQIBADANBgkqhkiG9w0BAQ\n{end}\n"""\n')
        result = self.check("Edit", {"file_path": str(target), "old_string": "MIIEvQIBADANBgkqhkiG9w0BAQ",
                                     "new_string": "MIIEpAIBAAKCAQEAu1SU1LfVLP"})
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("MIIEpA", result.stderr)

    def test_S_014_1_a_private_key_whose_body_looks_like_an_example_still_counts(self):
        begin, end = "-----BEGIN " + "PRIVATE KEY-----", "-----END " + "PRIVATE KEY-----"
        result = self.check("Write", {"file_path": str(self.repo / "key.pem.txt"),
                                      "content": f"{begin}\nMIIEvQxxxxxxEXAMPLEIBAD\n{end}\n"})
        self.assertEqual(result.returncode, 2)

    def test_S_014_1_replace_all_is_simulated_on_every_occurrence(self):
        key = stripe_key()
        target = self.repo / "config.py"
        write(target, f"X = 'TAIL'\nKEY = '{key[:18]}TAIL'\n")
        result = self.check("Edit", {"file_path": str(target), "old_string": "TAIL", "new_string": key[18:],
                                     "replace_all": True})
        self.assertEqual(result.returncode, 2)

    def test_S_014_1_a_new_body_under_an_armored_key_with_a_dash_in_its_comment_is_blocked(self):
        begin = "-----BEGIN PGP " + "PRIVATE KEY BLOCK-----"
        end = "-----END PGP " + "PRIVATE KEY BLOCK-----"
        target = self.repo / "keys.py"
        write(target, f'A = """{begin}\nComment: GPGTools - https://gpgtools.org\n\nlQOYBF0bQ2\n{end}\n"""\n')
        result = self.check("Edit", {"file_path": str(target), "old_string": "lQOYBF0bQ2", "new_string": "lQVYBGaX9e"})
        self.assertEqual(result.returncode, 2)

    def test_S_014_1_a_key_finished_in_a_file_that_isnt_utf8_is_blocked(self):
        key = stripe_key()
        target = self.repo / "legacy.py"
        target.write_bytes(b"# \xff\nKEY = '" + key[:18].encode() + b"PLACEHOLDER'\n")
        result = self.check("Edit", {"file_path": str(target), "old_string": "PLACEHOLDER", "new_string": key[18:]})
        self.assertEqual(result.returncode, 2)

    def test_S_014_1_an_old_string_typed_with_straight_quotes_still_finds_curly_ones(self):
        key = stripe_key()
        target = self.repo / "config.py"
        write(target, f"KEY = '{key[:18]}PLACEHOLDER' # “note”\n")
        result = self.check("Edit", {"file_path": str(target), "old_string": "PLACEHOLDER' # \"note\"",
                                     "new_string": f"{key[18:]}' # \"note\""})
        self.assertEqual(result.returncode, 2)

    def test_S_014_1_an_error_while_checking_blocks_the_write_without_the_content(self):
        spec = importlib.util.spec_from_file_location("fidelius_under_test", FIDELIUS)
        fidelius = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fidelius)
        payload = json.dumps({"tool_name": "Write", "cwd": str(self.repo),
                              "tool_input": {"file_path": str(self.repo / "a.py"), "content": stripe_key()}})
        stderr = io.StringIO()
        with mock.patch.object(fidelius, "check", side_effect=RecursionError("deep")), \
                mock.patch("sys.stdin", io.StringIO(payload)), mock.patch("sys.stderr", stderr):
            self.assertEqual(fidelius.main(), 2)
        self.assertIn("could not check", stderr.getvalue())
        self.assertNotIn(stripe_key(), stderr.getvalue())

    def test_S_014_1_a_path_git_cannot_take_still_blocks_without_a_crash(self):
        result = self.check("Edit", {"file_path": str(self.repo / "a\u0000b"), "old_string": "x",
                                     "new_string": stripe_key()})
        self.assertEqual(result.returncode, 2)
        self.assertNotIn("Traceback", result.stderr)

    def test_S_014_1_list_valued_content_is_checked(self):
        key = stripe_key()
        self.assert_blocked("NotebookEdit", {"notebook_path": str(self.repo / "nb.ipynb"),
                                             "new_source": ["KEY = '", key[:10], key[10:], "'\n"]})

    def test_S_014_2_the_repo_is_found_from_the_file_when_cwd_is_elsewhere(self):
        plain = init_repo(pathlib.Path(self.tmp.name).resolve() / "plain")
        line = f"KEY = '{stripe_key()}'\n"
        result = self.check("Write", {"file_path": str(self.repo / "new" / "config.py"), "content": line}, cwd=plain)
        self.assertEqual(result.returncode, 2)
        result = self.check("Write", {"file_path": str(self.repo / "config.py"), "content": line},
                            cwd=self.repo / "missing")
        self.assertEqual(result.returncode, 2)

    def test_S_014_1_clean_content_and_documented_examples_pass(self):
        target = str(self.repo / "README.md")
        self.assert_allowed("Write", {"file_path": target, "content": "Set KEY to your_api_key.\n"})
        self.assert_allowed("Write", {"file_path": target, "content": "AK" + "IA" + "IOSFODNN7" + "EXAMPLE\n"})

    def test_S_014_2_a_repo_without_accio_is_left_alone(self):
        plain = init_repo(pathlib.Path(self.tmp.name).resolve() / "plain")
        self.assert_allowed("Write", {"file_path": str(plain / "config.py"), "content": stripe_key()}, cwd=plain)

    def test_other_tools_and_bad_payloads_pass_silently(self):
        self.assert_allowed("Bash", {"command": f"echo {stripe_key()}"})
        for raw in ("not json", json.dumps({"tool_name": "Write", "tool_input": "x"}),
                    json.dumps({"tool_name": "Write", "tool_input": {"content": 5}, "cwd": str(self.repo)})):
            result = subprocess.run([sys.executable, "-I", str(FIDELIUS)], input=raw, capture_output=True, text=True,
                                    check=False)
            self.assertEqual((result.returncode, result.stderr), (0, ""), raw)

    def test_hooks_json_runs_fidelius_on_writes_and_edits(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [entry for entry in config["hooks"]["PreToolUse"] if "fidelius.py" in json.dumps(entry)]
        self.assertEqual(len(entries), 1)
        for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            self.assertIn(tool, entries[0]["matcher"].split("|"))


if __name__ == "__main__":
    unittest.main()
