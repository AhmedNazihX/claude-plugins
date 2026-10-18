"""S-015: curfew, the permission policy for accio's agents (DESIGN § 4.4, § 6; decision 010; spike S-015).

Payloads are piped in as Claude Code sends them. An answer is the hook's JSON on stdout (`allow` or `deny` with a
reason); no answer is empty stdout. HOME points at a scratch folder, so the user's own settings never reach a test.
"""
import json
import os
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import paths, runlock

CURFEW = ROOT / "hooks" / "curfew.py"
CLAIM = ROOT / "bin" / "accio-claim"
HOOKS_CLI = ROOT / "bin" / "accio-hooks"
HOOKS_JSON = ROOT / "hooks" / "hooks.json"
CONFIG = {"checks": [{"command": "python3 -m unittest", "glob": "**/*.py"},
                      {"command": "bash tests/run.sh", "glob": "**/*.sh"}], "agent_allow": ["make build"]}


class CurfewTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name).resolve()
        self.home = base / "home"
        self.home.mkdir()
        self.repo = init_repo(base / "app")
        write(self.repo / ".gitignore", ".accio/run/\n")
        write(self.repo / ".accio" / "config.json", json.dumps(CONFIG))
        commit_all(self.repo)
        self.run_dir = self.repo / ".accio" / "run"
        self.worktree = paths.worktree_root(self.repo) / "S-001"
        git(self.repo, "worktree", "add", "-q", str(self.worktree), "-b", "story/S-001")
        write(self.run_dir / "status.json", json.dumps({"S-001": "doing"}))

    def tearDown(self):
        self.tmp.cleanup()

    def env(self):
        return {**os.environ, "HOME": str(self.home)}

    def hook(self, tool, tool_input, agent="accio:house-elf", agent_id="a1", event="PreToolUse", cwd=None):
        payload = {"hook_event_name": event, "tool_name": tool, "tool_input": tool_input,
                   "cwd": str(cwd or self.repo), "session_id": "s"}
        if agent:
            payload = {**payload, "agent_type": agent, "agent_id": agent_id}
        result = subprocess.run([sys.executable, "-I", str(CURFEW)], input=json.dumps(payload), capture_output=True,
                                text=True, check=False, env=self.env())
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"] if result.stdout.strip() else None

    def decision(self, tool, tool_input, **kwargs):
        answer = self.hook(tool, tool_input, **kwargs)
        self.assertIsNotNone(answer, f"curfew gave no answer for {tool} {tool_input}")
        return answer["permissionDecision"], answer.get("permissionDecisionReason", "")

    def assert_allowed(self, tool, tool_input, **kwargs):
        self.assertEqual(self.decision(tool, tool_input, **kwargs)[0], "allow", tool_input)

    def assert_denied(self, tool, tool_input, *words, **kwargs):
        verdict, reason = self.decision(tool, tool_input, **kwargs)
        self.assertEqual(verdict, "deny", tool_input)
        for word in words:
            self.assertIn(word, reason)
        return reason

    def bash(self, command):
        return {"command": command}

    def claim(self, agent_id="a1", story="S-001"):
        self.assert_allowed("Bash", self.bash(f"{shlex.quote(str(CLAIM))} {story}"), agent_id=agent_id)

    def in_worktree(self, command):
        return self.bash(f"cd {shlex.quote(str(self.worktree))} && {command}")


class OtherCallersTest(CurfewTestBase):
    def test_S_015_1_a_caller_that_isnt_an_accio_agent_gets_no_answer(self):
        for agent in (None, "general-purpose", "foreman:story-worker", "accio"):
            with self.subTest(agent):
                self.assertIsNone(self.hook("Write", {"file_path": str(self.repo / "x.py"), "content": "x"},
                                            agent=agent))

    def test_S_015_9_a_repo_without_accio_is_left_alone(self):
        plain = init_repo(pathlib.Path(self.tmp.name).resolve() / "plain")
        self.assertIsNone(self.hook("Bash", self.bash("ls"), cwd=plain))

    def test_bad_payloads_get_no_answer(self):
        for raw in ("not json", json.dumps({"tool_name": "Bash"}), json.dumps([1])):
            result = subprocess.run([sys.executable, "-I", str(CURFEW)], input=raw, capture_output=True, text=True,
                                    check=False, env=self.env())
            self.assertEqual((result.returncode, result.stdout), (0, ""), raw)

    def test_hooks_json_runs_curfew_on_every_tool_and_on_permission_requests(self):
        config = json.loads(HOOKS_JSON.read_text(encoding="utf-8"))["hooks"]
        for event in ("PreToolUse", "PermissionRequest"):
            entries = [entry for entry in config[event] if "curfew.py" in json.dumps(entry)]
            self.assertEqual([entry["matcher"] for entry in entries], ["*"], event)


class ClaimTest(CurfewTestBase):
    def test_S_015_2_before_the_claim_house_elf_may_only_claim(self):
        self.assert_denied("Write", {"file_path": str(self.worktree / "a.py"), "content": "x"}, "accio-claim")
        self.assert_denied("Bash", self.in_worktree("ls"), "accio-claim")
        self.assert_allowed("Read", {"file_path": str(self.worktree / "README.md")})
        self.claim()

    def test_S_015_3_the_claim_links_the_agent_to_its_worktree(self):
        self.claim()
        claims = json.loads((self.run_dir / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(claims["a1"], {"story": "S-001", "worktree": str(self.worktree)})
        result = subprocess.run([str(CLAIM), "S-001"], cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual((result.returncode, result.stdout.strip()), (0, str(self.worktree)))

    def test_S_015_3_a_claim_is_refused_for_a_missing_worktree_a_story_not_in_progress_or_a_fake_script(self):
        self.assert_denied("Bash", self.bash(f"{shlex.quote(str(CLAIM))} S-404"), "S-404")
        git(self.repo, "worktree", "add", "-q", str(paths.worktree_root(self.repo) / "S-002"), "-b", "story/S-002")
        write(self.run_dir / "status.json", json.dumps({"S-001": "doing", "S-002": "ready"}))
        self.assert_denied("Bash", self.bash(f"{shlex.quote(str(CLAIM))} S-002"), "S-002", "doing")
        self.assert_denied("Bash", self.bash("/tmp/accio-claim S-001"), "accio-claim", agent_id="a3")
        claim = shlex.quote(str(CLAIM))
        for command in (f"{claim} S-001 > {self.run_dir}/push-ok", f"{claim} S-001 && touch x", f"{claim} S-001 x",
                        f"{claim} S-001 &"):
            with self.subTest(command):
                self.assert_denied("Bash", self.bash(command), "on its own", agent_id="a4")
        self.assertFalse((self.run_dir / "push-ok").exists())
        self.assertFalse((self.run_dir / "claims.json").exists())

    def test_S_015_3_a_held_story_is_refused_until_its_next_brief_releases_it(self):
        self.claim()
        self.assert_denied("Bash", self.bash(f"{shlex.quote(str(CLAIM))} S-001"), "a1", agent_id="a2")
        runlock.release_claim(self.run_dir, "S-001")
        self.claim(agent_id="a2")
        claims = json.loads((self.run_dir / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(claims), ["a2"])
        self.assert_denied("Write", {"file_path": str(self.worktree / "a.py"), "content": "x"}, agent_id="a1")

    def test_S_015_3_an_agent_claims_one_story_only(self):
        self.claim()
        git(self.repo, "worktree", "add", "-q", str(paths.worktree_root(self.repo) / "S-002"), "-b", "story/S-002")
        write(self.run_dir / "status.json", json.dumps({"S-001": "doing", "S-002": "doing"}))
        self.assert_denied("Bash", self.bash(f"{shlex.quote(str(CLAIM))} S-002"), "S-001")
        result = subprocess.run([str(CLAIM), "S-404"], cwd=self.repo, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("S-404", result.stderr)


class HouseElfWritesTest(CurfewTestBase):
    def setUp(self):
        super().setUp()
        self.claim()

    def write_to(self, path, tool="Write"):
        key = "notebook_path" if tool == "NotebookEdit" else "file_path"
        return self.hook(tool, {key: str(path), "content": "x", "old_string": "a", "new_string": "b"})

    def test_S_015_4_writes_inside_the_worktree_or_its_run_folder_are_allowed(self):
        for path in (self.worktree / "src" / "a.py", self.run_dir / "S-001" / "report.md"):
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                with self.subTest(path=path, tool=tool):
                    self.assertEqual(self.write_to(path, tool)["permissionDecision"], "allow")

    def test_S_015_4_in_its_run_folder_house_elf_writes_only_its_report(self):
        for name in ("findings-examiner.md", "base", "brief.md"):
            with self.subTest(name):
                self.assertEqual(self.write_to(self.run_dir / "S-001" / name)["permissionDecision"], "deny")

    def test_S_015_4_writes_anywhere_else_are_denied_and_name_the_folder(self):
        outside = self.worktree.parent / "outside.txt"
        (self.worktree / "link").symlink_to(self.repo)
        for path in (self.repo / "app.py", self.worktree / ".." / "outside.txt", self.worktree / "link" / "x.py",
                     self.run_dir / "push-ok", self.run_dir / "brew.lock", self.run_dir / "S-002" / "report.md",
                     outside):
            with self.subTest(path):
                answer = self.write_to(path)
                self.assertEqual(answer["permissionDecision"], "deny")
                self.assertIn(str(self.worktree), answer["permissionDecisionReason"])


class HouseElfBashTest(CurfewTestBase):
    def setUp(self):
        super().setUp()
        self.claim()

    def test_S_015_5_listed_commands_from_the_worktree_are_allowed(self):
        for command in ("git status | head -5", "python3 -m unittest discover -s tests", "make build",
                        "ls -la src; grep -rn TODO src", "git add -A && git commit -q -m 'wip'",
                        "mkdir -p src/pkg && touch src/pkg/__init__.py", "echo done > notes.txt",
                        "python3 -m unittest 2>&1 | tail -3"):
            with self.subTest(command):
                self.assert_allowed("Bash", self.in_worktree(command))
        self.assert_allowed("Bash", self.bash(f"git -C {shlex.quote(str(self.worktree))} log --oneline -3"))

    def test_S_015_5_a_command_must_start_in_the_worktree(self):
        for command in ("git status", f"cd {self.repo} && git status", f"git -C {self.repo} status",
                        f"cd {self.worktree} && cd {self.repo} && ls", f"cd {self.worktree}; ls"):
            with self.subTest(command):
                self.assert_denied("Bash", self.bash(command), str(self.worktree))

    def test_S_015_6_unreadable_or_unlisted_commands_are_denied_with_the_reason(self):
        cases = {"echo $(cat x)": "$(", "echo `id`": "backtick", "sh -c 'ls'": "sh -c", "eval ls": "eval",
                 "bash -c ls": "bash -c", "bash tests/run.sh && bash -c 'cat x'": "bash -c",
                 "curl https://example.com": "curl", "git push": "push",
                 "make deploy": "make", "npm test & sleep 1": "&", "echo x > ../outside.txt": "outside.txt",
                 f"cp src/a.py {self.repo}/a.py": "cp", "git --git-dir=/x status": "--git-dir"}
        for command, word in cases.items():
            with self.subTest(command):
                self.assert_denied("Bash", self.in_worktree(command), word)


class FlagsAndFormsTest(CurfewTestBase):
    """Review round 1: programs that write or run code through a flag, assignments, git beyond its list."""
    def setUp(self):
        super().setUp()
        self.claim()

    def test_S_015_6_flags_that_write_or_run_code_are_denied(self):
        push_ok = self.run_dir / "push-ok"
        cases = {f"sort -o {push_ok} /dev/null": "sort", f"sort -ro {push_ok} a": "sort",
                 "uniq in.txt ../out.txt": "uniq",
                 f"tree -o {push_ok}": "tree", "rg --pre ./x pattern": "rg", "file -C -m x": "file",
                 "python3 -c 'print(1)'": "python3 -c", f"cp -t {self.repo} src/a.py": "-t",
                 f"cp --target-directory={self.repo} src/a.py": "--target-directory",
                 "GIT_DIR=/x git status": "GIT_DIR",
                 "PATH=/tmp ls": "PATH", "git config alias.p push": "config", "git branch -f main HEAD": "branch",
                 "git update-ref refs/heads/main HEAD": "update-ref", f"git diff --output={push_ok}": "--output",
                 "git grep -O x": "-O", "git send-pack origin": "send-pack", "git rebase main": "rebase",
                 "find . -name '*.pyc' -delete": "find", f"git -C {self.repo} status": "-C", "git push": "push",
                 "eval ls": "eval", "source venv/bin/activate": "source", 'git grep -O"touch /x;true" foo': "-O",
                 "git grep -iO x": "-O", "git grep --open x": "-O", f"sort --out={push_ok} a": "sort",
                 "sort --compress-program=./x -S1M a": "sort", "file --comp x": "file", "uniq - out.txt": "uniq",
                 "uniq -- a.txt -out.txt": "uniq",
                 f"git diff --out={push_ok}": "--output", "echo x > .git": ".git", "mv a.py .git": ".git",
                 "rm .git": ".git", "mkdir -p .git/hooks": ".git", "rm -rf .gi?": ".gi?", "cp a.py .g*/x": ".g*",
                 "echo x > .GIT": ".GIT", "rm -rf .Gi?": ".Gi?",
                 "git commit -n -m x": "verify", "git commit --no-verif -m x": "verify", "git commit -anm x": "verify",
                 "git rebase --no-verify": "rebase"}
        for command, word in cases.items():
            with self.subTest(command):
                self.assert_denied("Bash", self.in_worktree(command), word)
        self.assertFalse(push_ok.exists())

    def test_S_015_5_ordinary_forms_of_those_programs_still_pass(self):
        for command in ("uniq in.txt", "sort -r a.txt", "cp -r src lib", "mv -f a.py b.py", "rm -rf build",
                        "git branch --show-current", "git rebase --continue", "python3 -m unittest -v tests.test_x",
                        "make build", "git commit -q -m 'x'", "git diff --stat", "cp -- -odd.txt b.txt",
                        "rm -rf *", "rm -f src/*.pyc", "git commit -am 'x'", "git commit -mnew"):
            with self.subTest(command):
                self.assert_allowed("Bash", self.in_worktree(command))

    def test_S_015_5_a_redirect_in_the_git_C_form_is_denied(self):
        self.assert_denied("Bash", self.bash(f"git -C {self.worktree} log > .accio/run/claims.json"), "claims.json")
        self.assert_allowed("Bash", self.bash(f"git -C {self.worktree} log 2>/dev/null"))

    def test_a_check_that_cant_be_read_is_named(self):
        write(self.repo / ".accio" / "config.json",
              json.dumps({"checks": [{"command": "python3 'unbalanced", "glob": "*"}]}))
        self.assert_denied("Bash", self.in_worktree("ls"), "config.json")

    def test_S_015_4_the_worktrees_git_link_is_out_of_reach(self):
        self.assert_denied("Write", {"file_path": str(self.worktree / ".git"), "content": "gitdir: x"}, ".git")
        self.assert_denied("Write", {"file_path": str(self.worktree / ".Git"), "content": "gitdir: x"}, ".git")
        self.assert_allowed("Write", {"file_path": str(self.worktree / ".gitignore"), "content": "x"})

    def test_prefects_git_has_no_network_options(self):
        self.assert_denied("Bash", self.in_worktree("git ls-remote --upload-pack=./x ."), "ls-remote",
                           agent="accio:prefect")

    def test_prefects_git_branch_only_lists(self):
        self.assert_allowed("Bash", self.in_worktree("git branch --list"), agent="accio:prefect")
        self.assert_denied("Bash", self.in_worktree("git branch -D story/S-001"), "branch", agent="accio:prefect")


class OtherAgentsTest(CurfewTestBase):
    def test_S_015_7_reviewers_read_and_write_only_their_findings(self):
        findings = self.run_dir / "S-001" / "findings-examiner.md"
        for agent in ("accio:examiner", "accio:professor", "accio:auror"):
            with self.subTest(agent):
                self.assert_allowed("Read", {"file_path": str(self.worktree / "a.py")}, agent=agent)
                self.assert_allowed("Grep", {"pattern": "x", "path": str(self.worktree)}, agent=agent)
                self.assert_allowed("Write", {"file_path": str(findings), "content": "x"}, agent=agent)
                self.assert_denied("Write", {"file_path": str(self.worktree / "a.py"), "content": "x"}, agent,
                                   agent=agent)
                self.assert_denied("Bash", self.bash("ls"), agent, agent=agent)
                self.assert_denied("WebFetch", {"url": "https://example.com"}, agent=agent)

    def test_S_015_7_each_agent_gets_its_own_exact_list(self):
        board = shlex.quote(str(ROOT / "bin" / "accio-board"))
        self.assert_allowed("Bash", self.bash(f"{board} ready --json"), agent="accio:portkey")
        self.assert_denied("Bash", self.bash("ls"), "portkey", agent="accio:portkey")
        self.assert_denied("Bash", self.bash("/tmp/accio-board ready"), "portkey", agent="accio:portkey")
        script = lambda name: shlex.quote(str(ROOT / "bin" / name))
        cases = (("portkey", "accio-hooks verify", True), ("portkey", "accio-board unlock", True),
                 ("portkey", "accio-brief S-001", True), ("portkey", "accio-hooks uninstall", False),
                 ("portkey", "accio-ledger clear S-001", False), ("prefect", "accio-ledger record S-001", True),
                 ("prefect", "accio-board move S-001 review", True), ("prefect", "accio-board unlock", False),
                 ("prefect", "accio-hooks uninstall", False), ("prefect", "accio-check S-001", True),
                 ("prefect", "accio-check S-001 snapshot", False),
                 ("prefect", "accio-check S-001 snapshot --fresh", False),
                 ("prefect", "accio-check S-001 {snapshot,}", False), ("prefect", "accio-check S-001 $X", False),
                 ("portkey", "accio-check S-001 snapshot --fresh", True),
                 ("portkey", "accio-check S-001 snapshot", True), ("headmaster", "accio-check S-001", False),
                 ("headmaster", "accio-ledger check S-001", True),
                 ("headmaster", "accio-ledger clear S-001", False))
        for agent, command, allowed in cases:
            with self.subTest(agent=agent, command=command):
                name, _, rest = command.partition(" ")
                verdict, _ = self.decision("Bash", self.bash(f"{script(name)} {rest}"), agent=f"accio:{agent}")
                self.assertEqual(verdict, "allow" if allowed else "deny")
        self.assert_allowed("Bash", self.in_worktree("python3 -m unittest"), agent="accio:prefect")
        self.assert_allowed("Bash", self.bash(f"git -C {shlex.quote(str(self.worktree))} diff --stat"),
                            agent="accio:prefect")
        self.assert_denied("Bash", self.in_worktree("git commit -m x"), "commit", agent="accio:prefect")
        self.assert_denied("Write", {"file_path": str(self.run_dir / "push-ok"), "content": "x"},
                           agent="accio:prefect")
        self.assert_allowed("Write", {"file_path": str(self.run_dir / "questions" / "S-001.md"), "content": "x"},
                            agent="accio:prefect")
        self.assert_allowed("WebFetch", {"url": "https://example.com"}, agent="accio:seeker")
        self.assert_allowed("Write", {"file_path": str(self.repo / ".accio" / "stories" / "S-009.md"),
                                      "content": "x"}, agent="accio:quill")
        self.assert_allowed("Write", {"file_path": str(self.run_dir / "questions" / "S-001.md"), "content": "x"},
                            agent="accio:headmaster")
        self.assert_denied("Write", {"file_path": str(self.repo / "x.md"), "content": "x"}, agent="accio:librarian")
        self.assert_denied("Read", {"file_path": "x"}, "accio:nobody", agent="accio:nobody")


class AskRulesTest(CurfewTestBase):
    def setUp(self):
        super().setUp()
        self.claim()

    def test_S_015_10_a_call_matching_a_settings_ask_rule_is_denied_and_names_the_rule(self):
        write(self.repo / ".claude" / "settings.json", json.dumps({"permissions": {"ask": ["Bash(git commit:*)"]}}))
        write(self.home / ".claude" / "settings.json", json.dumps({"permissions": {"ask": ["Edit"]}}))
        self.assert_denied("Bash", self.in_worktree("git add -A && git commit -m x"), "Bash(git commit:*)",
                           "freeze")
        self.assert_allowed("Bash", self.in_worktree("git status"))
        self.assert_denied("Edit", {"file_path": str(self.worktree / "a.py"), "old_string": "a", "new_string": "b"},
                           "Edit")
        self.assert_allowed("Write", {"file_path": str(self.worktree / "a.py"), "content": "x"})
        write(self.repo / ".claude" / "settings.local.json", json.dumps({"permissions": {"ask": ["Bash(ls *)"]}}))
        self.assert_denied("Bash", self.in_worktree("ls src"), "Bash(ls *)")

    def test_S_015_10_a_claim_denied_by_an_ask_rule_is_not_recorded(self):
        write(self.repo / ".claude" / "settings.json", json.dumps({"permissions": {"ask": ["Bash"]}}))
        self.assert_denied("Bash", self.bash(f"{shlex.quote(str(CLAIM))} S-001"), "freeze", agent_id="a7")
        claims = json.loads((self.run_dir / "claims.json").read_text(encoding="utf-8"))
        self.assertNotIn("a7", claims)

    def test_S_015_11_a_recording_that_fails_gives_no_answer(self):
        (self.run_dir / "stuck.json").mkdir()
        self.assertIsNone(self.hook("Bash", self.bash("touch x"), event="PermissionRequest"))

    def test_S_015_11_a_permission_request_from_an_accio_agent_is_recorded(self):
        self.assertIsNone(self.hook("Bash", self.bash("touch x"), event="PermissionRequest"))
        self.assertIsNone(self.hook("Bash", self.bash("touch y"), event="PermissionRequest", agent="general-purpose"))
        stuck = json.loads((self.run_dir / "stuck.json").read_text(encoding="utf-8"))
        self.assertEqual([(s["agent_id"], s["agent_type"], s["tool"], s["detail"]) for s in stuck],
                         [("a1", "accio:house-elf", "Bash", "touch x")])

    def test_S_015_12_verify_lists_the_ask_rules_a_build_would_stop_on(self):
        write(self.repo / ".claude" / "settings.json", json.dumps({"permissions": {"ask": ["Bash(npm publish:*)"]}}))
        run = lambda *args: subprocess.run([str(HOOKS_CLI), *args], cwd=self.repo, capture_output=True, text=True,
                                           check=False, env={**self.env(), "CLAUDECODE": ""})
        self.assertEqual(run("install").returncode, 0)
        result = run("verify")
        self.assertIn("Bash(npm publish:*)", result.stdout)
        self.assertIn(".claude/settings.json", result.stdout)


if __name__ == "__main__":
    unittest.main()
