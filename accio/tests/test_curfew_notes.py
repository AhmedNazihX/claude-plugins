"""S-076/3: curfew lets prefect write a READY story's brew-notes.md, the note brew asks it to keep for owl.md.

brew.js's outcome step has prefect write `.accio/run/<ID>/brew-notes.md` (a boggart or mad-eye skip, say), and
accio-summary shows it first under the story's Risks. These tests send that write through the real hook and check
look-alikes and other agents are still denied.
"""
from test_curfew import CurfewTestBase

PREFECT = "accio:prefect"
NOTES = "brew-notes.md"


class PrefectNotesTest(CurfewTestBase):
    def write(self, target):
        return {"file_path": str(target), "content": "boggart gave no answer\n"}

    def test_S_076_3_prefect_writes_a_storys_brew_notes(self):
        for story_id in ("S-001", "S-123"):
            with self.subTest(story_id=story_id):
                self.assert_allowed("Write", self.write(self.run_dir / story_id / NOTES), agent=PREFECT)

    def test_S_076_3_prefect_still_may_not_write_look_alikes(self):
        denied = (self.run_dir / NOTES, self.run_dir / "S-001" / "sub" / NOTES, self.run_dir / "S-x" / NOTES,
                  self.run_dir / "S-001" / f"{NOTES}.bak", self.run_dir / "S-001" / "notes.md",
                  self.run_dir / "wand" / NOTES, self.worktree / ".accio" / "run" / "S-001" / NOTES)
        for target in denied:
            with self.subTest(target=target):
                self.assert_denied("Write", self.write(target), "prefect", agent=PREFECT)

    def test_S_076_3_no_other_agent_writes_brew_notes(self):
        for agent in ("accio:boggart", "accio:mad-eye", "accio:headmaster", "accio:examiner", "accio:portkey"):
            with self.subTest(agent=agent):
                self.assertEqual(self.decision("Write", self.write(self.run_dir / "S-001" / NOTES), agent=agent)[0],
                                 "deny")
