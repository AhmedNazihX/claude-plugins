"""S-007: how wand, sort, prophecy and owl end. A text check of each SKILL.md: when /accio is driving the step ends
"next: <step> (accio carries on)"; run alone it keeps its "/accio:X" ending."""
import unittest

from support import ROOT

NEXT_STEP = {"wand": "sort", "sort": "prophecy", "prophecy": "brew", "owl": "prophecy"}
DRIVING = "the `accio` conductor skill was loaded earlier in this chat and has not finished"


def flat(skill):
    return " ".join((ROOT / "skills" / skill / "SKILL.md").read_text(encoding="utf-8").split())


class StepEndingsTest(unittest.TestCase):
    def test_S_007_1_driven_by_accio_ends_with_next_step_and_carries_on(self):
        for skill, step in NEXT_STEP.items():
            with self.subTest(skill=skill):
                text = flat(skill)
                self.assertIn(DRIVING, text)
                self.assertIn(f"next: {step} (accio carries on)", text)

    def test_S_007_2_alone_keeps_the_slash_command_ending(self):
        for skill, step in NEXT_STEP.items():
            with self.subTest(skill=skill):
                text = flat(skill)
                self.assertIn(f"/accio:{step}", text)
                self.assertIn("runs alone", text)


if __name__ == "__main__":
    unittest.main()
