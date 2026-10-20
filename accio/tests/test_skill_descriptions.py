"""S-030: every skill description says when to use it, and the skills stay inside the description budget."""
import re
import unittest

from support import ROOT

SKILLS = ROOT / "skills"
MAX_SKILL_CHARS = 3100  # about 1,000 tokens for all seven skills (prompt-audit.md, "Description budget")


def front_matter(path):
    block = path.read_text(encoding="utf-8").split("---", 2)[1]
    fields = {}
    for match in re.finditer(r"^([a-z_-]+): (.*)$", block, re.M):
        fields[match.group(1)] = match.group(2)
    return fields


def all_skills():
    return {path.parent.name: front_matter(path) for path in sorted(SKILLS.glob("*/SKILL.md"))}


class SkillDescriptionsTest(unittest.TestCase):
    def test_S_030_1_every_skill_says_when_to_use_it(self):
        skills = all_skills()
        self.assertGreaterEqual(len(skills), 7)
        for name, fields in skills.items():
            with self.subTest(name):
                self.assertTrue(fields.get("when_to_use", "").startswith("When "), name)
                self.assertIn("Not for", fields["when_to_use"])
                self.assertTrue(fields.get("description"), name)

    def test_S_030_1_skill_descriptions_fit_the_budget(self):
        total = sum(len(f.get("description", "")) + len(f.get("when_to_use", "")) for f in all_skills().values())
        self.assertLessEqual(total, MAX_SKILL_CHARS)


if __name__ == "__main__":
    unittest.main()
