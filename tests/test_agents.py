"""S-018: the review agents, the findings template and the method checklists (DESIGN § 4.2, § 7.1, § 12.5;
decision 011); and, for every accio agent, that its tools match what curfew lets it do (S-015)."""
import importlib.util
import pathlib
import unittest

from support import ROOT

from accio_lib import policy

AGENTS = ROOT / "agents"
REFERENCES = ROOT / "references"
REVIEW_REPLY = ('"verdict"', '"counts"', '"critical"', '"major"', '"minor"', '"path"')
REVIEWERS = ("examiner", "professor", "auror")


def front_and_body(name):
    text = (AGENTS / f"{name}.md").read_text(encoding="utf-8")
    front, body = text.removeprefix("---\n").split("\n---\n", 1)
    return dict(line.split(":", 1) for line in front.strip().splitlines()), body


def tools(name):
    return {tool.strip() for tool in front_and_body(name)[0]["tools"].split(",")}


class ReviewAgentsTest(unittest.TestCase):
    def test_S_018_1_each_agent_sets_its_model_tools_and_reply(self):
        expected = {**{name: ({"Read", "Grep", "Glob", "Write"}, REVIEW_REPLY) for name in REVIEWERS},
                    "headmaster": ({"Read", "Grep", "Glob", "Bash", "Write"}, ('"kind"', '"ruling"', '"question"',
                                                                               '"text"', '"path"'))}
        for name, (agent_tools, reply_words) in expected.items():
            with self.subTest(name):
                fields, body = front_and_body(name)
                self.assertEqual(fields["name"].strip(), name)
                self.assertEqual(fields["model"].strip(), "sonnet")
                self.assertEqual(tools(name), agent_tools)
                for word in reply_words:
                    self.assertIn(word, body)

    def test_reviewers_keep_the_confidence_rule_their_findings_file_and_fix_rounds(self):
        for name in REVIEWERS:
            with self.subTest(name):
                _, body = front_and_body(name)
                for words in ("confidence ≥ 80", f"findings-{name}.md", "In a fix round", "only the fix diff",
                              "same id"):
                    self.assertIn(words, body)

    def test_the_template_holds_every_field_including_id_and_status(self):
        text = (REFERENCES / "findings-template.md").read_text(encoding="utf-8")
        for field in ("id:", "status:", "severity:", "confidence:", "where:", "claim:", "failure:", "dod:"):
            self.assertIn(field, text)

    def test_each_risk_area_has_a_checklist_of_things_to_inspect(self):
        index = (REFERENCES / "checklists" / "README.md").read_text(encoding="utf-8")
        self.assertIn("matched whole", index)
        for name in ("auth-and-security", "performance", "data-migration", "accessibility"):
            with self.subTest(name):
                self.assertIn(f"`{name}.md`", index)
                text = (REFERENCES / "checklists" / f"{name}.md").read_text(encoding="utf-8")
                self.assertGreaterEqual(text.count("\n- "), 4)
                self.assertNotIn("in your head", text)


class BrewRolesTest(unittest.TestCase):
    """S-020: what brew.js asks of each agent is in that agent's own file."""

    def test_portkey_knows_the_review_package_and_the_fix_brief(self):
        _, body = front_and_body("portkey")
        for words in ("--review", "--since", "--fix", '"package"', '"head"', '"risky"'):
            self.assertIn(words, body)

    def test_reviewers_let_a_ruling_stand(self):
        for name in REVIEWERS:
            with self.subTest(name):
                self.assertIn("ruling", front_and_body(name)[1])

    def test_S_020_6_every_model_heavy_agent_has_a_turn_limit(self):
        for name in ("house-elf", *REVIEWERS, "headmaster"):
            with self.subTest(name):
                self.assertGreater(int(front_and_body(name)[0].get("maxTurns", "0")), 0)


class AgentsMatchCurfewTest(unittest.TestCase):
    """A tool an agent has but curfew denies (or the reverse) turns into a BLOCKED story at run time."""

    def test_every_agents_tools_match_its_curfew_list(self):
        for path in sorted(AGENTS.glob("*.md")):
            name = path.stem
            if name == "house-elf":
                continue
            with self.subTest(name):
                lists = policy.AGENTS[name]
                agent_tools = tools(name)
                self.assertEqual("Bash" in agent_tools, bool(lists.bash))
                self.assertEqual("Write" in agent_tools, bool(lists.writes))
                self.assertEqual(bool({"WebSearch", "WebFetch"} & agent_tools), lists.web)


class PublishTest(unittest.TestCase):
    def test_the_references_the_reviewers_read_are_published(self):
        spec = importlib.util.spec_from_file_location("publish_under_test", ROOT / "scripts" / "publish.py")
        publish = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publish)
        self.assertIn("references", publish.SHIPPED)


if __name__ == "__main__":
    unittest.main()
