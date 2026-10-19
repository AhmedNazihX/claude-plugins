"""S-007: accio-brief (worktree and branch per story, rebase, brief and fix brief)."""
import json
import pathlib
import shlex
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

BRIEF = ROOT / "bin" / "accio-brief"

STORY = """---
id: {id}
title: Reset email
track: story
status: ready
files: [src/a.py, src/new.py]
---
## Context
Users forget passwords.
## Reuse
Use the mailer in src/mail.py.
## Definition of Done
- [ ] {id}/1 WHEN a user asks for a reset THE SYSTEM SHALL email a link
- [ ] {id}/2 (no test) checks pass
## Review notes
{notes}
## Blocked question
{blocked}
"""


class BriefTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.tmp.name).resolve()
        self.repo = init_repo(self.base / "app")
        write(self.repo / "src" / "a.py", "value = 1\n")
        commit_all(self.repo)
        self.accio = self.repo / ".accio"
        write(self.accio / "config.json", json.dumps({"checks": [
            {"command": "python3 -m unittest", "glob": "**/*.py"}, {"command": "npm test", "glob": "web/**"}]}))
        self.add_story("S-001")
        self.wt_root = self.base / ".app-accio-wt"

    def tearDown(self):
        self.tmp.cleanup()

    def add_story(self, story_id, notes="", blocked=""):
        write(self.accio / "stories" / f"{story_id}.md", STORY.format(id=story_id, notes=notes, blocked=blocked))

    def brief(self, *args, check=True):
        result = subprocess.run([sys.executable, "-I", str(BRIEF), *args], cwd=self.repo,
                                capture_output=True, text=True, check=False)
        if check:
            self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if check else result

    def head(self, rev, cwd=None):
        return git(cwd or self.repo, "rev-parse", rev)

    # S-007/1
    def test_S_007_1_creates_the_worktree_and_branch_from_base(self):
        reply = self.brief("S-001")
        worktree = self.wt_root / "S-001"
        self.assertEqual(pathlib.Path(reply["worktree"]), worktree)
        self.assertEqual(self.head("story/S-001"), self.head("main"))
        self.assertEqual(git(worktree, "branch", "--show-current"), "story/S-001")
        self.assertEqual(reply["base"], self.head("main"))
        self.assertTrue(pathlib.Path(reply["brief"]).is_file())

    def test_S_007_1_a_stacked_child_starts_from_its_parent_head(self):
        self.brief("S-001")
        write(self.wt_root / "S-001" / "src" / "parent.py", "x = 1\n")
        commit_all(self.wt_root / "S-001")
        self.add_story("S-002")
        reply = self.brief("S-002", "--parent", "story/S-001")
        self.assertEqual(self.head("story/S-002"), self.head("story/S-001"))
        self.assertEqual(reply["base"], self.head("story/S-001"))

    # S-007/2
    def test_S_007_2_reuses_the_branch_and_rebases_it_on_base(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "new.py", "y = 2\n")
        commit_all(worktree, "checkpoint")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        reply = self.brief("S-001")
        self.assertEqual(git(worktree, "merge-base", "HEAD", "main"), self.head("main"))
        self.assertEqual(git(worktree, "log", "-1", "--format=%s"), "checkpoint")
        self.assertEqual(reply["base"], self.head("main"))

    def test_S_007_2_a_kept_branch_without_a_worktree_gets_one_again(self):
        self.brief("S-001")
        git(self.repo, "worktree", "remove", str(self.wt_root / "S-001"))
        self.brief("S-001")
        self.assertEqual(git(self.wt_root / "S-001", "branch", "--show-current"), "story/S-001")

    # S-007/3
    def test_S_007_3_a_rebase_conflict_goes_into_the_brief(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "a.py", "value = 2\n")
        commit_all(worktree, "story change")
        write(self.repo / "src" / "a.py", "value = 3\n")
        commit_all(self.repo, "main change")
        before = self.head("story/S-001")
        reply = self.brief("S-001")
        text = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        self.assertIn("Rebase conflict", text)
        self.assertIn("src/a.py", text)
        self.assertEqual(self.head("story/S-001"), before)
        self.assertNotIn("rebase", git(worktree, "status").lower().split("\n")[0])

    def test_uncommitted_work_is_never_rebased_away(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "wip.py", "z = 3\n")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        reply = self.brief("S-001")
        self.assertTrue((worktree / "src" / "wip.py").is_file())
        self.assertIn("uncommitted", pathlib.Path(reply["brief"]).read_text(encoding="utf-8"))

    # S-007/4
    def test_S_017_4_a_new_brief_clears_the_main_snapshot_but_a_fix_brief_keeps_it(self):
        snapshot = self.accio / "run" / "S-001" / "main-snapshot.json"
        self.brief("S-001")
        write(snapshot, "{}\n")
        findings = self.base / "findings.md"
        write(findings, "- major: x\n")
        self.brief("S-001", "--fix", str(findings))
        self.assertTrue(snapshot.exists())
        self.brief("S-001")
        self.assertFalse(snapshot.exists())

    def test_S_015_3_a_new_brief_releases_the_storys_claim(self):
        claims = {"a1": {"story": "S-001", "worktree": "x"}, "a2": {"story": "S-002", "worktree": "y"}}
        write(self.accio / "run" / "claims.json", json.dumps(claims))
        self.brief("S-001")
        left = json.loads((self.accio / "run" / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(left), ["a2"])

    def test_S_007_4_the_brief_holds_everything_the_implementer_needs(self):
        self.add_story("S-001", notes="The link must expire in 15 minutes, not 30.")
        reply = self.brief("S-001")
        text = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        for expected in ("S-001/1 WHEN a user asks", "S-001/2 (no test)", "src/a.py", "src/new.py",
                         "Use the mailer in src/mail.py.", "python3 -m unittest", str(ROOT / "bin" / "accio-board"),
                         "15 minutes, not 30", str(self.wt_root / "S-001")):
            self.assertIn(expected, text)
        self.assertNotIn("npm test", text)

    def test_the_brief_carries_the_storys_context(self):
        text = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        context = text.split("## Context", 1)[1].split("\n## ", 1)[0]
        self.assertIn("Users forget passwords.", context)

    def test_an_answered_blocked_question_reaches_the_brief(self):
        self.add_story("S-001", blocked="Should the link expire?\n\nAnswer: Yes, after 15 minutes.")
        text = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        self.assertIn("Should the link expire?", text)
        self.assertIn("Answer: Yes, after 15 minutes.", text)

    def test_S_007_4_existing_files_are_listed_as_code_to_reuse(self):
        reply = self.brief("S-001")
        text = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        reuse = text.split("## Existing code to reuse", 1)[1].split("\n## ", 1)[0]
        self.assertIn("src/a.py", reuse)
        self.assertNotIn("src/new.py", reuse)

    # S-007/5
    def test_S_007_5_a_fix_brief_lists_only_the_findings(self):
        self.brief("S-001")
        findings = self.accio / "run" / "S-001" / "findings-spec.md"
        write(findings, "- major, 90, src/a.py:1: the link never expires\n")
        reply = self.brief("S-001", "--fix", str(findings))
        text = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        self.assertTrue(reply["brief"].endswith("fix-brief.md"))
        self.assertIn("the link never expires", text)
        self.assertIn(str(self.wt_root / "S-001"), text)
        self.assertNotIn("Use the mailer", text)
        self.assertNotIn("S-001/1 WHEN", text)

    def earlier_text(self, **story_args):
        if story_args:
            self.add_story("S-001", **story_args)
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "new.py", "y = 2\n")
        commit_all(worktree, "old unreviewed work")
        return pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")

    # S-012/1
    def test_S_012_1_commits_past_the_base_are_listed(self):
        text = self.earlier_text()
        section = text.split("## Your earlier work", 1)[1].split("\n## ", 1)[0]
        self.assertIn("old unreviewed work", section)
        self.assertIn(self.head("story/S-001")[:7], section)

    # S-012/2
    def test_S_012_2_the_section_says_the_commits_were_not_accepted(self):
        text = self.earlier_text()
        section = text.split("## Your earlier work", 1)[1].split("\n## ", 1)[0]
        self.assertIn("not accepted", section)

    # S-012/3
    def test_S_012_3_review_notes_and_the_answer_sit_beside_the_section(self):
        text = self.earlier_text(notes="The link must expire.", blocked="Expire?\n\nAnswer: Yes.")
        section = text.split("## Your earlier work", 1)[1].split("\n## Definition of Done", 1)[0]
        self.assertIn("The link must expire.", section)
        self.assertIn("Answer: Yes.", section)

    # S-012/4
    def test_S_012_4_no_commits_past_the_base_leaves_the_section_out(self):
        self.brief("S-001")
        text = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        self.assertNotIn("Your earlier work", text)

    def test_S_012_4_a_missing_worktree_leaves_the_section_out(self):
        sys.path.insert(0, str(ROOT / "bin"))
        from accio_lib import brief
        self.assertEqual(brief.earlier_commits(self.base / "nowhere", "0" * 40, None), ())

    def test_a_rebase_already_in_progress_is_left_alone(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "a.py", "value = 2\n")
        commit_all(worktree, "story change")
        write(self.repo / "src" / "a.py", "value = 3\n")
        commit_all(self.repo, "main change")
        subprocess.run(["git", "rebase", "main"], cwd=worktree, capture_output=True, check=False)
        write(worktree / "src" / "a.py", "value = 23\n")
        commit_all(worktree, "resolved by hand")
        resolved = self.head("HEAD", cwd=worktree)
        write(self.repo / "docs.md", "main moves again\n")
        commit_all(self.repo, "main again")
        reply = self.brief("S-001")
        self.assertEqual(self.head("HEAD", cwd=worktree), resolved)
        self.assertTrue(pathlib.Path(git(worktree, "rev-parse", "--git-path", "rebase-merge")).exists()
                        or pathlib.Path(git(worktree, "rev-parse", "--git-path", "rebase-apply")).exists())
        self.assertIn("rebase in progress", pathlib.Path(reply["brief"]).read_text(encoding="utf-8"))

    def test_a_stacked_child_follows_a_rewritten_parent_without_replaying_old_commits(self):
        self.brief("S-001")
        parent = self.wt_root / "S-001"
        write(parent / "src" / "p.py", "p = 1\n")
        commit_all(parent, "p1")
        self.add_story("S-002")
        self.brief("S-002", "--parent", "story/S-001")
        child = self.wt_root / "S-002"
        write(child / "src" / "c.py", "c = 1\n")
        commit_all(child, "c1")
        write(parent / "src" / "p.py", "p = 2\n")
        git(parent, "add", "-A")
        git(parent, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--amend", "-m", "p1 amended")
        reply = self.brief("S-002", "--parent", "story/S-001")
        self.assertNotIn("Rebase conflict", pathlib.Path(reply["brief"]).read_text(encoding="utf-8"))
        self.assertEqual(git(child, "log", "--format=%s", "main..HEAD").splitlines(), ["c1", "p1 amended"])

    def test_a_stacked_child_with_uncommitted_work_is_told_the_onto_command(self):
        self.brief("S-001")
        parent = self.wt_root / "S-001"
        write(parent / "src" / "p.py", "p = 1\n")
        commit_all(parent, "p1")
        self.add_story("S-002")
        self.brief("S-002", "--parent", "story/S-001")
        child = self.wt_root / "S-002"
        write(child / "src" / "c.py", "c = 1\n")
        commit_all(child, "c1")
        old_parent = self.head("story/S-001")
        write(parent / "src" / "p.py", "p = 2\n")
        git(parent, "add", "-A")
        git(parent, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--amend", "-m", "p1 amended")
        write(child / "src" / "wip.py", "w = 1\n")
        text = pathlib.Path(self.brief("S-002", "--parent", "story/S-001")["brief"]).read_text(encoding="utf-8")
        self.assertIn(f"rebase --onto {self.head('story/S-001')} {old_parent}", text)

    def test_a_worktree_folder_deleted_by_hand_is_recreated(self):
        self.brief("S-001")
        import shutil
        shutil.rmtree(self.wt_root / "S-001")
        self.brief("S-001")
        self.assertEqual(git(self.wt_root / "S-001", "branch", "--show-current"), "story/S-001")

    def test_a_folder_in_files_keeps_every_check(self):
        write(self.accio / "stories" / "S-003.md", STORY.format(id="S-003", notes="", blocked="").replace(
            "files: [src/a.py, src/new.py]", "files: [web/, src/a.py]"))
        text = pathlib.Path(self.brief("S-003")["brief"]).read_text(encoding="utf-8")
        self.assertIn("npm test", text)
        self.assertIn("python3 -m unittest", text)

    def test_paths_in_commands_are_shell_quoted(self):
        spaced = pathlib.Path(self.tmp.name).resolve() / "My Projects"
        repo = init_repo(spaced / "app")
        write(repo / ".accio" / "stories" / "S-001.md", STORY.format(id="S-001", notes="", blocked=""))
        result = subprocess.run([sys.executable, "-I", str(BRIEF), "S-001"], cwd=repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        reply = json.loads(result.stdout)
        text = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        self.assertIn(f"cd {shlex.quote(reply['worktree'])} &&", text)

    def test_notes_come_before_the_story_details(self):
        self.brief("S-001")
        write(self.wt_root / "S-001" / "src" / "wip.py", "z = 3\n")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        text = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        self.assertLess(text.index("Before you start"), text.index("## Definition of Done"))

    def test_bad_or_mismatched_ids_are_refused(self):
        for bad in ("../stories/S-001", "/tmp/S-001", "S-1"):
            result = self.brief(bad, "--fix", "x", check=False)
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertNotIn("Traceback", result.stderr)
        write(self.accio / "stories" / "S-005.md", STORY.format(id="S-006", notes="", blocked=""))
        self.assertIn("S-006", self.brief("S-005", check=False).stderr)

    def test_a_fix_brief_needs_the_worktree(self):
        findings = self.accio / "run" / "S-001" / "findings.md"
        write(findings, "- a finding\n")
        result = self.brief("S-001", "--fix", str(findings), check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("worktree", result.stderr)

    def test_unknown_story_is_a_plain_error(self):
        result = self.brief("S-404", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("S-404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_an_unknown_parent_is_a_plain_error(self):
        result = self.brief("S-001", "--parent", "story/S-404", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("story/S-404", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
