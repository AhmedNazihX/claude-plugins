"""S-079, S-082: the reviewers (examiner, professor, auror, boggart) judge the code and the story, never house-elf's
report.

house-elf writes its report to `<worktree root>/.reports/<ID>/build-report.md`, beside the story worktrees and outside
the main checkout, so no reviewer's search of the main checkout or the worktree passes over it (S-082). curfew denies
the reviewers a Read, Grep or Glob inside that `.reports/` folder, and a Grep or Glob from a folder that holds it, with
the reason; `~` and relative paths count as the tool reads them, and a path curfew can't resolve is denied. A Read of
an older build's `.accio/run/<ID>/build-report.md` stays denied. Any file pattern is fine in the main checkout and the
worktree. Their package and findings files stay readable, a Grep for the word `build-report` in the code is allowed,
and house-elf, headmaster and prefect keep their access to the report. Payloads go through the real hook, as the
other curfew tests do.
"""
import os

from support import write
from test_curfew import CurfewTestBase

from accio_lib import paths

REVIEWERS = ("accio:examiner", "accio:professor", "accio:auror", "accio:boggart")
REASON = "builder's report"
ANY_FILE_PATTERN = ("*.md", "**/*.md", "build-re*", "*REPORT*", "*.{md,txt}", "!*.py", "**", "docs/**", "*.md *.py",
                    "*.md,*.py", "build\\-report.md", "[^x]uild-report.md", "[b]uild-report.md", "build-report.md")


class ReviewersNeverReadTheReportTest(CurfewTestBase):
    def setUp(self):
        super().setUp()
        self.story_run = self.run_dir / "S-001"
        self.wt_root = paths.worktree_root(self.repo)
        self.reports = paths.reports_dir(self.repo)
        self.report = paths.report_path(self.repo, "S-001")
        write(self.report, "## What changed\nall of it\n")
        write(self.story_run / "build-report.md", "## What changed\nan older build\n")
        write(self.story_run / "review-package.md", "# Review package\n")
        write(self.story_run / "review.diff", "+x\n")
        write(self.story_run / "examiner-findings.md", "- id: examiner-1\n")
        write(self.worktree / "a.py", "x = 1\n")

    def read(self, path):
        return {"file_path": str(path)}

    def assert_denied_for_reviewers(self, cases, *words):
        for agent in REVIEWERS:
            for tool, tool_input, cwd in cases:
                with self.subTest(agent=agent, tool=tool, tool_input=tool_input, cwd=cwd):
                    self.assert_denied(tool, tool_input, REASON, *words, agent=agent, cwd=cwd)

    def assert_allowed_for_reviewers(self, cases):
        for agent in REVIEWERS:
            for tool, tool_input, cwd in cases:
                with self.subTest(agent=agent, tool=tool, tool_input=tool_input, cwd=cwd):
                    self.assert_allowed(tool, tool_input, agent=agent, cwd=cwd)

    def test_S_082_4_a_reviewer_reading_a_file_in_the_reports_folder_is_denied_with_the_reason(self):
        link = self.repo / "link"
        os.symlink(self.reports / "S-001", link)
        reports = (self.report, paths.report_path(self.repo, "S-123"), self.reports / "S-001" / "notes.md",
                   link / "build-report.md", self.reports / "S-002" / ".." / "S-001" / "build-report.md",
                   self.wt_root / ".REPORTS" / "S-001" / "build-report.md")
        self.assert_denied_for_reviewers([("Read", self.read(path), None) for path in reports], "never")

    def test_S_082_4_a_reviewer_reading_an_older_builds_report_in_the_run_folder_is_denied(self):
        reports = (self.story_run / "build-report.md", self.run_dir / "S-123" / "build-report.md",
                   self.story_run / "BUILD-REPORT.md", self.repo / ".ACCIO" / "Run" / "S-001" / "build-report.md")
        self.assert_denied_for_reviewers([("Read", self.read(path), None) for path in reports], "never")

    def test_S_082_4_a_search_inside_the_reports_folder_or_from_a_folder_that_holds_it_is_denied(self):
        searches = (("Grep", {"pattern": "risk", "path": str(self.reports)}),
                    ("Grep", {"pattern": "risk", "path": str(self.reports / "S-001")}),
                    ("Grep", {"pattern": "risk", "path": str(self.report)}),
                    ("Grep", {"pattern": "risk", "path": str(self.story_run / "build-report.md")}),
                    ("Grep", {"pattern": "risk", "path": str(self.wt_root)}),
                    ("Grep", {"pattern": "risk", "path": str(self.repo.parent)}),
                    ("Grep", {"pattern": "risk", "path": "/"}),
                    ("Grep", {"pattern": "risk", "path": str(self.worktree / "..")}),
                    ("Glob", {"pattern": "*.md", "path": str(self.reports / "S-001")}),
                    ("Glob", {"pattern": "**/*.md", "path": str(self.wt_root)}),
                    ("Glob", {"pattern": f"{self.reports}/*/*.md"}),
                    ("Glob", {"pattern": f"{self.wt_root}/**/*.md"}),
                    ("Glob", {"pattern": f"{self.repo.parent}/**/build-report.md"}))
        self.assert_denied_for_reviewers([(tool, tool_input, None) for tool, tool_input in searches])

    def test_S_082_4_a_home_or_relative_path_is_taken_as_the_tool_takes_it(self):
        home_wt = "~/../.app-accio-wt"  # the tests' HOME is a sibling of the repo and of its worktree folder
        cases = (("Read", {"file_path": f"{home_wt}/.reports/S-001/build-report.md"}, None),
                 ("Grep", {"pattern": "risk", "path": home_wt}, None),
                 ("Grep", {"pattern": "risk", "path": "~/.."}, None),
                 ("Glob", {"pattern": f"{home_wt}/.reports/*/*.md"}, None),
                 ("Read", {"file_path": "../.reports/S-001/build-report.md"}, self.worktree),
                 ("Grep", {"pattern": "risk", "path": ".."}, self.worktree),
                 ("Glob", {"pattern": "../.reports/**"}, self.worktree),
                 ("Glob", {"pattern": "../**/*.md"}, self.worktree),
                 ("Glob", {"pattern": "S-001/*.md", "path": "../.reports"}, self.worktree),
                 ("Grep", {"pattern": "risk", "path": ".."}, self.repo),
                 ("Read", {"file_path": ".accio/run/S-001/build-report.md"}, self.repo))
        self.assert_denied_for_reviewers(cases)

    def test_S_082_4_a_path_curfew_cant_resolve_is_denied(self):
        cases = (("Grep", {"pattern": "risk", "path": 5}, None), ("Glob", {"pattern": "*.md", "path": 5}, None),
                 ("Read", {"file_path": 5}, None),
                 # `..` past a wildcard or inside braces: fail closed
                 ("Glob", {"pattern": "*/../../.reports/*"}, self.worktree),
                 ("Glob", {"pattern": "{src,../..}/.reports/*"}, self.worktree))
        self.assert_denied_for_reviewers(cases, "can't resolve")

    def test_S_082_5_a_search_of_the_main_checkout_or_the_worktree_with_any_file_pattern_is_allowed(self):
        cases = []
        for folder in (None, str(self.repo), str(self.repo / ".accio"), str(self.worktree)):
            where = {"path": folder} if folder else {}
            cases += [("Grep", {"pattern": "risk", "glob": pattern, **where}, None) for pattern in ANY_FILE_PATTERN]
            cases += [("Glob", {"pattern": pattern, **where}, None) for pattern in ANY_FILE_PATTERN]
        cases += [("Grep", {"pattern": "risk"}, self.worktree), ("Glob", {"pattern": "**/*.md"}, self.worktree),
                  ("Glob", {"pattern": f"{self.repo}/**/*.md"}, None),
                  ("Glob", {"pattern": f"{self.worktree}/**/build-report.md"}, None)]
        self.assert_allowed_for_reviewers(cases)

    def test_S_082_5_it_no_longer_matters_whether_git_ignores_the_run_folder(self):
        write(self.repo / ".gitignore", "")
        self.assert_allowed_for_reviewers([("Grep", {"pattern": "risk"}, None),
                                           ("Grep", {"pattern": "risk", "glob": "*.md", "path": str(self.repo)}, None)])

    def test_S_079_3_a_reviewer_may_search_the_code_for_the_word_build_report(self):
        self.assert_allowed_for_reviewers([("Grep", {"pattern": "build-report"}, None),
                                           ("Grep", {"pattern": "build-report", "path": str(self.worktree)}, None)])

    def test_S_079_3_a_reviewer_still_reads_its_package_findings_diff_and_the_code(self):
        reads = [self.story_run / name for name in ("review-package.md", "review.diff", "examiner-findings.md")]
        reads += [self.worktree / "a.py", self.repo / ".accio" / "stories" / "S-001.md"]
        self.assert_allowed_for_reviewers([("Read", self.read(path), None) for path in reads])

    def test_S_079_3_S_082_2_house_elf_headmaster_and_prefect_keep_their_access_to_the_report(self):
        self.claim()
        for agent in ("accio:house-elf", "accio:headmaster", "accio:prefect"):
            with self.subTest(agent=agent):
                self.assert_allowed("Read", self.read(self.report), agent=agent)
                self.assert_allowed("Grep", {"pattern": "risk", "path": str(self.reports)}, agent=agent)
                self.assert_allowed("Glob", {"pattern": f"{self.reports}/**/build-report.md"}, agent=agent)
        self.assert_allowed("Read", self.read(self.report), agent="accio:house-elf", agent_id="unclaimed")
