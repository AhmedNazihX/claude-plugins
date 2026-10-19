"""S-003: what owl's SKILL.md says about starting howler. A text check: it proves what the skill says,
not that a model follows it (the live run is S-003/10)."""
import unittest

from support import ROOT

SKILL = ROOT / "skills" / "owl" / "SKILL.md"
MAX_LINES = 80


def skill_text():
    return SKILL.read_text(encoding="utf-8")


def step_6():
    return " ".join(skill_text().split("## 6.", 1)[1].split("End in the report format", 1)[0].split())


class OwlHowlerTest(unittest.TestCase):
    def test_S_003_1_step_6_calls_agent_with_howler_after_a_push(self):
        text = step_6()
        self.assertIn("Agent tool", text)
        self.assertIn("accio:howler", text)

    def test_S_003_2_prompt_holds_sha_base_iteration_and_what_happened(self):
        text = step_6()
        for phrase in ("full sha", "base branch", "accio-owl push-ok", "iteration number", "What happened"):
            with self.subTest(phrase):
                self.assertIn(phrase, text)

    def test_S_003_3_no_howler_when_push_fails_and_it_comes_after_the_push(self):
        text = step_6()
        self.assertIn("If the push fails", text)
        self.assertIn("don't start howler", text)
        self.assertLess(text.index("git push origin"), text.index("accio:howler"))

    def test_S_018_3_prompt_holds_prev_and_says_what_to_tell_howler_when_null(self):
        text = step_6()
        for phrase in ("`prev`", "`null`", "no previous pushed commit"):
            with self.subTest(phrase):
                self.assertIn(phrase, text)

    def test_S_003_4_agent_is_an_allowed_tool(self):
        line = next(l for l in skill_text().splitlines() if l.startswith("allowed-tools:"))
        tools = [t.strip() for t in line.removeprefix("allowed-tools:").split(",")]
        self.assertIn("Agent", tools)

    def test_S_003_5_skill_has_at_most_80_lines(self):
        self.assertLessEqual(len(skill_text().splitlines()), MAX_LINES)


if __name__ == "__main__":
    unittest.main()
