"""S-010: accio-summary (run/owl.md: what changed, how to try it, risks, cost; questions; stacking)."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, init_repo, write

from accio_lib import brief, paths, story, summary

SUMMARY = ROOT / "bin" / "accio-summary"
REPORT = """# Report S-001
## What changed
Added a reset link email and a 30-minute expiry.
## How to try it
Run the app, click "Forgot password" and check the mail log.
## Risks
Mail sending fails silently if SMTP is down.
## Notes
Long notes that the summary must leave out.
"""


def story_text(story_id, deps=(), title=None, extra=""):
    dep_line = f"deps: [{', '.join(deps)}]\n" if deps else ""
    return (f"---\nid: {story_id}\ntitle: {title or 'Story ' + story_id}\ntrack: story\nstatus: ready\n{dep_line}"
            f"{extra}---\n## Definition of Done\n- [ ] {story_id}/1 WHEN x THE SYSTEM SHALL y\n")


def agent(run_dir, agent_id, label, output_tokens):
    write(run_dir / f"agent-{agent_id}.meta.json", json.dumps({"description": label}))
    line = {"type": "assistant", "message": {"id": f"m-{agent_id}", "usage": {"output_tokens": output_tokens}}}
    write(run_dir / f"agent-{agent_id}.jsonl", json.dumps(line) + "\n")


class SummaryBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        self.accio = self.repo / ".accio"
        self.transcripts = pathlib.Path(self.tmp.name) / "wf_1"
        self.add("S-001", "review")
        self.add("S-002", "blocked")
        self.add("S-003", "review", deps=("S-001",))
        self.add("S-004", "done")
        self.write_report("S-001", REPORT)
        write(self.accio / "run" / "questions" / "S-002.md", "Should the link expire after 15 or 30 minutes?\n")
        agent(self.transcripts, "a1", "S-001 implement", 212_000)
        agent(self.transcripts, "a2", "S-003 implement", 90_000)

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, story_id, status, deps=(), title=None, extra=""):
        write(self.accio / "stories" / f"{story_id}.md", story_text(story_id, deps, title, extra))
        overrides_path = self.accio / "run" / "status.json"
        overrides = json.loads(overrides_path.read_text()) if overrides_path.exists() else {}
        write(overrides_path, json.dumps({**overrides, story_id: status}))

    def call(self, *args):
        return subprocess.run([sys.executable, "-I", str(SUMMARY), *args],
                              cwd=self.repo, capture_output=True, text=True, check=False)

    def run_summary(self):
        result = self.call("--run", str(self.transcripts))
        self.assertEqual(result.returncode, 0, result.stderr)
        return (self.accio / "run" / "owl.md").read_text(encoding="utf-8")

    def block(self, text, story_id):
        """One story's whole block, heading included (blocks are separated by a blank line)."""
        return f"### {story_id} " + text.split(f"### {story_id} ", 1)[1].split("\n\n", 1)[0]

    def write_report(self, story_id, text):
        write(paths.report_path(self.repo, story_id), text)


class SummaryTest(SummaryBase):
    def test_S_082_3_the_summary_quotes_the_report_from_beside_the_worktrees(self):
        self.assertEqual(paths.report_path(self.repo, "S-001"),
                         self.repo.parent / ".app-accio-wt" / ".reports" / "S-001" / "build-report.md")
        self.assertIn("Added a reset link email", self.block(self.run_summary(), "S-001"))

    def test_S_082_3_an_older_build_s_report_in_the_run_folder_is_quoted_when_only_it_exists(self):
        write(self.accio / "run" / "S-003" / "build-report.md", "## What changed\nAn older build's change.\n")
        self.assertIn("Changed: An older build's change.", self.block(self.run_summary(), "S-003"))

    def test_S_082_3_the_new_report_wins_over_an_old_one(self):
        write(self.accio / "run" / "S-001" / "build-report.md", "## What changed\nA stale change.\n")
        part = self.block(self.run_summary(), "S-001")
        self.assertIn("Added a reset link email", part)
        self.assertNotIn("A stale change", part)

    def test_S_010_1_each_ready_story_gets_change_try_risk_and_cost(self):
        part = self.block(self.run_summary(), "S-001")
        for expected in ("Added a reset link email", "Forgot password", "SMTP is down", "212k tokens"):
            self.assertIn(expected, part)
        self.assertNotIn("Long notes", part)

    def test_S_010_1_a_missing_report_says_so(self):
        self.assertIn("no report written", self.block(self.run_summary(), "S-003"))

    def test_S_010_1_a_comment_in_a_code_block_does_not_end_the_section(self):
        self.write_report("S-001", REPORT.replace('Run the app, click "Forgot password" and check the mail log.',
                                                  "```bash\n# start the app\nmake run\n```\nThen open /forgot."))
        self.assertIn("Then open /forgot", self.block(self.run_summary(), "S-001"))

    def test_S_010_1_a_subsection_stays_inside_its_section(self):
        self.write_report("S-001", "## What changed\n### API\nNew endpoint.\n## Risks\nSMTP may fail.\n")
        part = self.block(self.run_summary(), "S-001")
        self.assertIn("Changed: API New endpoint.", part)
        self.assertIn("Risks: SMTP may fail.", part)

    def test_S_010_1_only_a_matching_fence_closes_a_code_block(self):
        nested = "````md\n```\n# not a heading\n```\n````"
        mixed = "```\n~~~\n# not a heading either\n```"
        for code in (nested, mixed):
            self.write_report("S-001", f"## How to try it\n{code}\nThen run it.\n## Risks\nSMTP may fail.\n")
            part = self.block(self.run_summary(), "S-001")
            self.assertIn("Then run it.", part, code)
            self.assertIn("Risks: SMTP may fail.", part, code)

    def test_report_headings_match_in_any_case_level_or_with_a_colon(self):
        self.write_report("S-001", "### what changed:\nA reset link.\n## HOW TO TRY IT\nClick it.\n"
                                   "## Risks:\nNone known.\n")
        part = self.block(self.run_summary(), "S-001")
        for expected in ("Changed: A reset link.", "Try it: Click it.", "Risks: None known."):
            self.assertIn(expected, part)

    def test_S_010_1_a_missing_risks_section_is_not_read_as_no_risks(self):
        self.write_report("S-001", "## What changed\nA reset link.\n")
        self.assertIn("Risks: (missing from the report)", self.block(self.run_summary(), "S-001"))

    def test_S_010_1_an_unreadable_report_says_unreadable_not_missing(self):
        paths.report_path(self.repo, "S-001").write_bytes(b"## What changed\n\xff\xfe bad bytes\n")
        part = self.block(self.run_summary(), "S-001")
        self.assertIn("report unreadable", part)
        self.assertNotIn("no report written", part)

    def test_S_010_2_a_blocked_story_shows_its_question(self):
        self.assertIn("15 or 30 minutes", self.block(self.run_summary(), "S-002"))

    def test_S_010_2_a_blank_question_file_says_no_question_was_recorded(self):
        write(self.accio / "run" / "questions" / "S-002.md", "\n  \n")
        self.assertIn("Question: (no question recorded)", self.block(self.run_summary(), "S-002"))

    def test_S_010_2_an_unreadable_question_file_says_so(self):
        (self.accio / "run" / "questions" / "S-002.md").write_bytes(b"\xff\xfe bad bytes\n")
        self.assertIn("Question: (question file unreadable)", self.block(self.run_summary(), "S-002"))

    def test_S_010_3_a_stacked_child_says_its_parent_must_be_accepted(self):
        self.assertIn("accept S-001 too", self.block(self.run_summary(), "S-003"))

    def test_S_010_3_a_parent_not_in_review_means_the_child_cant_be_accepted_yet(self):
        self.add("S-003", "review", deps=("S-001", "S-002", "S-004"))
        part = self.block(self.run_summary(), "S-003")
        self.assertIn("accept S-001 too", part)
        self.assertIn("can't be accepted yet: S-002 is blocked", part)
        self.assertNotIn("S-004", part.split("\n", 1)[1])

    def test_S_010_4_each_story_stays_within_150_tokens_however_long_its_parts(self):
        long_title = "A very long story title " * 10
        parents = [f"S-1{n:02d}" for n in range(6)]
        for parent in parents:
            self.add(parent, "review")
        self.add("S-001", "review", deps=parents, title=long_title)
        long_sections = (f"## {heading}\n{'word ' * 400}\n" for heading, _ in summary.REPORT_SECTIONS)
        self.write_report("S-001", "".join(long_sections))
        write(self.accio / "run" / "questions" / "S-002.md", "Which one? " * 200)
        text = self.run_summary()
        for story_id in ("S-001", "S-002", "S-003"):
            self.assertLessEqual(summary.estimate_tokens(self.block(text, story_id)), summary.STORY_TOKEN_TARGET)
        part = self.block(text, "S-001")
        self.assertIn("+4 more", part)
        for _, label in summary.REPORT_SECTIONS:
            self.assertIn(f"- {label}: word", part)

    def test_owl_shows_fresh_tokens_with_cache_reads_apart(self):
        self.assertEqual(summary._cost({"tokens": 2_400_000, "fresh": 300_000, "over": False}),
                         "300k tokens (+2100k cache reads)")
        self.assertEqual(summary._cost({"tokens": 212_000, "fresh": 212_000, "over": True}),
                         "212k tokens (over budget)")

    def test_the_story_budget_decides_over_budget(self):
        self.add("S-001", "review", extra="budget_tokens: 100000\n")
        self.assertIn("212k tokens (over budget)", self.block(self.run_summary(), "S-001"))

    def test_transcripts_are_required(self):
        self.assertEqual(self.call().returncode, 2)

    def test_done_stories_are_left_out_and_unknown_cost_is_said(self):
        text = self.run_summary()
        self.assertNotIn("### S-004", text)
        self.assertIn("cost unknown", self.block(text, "S-002"))

    def test_both_briefs_ask_for_every_section_the_summary_reads(self):
        parsed = story.parse(self.accio / "stories" / "S-001.md")
        worktree = pathlib.Path(self.tmp.name) / "wt"
        rendered = {"brief": brief.render_brief(parsed, self.accio, worktree, "0" * 40, [], [], []),
                    "fix brief": brief.render_fix(parsed, self.accio, worktree, ["- a finding"])}
        for name, text in rendered.items():
            for heading, _ in summary.REPORT_SECTIONS:
                self.assertIn(f"`## {heading}`", text, name)

    def test_the_summary_ends_with_the_one_batch_answer(self):
        self.assertIn("accept, reject or drop", self.run_summary())


class BuildNotesTest(SummaryBase):
    """S-076/3: a note brew left for a READY story (boggart's or mad-eye's) shows first under its Risks."""
    def write_note(self, story_id, text):
        write(self.accio / "run" / story_id / summary.NOTES_NAME, text)

    def risks(self, story_id):
        part = self.block(self.run_summary(), story_id)
        return next(line for line in part.splitlines() if line.startswith("- Risks:"))

    def test_S_076_3_a_boggart_note_shows_first_under_risks(self):
        self.write_note("S-001", "boggart: 1 break outside the DoD, logged for owl\n")
        line = self.risks("S-001")
        self.assertTrue(line.startswith("- Risks: Build note: boggart: 1 break outside the DoD, logged for owl."), line)
        self.assertIn("SMTP is down", line)

    def test_S_076_3_a_mad_eye_skip_note_shows_under_risks(self):
        self.write_note("S-001", "mad-eye skipped: the preview did not start (port in use)")
        self.assertIn("Build note: mad-eye skipped: the preview did not start (port in use).", self.risks("S-001"))

    def test_S_076_3_a_story_without_a_report_still_shows_its_note(self):
        self.write_note("S-003", "boggart gave no answer")
        part = self.block(self.run_summary(), "S-003")
        self.assertIn("no report written", part)
        self.assertIn("- Risks: Build note: boggart gave no answer.", part)

    def test_S_076_3_no_note_leaves_risks_as_the_report_says(self):
        self.assertEqual(self.risks("S-001"), "- Risks: Mail sending fails silently if SMTP is down.")
        self.write_note("S-001", "  \n")
        self.assertEqual(self.risks("S-001"), "- Risks: Mail sending fails silently if SMTP is down.")

    def test_S_076_3_a_long_note_keeps_the_story_within_its_token_target(self):
        self.write_note("S-001", "mad-eye skipped: " + "word " * 400)
        part = self.block(self.run_summary(), "S-001")
        self.assertLessEqual(summary.estimate_tokens(part), summary.STORY_TOKEN_TARGET)
        self.assertIn("- Risks: Build note: mad-eye skipped: word", part)

    def test_S_076_3_an_unreadable_note_says_so_rather_than_vanishing(self):
        note = self.accio / "run" / "S-001" / summary.NOTES_NAME
        note.parent.mkdir(parents=True, exist_ok=True)  # the report no longer makes this folder (S-082)
        note.write_bytes(b"\xff\xfe bad bytes\n")
        self.assertIn(f"Build note: ({summary.NOTES_NAME} unreadable).", self.risks("S-001"))

    def test_S_076_3_a_blocked_story_shows_no_note(self):
        self.write_note("S-002", "boggart gave no answer")
        self.assertNotIn("Build note", self.block(self.run_summary(), "S-002"))


if __name__ == "__main__":
    unittest.main()
