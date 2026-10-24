"""S-071: curfew lets prefect write the mad-eye and boggart findings files brew.js asks it for.

brew.js has prefect write `.accio/run/<ID>/mad-eye-findings.md` (writeSeenFindings) and
`.accio/run/<ID>/boggart-findings.md` (writeBrokenFindings), since neither agent edits. These tests send those writes
through the real hook, as S-070's do, and check look-alikes are still denied.
"""
from test_curfew import CurfewTestBase

PREFECT = "accio:prefect"
FINDINGS = ("mad-eye-findings.md", "boggart-findings.md")


class PrefectFindingsTest(CurfewTestBase):
    def write_as_prefect(self, target):
        return {"file_path": str(target), "content": "- id: x\n"}

    def test_S_071_1_prefect_writes_a_storys_mad_eye_and_boggart_findings(self):
        for story_id in ("S-001", "S-123"):
            for name in FINDINGS:
                with self.subTest(story_id=story_id, name=name):
                    self.assert_allowed("Write", self.write_as_prefect(self.run_dir / story_id / name), agent=PREFECT)
                    self.assert_allowed("Edit", {"file_path": str(self.run_dir / story_id / name), "old_string": "a",
                                                 "new_string": "b"}, agent=PREFECT)

    def test_S_071_1_prefects_earlier_writes_still_work(self):
        for target in (self.run_dir / "S-001" / "ui-steps.txt", self.run_dir / "questions" / "S-001.md"):
            with self.subTest(target=target):
                self.assert_allowed("Write", self.write_as_prefect(target), agent=PREFECT)

    def test_S_071_1_prefect_still_may_not_write_other_paths(self):
        accio = self.repo / ".accio"
        denied = (self.run_dir / "S-001" / "examiner-findings.md", self.run_dir / "S-001" / "check-findings.md",
                  self.run_dir / "S-001" / "auror-findings.md", self.run_dir / "S-001" / "professor-findings.md",
                  self.run_dir / "S-001" / "mad-eye-findings.md.bak", self.run_dir / "S-001" / "mad-eye-findings.txt",
                  self.run_dir / "S-001" / "boggart" / "boggart-findings.md",
                  self.run_dir / "S-001" / "sub" / "mad-eye-findings.md", self.run_dir / "mad-eye-findings.md",
                  self.run_dir / "wand" / "mad-eye-findings.md", self.run_dir / "S-x" / "boggart-findings.md",
                  self.run_dir / "S-001" / "build-report.md", self.run_dir / "push-ok", accio / "config.json",
                  self.worktree / ".accio" / "run" / "S-001" / "mad-eye-findings.md", self.worktree / "a.py",
                  self.repo / "boggart-findings.md")
        for target in denied:
            with self.subTest(target=target):
                self.assert_denied("Write", self.write_as_prefect(target), "prefect", agent=PREFECT)

    def test_S_071_1_mad_eye_and_boggart_still_may_not_write_their_findings_themselves(self):
        for agent, name in (("accio:mad-eye", "mad-eye-findings.md"), ("accio:boggart", "boggart-findings.md")):
            with self.subTest(agent=agent):
                self.assert_denied("Write", self.write_as_prefect(self.run_dir / "S-001" / name), agent.split(":")[1],
                                   agent=agent)
