"""S-076/4: every command and write brew.js gives an accio agent goes through the real curfew hook as that agent.

The list is tests/fixtures/brew-curfew.json. tests/workflow/brew-curfew.test.mjs renders brew.js's prompts and checks
that every command and `.accio/run/` path in them is on it (and nothing stale is), so a new prompt can't skip this
test. Its `steps` part holds the commands of the agent-file steps brew.js points to ("follow your step 3"); the test
below checks those files name no other command. Found 2026-10-24: curfew had denied prefect `accio-break <ID> verify`
since 0.8.0, and tests with stub agents never saw it.
"""
import json
import re
import shlex

from support import ROOT

from accio_lib import policy
from test_curfew import CurfewTestBase

CONTRACT = json.loads((ROOT / "tests" / "fixtures" / "brew-curfew.json").read_text(encoding="utf-8"))
AGENT_FILES = {"accio:portkey": "portkey.md", "accio:prefect": "prefect.md", "accio:boggart": "boggart.md"}
SPAN = re.compile(r"`(accio-[a-z]+ [^`]+)`")
SCREENSHOT = f"{policy.DEFAULT_MCP_PREFIX}browser_take_screenshot"
STORY = "S-001"
HEAD = "0123456789abcdef0123456789abcdef01234567"


def entries(part, kind):
    """(agent, item) for every item of `kind` (run, mentions, write, read) in the list's `part` (brew or steps)."""
    return [(agent, item) for agent, lists in CONTRACT[part].items() for item in lists.get(kind, ())]


class BrewCurfewContractTest(CurfewTestBase):
    def fill(self, text):
        """The list's placeholders, as a real build would fill them in this test's repo."""
        values = {"<ID>": STORY, "<commit>": HEAD, "<sum>": "89abcdef", "<name>": "line-1", "<panel>": "story",
                  "<key>": "0123abcd", "<worktree>": str(self.worktree),
                  "<findings file> …": f".accio/run/{STORY}/check-findings.md",
                  "<file>": str(self.run_dir / STORY / "boggart" / "repros" / "r1.py")}
        for placeholder, value in values.items():
            text = text.replace(placeholder, value)
        self.assertNotIn("<", text, f"a placeholder this test can't fill: {text}")
        return text

    def commands(self, template):
        """The command as the agent may type it: the script by name (on PATH), and by its absolute path."""
        words = shlex.split(self.fill(template))
        return (shlex.join(words), shlex.join([str(ROOT / "bin" / words[0]), *words[1:]]))

    def assert_runs(self, part):
        for agent, template in entries(part, "run"):
            for command in self.commands(template):
                with self.subTest(agent=agent, command=command):
                    verdict, reason = self.decision("Bash", self.bash(command), agent=agent)
                    self.assertEqual(verdict, "allow", reason)

    def target(self, path):
        filled = self.fill(path)
        return self.repo / (filled + "r1.py" if filled.endswith("/") else filled)

    def test_S_076_4_every_command_brew_gives_an_agent_is_allowed_as_that_agent(self):
        self.assertTrue(entries("brew", "run"))
        self.assert_runs("brew")

    def test_S_076_4_every_command_of_the_agent_file_steps_brew_points_to_is_allowed(self):
        self.assert_runs("steps")

    def test_S_076_4_every_file_brew_asks_an_agent_to_write_is_allowed_as_that_agent(self):
        self.assertTrue(entries("brew", "write"))
        for agent, path in entries("brew", "write"):
            target = self.target(path)
            with self.subTest(agent=agent, target=target):
                if agent == "accio:mad-eye":  # mad-eye saves screenshots with the browser tool, never Write
                    self.assert_allowed(SCREENSHOT, {"filename": str(target)}, agent=agent)
                else:
                    self.assert_allowed("Write", {"file_path": str(target), "content": "x\n"}, agent=agent)

    def test_S_076_4_every_file_brew_names_an_agent_to_read_is_readable(self):
        for agent, path in entries("brew", "read"):
            with self.subTest(agent=agent, path=path):
                self.assert_allowed("Read", {"file_path": str(self.target(path))}, agent=agent)

    def test_S_076_4_the_agent_files_name_no_command_the_list_lacks(self):
        for agent, name in AGENT_FILES.items():
            text = (ROOT / "agents" / name).read_text(encoding="utf-8").replace("\n", " ")
            lists = CONTRACT["steps"].get(agent, {})
            known = {*lists.get("run", ()), *lists.get("mentions", ())}
            with self.subTest(agent=agent):
                self.assertEqual(sorted(set(SPAN.findall(text)) - known), [],
                                 "add these to tests/fixtures/brew-curfew.json steps (run, or mentions)")

    def test_S_076_4_a_command_off_the_list_is_still_denied(self):
        """The hook is really judging: a look-alike of a listed command fails."""
        denied = (("accio:prefect", f"accio-break {STORY} try x.py"), ("accio:portkey", "accio-ledger key x"),
                  ("accio:boggart", f"accio-break {STORY} verify"), ("accio:headmaster", "accio-board unlock"))
        for agent, command in denied:
            with self.subTest(agent=agent, command=command):
                self.assertEqual(self.decision("Bash", self.bash(command), agent=agent)[0], "deny")
