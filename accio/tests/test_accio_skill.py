"""S-006: what the /accio conductor SKILL.md says. A text check: it proves what the skill says, not that a
model follows it (the live run is the eval accio/evals/accio/design-no-stories)."""
import re
import unittest

from support import ROOT

SKILL = ROOT / "skills" / "accio" / "SKILL.md"
MAX_LINES = 50
NEXT = "accio-board next --json"


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def flat():
    return " ".join(skill_text().split())


class AccioSkillTest(unittest.TestCase):
    def test_S_006_1_name_is_accio_and_at_most_50_lines(self):
        text = skill_text()
        self.assertRegex(text, r"(?m)^name: accio$")
        self.assertLessEqual(len(text.splitlines()), MAX_LINES)

    def test_S_025_1_passes_driven_to_each_step_skill(self):
        self.assertIn("argument `driven`", flat())

    def test_S_006_2_runs_next_before_any_step_skill(self):
        text = " ".join(skill_text().split("---", 2)[2].split())  # the body, after the frontmatter
        self.assertIn(NEXT, text)
        self.assertLess(text.index(NEXT), text.index("Skill"))
        self.assertIn("accio-board next", next(l for l in skill_text().splitlines() if l.startswith("allowed-tools:")))

    def test_S_006_3_auto_true_runs_the_step_skill_and_reads_the_board_again(self):
        text = flat()
        self.assertIn("`auto` is true", text)
        self.assertRegex(text, r"`auto` is true.{0,200}?run that step's skill.{0,200}?(read|run).{0,200}?again")

    def test_S_006_4_auto_false_stops_at_the_skills_question_then_carries_on(self):
        text = flat()
        self.assertRegex(text, r"(?i)`auto` is false.{0,200}?still run that step's skill")
        self.assertIn("first question", text)
        self.assertRegex(text, r"(?i)after the answer.{0,200}?(read|run).{0,200}?again")

    def test_S_006_4_done_stops_with_its_sentence_and_no_skill(self):
        text = flat()
        self.assertRegex(text, r"`done`.{0,200}?sentence.{0,200}?no skill|`done`.{0,200}?no skill.{0,200}?sentence")

    def test_S_006_never_tells_the_user_to_type_a_step_command(self):
        self.assertIn("never say", flat().lower())
        self.assertNotRegex(skill_text(), r"(?i)\btype /accio:(wand|sort|prophecy|owl|brew)")

    def test_S_087_3_stops_and_passes_on_a_step_that_ended_with_an_error_a_refusal_or_a_need(self):
        text = flat()
        rule = re.search(r"(?i)after a step's skill ends, stop and pass on its message.{0,600}", text)
        self.assertTrue(rule, "the skill says to stop and pass on the step's message")
        ending = rule.group(0)
        self.assertIn("`accio-…:` error", ending)
        self.assertRegex(ending, r"(?i)\brefus")
        self.assertIn('"What I need from you"', ending)
        self.assertRegex(ending, r'anything but "nothing" or "next: …"')
        self.assertRegex(ending, r"(?i)don't read the board again")

    def test_S_087_3_the_loop_goes_back_to_1_only_after_a_clean_ending(self):
        loop = " ".join(skill_text().split("## Loop", 1)[1].split("\n## ", 1)[0].split())
        self.assertNotIn("Do the step, then go back to 1", loop)
        self.assertRegex(loop, r"(?i)only when it ended clean.{0,40}go back to 1")
        self.assertRegex(flat(), r"`auto` is true.{0,300}?unless it ended as .When a step ends. says")

    def test_S_006_brew_is_started_by_the_skill_and_wait_resumes_at_the_end_notice(self):
        text = flat()
        self.assertIn("accio:brew", text)
        self.assertIn("Workflow", text)
        self.assertRegex(text, r"`wait`.{0,200}?end notice")
        self.assertTrue(re.search(r"(?m)^allowed-tools:.*\bWorkflow\b", skill_text()))


if __name__ == "__main__":
    unittest.main()
