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

from accio_lib import paths, policy, runlock

CURFEW = ROOT / "hooks" / "curfew.py"
STARTUP = ROOT / "hooks" / "_startup.py"
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

    def test_S_015_4_S_082_2_writes_inside_the_worktree_or_to_its_report_are_allowed(self):
        for path in (self.worktree / "src" / "a.py", paths.report_path(self.repo, "S-001")):
            for tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
                with self.subTest(path=path, tool=tool):
                    self.assertEqual(self.write_to(path, tool)["permissionDecision"], "allow")

    def test_S_015_4_in_its_run_folder_house_elf_writes_nothing(self):
        for name in ("examiner-findings.md", "base", "brief.md", "build-report.md"):
            with self.subTest(name):
                self.assertEqual(self.write_to(self.run_dir / "S-001" / name)["permissionDecision"], "deny")

    def test_S_082_2_another_storys_report_or_another_file_beside_its_own_is_denied(self):
        reports = paths.reports_dir(self.repo)
        for path in (paths.report_path(self.repo, "S-002"), reports / "S-001" / "notes.md", reports / "S-001.md",
                     reports / "S-002" / ".." / "S-003" / "build-report.md"):
            with self.subTest(path=path):
                answer = self.write_to(path)
                self.assertEqual(answer["permissionDecision"], "deny")
                self.assertIn(str(paths.report_path(self.repo, "S-001")), answer["permissionDecisionReason"])

    def test_S_015_4_writes_anywhere_else_are_denied_and_name_the_folder(self):
        outside = self.worktree.parent / "outside.txt"
        (self.worktree / "link").symlink_to(self.repo)
        for path in (self.repo / "app.py", self.worktree / ".." / "outside.txt", self.worktree / "link" / "x.py",
                     self.run_dir / "push-ok", self.run_dir / "brew.lock", self.run_dir / "S-002" / "build-report.md",
                     paths.report_path(self.repo, "S-002"), outside):
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

    def test_S_022_7_a_command_owl_allowed_once_is_allowed_for_that_storys_next_build_only(self):
        self.assert_denied("Bash", self.in_worktree("docker compose up -d"), "docker")
        grants = self.run_dir / runlock.ALLOW_ONCE_NAME
        grants.write_text(json.dumps({"stories": {"S-002": ["docker compose up"]}}))
        self.assert_denied("Bash", self.in_worktree("docker compose up -d"), "docker")  # another story's grant
        grants.write_text(json.dumps({"stories": {"S-001": ["docker compose up -d"]}}))
        self.assert_allowed("Bash", self.in_worktree("docker compose up -d"))
        runlock.release(self.run_dir)  # the build ends and drops its claims (S-057/2)
        self.claim()
        self.assert_denied("Bash", self.in_worktree("docker compose up -d"), "docker")

    def test_S_040_1_the_exact_agent_allow_command_is_allowed(self):
        self.assert_allowed("Bash", self.in_worktree("make build"))

    def test_S_040_2_an_agent_allow_command_with_anything_added_is_denied(self):
        for command in ("make build --x", "make build; rm x", "make build extra", "make build && rm x"):
            with self.subTest(command):
                self.assert_denied("Bash", self.in_worktree(command))

    def test_S_040_3_a_listed_check_with_extra_arguments_is_still_allowed(self):
        self.assert_allowed("Bash", self.in_worktree("python3 -m unittest discover -s tests --verbose"))

    def test_S_040_4_an_allow_once_entry_with_anything_added_is_denied(self):
        grants = self.run_dir / runlock.ALLOW_ONCE_NAME
        grants.write_text(json.dumps({"stories": {"S-001": ["docker compose up"]}}))
        self.assert_allowed("Bash", self.in_worktree("docker compose up"))
        for command in ("docker compose up -d", "docker compose up; rm x"):
            with self.subTest(command):
                self.assert_denied("Bash", self.in_worktree(command), "docker")

    def test_S_040_5_the_docs_state_the_whole_command_rule(self):
        from accio_lib import bashpolicy
        docstring = " ".join((bashpolicy.__doc__ or "").split())
        self.assertIn("an `agent_allow` entry (and an allow-once one) matches the whole command", docstring)
        backlog = " ".join((ROOT / "docs" / "BACKLOG.md").read_text().split())
        self.assertIn("`agent_allow` and allow-once entries match the whole command", backlog)

    def test_an_ansi_c_spelled_command_is_judged_as_bash_runs_it(self):
        self.assert_denied("Bash", self.in_worktree(r"$'\x63\x75\x72\x6c' https://example.com"), "curl")

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
                        "rm -rf *", "rm -f src/*.pyc", "git commit -am 'x'", "git commit -mnew", "accio-board refresh"):
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


PREVIEW_URL = "http://localhost:3000/app"
BROWSER = "mcp__plugin_playwright_playwright__browser_"
MAD_EYE = "accio:mad-eye"


class MadEyeBrowserTest(CurfewTestBase):
    def setUp(self):
        super().setUp()
        config = {**CONFIG, "preview": {"command": "npm start", "url": PREVIEW_URL}}
        write(self.repo / ".accio" / "config.json", json.dumps(config))
        self.shots = self.run_dir / "S-001" / "mad-eye"

    def browse(self, name, tool_input, **kwargs):
        return self.decision(BROWSER + name, tool_input, agent=MAD_EYE, **kwargs)

    def test_S_046_1_navigate_to_the_preview_origin_is_allowed(self):
        for url in (PREVIEW_URL, "http://localhost:3000/other?x=1", "HTTP://LOCALHOST:3000"):
            with self.subTest(url):
                self.assertEqual(self.browse("navigate", {"url": url})[0], "allow")

    def test_S_046_2_navigate_to_another_origin_is_denied(self):
        for url in ("http://localhost:3001/", "https://localhost:3000/", "http://example.com/",
                    "http://localhost:3000@evil.com/", "file:///etc/passwd", "localhost:3000", ""):
            with self.subTest(url):
                verdict, reason = self.browse("navigate", {"url": url})
                self.assertEqual(verdict, "deny")
                self.assertIn("origin", reason)

    def test_S_046_2_navigate_is_denied_without_a_preview_url(self):
        write(self.repo / ".accio" / "config.json", json.dumps(CONFIG))
        verdict, reason = self.browse("navigate", {"url": PREVIEW_URL})
        self.assertEqual(verdict, "deny")
        self.assertIn("preview.url", reason)

    def test_S_046_9_urls_that_a_browser_reads_differently_are_denied(self):
        for url in ("http://evil.com\\@localhost:3000/", "http://evil.com@localhost:3000/",
                    "http://localhost:3000\\@evil.com/", "http://localhost:3000/ x", "http://localhost:3000/\tx",
                    "http://localhost:3000/\nx", "http://localhost:3000/\x00", " http://localhost:3000/",
                    "http://localhost:3000/\\x"):
            with self.subTest(url):
                verdict, reason = self.browse("navigate", {"url": url})
                self.assertEqual(verdict, "deny")
                self.assertIn("origin", reason)

    def test_S_046_10_a_filename_on_any_browser_tool_gets_the_folder_rule(self):
        (self.shots).mkdir(parents=True)
        for name in ("snapshot", "console_messages", "take_screenshot", "click"):
            with self.subTest(name):
                good = self.browse(name, {"filename": str(self.shots / "a.md")})
                self.assertEqual(good[0], "allow")
                for bad in (str(self.repo / "a.md"), "a.md", str(self.shots / ".." / "a.md")):
                    verdict, reason = self.browse(name, {"filename": bad})
                    self.assertEqual(verdict, "deny", bad)
                    self.assertIn("mad-eye", reason)

    def test_S_046_10_snapshot_without_a_filename_is_allowed(self):
        self.assertEqual(self.browse("snapshot", {})[0], "allow")

    def test_S_046_3_screenshot_into_the_mad_eye_folder_is_allowed(self):
        for story_id in ("S-001", "S-123"):
            shot = self.run_dir / story_id / "mad-eye" / "home.png"
            self.assertEqual(self.browse("take_screenshot", {"filename": str(shot)})[0], "allow", story_id)

    def test_S_046_4_screenshot_outside_the_folder_is_denied(self):
        outside = self.tmp.name
        (self.shots).mkdir(parents=True)
        os.symlink(outside, self.shots / "link")
        for name in (str(self.repo / "home.png"), str(self.run_dir / "S-001" / "home.png"),
                     str(self.shots / ".." / "home.png"), str(self.shots / "link" / "home.png"),
                     str(self.run_dir / "notes" / "mad-eye" / "home.png"), str(self.shots), "home.png", ""):
            with self.subTest(name):
                verdict, reason = self.browse("take_screenshot", {"filename": name})
                self.assertEqual(verdict, "deny")
                self.assertIn("mad-eye", reason)

    def test_S_046_4_screenshot_without_a_filename_is_denied(self):
        self.assertEqual(self.browse("take_screenshot", {})[0], "deny")

    def test_S_046_5_a_tool_off_the_list_is_denied(self):
        for name in ("evaluate", "run_code_unsafe", "file_upload", "network_requests", "drop"):
            with self.subTest(name):
                verdict, reason = self.browse(name, {})
                self.assertEqual(verdict, "deny")
                self.assertIn("browser_" + name, reason)

    def test_S_046_5_the_fixed_list_is_allowed(self):
        for name in ("snapshot", "click", "type", "fill_form", "select_option", "hover", "press_key", "wait_for",
                     "resize", "console_messages", "close"):
            with self.subTest(name):
                self.assertEqual(self.browse(name, {})[0], "allow")

    def test_S_046_6_any_other_agent_is_denied(self):
        for agent in ("accio:house-elf", "accio:portkey", "accio:seeker", "accio:librarian"):
            for name in ("snapshot", "navigate"):
                with self.subTest(agent + name):
                    self.assert_denied(BROWSER + name, {"url": PREVIEW_URL}, "mad-eye", agent=agent)

    def test_S_046_7_the_configured_prefix_replaces_the_default(self):
        config = {"preview": {"url": PREVIEW_URL, "mcp_prefix": "mcp__pw__"}}
        ctx = policy.Context(root=self.repo, accio=self.repo / ".accio", bin_dir=ROOT / "bin", config=config,
                             claims={}, statuses={})
        self.assertTrue(policy.decide("mad-eye", "a1", "mcp__pw__browser_snapshot", {}, ctx).allow)
        self.assertTrue(policy.decide("mad-eye", "a1", "mcp__pw__browser_navigate", {"url": PREVIEW_URL}, ctx).allow)
        self.assertFalse(policy.decide("mad-eye", "a1", BROWSER + "snapshot", {}, ctx).allow)
        self.assertFalse(policy.decide("house-elf", "a1", "mcp__pw__browser_snapshot", {}, ctx).allow)
        self.assertFalse(policy.decide("mad-eye", "a1", "mcp__pw__browser_evaluate", {}, ctx).allow)


class MadEyeFenceTest(CurfewTestBase):
    """S-064: while a fence record names the agent, only navigate (on the origin), screenshot and close are allowed."""

    def setUp(self):
        super().setUp()
        config = {**CONFIG, "preview": {"command": "npm start", "url": PREVIEW_URL}}
        write(self.repo / ".accio" / "config.json", json.dumps(config))
        self.shots = self.run_dir / "S-001" / "mad-eye"

    def browse(self, name, tool_input, **kwargs):
        return self.decision(BROWSER + name, tool_input, agent=MAD_EYE, **kwargs)

    def fence(self, *agent_ids):
        write(self.run_dir / "mad-eye-fence.json",
              json.dumps({agent_id: {"url": "http://evil.com/"} for agent_id in agent_ids}))

    def shot(self):
        return {"filename": str(self.shots / "a.png")}

    def test_S_064_1_a_fenced_agent_is_denied_every_other_browser_tool(self):
        self.fence("a1")
        for name in ("click", "type", "snapshot", "fill_form", "select_option", "hover", "press_key", "wait_for",
                     "resize", "console_messages"):
            with self.subTest(name):
                verdict, reason = self.browse(name, {})
                self.assertEqual(verdict, "deny")
                self.assertIn("fence", reason)

    def test_S_064_2_a_fenced_agent_may_navigate_to_the_origin(self):
        self.fence("a1")
        self.assertEqual(self.browse("navigate", {"url": PREVIEW_URL})[0], "allow")

    def test_S_064_3_a_fenced_agent_may_not_navigate_off_the_origin(self):
        self.fence("a1")
        verdict, reason = self.browse("navigate", {"url": "http://example.com/"})
        self.assertEqual(verdict, "deny")
        self.assertIn("origin", reason)

    def test_S_064_4_a_fenced_agent_may_close_but_not_screenshot(self):
        # commit security review: a screenshot while fenced is a picture of the off-origin page
        self.fence("a1")
        self.assertEqual(self.browse("take_screenshot", self.shot())[0], "deny")
        self.assertEqual(self.browse("close", {})[0], "allow")

    def test_S_064_5_a_fenced_agent_may_not_read_grep_or_glob(self):
        self.fence("a1")
        for tool, tool_input in (("Read", {"file_path": str(self.repo / "x.md")}), ("Grep", {"pattern": "x"}),
                                 ("Glob", {"pattern": "*"}), ("LS", {"path": str(self.repo)})):
            with self.subTest(tool):
                verdict, reason = self.decision(tool, tool_input, agent=MAD_EYE)
                self.assertEqual(verdict, "deny")
                self.assertIn("fence", reason)

    def test_S_064_6_no_fence_for_this_agent_means_todays_rules(self):
        for content in (None, json.dumps({"other": {"url": "x"}})):
            with self.subTest(content):
                (self.run_dir / "mad-eye-fence.json").unlink(missing_ok=True)
                if content is not None:
                    write(self.run_dir / "mad-eye-fence.json", content)
                self.assertEqual(self.browse("click", {})[0], "allow")
                self.assertEqual(self.decision("Read", {"file_path": str(self.repo / "x.md")}, agent=MAD_EYE)[0],
                                 "allow")

    def test_S_064_6_a_fence_file_that_cannot_be_read_fences_mad_eye(self):
        # push security review: fail closed, as fence.py does, not open
        for content in ("{not json", "[]", None):
            with self.subTest(content):
                path = self.run_dir / "mad-eye-fence.json"
                if path.is_dir():
                    path.rmdir()
                path.unlink(missing_ok=True)
                if content is None:
                    path.mkdir()  # unreadable as a file
                else:
                    write(path, content)
                self.assertEqual(self.browse("click", {})[0], "deny")
                self.assertEqual(self.browse("navigate", {"url": PREVIEW_URL})[0], "allow")
                self.assertEqual(self.browse("navigate", {"url": "http://example.com/"})[0], "deny")
                self.assertEqual(self.decision("Read", {"file_path": str(self.repo / "x.md")},
                                               agent="accio:librarian")[0], "allow")

    def test_S_064_a_fence_on_another_agent_does_not_fence_other_agents(self):
        self.fence("a1")
        verdict, _ = self.decision("Read", {"file_path": str(self.repo / "x.md")}, agent="accio:librarian")
        self.assertEqual(verdict, "allow")


class MadEyeSavedPagesTest(CurfewTestBase):
    """S-065: mad-eye never reads the browser's saved pages, fenced or not."""

    def setUp(self):
        super().setUp()
        self.saved = self.repo / ".playwright-mcp"
        write(self.saved / "page-1.yml", "- page")
        write(self.repo / "x.md", "x")

    def read(self, path, agent=MAD_EYE):
        return self.decision("Read", {"file_path": str(path)}, agent=agent)

    def test_S_065_1_read_under_the_saved_pages_is_denied(self):
        verdict, reason = self.read(self.saved / "page-1.yml")
        self.assertEqual(verdict, "deny")
        self.assertIn("saved pages", reason)

    def test_S_065_2_a_symlink_or_dotdot_to_the_saved_pages_is_denied(self):
        (self.repo / "link").symlink_to(self.saved)
        self.assertEqual(self.read(self.repo / "link" / "page-1.yml")[0], "deny")
        self.assertEqual(self.read(self.repo / "src" / ".." / ".playwright-mcp" / "page-1.yml")[0], "deny")

    def test_S_065_2_a_different_letter_case_is_denied(self):
        self.assertEqual(self.read(self.repo / ".PLAYWRIGHT-MCP" / "page-1.yml")[0], "deny")
        self.assertEqual(self.read(self.repo / ".Playwright-Mcp" / "page-1.yml")[0], "deny")

    def test_S_065_3_grep_glob_and_ls_are_denied(self):
        for tool, tool_input in (("Grep", {"pattern": "x"}), ("Glob", {"pattern": "*"}),
                                 ("LS", {"path": str(self.repo)})):
            with self.subTest(tool):
                self.assertEqual(self.decision(tool, tool_input, agent=MAD_EYE)[0], "deny")

    def test_S_065_4_read_of_other_files_is_allowed(self):
        self.assertEqual(self.read(self.repo / "x.md")[0], "allow")

    def test_S_065_5_other_agents_keep_todays_rules(self):
        for agent in ("accio:librarian", "accio:examiner"):
            with self.subTest(agent):
                self.assertEqual(self.read(self.saved / "page-1.yml", agent)[0], "allow")
                for tool in ("Grep", "Glob"):
                    self.assertEqual(self.decision(tool, {"pattern": "x"}, agent=agent)[0], "allow")


class OtherAgentsTest(CurfewTestBase):
    def test_S_024_seeker_and_wandmaker_write_only_their_notes(self):
        accio = self.repo / ".accio"
        for agent, own in (("seeker", "seeker-notes.md"), ("wandmaker", "wandmaker-options.md")):
            with self.subTest(agent):
                self.assert_allowed("Write", {"file_path": str(self.run_dir / "wand" / own), "content": "x"},
                                    agent=f"accio:{agent}")
                for target in (accio / "design.md", self.run_dir / "wand" / "other.md", accio / "stories" / "S-001.md"):
                    self.assert_denied("Write", {"file_path": str(target), "content": "x"}, agent, agent=f"accio:{agent}")
        self.assert_allowed("WebSearch", {"query": "x"}, agent="accio:seeker")
        self.assert_denied("WebSearch", {"query": "x"}, "wandmaker", agent="accio:wandmaker")

    def test_S_081_2_first_year_writes_only_its_notes_file(self):
        accio = self.repo / ".accio"
        agent = "accio:first-year"
        self.assert_allowed("Write", {"file_path": str(self.run_dir / "wand" / "first-year-notes.md"),
                                      "content": "x"}, agent=agent)
        for target in (accio / "design.md", accio / "decisions" / "001-x.md", self.run_dir / "wand" / "seeker-notes.md",
                       self.run_dir / "wand" / "other.md", self.worktree / "a.py", self.repo / "first-year-notes.md"):
            with self.subTest(str(target)):
                self.assert_denied("Write", {"file_path": str(target), "content": "x"}, "first-year", agent=agent)
        self.assert_denied("Edit", {"file_path": str(accio / "design.md"), "old_string": "a", "new_string": "b"},
                           "first-year", agent=agent)
        self.assert_denied("Bash", self.bash("ls"), "Bash", agent=agent)
        self.assert_denied("WebSearch", {"query": "x"}, "first-year", agent=agent)

    def test_S_023_1_quill_writes_story_files_and_its_summary_only(self):
        accio = self.repo / ".accio"
        for target in (accio / "stories" / "S-012.md", self.run_dir / "sort" / "quill-summary.md"):
            self.assert_allowed("Write", {"file_path": str(target), "content": "x"}, agent="accio:quill")
        for target in (accio / "config.json", accio / "stories" / "notes.md", accio / "design.md",
                       self.worktree / "a.py", self.run_dir / "sort" / "examiner-findings.md",
                       self.run_dir / "S-001" / "build-report.md"):
            self.assert_denied("Write", {"file_path": str(target), "content": "x"}, "quill", agent="accio:quill")
        self.assert_denied("Bash", self.bash("ls"), "Bash", agent="accio:quill")

    def test_S_036_3_headmaster_writes_its_ruling_file(self):
        for name in ("ruling-r0.md", "ruling-r2.md"):
            self.assert_allowed("Write", {"file_path": str(self.run_dir / "S-001" / name), "content": "x"},
                                agent="accio:headmaster")

    def test_S_036_4_headmaster_writes_no_other_new_file(self):
        for target in (self.run_dir / "S-001" / "notes.md", self.run_dir / "S-001" / "ruling.md",
                       self.run_dir / "S-001" / "build-report.md", self.run_dir / "S-001" / "ruling-r1.txt",
                       self.run_dir / "ruling-r1.md", self.run_dir / "S-001" / "sub" / "ruling-r1.md",
                       self.run_dir / "push-ok", self.repo / ".accio" / "design.md"):
            self.assert_denied("Write", {"file_path": str(target), "content": "x"}, "headmaster",
                               agent="accio:headmaster")

    def test_S_015_7_reviewers_read_and_write_only_their_findings(self):
        findings = self.run_dir / "S-001" / "examiner-findings.md"
        for agent in ("accio:examiner", "accio:professor", "accio:auror"):
            with self.subTest(agent):
                self.assert_allowed("Read", {"file_path": str(self.worktree / "a.py")}, agent=agent)
                self.assert_allowed("Grep", {"pattern": "x", "path": str(self.worktree)}, agent=agent)
                self.assert_allowed("Write", {"file_path": str(findings), "content": "x"}, agent=agent)
                self.assert_denied("Write", {"file_path": str(self.worktree / "a.py"), "content": "x"}, agent,
                                   agent=agent)
                self.assert_denied("Bash", self.bash("ls"), agent, agent=agent)
                self.assert_denied("WebFetch", {"url": "https://example.com"}, agent=agent)

    def test_every_agent_may_hand_back_its_reply_even_before_a_claim(self):
        # A background agent's reply reaches its caller only through SubagentHandback (seen live 2026-10-19: curfew's
        # deny lost the replies of seeker, wandmaker, quill and examiner), and a workflow agent's schema reply only
        # through StructuredOutput (spike finding 16).
        for agent in (*policy.AGENTS, "house-elf"):
            for tool in sorted(policy.REPLY_TOOLS):
                with self.subTest(agent=agent, tool=tool):
                    self.assert_allowed(tool, {"message": "done"}, agent=f"accio:{agent}")
        for tool in sorted(policy.REPLY_TOOLS):
            self.assert_denied(tool, {"message": "done"}, "accio:nobody", agent="accio:nobody")
        for near_miss in ("subagenthandback", "SubagentHandbackX", "StructuredOutput2", "TaskStop"):
            self.assert_denied(near_miss, {"message": "done"}, near_miss, agent="accio:quill")

    def test_S_015_7_each_agent_gets_its_own_exact_list(self):
        board = shlex.quote(str(ROOT / "bin" / "accio-board"))
        self.assert_allowed("Bash", self.bash(f"{board} ready --json"), agent="accio:portkey")
        self.assert_denied("Bash", self.bash("ls"), "portkey", agent="accio:portkey")
        self.assert_denied("Bash", self.bash("/tmp/accio-board ready"), "portkey", agent="accio:portkey")
        script = lambda name: shlex.quote(str(ROOT / "bin" / name))
        cases = (("portkey", "accio-hooks verify", True), ("portkey", "accio-board unlock", True),
                 ("portkey", "accio-brief S-001", True), ("portkey", "accio-brief S-001 --release", True),
                 ("portkey", "accio-hooks uninstall", False),
                 ("portkey", "accio-ledger clear S-001", False), ("prefect", "accio-ledger record S-001", True),
                 ("prefect", "accio-board move S-001 review", True), ("prefect", "accio-board unlock", False),
                 ("prefect", "accio-board refresh", True), ("portkey", "accio-board refresh", True),
                 ("prefect", "accio-hooks uninstall", False), ("prefect", "accio-check S-001", True),
                 ("prefect", "accio-check S-001 snapshot", False),
                 ("prefect", "accio-check S-001 snapshot --fresh", False),
                 ("prefect", "accio-check S-001 {snapshot,}", False), ("prefect", "accio-check S-001 $X", False),
                 ("portkey", "accio-check S-001 snapshot --fresh", True),
                 ("portkey", "accio-check S-001 snapshot", True), ("headmaster", "accio-check S-001", False),
                 ("headmaster", "accio-ledger check S-001", True),
                 ("headmaster", "accio-ledger clear S-001", False),
                 ("headmaster", "accio-ledger record S-001 k pass", False))  # S-020: the workflow records
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


class BoggartTest(CurfewTestBase):
    AGENT = "accio:boggart"

    def setUp(self):
        super().setUp()
        self.repros = self.run_dir / "S-001" / "boggart" / "repros"
        self.brk = shlex.quote(str(ROOT / "bin" / "accio-break"))

    def write(self, target):
        return self.decision("Write", {"file_path": str(target), "content": "x"}, agent=self.AGENT)[0]

    def test_S_052_4_a_write_under_its_repros_folder_is_allowed(self):
        self.assertEqual(self.write(self.repros / "repro_a.py"), "allow")
        self.assertEqual(self.write(self.run_dir / "S-123" / "boggart" / "repros" / "r.js"), "allow")

    def test_S_052_5_verdicts_and_any_other_path_are_denied(self):
        link = self.repros / "link"
        self.repros.mkdir(parents=True)
        os.symlink(self.tmp.name, link)
        for target in (self.run_dir / "S-001" / "boggart" / "verdicts.json", self.run_dir / "S-001" / "boggart" / "log.txt",
                       self.repros / "sub" / "r.py", self.repros, self.repros / ".." / "verdicts.json",
                       link / "r.py", self.run_dir / "S-001" / "build-report.md", self.run_dir / "S-001" / "repros" / "r.py",
                       self.run_dir / "x" / "boggart" / "repros" / "r.py", self.worktree / "a.py",
                       self.run_dir / "push-ok"):
            with self.subTest(target=str(target)):
                self.assertEqual(self.write(target), "deny")

    def test_S_052_7_it_may_read(self):
        for tool, tool_input in (("Read", {"file_path": str(self.worktree / "a.py")}),
                                 ("Grep", {"pattern": "x", "path": str(self.worktree)}),
                                 ("Glob", {"pattern": "*.py"}), ("LS", {"path": str(self.worktree)})):
            with self.subTest(tool=tool):
                self.assert_allowed(tool, tool_input, agent=self.AGENT)
        self.assert_denied("WebFetch", {"url": "https://example.com"}, agent=self.AGENT)

    def bash_verdict(self, command):
        return self.decision("Bash", self.bash(command), agent=self.AGENT)[0]

    def test_S_052_8_accio_break_try_on_its_own_repro_is_allowed(self):
        self.assertEqual(self.bash_verdict(f"{self.brk} S-001 try {self.repros}/repro_a.py"), "allow")
        self.assertEqual(self.bash_verdict(f"accio-break S-001 try {self.repros}/repro_a.py"), "allow")

    def test_S_052_8_every_other_command_is_denied(self):
        good = f"{self.brk} S-001 try {self.repros}/r.py"
        for command in (f"{self.brk} S-001 verify", f"{self.brk} S-002 try {self.repros}/r.py",
                        f"{self.brk} S-001 try {self.run_dir}/S-001/boggart/verdicts.json",
                        f"{self.brk} S-001 try {self.repros}/../verdicts.json",
                        f"{self.brk} S-001 try {self.repros}/sub/r.py", f"{self.brk} S-001 try {self.repros}/",
                        f"{self.brk} S-001 try {self.worktree}/a.py", f"{self.brk} S-001 try r.py",
                        f"{self.brk} S-001 try {self.repros}/r.py extra", f"{self.brk} S-001",
                        f"{good} && rm -rf x", f"{good} > {self.run_dir}/S-001/boggart/verdicts.json",
                        f"/tmp/accio-break S-001 try {self.repros}/r.py", "ls", "python3 x.py", "git status"):
            with self.subTest(command=command):
                self.assertEqual(self.bash_verdict(command), "deny")


class HowlerTest(CurfewTestBase):
    SHA = "a" * 40
    OTHER = "b" * 40

    def verdict(self, command):
        return self.decision("Bash", self.bash(command), agent="accio:howler")[0]

    def allowed(self, command):
        self.assertEqual(self.verdict(command), "allow", command)

    def denied(self, command):
        self.assertEqual(self.verdict(command), "deny", command)

    def test_S_001_1_run_list_by_commit_is_allowed(self):
        self.allowed(f"gh run list --commit {self.SHA} --json databaseId,workflowDatabaseId,headSha,status,"
                     "conclusion,name")

    def test_S_001_2_run_list_by_workflow_and_branch_is_allowed(self):
        self.allowed("gh run list --workflow 123 --branch main --limit 5 --json databaseId,headSha,conclusion")

    def test_S_001_3_run_watch_with_the_null_redirect_is_allowed(self):
        self.allowed("gh run watch 123 --exit-status --compact > /dev/null 2>&1")

    def test_S_001_4_run_view_json_jobs_is_allowed(self):
        self.allowed("gh run view 123 --json jobs")

    def test_S_001_5_failed_log_piped_into_tail_60_is_allowed(self):
        self.allowed("gh run view 123 --log-failed --job 456 | tail -60")

    def test_S_001_6_merge_base_is_ancestor_is_allowed(self):
        self.allowed(f"git merge-base --is-ancestor {self.SHA} {self.OTHER}")

    def test_S_001_7_diff_name_only_is_allowed(self):
        self.allowed(f"git diff --name-only {self.SHA} {self.OTHER}")

    def test_S_001_8_rev_parse_head_is_allowed(self):
        self.allowed("git rev-parse HEAD")

    def test_S_001_9_remote_get_url_origin_is_allowed(self):
        self.allowed("git remote get-url origin")

    def test_S_001_10_run_rerun_is_denied(self):
        self.denied("gh run rerun 1")

    def test_S_001_11_run_cancel_is_denied(self):
        self.denied("gh run cancel 1")

    def test_S_001_12_git_log_is_denied(self):
        self.denied("git log")

    def test_S_001_13_git_push_is_denied(self):
        self.denied("git push")

    def test_S_001_14_sleep_is_denied(self):
        self.denied("sleep 5")

    def test_S_001_15_cat_is_denied(self):
        self.denied("cat x")

    def test_S_001_16_a_variable_before_the_command_is_denied(self):
        self.denied("GH_PAGER=cat gh run list")

    def test_S_001_17_an_unknown_flag_is_denied_and_named(self):
        self.denied("gh run view 1 -R x/y")
        reason = self.assert_denied("Bash", self.bash("gh run view 1 -R x/y"), "howler", agent="accio:howler")
        self.assertIn("gh run view", reason)
        self.assertIn("-R", reason)

    def test_S_001_18_a_run_id_that_is_not_digits_is_denied(self):
        self.denied("gh run view abc")

    def test_S_001_19_git_diff_output_flag_is_denied(self):
        self.denied("git diff --name-only --output=f")

    def test_S_001_20_a_json_field_outside_the_set_is_denied(self):
        self.denied("gh run view 1 --json token")
        self.denied("gh run view 1 --json jobs,token")
        self.denied("gh run view 1 --json url")

    def test_S_001_21_other_agents_keep_their_decisions(self):
        script = shlex.quote(str(ROOT / "bin" / "accio-board"))
        self.assert_allowed("Bash", self.bash(f"{script} ready --json"), agent="accio:portkey")
        self.assert_denied("Bash", self.bash("gh run list"), "gh run", agent="accio:portkey")
        self.assert_denied("Bash", self.bash("ls"), "Bash", agent="accio:quill")
        self.assert_denied("Bash", self.bash("git rev-parse HEAD"), "Bash", agent="accio:examiner")
        self.assert_allowed("Bash", self.in_worktree("python3 -m unittest"), agent="accio:prefect")
        self.assert_allowed("Write", {"file_path": str(self.run_dir / "questions" / "S-001.md"), "content": "x"},
                            agent="accio:headmaster")

    def test_howler_tail_is_only_tail_60_after_a_pipe_with_no_redirect(self):
        for command in ("tail -60 < some-file", "tail -60", "tail -60 some-file", "tail -61",
                        "gh run view 1 --log-failed | tail -60 < some-file",
                        "gh run view 1 --log-failed | tail -60 > out.txt", "gh run view 1 | tail -f",
                        "gh run view 1 | tail -n 60", "gh run view 1 | tail -100", "tail -f x"):
            with self.subTest(command=command):
                self.denied(command)

    def test_howler_redirect_only_after_run_watch_and_only_to_null(self):
        for command in ("gh run watch 1 > out.txt", "gh run watch 1 > /dev/null", "gh run view 1 > /dev/null 2>&1",
                        "git rev-parse HEAD > /dev/null", "gh run watch 1 2>&1", "gh run view 1 < x",
                        "gh run watch 1 > /dev/null 2>&1 > out.txt"):
            with self.subTest(command=command):
                self.denied(command)

    def test_howler_pipe_only_into_tail_and_no_other_operator(self):
        for command in ("gh run view 1 | cat", "gh run view 1 --log-failed | tail -60 | tail -60",
                        "git rev-parse HEAD && git rev-parse HEAD", "git rev-parse HEAD; git rev-parse HEAD",
                        "git rev-parse HEAD || git rev-parse HEAD", "gh run view 1 &", "git rev-parse $" "(echo HEAD)",
                        "gh run view 1 --json=jobs", "gh run view 1 --repo x/y", "gh run view ١"):
            with self.subTest(command=command):
                self.denied(command)

    def test_howler_values_follow_the_fixed_patterns(self):
        for command in ("gh run list --commit abc", f"gh run list --commit {'A' * 40}",
                        "gh run list --limit x", "gh run list --branch 'a b'", "gh run list --branch --json",
                        "git rev-parse --git-dir", "git remote get-url -v", "git rev-parse HEAD~1",
                        f"git merge-base --is-ancestor {self.SHA}", "gh run list --json"):
            with self.subTest(command=command):
                self.denied(command)
        self.allowed("gh run list --branch feature/a-b_c.1")
        self.allowed("gh run list --json name,jobs,headBranch")


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


class CurfewStartupCrashTest(unittest.TestCase):
    """S-033, S-037/4: curfew (through `_startup.py`) with an unimportable `accio_lib` (a copy of curfew beside a broken library)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.tmp.name).resolve()
        (base / "hooks").mkdir()
        (base / "bin" / "accio_lib").mkdir(parents=True)
        (base / "hooks" / "curfew.py").write_text(CURFEW.read_text(encoding="utf-8"), encoding="utf-8")
        (base / "hooks" / "_startup.py").write_text(STARTUP.read_text(encoding="utf-8"), encoding="utf-8")
        (base / "bin" / "accio_lib" / "__init__.py").write_text("raise ImportError('broken update')\n",
                                                                 encoding="utf-8")
        self.script = base / "hooks" / "curfew.py"

    def tearDown(self):
        self.tmp.cleanup()

    def run_curfew(self, **fields):
        payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"},
                   "cwd": self.tmp.name, **fields}
        result = subprocess.run([sys.executable, "-I", str(self.script)], input=json.dumps(payload),
                                capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_S_033_2_accio_agent_is_denied_with_the_error(self):
        out = json.loads(self.run_curfew(agent_type="accio:house-elf", agent_id="a1"))["hookSpecificOutput"]
        self.assertEqual(out["permissionDecision"], "deny")
        self.assertIn("ImportError", out["permissionDecisionReason"])
        self.assertIn("broken update", out["permissionDecisionReason"])

    def test_S_033_3_main_chat_and_other_agents_get_no_answer(self):
        self.assertEqual(self.run_curfew().strip(), "")
        self.assertEqual(self.run_curfew(agent_type="other:agent", agent_id="a2").strip(), "")

    def test_S_033_4_permission_request_gets_no_answer(self):
        self.assertEqual(self.run_curfew(hook_event_name="PermissionRequest", agent_type="accio:house-elf",
                                         agent_id="a1").strip(), "")


if __name__ == "__main__":
    unittest.main()
