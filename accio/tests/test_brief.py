"""S-007: accio-brief (worktree and branch per story, rebase, brief and fix brief)."""
import json
import pathlib
import re
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

    def stacked_child(self):
        """S-001 with a commit of its own, then S-002 (deps: [S-001]) briefed on it, as brew does."""
        self.brief("S-001")
        write(self.wt_root / "S-001" / "src" / "parent.py", "x = 1\n")
        commit_all(self.wt_root / "S-001")
        write(self.accio / "stories" / "S-002.md", STORY.format(id="S-002", notes="", blocked="").replace(
            "status: ready\n", "status: ready\ndeps: [S-001]\n"))
        return self.brief("S-002", "--parent", "story/S-001")

    def pins(self, story_id):
        return (self.accio / "run" / story_id / "parent-heads").read_text(encoding="utf-8")

    def test_S_074_1_a_stacked_child_pins_its_parents_head_beside_its_base(self):
        reply = self.stacked_child()
        parent_head = self.head("story/S-001")
        self.assertEqual(self.pins("S-002"), f"S-001 {parent_head}\n")
        self.assertEqual((self.accio / "run" / "S-002" / "base").read_text(encoding="utf-8").strip(), parent_head)
        self.assertEqual(reply["base"], parent_head)
        log = (self.accio / "run" / "base-writes.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(log[-1], f"S-002 S-001 {parent_head}")

    def test_S_074_1_a_story_without_parents_pins_nothing_and_a_rebrief_drops_old_pins(self):
        self.brief("S-001")
        self.assertEqual(self.pins("S-001"), "")
        self.stacked_child()
        write(self.accio / "stories" / "S-002.md", STORY.format(id="S-002", notes="", blocked=""))  # no deps now
        self.brief("S-002")
        self.assertEqual(self.pins("S-002"), "")

    def test_S_074_1_a_dep_without_a_story_branch_is_not_pinned(self):
        write(self.accio / "stories" / "S-002.md", STORY.format(id="S-002", notes="", blocked="").replace(
            "status: ready\n", "status: ready\ndeps: [S-009]\n"))
        self.brief("S-002")
        self.assertEqual(self.pins("S-002"), "")

    def test_S_074_3_the_child_diffs_from_the_pinned_head_after_its_parent_is_amended(self):
        self.stacked_child()
        pinned = self.head("story/S-001")
        child = self.wt_root / "S-002"
        write(child / "src" / "new.py", "y = 2\n")
        commit_all(child, "child work")
        parent = self.wt_root / "S-001"
        write(parent / "src" / "parent.py", "x = 2\n")
        git(parent, "add", "-A")
        git(parent, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "--amend", "-m", "amended")
        from accio_lib import checks
        self.assertEqual(checks.diff_start(self.accio / "run" / "S-002", child, "main"), pinned)

    def test_S_016_1_each_base_write_is_logged_and_earlier_lines_kept(self):
        self.brief("S-001")
        self.add_story("S-002")
        self.brief("S-002")
        first = self.head("main")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        self.brief("S-001")
        log = (self.accio / "run" / "base-writes.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(log, [f"S-001 {first}", f"S-002 {first}", f"S-001 {self.head('main')}"])

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

    def conflict(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "a.py", "value = 2\n")
        commit_all(worktree, "story change")
        write(self.repo / "src" / "a.py", "value = 3\n")
        commit_all(self.repo, "main change")
        return worktree

    def rebasing(self, worktree):
        for name in ("rebase-merge", "rebase-apply"):
            if (worktree / git(worktree, "rev-parse", "--git-path", name)).exists():
                return True
        return False

    # S-022/1
    def test_S_022_1_a_conflicting_rerun_leaves_the_rebase_in_progress(self):
        worktree = self.conflict()
        self.brief("S-001")
        self.assertTrue(self.rebasing(worktree))
        self.assertIn("src/a.py", git(worktree, "diff", "--name-only", "--diff-filter=U"))

    def finish_rebase(self, worktree):
        write(worktree / "src" / "a.py", "value = 4\n")
        git(worktree, "add", "src/a.py")
        subprocess.run(["git", "-c", "core.editor=true", "rebase", "--continue"], cwd=worktree, check=True,
                       capture_output=True, text=True)

    def recorded(self):
        return (self.accio / "run" / "S-001" / "base").read_text(encoding="utf-8").strip()

    def diff_start(self, worktree):
        from accio_lib import checks
        return checks.diff_start(self.accio / "run" / "S-001", worktree, "main")

    def test_S_067_1_a_conflicted_rebase_records_the_new_base_and_logs_it(self):
        worktree = self.conflict()
        self.brief("S-001")
        self.assertTrue(self.rebasing(worktree))
        self.assertEqual(self.recorded(), self.head("main"))
        log = (self.accio / "run" / "base-writes.log").read_text(encoding="utf-8").splitlines()
        self.assertEqual(log[-1], f"S-001 {self.head('main')}")

    def test_S_067_2_after_the_conflict_is_resolved_the_diff_starts_at_the_new_base(self):
        worktree = self.conflict()
        self.brief("S-001")
        self.finish_rebase(worktree)
        self.assertEqual(self.diff_start(worktree), self.head("main"))
        changed = git(worktree, "diff", "--name-only", self.diff_start(worktree), "HEAD").splitlines()
        self.assertEqual(changed, ["src/a.py"])

    def test_S_067_3_an_aborted_conflicted_rebase_falls_back_to_the_merge_base(self):
        worktree = self.conflict()
        old_base = self.head("main~1")
        self.brief("S-001")
        git(worktree, "rebase", "--abort")
        self.assertEqual(self.diff_start(worktree), old_base)

    def test_S_067_4_a_rebase_already_in_progress_still_records_the_base_asked_for(self):
        worktree = self.conflict()
        self.brief("S-001")
        write(self.accio / "run" / "S-001" / "base", self.head("main~1") + "\n")
        self.brief("S-001")
        self.assertEqual(self.recorded(), self.head("main"))
        self.finish_rebase(worktree)
        self.assertEqual(self.diff_start(worktree), self.head("main"))

    def test_S_067_5_a_clean_rebase_records_the_new_base(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "new.py", "y = 2\n")
        commit_all(worktree, "story change")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        self.brief("S-001")
        self.assertEqual(self.recorded(), self.head("main"))

    # S-022/2
    def test_S_022_2_the_brief_names_the_conflicted_files_and_rebase_continue(self):
        self.conflict()
        text = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        self.assertIn("Rebase conflict", text)
        self.assertIn("src/a.py", text)
        self.assertIn(f"git -C {shlex.quote(str(self.wt_root / 'S-001'))} rebase --continue", text)

    # S-022/3
    def test_S_022_3_uncommitted_work_is_committed_as_a_checkpoint_before_the_rebase(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "wip.py", "z = 3\n")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        self.brief("S-001")
        self.assertEqual(git(worktree, "status", "--porcelain"), "")
        self.assertEqual(git(worktree, "merge-base", "HEAD", "main"), self.head("main"))
        self.assertTrue((worktree / "src" / "wip.py").is_file())
        self.assertIn("checkpoint", git(worktree, "log", "-1", "--format=%s"))

    # S-022/4
    def test_S_022_4_a_failed_rebase_without_a_conflict_blocks_with_one_question(self):
        self.brief("S-001")
        worktree = self.wt_root / "S-001"
        write(worktree / "src" / "new.py", "y = 2\n")
        commit_all(worktree, "story change")
        write(self.repo / "docs.md", "main moved\n")
        commit_all(self.repo, "main moves on")
        hook = worktree / git(worktree, "rev-parse", "--git-path", "hooks") / "pre-rebase"
        write(hook, "#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        result = self.brief("S-001", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("?", result.stderr)
        self.assertEqual(len(result.stderr.strip().splitlines()), 1)
        self.assertFalse(self.rebasing(worktree))

    # S-022/5
    def test_S_022_5_no_brief_text_names_a_rebase_command_curfew_denies(self):
        sys.path.insert(0, str(ROOT / "bin"))
        from accio_lib import bashpolicy
        self.conflict()
        texts = [pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8"),
                 pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")]  # 2nd: rebase in progress
        for text in texts:
            for command in re.findall(r"`([^`]*git [^`]*rebase[^`]*)`", text):
                rebase_args = shlex.split(command)
                rebase_args = rebase_args[rebase_args.index("rebase") + 1:]
                self.assertTrue(len(rebase_args) == 1 and rebase_args[0] in bashpolicy.REBASE_STEPS, command)

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

    def test_S_057_1_release_drops_the_storys_claim_and_leaves_the_brief_alone(self):
        claims = {"a1": {"story": "S-001", "worktree": "x"}, "a2": {"story": "S-002", "worktree": "y"}}
        write(self.accio / "run" / "claims.json", json.dumps(claims))
        reply = self.brief("S-001")  # the brief a first builder had
        write(self.accio / "run" / "claims.json", json.dumps(claims))
        before = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        released = self.brief("S-001", "--release")
        self.assertEqual(released, {"released": "S-001"})
        left = json.loads((self.accio / "run" / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(left), ["a2"])  # S-057/3: the other story's claim stays
        self.assertEqual(pathlib.Path(reply["brief"]).read_text(encoding="utf-8"), before)

    def test_S_057_2_the_end_of_a_build_leaves_no_claim(self):
        sys.path.insert(0, str(ROOT / "bin"))
        from accio_lib import runlock
        run = self.accio / "run"
        runlock.take(run)
        write(run / "claims.json", json.dumps({"a1": {"story": "S-001", "worktree": "x"}}))
        runlock.release(run)
        self.assertFalse((run / "claims.json").exists() and json.loads((run / "claims.json").read_text("utf-8")))

    def test_S_007_4_the_brief_holds_everything_the_implementer_needs(self):
        self.add_story("S-001", notes="The link must expire in 15 minutes, not 30.")
        reply = self.brief("S-001")
        text = pathlib.Path(reply["brief"]).read_text(encoding="utf-8")
        for expected in ("S-001/1 WHEN a user asks", "S-001/2 (no test)", "src/a.py", "src/new.py",
                         "Use the mailer in src/mail.py.", "python3 -m unittest", "`accio-board refresh`",
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

    def fix_text(self):
        self.brief("S-001")
        findings = self.accio / "run" / "S-001" / "findings-spec.md"
        write(findings, "- major, 90, src/a.py:1: the link never expires\n")
        return pathlib.Path(self.brief("S-001", "--fix", str(findings))["brief"]).read_text(encoding="utf-8")

    def test_S_082_1_the_brief_and_the_fix_brief_name_the_report_outside_the_main_checkout(self):
        report = self.wt_root / ".reports" / "S-001" / "build-report.md"
        story_brief = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        for text in (story_brief, self.fix_text()):
            with self.subTest(brief=text[:40]):
                self.assertIn(f"Write your report to `{report}`", text)
                self.assertNotIn(str(self.accio / "run" / "S-001" / "build-report.md"), text)

    def test_S_021_1_a_fix_brief_names_the_story_briefs_path(self):
        self.assertIn(str(self.accio / "run" / "S-001" / "brief.md"), self.fix_text())

    def test_S_021_2_a_fix_brief_lists_the_same_files_and_checks(self):
        story_brief = pathlib.Path(self.brief("S-001")["brief"]).read_text(encoding="utf-8")
        text = self.fix_text()
        for heading in ("## Files you may change (plus their tests)", "## Checks to run"):
            self.assertEqual(story_brief.split(heading, 1)[1].split("\n## ", 1)[0],
                             text.split(heading, 1)[1].split("\n## ", 1)[0])
        self.assertIn("python3 -m unittest", text)
        self.assertNotIn("npm test", text)

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

    def test_S_022_3_a_stacked_child_with_uncommitted_work_is_checkpointed_then_rebased_onto_the_new_parent(self):
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
        self.brief("S-002", "--parent", "story/S-001")
        self.assertEqual(git(child, "merge-base", "HEAD", "story/S-001"), self.head("story/S-001"))
        self.assertNotEqual(self.head("story/S-001"), old_parent)
        self.assertEqual(git(child, "log", "--format=%s", "story/S-001..HEAD").splitlines()[1:], ["c1"])

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
        self.conflict()
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
