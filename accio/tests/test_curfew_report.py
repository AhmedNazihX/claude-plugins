"""S-079: the reviewers (examiner, professor, auror, boggart) judge the code and the story, never house-elf's report.

curfew denies them a Read of any `build-report.md` under `.accio/run/`, and a Grep or Glob inside `.accio/run/`, for
files named `build-report`, or from above `.accio/run/` while git doesn't ignore it, with the reason; `~` and
relative paths count as the tool reads them (security review, 2026-10-25). Their package and findings files stay
readable, a Grep for the word `build-report` in the code is allowed, and house-elf, headmaster and prefect keep their
access to the report. Payloads go through the real hook, as the other curfew tests do.
"""
import os

from support import write
from test_curfew import CurfewTestBase

REVIEWERS = ("accio:examiner", "accio:professor", "accio:auror", "accio:boggart")
REASON = "builder's report"


class ReviewersNeverReadTheReportTest(CurfewTestBase):
    def setUp(self):
        super().setUp()
        self.story_run = self.run_dir / "S-001"
        self.report = self.story_run / "build-report.md"
        write(self.report, "## What changed\nall of it\n")
        write(self.story_run / "review-package.md", "# Review package\n")
        write(self.story_run / "review.diff", "+x\n")
        write(self.story_run / "examiner-findings.md", "- id: examiner-1\n")
        write(self.worktree / "a.py", "x = 1\n")

    def read(self, path):
        return {"file_path": str(path)}

    def test_S_079_2_a_reviewer_reading_a_build_report_is_denied_with_the_reason(self):
        link = self.repo / "link"
        os.symlink(self.story_run, link)
        reports = (self.report, self.run_dir / "S-123" / "build-report.md",
                   self.run_dir / "fix-login-typo" / "build-report.md", link / "build-report.md",
                   self.story_run / "boggart" / ".." / "build-report.md", self.story_run / "BUILD-REPORT.md",
                   self.repo / ".ACCIO" / "Run" / "S-001" / "build-report.md")
        for agent in REVIEWERS:
            for path in reports:
                with self.subTest(agent=agent, path=str(path)):
                    self.assert_denied("Read", self.read(path), REASON, "never", agent=agent)

    def test_S_079_2_a_reviewer_grepping_or_globbing_a_run_folder_or_for_build_report_is_denied(self):
        searches = (("Grep", {"pattern": "risk", "path": str(self.story_run)}),
                    ("Grep", {"pattern": "risk", "path": str(self.run_dir)}),
                    ("Grep", {"pattern": "risk", "path": str(self.report)}),
                    ("Grep", {"pattern": "risk", "path": str(self.story_run / "boggart" / "..")}),
                    ("Grep", {"pattern": "Risks", "glob": "**/Build-Report.md"}),
                    ("Glob", {"pattern": "*.md", "path": str(self.story_run)}),
                    ("Glob", {"pattern": "**/build-report.md"}),
                    ("Glob", {"pattern": f"{self.story_run}/*.md"}),
                    ("Glob", {"pattern": f"{self.run_dir}/S-*/b*.md"}))
        for agent in REVIEWERS:
            for tool, tool_input in searches:
                with self.subTest(agent=agent, tool=tool, tool_input=tool_input):
                    self.assert_denied(tool, tool_input, REASON, agent=agent)

    def test_S_079_2_a_home_or_relative_path_is_taken_as_the_tool_takes_it(self):
        home_run = "~/../app/.accio/run"  # the tests' HOME is a sibling of the repo
        cases = (("Read", {"file_path": f"{home_run}/S-001/build-report.md"}, None),
                 ("Grep", {"pattern": "risk", "path": home_run}, None),
                 ("Glob", {"pattern": f"{home_run}/S-*/*.md"}, None),
                 ("Read", {"file_path": ".accio/run/S-001/build-report.md"}, self.repo),
                 ("Grep", {"pattern": "risk", "path": ".accio/run"}, self.repo),
                 ("Grep", {"pattern": "risk", "path": "run/S-001"}, self.repo / ".accio"),
                 ("Glob", {"pattern": ".accio/run/S-*/*.md"}, self.repo),
                 ("Glob", {"pattern": "S-001/*.md", "path": "run"}, self.repo / ".accio"))
        for agent in REVIEWERS:
            for tool, tool_input, cwd in cases:
                with self.subTest(agent=agent, tool=tool, tool_input=tool_input):
                    self.assert_denied(tool, tool_input, REASON, agent=agent, cwd=cwd)

    def test_S_079_2_a_path_curfew_cant_resolve_is_denied(self):
        for agent in REVIEWERS:
            with self.subTest(agent=agent):
                self.assert_denied("Grep", {"pattern": "risk", "path": 5}, REASON, "can't resolve", agent=agent)

    def test_S_079_2_a_search_from_above_the_run_folder_needs_git_to_ignore_it(self):
        write(self.repo / ".gitignore", "")  # git no longer ignores .accio/run/, so a root search would reach it
        for agent in REVIEWERS:
            for tool_input in ({"pattern": "risk"}, {"pattern": "risk", "path": str(self.repo)},
                               {"pattern": "risk", "path": str(self.repo / ".accio")}):
                with self.subTest(agent=agent, tool_input=tool_input):
                    self.assert_denied("Grep", tool_input, REASON, "doesn't ignore", agent=agent)
            with self.subTest(agent=agent, tool="worktree"):
                self.assert_allowed("Grep", {"pattern": "risk", "path": str(self.worktree)}, agent=agent)

    def test_S_079_3_a_reviewer_may_search_the_code_for_the_word_build_report(self):
        for agent in REVIEWERS:
            for tool_input in ({"pattern": "build-report"}, {"pattern": "build-report", "path": str(self.worktree)}):
                with self.subTest(agent=agent, tool_input=tool_input):
                    self.assert_allowed("Grep", tool_input, agent=agent)

    def test_S_079_3_a_reviewer_still_reads_its_package_findings_diff_and_the_code(self):
        for agent in REVIEWERS:
            for name in ("review-package.md", "review.diff", "examiner-findings.md"):
                with self.subTest(agent=agent, name=name):
                    self.assert_allowed("Read", self.read(self.story_run / name), agent=agent)
            with self.subTest(agent=agent, tool="search"):
                self.assert_allowed("Read", self.read(self.worktree / "a.py"), agent=agent)
                self.assert_allowed("Read", self.read(self.repo / ".accio" / "stories" / "S-001.md"), agent=agent)
                self.assert_allowed("Grep", {"pattern": "x", "path": str(self.worktree)}, agent=agent)
                self.assert_allowed("Glob", {"pattern": "**/*.py", "path": str(self.worktree)}, agent=agent)
                self.assert_allowed("Grep", {"pattern": "x"}, agent=agent)

    def test_S_079_3_house_elf_headmaster_and_prefect_keep_their_access_to_the_report(self):
        self.claim()
        for agent in ("accio:house-elf", "accio:headmaster", "accio:prefect"):
            with self.subTest(agent=agent):
                self.assert_allowed("Read", self.read(self.report), agent=agent)
                self.assert_allowed("Grep", {"pattern": "risk", "path": str(self.story_run)}, agent=agent)
                self.assert_allowed("Glob", {"pattern": "**/build-report.md"}, agent=agent)
        self.assert_allowed("Read", self.read(self.report), agent="accio:house-elf", agent_id="unclaimed")
