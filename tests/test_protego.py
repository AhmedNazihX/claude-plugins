"""S-013: protego, the PreToolUse Bash guard (DESIGN § 4.4, decision 004). Payloads are piped in as Claude Code
sends them; a block is exit 2 with the reason and the safe alternative on stderr, a pass is exit 0 and silent.
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

PROTEGO = ROOT / "hooks" / "protego.py"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"


def path_without_dcg(extra=()):
    dirs = [d for d in os.environ.get("PATH", "").split(os.pathsep) if d and not (pathlib.Path(d) / "dcg").exists()]
    return os.pathsep.join([*map(str, extra), *dirs])


class ProtegoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")
        (self.repo / ".accio").mkdir()
        self.home = self.base / "home"  # an empty home, so the real user's Claude settings never leak in
        self.home.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, command, cwd=None, tool="Bash", path=None, raw=None):
        payload = raw if raw is not None else json.dumps({
            "hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": {"command": command},
            "cwd": str(cwd or self.repo)})
        env = {**os.environ, "PATH": path or path_without_dcg(), "TMPDIR": tempfile.gettempdir(),
               "HOME": str(self.home)}
        return subprocess.run([sys.executable, "-I", str(PROTEGO)], input=payload, env=env,
                              capture_output=True, text=True, check=False)

    def assert_blocked(self, command, *expected, cwd=None, path=None):
        result = self.check(command, cwd=cwd, path=path)
        self.assertEqual(result.returncode, 2, f"{command!r} was not blocked")
        self.assertIn("Instead", result.stderr, command)
        for text in expected:
            self.assertIn(text, result.stderr, command)

    def assert_allowed(self, command, cwd=None, path=None):
        result = self.check(command, cwd=cwd, path=path)
        self.assertEqual((result.returncode, result.stderr), (0, ""), command)

    def test_S_013_1_the_destructive_list_is_blocked_with_an_alternative(self):
        for command in ("git reset --hard HEAD~1", "git -C . reset --hard", "git --no-pager reset --hard",
                        "git clean -fd", "git clean --force", "git clean -xdf",
                        "git branch -D feature", "git branch --delete --force feature", "git branch -df feature",
                        "echo ok && git reset --hard", "true; git clean -f", "sudo git reset --hard",
                        "bash -c 'git reset --hard'"):
            with self.subTest(command):
                self.assert_blocked(command)

    def test_S_013_1_rm_rf_outside_the_repo_is_blocked(self):
        for command in ("rm -rf /usr/local/accio-other", "rm -rf ..", "rm -fr ~/projects", "cd / && rm -rf usr",
                        "rm -r -f ../sibling", "rm --recursive --force ../sibling", 'rm -rf "$HOME/x"',
                        "rm -rf .", "rm -rf .git", "rm -rf build ~/accio-elsewhere", "sudo rm -rf /"):
            with self.subTest(command):
                self.assert_blocked(command, "rm -rf")

    def test_S_013_1_hook_bypasses_are_blocked(self):
        for command in ("git commit --no-verify -m x", "git commit -n -m x", "git commit -anm x",
                        "git push --no-verify origin feature", "git merge --no-verify feature",
                        "HUSKY=0 git commit -m x",
                        "git config core.hooksPath /dev/null", "git config --unset core.hooksPath",
                        "git config --global core.hookspath x", "git -c core.hooksPath=/dev/null commit -m x"):
            with self.subTest(command):
                self.assert_blocked(command)

    def test_S_013_1_ordinary_commands_pass(self):
        worktree = self.base / ".app-accio-wt" / "S-001"
        for command in ("git status", "git reset --soft HEAD~1", "git reset HEAD file.py", "git clean -n",
                        "rm -rf build", "rm -rf ./node_modules dist", 'echo "git reset --hard"',
                        "git config --get core.hooksPath", "git config core.hooksPath",
                        "git log --grep=--no-verify", "git commit -m 'skip -n'",
                        "git commit -am '-n is text here'", "git push -n origin main",
                        "grep -rf patterns.txt .", f"cd {worktree} && rm -rf build", "rm -f stale.lock"):
            with self.subTest(command):
                self.assert_allowed(command)

    def test_S_013_1_redirects_heredocs_and_subshells_are_not_misread(self):
        script = "cat > notes.md <<'N'\nrm -rf /\nunset CLAUDECODE\nN\ngit status"
        for command in ("rm -rf build 2>/dev/null", "rm -rf build >/dev/null 2>&1 || true", "rm -rf build &>/dev/null",
                        script, "cat <<-EOF > run.sh\n\trm -rf \"$OUT\"\n\tEOF", "(cd / && ls); rm -rf build",
                        'cd "$(git rev-parse --show-toplevel)" && rm -rf build', "git clean -nfd",
                        "git clean --dry-run -f", "HUSKY=0 npm ci", "git commit -uno -m x", "git commit -unormal"):
            with self.subTest(command):
                self.assert_allowed(command)
        self.assert_blocked("cat <<'N' > x\nhello\nN\ngit reset --hard")
        self.assert_blocked("(cd /tmp && ls); git reset --hard")

    def test_S_013_1_temp_folders_and_symlinked_spellings_can_be_cleaned(self):
        real = pathlib.Path(os.path.realpath(tempfile.gettempdir()))
        for command in (f"rm -rf {real / 'accio-probe' / 'build'}", 'rm -rf "$TMPDIR/accio-probe"',
                        "rm -rf /tmp/accio-probe/out"):
            with self.subTest(command):
                self.assert_allowed(command)
        self.assert_blocked(f"rm -rf {real}", "rm -rf")
        self.assert_blocked("rm -rf /tmp/*", "rm -rf")
        self.assert_blocked(f"rm -rf {self.base}", "rm -rf")
        self.assert_allowed("rm -rf build/* *.pyc")
        linked = self.base / "linked"
        linked.symlink_to(self.repo)
        self.assert_allowed(f"rm -rf {linked / 'build'}")

    def test_S_013_1_spellings_that_slipped_past_are_blocked(self):
        for command in ("git commit --no-ver -m x", "git reset --ha", "git clean --forc", "git branch --del --fo x",
                        "git commit -S -n -m x", "git config core.hooksPath \"\"", "git commit -m \"\" -n",
                        "GIT_CONFIG_PARAMETERS=\"'core.hooksPath=/dev/null'\" git commit -m x",
                        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=core.hooksPath GIT_CONFIG_VALUE_0=/x git commit -m x",
                        "export GIT_CONFIG_KEY_0=core.hooksPath", "HUSKY=0 git commit -m x", "export HUSKY=0"):
            with self.subTest(command):
                self.assert_blocked(command)

    def test_S_013_1_quoting_decides_what_is_an_operator_or_a_heredoc(self):
        for command in ('echo "use <<EOF in bash"\ngit reset --hard', 'python3 -c "print(1<<shift)"\ngit reset --hard',
                        "cat <<EOF\ngit reset --hard", 'echo "(" ; cd / ; echo ")" ; rm -rf build',
                        'cd "$SOMEWHERE" && rm -rf build', 'cd / && rm -rf "$PWD/x"', "pushd / && rm -rf build",
                        "git clean -f -en", "git clean -fe keep.txt", "git clean -f -e -n",
                        "git clean -f --exclude -n",
                        "declare +x CLAUDECODE"):
            with self.subTest(command):
                self.assert_blocked(command)
        for command in ("cat <<'END-MSG' > x\nunset CLAUDECODE\nEND-MSG", "cat <<\\EOF > x\nunset CLAUDECODE\nEOF",
                        "(cd /opt && ls)>out; rm -rf build", 'rm -rf "$PWD/build"', "git log -n 5 >out"):
            with self.subTest(command):
                self.assert_allowed(command)

    def test_S_013_1_a_glob_or_slash_through_a_symlink_is_judged_where_it_points(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.repo / "outlink").symlink_to(outside)
        for command in ("rm -rf outlink/*", "rm -rf outlink/"):
            with self.subTest(command):
                self.assert_blocked(command, "rm -rf")
        self.assert_allowed("rm -rf outlink")

    def test_an_unclosed_quote_is_one_word_as_the_shell_reads_it(self):
        """The shell refuses to run this at all (unexpected end of file), so nothing in it runs."""
        self.assert_allowed('echo "unterminated && git reset --hard')

    def test_S_013_1_shell_grammar_does_not_hide_a_listed_command(self):
        for command in ("echo $'\\'' ; git reset --hard ; echo hi", "{ git reset --hard; }",
                        "if true; then git reset --hard; fi", "for f in a; do git reset --hard; done",
                        "! git reset --hard", "true && { cd ~; }; rm -rf Documents", "rm -rf {,~}",
                        "rm -rf {x,~/Documents}", "cd -P ~ && rm -rf Documents", "cd -- ~ && rm -rf Documents",
                        "pushd +1 && rm -rf build", "pushd && rm -rf build",
                        "echo $((1<<n))\ngit reset --hard\nn", 'echo "$(git reset --hard)"', "echo `git reset --hard`",
                        "bash <<'E'\ngit reset --hard\nE", "bash <<< 'git reset --hard'", "eval 'git reset --hard'",
                        "(cd ~; case x in x) rm -rf Documents;; esac)", "TMPDIR=/ && rm -rf \"$TMPDIR/usr\"",
                        "PWD=/ ; rm -rf $PWD/etc", "HOME=/ ; rm -rf ~/etc", "git clean -f --exc -n",
                        "git -c clean.requireForce=false clean -xd"):
            with self.subTest(command):
                self.assert_blocked(command)
        for command in ("cat <<E\n  E\nunset CLAUDECODE\nE", "for f in a b; do echo $f; done", "rm -rf build/{a,b}",
                        "cat <<< 'unset CLAUDECODE'", "echo \"$(git status)\""):
            with self.subTest(command):
                self.assert_allowed(command)

    def test_odd_input_never_crashes_the_hook(self):
        for command in ("cd a\u0000b; rm -rf c", "rm -rf a\u0000b"):
            with self.subTest(repr(command)):
                self.assertIn(self.check(command).returncode, (0, 2))
        path = self.fake_dcg()
        malformed = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": 3}]}}
        write(self.repo / ".claude" / "settings.json", json.dumps(malformed))
        self.assert_blocked("git reset --hard", path=path)

    def test_S_013_4_disabled_hooks_mean_dcg_is_not_running(self):
        path = self.fake_dcg()
        self.hook_dcg(self.repo / ".claude" / "settings.json")
        write(self.home / ".claude" / "settings.json", json.dumps({"disableAllHooks": True}))
        self.assert_blocked("git reset --hard", path=path)

    def test_S_013_2_a_safe_branch_delete_is_allowed(self):
        self.assert_allowed("git branch -d feature")
        self.assert_allowed("git branch --delete feature")

    def test_S_013_3_a_repo_without_accio_is_left_alone(self):
        plain = init_repo(self.base / "plain")
        self.assert_allowed("git reset --hard", cwd=plain)
        self.assert_allowed("unset CLAUDECODE", cwd=self.base)

    def fake_dcg(self):
        fake_bin = self.base / "fake-bin"
        write(fake_bin / "dcg", "#!/bin/sh\nexit 0\n")
        (fake_bin / "dcg").chmod(0o755)
        return path_without_dcg(extra=(fake_bin,))

    def hook_dcg(self, settings_path, matcher="Bash", command="dcg"):
        hook = {"matcher": matcher, "hooks": [{"type": "command", "command": command}]}
        write(settings_path, json.dumps({"hooks": {"PreToolUse": [hook]}}))

    def test_S_013_4_dcg_on_path_but_not_hooked_changes_nothing(self):
        path = self.fake_dcg()
        for command in ("git reset --hard", "git branch -D feature"):
            self.assert_blocked(command, path=path)

    def test_S_013_4_dcg_hooked_in_any_settings_file_is_deferred_to(self):
        path = self.fake_dcg()
        for settings in (self.home / ".claude" / "settings.json", self.repo / ".claude" / "settings.json",
                         self.repo / ".claude" / "settings.local.json"):
            with self.subTest(str(settings)):
                self.hook_dcg(settings)
                self.assert_allowed("git reset --hard", path=path)
                settings.unlink()
        self.hook_dcg(self.repo / ".claude" / "settings.json", matcher="Write")
        self.assert_blocked("git reset --hard", path=path)
        self.hook_dcg(self.repo / ".claude" / "settings.json", command="python3 my-dcgx-guard.py")
        self.assert_blocked("git reset --hard", path=path)
        self.hook_dcg(self.repo / ".claude" / "settings.json")
        self.assert_blocked("git reset --hard")

    def test_S_013_4_with_dcg_running_the_generic_list_is_left_to_it(self):
        path = self.fake_dcg()
        self.hook_dcg(self.repo / ".claude" / "settings.json", matcher="*")
        for command in ("git reset --hard", "rm -rf /usr/local/accio-other", "git branch -D feature"):
            self.assert_allowed(command, path=path)
        for command in ("git commit --no-verify -m x", "git config core.hooksPath x", "unset CLAUDECODE"):
            self.assert_blocked(command, path=path)

    def test_S_013_5_unsetting_claudecode_is_blocked_and_explained(self):
        for command in ("unset CLAUDECODE", "unset -v CLAUDECODE OTHER", "env -u CLAUDECODE git push",
                        "env --unset=CLAUDECODE git push", "CLAUDECODE= git push", "CLAUDECODE=0 git push",
                        "export CLAUDECODE=0", "git status && unset CLAUDECODE", "env -i git push",
                        "env -i PATH=/usr/bin git push", "env --ignore-environment git push", "env - git push",
                        "env -u CLAUDECODE bash -c 'git status'"):
            with self.subTest(command):
                self.assert_blocked(command, "CLAUDECODE", "push guard")
        self.assert_allowed("echo $CLAUDECODE")
        self.assert_allowed("env | grep CLAUDECODE")
        self.assert_allowed("env -i CLAUDECODE=1 git status")

    def test_other_tools_and_bad_payloads_pass_silently(self):
        self.assertEqual(self.check("git reset --hard", tool="Write").returncode, 0)
        for raw in ("not json", json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "a\u0000b"})):
            result = self.check("", raw=raw)
            self.assertEqual((result.returncode, result.stderr), (0, ""), raw)

    def test_hooks_json_runs_protego_on_bash(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))
        entries = [entry for entry in config["hooks"]["PreToolUse"] if entry["matcher"] == "Bash"]
        commands = [hook["command"] for entry in entries for hook in entry["hooks"]]
        self.assertTrue(any("${CLAUDE_PLUGIN_ROOT}/hooks/protego.py" in command for command in commands), commands)


if __name__ == "__main__":
    unittest.main()
