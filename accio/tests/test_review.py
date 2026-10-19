"""S-020: the review package (`accio-brief <ID> --review [--since <rev>]`) and the fix brief's conflict rule."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

BRIEF = ROOT / "bin" / "accio-brief"

STORY = """---
id: S-001
title: Reset email
track: story
status: ready
files: [{files}]
{risk}---
## Context
Users forget passwords.
## Definition of Done
- [ ] S-001/1 WHEN a user asks for a reset THE SYSTEM SHALL email a link
- [ ] S-001/2 (no test) checks pass
## Review notes
## Blocked question
"""


class ReviewPackageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")
        write(self.repo / "src" / "a.py", "value = 1\n")
        commit_all(self.repo)
        self.accio = self.repo / ".accio"
        write(self.accio / "config.json", json.dumps({"checks": [{"command": "python3 -m unittest", "glob": "**/*.py"}]}))
        self.worktree = self.base / ".app-accio-wt" / "S-001"

    def tearDown(self):
        self.tmp.cleanup()

    def story(self, files="src/a.py", risk=""):
        write(self.accio / "stories" / "S-001.md", STORY.format(files=files, risk=f"risk: {risk}\n" if risk else ""))

    def brief(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(BRIEF), "S-001", *args], cwd=self.repo,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        return result

    def build(self, path="src/a.py", text="value = 2\n"):
        write(self.worktree / path, text)
        commit_all(self.worktree)
        return git(self.worktree, "rev-parse", "HEAD")

    def package(self, *args):
        reply = self.brief("--review", *args)
        return reply, pathlib.Path(reply["package"]).read_text(encoding="utf-8")

    def test_S_020_5_the_package_names_the_diff_the_dod_the_findings_files_and_the_template(self):
        self.story()
        self.brief()
        head = self.build()
        reply, text = self.package()
        self.assertEqual(reply["head"], head)
        self.assertIs(reply["risky"], False)
        diff = pathlib.Path(reply["diff"])
        self.assertIn("+value = 2", diff.read_text(encoding="utf-8"))
        self.assertIn(str(diff), text)
        self.assertIn("S-001/1 WHEN a user asks for a reset", text)
        self.assertIn(str(self.accio / "run" / "S-001" / "<reviewer>-findings.md"), text)
        self.assertIn(str(ROOT / "references" / "findings-template.md"), text)
        self.assertIn("Checklists: none", text)
        self.assertNotIn("fix round", text.lower())

    def test_S_020_5_a_diff_that_touches_a_risky_path_is_risky_and_gets_the_security_checklist(self):
        self.story(files="src/a.py, src/auth/login.py")
        self.brief()
        self.build("src/auth/login.py", "ok = True\n")
        reply, text = self.package()
        self.assertIs(reply["risky"], True)
        self.assertIn("src/auth/login.py", text)
        self.assertIn(str(ROOT / "references" / "checklists" / "auth-and-security.md"), text)

    def test_S_020_5_a_risk_word_picks_its_checklist_and_only_security_words_call_auror(self):
        for risk, risky, checklist in (("auth", True, "auth-and-security.md"), ("performance", False, "performance.md"),
                                       ("author-notes", False, None)):
            with self.subTest(risk):
                self.story(risk=risk)
                self.brief()
                self.build(text=f"value = '{risk}'\n")
                reply, text = self.package()
                self.assertIs(reply["risky"], risky)
                if checklist:
                    self.assertIn(str(ROOT / "references" / "checklists" / checklist), text)
                else:
                    self.assertIn("Checklists: none", text)

    def test_S_020_2_a_re_review_package_holds_only_the_fix_diff(self):
        self.story()
        self.brief()
        first = self.build()
        self.build("src/b.py", "fixed = True\n")
        reply, text = self.package("--since", first)
        diff = pathlib.Path(reply["diff"]).read_text(encoding="utf-8")
        self.assertIn("+fixed = True", diff)
        self.assertNotIn("value = 2", diff)
        self.assertIn("fix round", text.lower())
        self.assertIn(first[:12], text)

    def test_S_020_5_a_path_git_would_quote_is_still_matched_against_the_risky_globs(self):
        self.story(files='src/a.py, .github/workflows/')
        self.brief()
        self.build('.github/workflows/de"ploy\tci.yml', "on: push\n")
        reply, text = self.package()
        self.assertIs(reply["risky"], True)
        self.assertIn('- `.github/workflows/de"ploy\tci.yml`\n', text)

    def test_S_020_5_in_a_fix_round_risky_means_the_fix_diff_touches_a_risky_path(self):
        self.story(files="src/a.py, src/b.py, src/auth/login.py")
        self.brief()
        first = self.build("src/auth/login.py", "ok = True\n")
        second = self.build("src/b.py", "fixed = True\n")
        self.assertIs(self.package("--since", first)[0]["risky"], False)
        self.build("src/auth/login.py", "ok = False\n")
        self.assertIs(self.package("--since", second)[0]["risky"], True)

    def test_S_020_2_since_must_be_an_earlier_commit_of_the_story(self):
        self.story()
        self.brief()
        self.build()
        for since in ("nope", git(self.repo, "rev-parse", "HEAD~0") + "x", self.other_commit()):
            with self.subTest(since):
                result = self.brief("--review", "--since", since, check=False)
                self.assertEqual(result.returncode, 1)
                self.assertIn("--since", result.stderr)

    def test_S_020_2_since_cannot_reach_back_before_the_story(self):
        write(self.repo / "src" / "c.py", "c = 1\n")
        commit_all(self.repo)
        self.story()
        self.brief()
        before_story = git(self.repo, "rev-parse", "HEAD~1")
        self.build()
        result = self.brief("--review", "--since", before_story, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("--since", result.stderr)
        self.assertEqual(self.brief("--review", "--since", git(self.repo, "rev-parse", "main"))["risky"], False)

    def fix_review(self, branch="fix/login-typo", acceptance="- the typo is gone\n- nothing else changes\n"):
        """S-013: run `--review --fix-branch` on a branch with one commit off main; acceptance None = no file."""
        self.story()  # gives the repo its .accio/stories folder
        if git(self.repo, "branch", "--list", branch) == "" and branch != "nope":
            git(self.repo, "checkout", "-q", "-b", branch)
            write(self.repo / "src" / "a.py", "value = 3\n")
            git(self.repo, "add", "src")  # not .accio/, which belongs to no branch
            git(self.repo, "commit", "-q", "-m", "fix the typo")
            git(self.repo, "checkout", "-q", "main")
        path = self.base / "acceptance.md"
        path.unlink(missing_ok=True)
        if acceptance is not None:
            write(path, acceptance)
        return subprocess.run([sys.executable, "-I", str(BRIEF), "--review", "--fix-branch", branch,
                               "--acceptance", str(path)], cwd=self.repo, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, check=False)

    def test_S_013_1_a_branch_that_is_not_a_story_gets_a_review_package(self):
        result = self.fix_review()
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        self.assertEqual(reply["head"], git(self.repo, "rev-parse", "fix/login-typo"))
        self.assertTrue(pathlib.Path(reply["package"]).is_file())
        self.assertIn("+value = 3", pathlib.Path(reply["diff"]).read_text(encoding="utf-8"))

    def test_S_013_2_the_package_holds_the_diff_the_acceptance_list_and_three_findings_paths(self):
        reply = json.loads(self.fix_review().stdout)
        text = pathlib.Path(reply["package"]).read_text(encoding="utf-8")
        self.assertIn(reply["diff"], text)
        self.assertIn("## Acceptance list\n- the typo is gone", text)
        self.assertNotIn("Definition of Done", text)
        for who in ("professor", "auror", "examiner"):
            self.assertIn(str(self.accio / "run" / "fix-login-typo" / f"{who}-findings.md"), text)

    def test_S_013_3_a_missing_or_empty_acceptance_file_writes_nothing(self):
        for content in (None, "", "  \n"):
            with self.subTest(content):
                result = self.fix_review(acceptance=content)
                self.assertEqual(result.returncode, 1)
                self.assertIn("acceptance file", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertFalse((self.accio / "run").exists())

    def test_S_013_1_a_story_branch_or_unknown_branch_is_refused(self):
        git(self.repo, "branch", "story/S-009")
        for branch in ("story/S-009", "nope"):
            with self.subTest(branch):
                result = self.fix_review(branch)
                self.assertEqual(result.returncode, 1)
                self.assertIn("accio-brief:", result.stderr)

    def test_S_013_4_a_story_review_reads_as_before(self):
        self.story()
        self.brief()
        self.build()
        text = self.package()[1]
        self.assertIn("## Definition of Done\n- S-001/1", text)
        self.assertIn("the implementer's report:", text)
        self.assertIn("Write them to `", text)

    def test_a_git_failure_is_a_plain_error_not_a_traceback(self):
        self.story()
        self.brief()
        self.build()
        (self.accio / "run" / "S-001" / "base").unlink()
        lonely = git(self.repo, "commit-tree", git(self.repo, "rev-parse", "HEAD^{tree}"), "-m", "no shared history")
        git(self.repo, "branch", "lonely", lonely)  # a base the story shares no history with: merge-base fails
        write(self.accio / "config.json", json.dumps({"base_branch": "lonely"}))
        result = self.brief("--review", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("accio-brief:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertIn("where S-001's diff starts", result.stderr)

    def other_commit(self):
        write(self.repo / "src" / "other.py", "x = 1\n")
        commit_all(self.repo)
        return git(self.repo, "rev-parse", "HEAD")

    def test_review_needs_the_worktree_and_cannot_mix_with_fix(self):
        self.story()
        self.assertIn("doesn't exist", self.brief("--review", check=False).stderr)
        self.brief()
        result = self.brief("--review", "--fix", str(self.base / "f.md"), check=False)
        self.assertEqual(result.returncode, 2)

    def test_S_020_3_the_fix_brief_says_a_conflicting_finding_goes_back_as_NEEDS_CONTEXT(self):
        self.story()
        self.brief()
        findings = self.base / "examiner-findings.md"
        write(findings, "- id: examiner-1\n  claim: wants SMS too\n")
        text = pathlib.Path(self.brief("--fix", str(findings))["brief"]).read_text(encoding="utf-8")
        self.assertIn("conflicts with the story", text)
        self.assertIn("NEEDS_CONTEXT", text)


if __name__ == "__main__":
    unittest.main()
