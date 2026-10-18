"""S-026: the skill evals (DESIGN § 8.5, § 9; decision 006): free graders only, a cost cap in CI, and every skill
shown to fire on its own trigger phrases. The evals themselves run with `claude plugin eval` (see evals/README.md)."""
import pathlib
import re
import unittest

from support import ROOT

EVALS = ROOT / "evals"
SKILLS = ROOT / "skills"
CI = ROOT / ".github" / "workflows" / "ci.yml"
FREE_GRADERS = {"regex", "tool_used", "tool_order", "file_exists"}
FIELD = re.compile(r"^(\w+):\s*(.*)$", re.MULTILINE)


def frontmatter(path):
    text = path.read_text(encoding="utf-8")
    head = text.split("\n---\n", 1)[0].removeprefix("---\n") if text.startswith("---\n") else ""
    return dict(FIELD.findall(head))


def cases():
    return sorted(path.parent for path in EVALS.rglob("prompt.md") if "results" not in path.parts)


class EvalSuiteTest(unittest.TestCase):
    def test_S_026_1_every_grader_is_a_free_one(self):
        paid = [f"{grader.relative_to(ROOT)}: {frontmatter(grader).get('type')}"
                for case in cases() for grader in sorted((case / "graders").glob("*.md"))
                if frontmatter(grader).get("type") not in FREE_GRADERS]
        self.assertEqual(paid, [])

    def test_S_026_1_ci_runs_the_ci_cases_with_a_two_dollar_cap_and_only_by_hand(self):
        text = CI.read_text(encoding="utf-8")
        command = next(line for line in text.splitlines() if "claude plugin eval" in line)
        self.assertIn("--max-cost-usd 2", command)
        self.assertIn("--tag ci", command)
        evals_job = text[text.index("  evals:"):]
        self.assertIn("workflow_dispatch", text.split("jobs:")[0])
        self.assertIn("github.event_name == 'workflow_dispatch'", evals_job)

    def test_S_026_2_every_skill_has_a_ci_case_that_shows_it_firing(self):
        missing = []
        for skill in sorted(path.name for path in SKILLS.iterdir() if (path / "SKILL.md").exists()):
            fired = [case for case in cases() if "ci" in frontmatter(case / "prompt.md").get("tags", "")
                     and any(frontmatter(grader).get("tool") == "Skill" and skill in grader.read_text(encoding="utf-8")
                             for grader in (case / "graders").glob("*.md"))]
            if not fired:
                missing.append(skill)
        self.assertEqual(missing, [])

    def test_every_case_has_a_grader_and_its_scaffold_inside_the_case(self):
        for case in cases():
            with self.subTest(case.relative_to(EVALS)):
                self.assertTrue(list((case / "graders").glob("*.md")))
                scaffold = re.search(r"scaffold_script:\s*(\S+)", (case / "case.yaml").read_text(encoding="utf-8")) \
                    if (case / "case.yaml").exists() else None
                if scaffold:
                    self.assertNotIn("..", scaffold.group(1))
                    self.assertTrue((case / scaffold.group(1)).exists())


if __name__ == "__main__":
    unittest.main()
