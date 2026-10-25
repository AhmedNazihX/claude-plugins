"""S-089: the brief lists agent_allow commands, house-elf.md names every command bashpolicy allows, record-design
commits a changed config.json, wand keeps proposed checks without a stop."""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

from support import ROOT, commit_all, git, init_repo, write

from accio_lib import bashpolicy

BRIEF = ROOT / "bin" / "accio-brief"
BOARD = ROOT / "bin" / "accio-board"
STORY = """---
id: S-001
title: Reset email
track: story
status: ready
files: [src/a.py]
---
## Context
Users forget passwords.
## Definition of Done
- [ ] S-001/1 WHEN a user asks for a reset THE SYSTEM SHALL email a link
"""


def run(script, repo, *args):
    return subprocess.run([sys.executable, "-I", str(script), *args], cwd=repo, stdin=subprocess.DEVNULL,
                          capture_output=True, text=True, check=False)


class BriefAllowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = init_repo(pathlib.Path(self.tmp.name).resolve() / "app")
        write(self.repo / "src" / "a.py", "v = 1\n")
        commit_all(self.repo)
        write(self.repo / ".accio" / "stories" / "S-001.md", STORY)

    def tearDown(self):
        self.tmp.cleanup()

    def brief_text(self, config):
        write(self.repo / ".accio" / "config.json", json.dumps(config))
        result = run(BRIEF, self.repo, "S-001")
        self.assertEqual(result.returncode, 0, result.stderr)
        return pathlib.Path(json.loads(result.stdout)["brief"]).read_text(encoding="utf-8")

    def test_S_089_1_the_brief_lists_each_agent_allow_command(self):
        text = self.brief_text({"agent_allow": ["claude plugin details", "make lint"]})
        scripts = text.split("## Scripts you may run", 1)[1].split("\n## ", 1)[0]
        for command in ("claude plugin details", "make lint"):
            self.assertIn(f"- `{command}`", scripts)

    def test_S_089_1_no_agent_allow_adds_nothing(self):
        text = self.brief_text({})
        scripts = text.split("## Scripts you may run", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(re.findall(r"`([^`]+)`", scripts), ["accio-claim", "accio-board refresh"])


class HouseElfNamesTest(unittest.TestCase):
    def test_S_089_2_house_elf_names_every_command_bashpolicy_allows(self):
        body = (ROOT / "agents" / "house-elf.md").read_text(encoding="utf-8")
        flat = " ".join(body.split())
        names = (bashpolicy.READ_ONLY_PROGRAMS | bashpolicy.FILE_PROGRAMS | bashpolicy.HOUSE_ELF_GIT)
        for name in sorted(names):
            with self.subTest(name):
                self.assertRegex(flat, r"`(git )?" + re.escape(name) + r"[` ]|[ ,]" + re.escape(name) + r"[`,]")
        self.assertIn("those your brief lists", flat)


class RecordDesignConfigTest(unittest.TestCase):
    def test_S_089_3_a_changed_tracked_config_is_committed_with_the_design(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(pathlib.Path(tmp).resolve() / "app")
            git(repo, "config", "user.name", "t")
            git(repo, "config", "user.email", "t@example.com")
            self.assertEqual(run(BOARD, repo, "init").returncode, 0)
            write(repo / ".accio" / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n")
            self.assertEqual(run(BOARD, repo, "record-design").returncode, 0)
            write(repo / ".accio" / "config.json", '{"checks": [{"command": "make test", "glob": "**"}]}\n')
            write(repo / ".accio" / "design.md", "# Design: x\n\n## Outcome\nUsers can sign in.\n\n## Export\nCSV.\n")
            self.assertEqual(run(BOARD, repo, "record-design").returncode, 0)
            committed = set(git(repo, "show", "--name-only", "--format=", "HEAD").splitlines())
            self.assertEqual(committed, {".accio/design.md", ".accio/config.json"})
            self.assertEqual(git(repo, "status", "--porcelain", "--", ".accio/config.json"), "")


class WandChecksTest(unittest.TestCase):
    def flat(self):
        return " ".join((ROOT / "skills" / "wand" / "SKILL.md").read_text(encoding="utf-8").split())

    def test_S_089_4_wand_keeps_proposed_checks_without_a_stop(self):
        text = self.flat()
        checks = text.split("**Check commands.**", 1)[1].split("**New design or design note.**", 1)[0]
        self.assertIn("I kept these check commands", checks)
        self.assertIn("say if one should go", checks)
        self.assertNotIn("ask which to keep", checks)

    def test_S_089_4_small_first_year_points_are_one_assumption_line(self):
        step = self.flat().split("**Fresh reader.**", 1)[1].split("4. Run `accio-board record-design`", 1)[0]
        self.assertIn("I'll assume", step)
        self.assertIn("one line", step)
        self.assertIn("each real decision", step)


if __name__ == "__main__":
    unittest.main()
