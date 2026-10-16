"""Tests for scripts/lint.py. Stdlib only: run with `python3 -m unittest discover -s tests` from the repo root.

Each test builds a small synthetic plugin in a temporary folder, plants one problem and checks the lint reports it.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "lint.py"

spec = importlib.util.spec_from_file_location("lint", SCRIPT)
assert spec and spec.loader
lint = importlib.util.module_from_spec(spec)
sys.modules["lint"] = lint
spec.loader.exec_module(lint)

READER = """---
name: reader
description: Reads files and reports. Read-only.
tools: Read, Grep, Glob
model: haiku
---

Body.
"""
START = """---
name: start
description: Starts things.
argument-hint: "<ID>"
---

Launch `foreman:reader`, the `reader` agent, then run the `start` skill again.
The `grilling` skill inspired this. See [the README](../../README.md) and [docs](https://example.com/x.md).
"""
HOOKS = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
    {"type": "command", "command": "\"${CLAUDE_PLUGIN_ROOT}/hooks/guard.sh\""},
]}]}}
CLEAN = {
    "agents/reader.md": READER,
    "skills/start/SKILL.md": START,
    "hooks/hooks.json": json.dumps(HOOKS, indent=2),
    "hooks/guard.sh": "#!/bin/bash\nexit 0\n",
    "scripts/helper.py": "import json\n",
    "scripts/tool.py": "from __future__ import annotations\nimport os.path\nfrom helper import json\n",
    ".claude-plugin/plugin.json": json.dumps({"name": "foreman", "version": "1.2.3"}, indent=2),
    "README.md": "# Foreman\n\n## Version\n\n1.2.3. See [CHANGELOG.md](CHANGELOG.md).\n",
    "CHANGELOG.md": "# Changelog\n\n## Unreleased\n\n- next\n\n## 1.2.3 (2026-10-16)\n\n- done\n\n## 1.2.2\n",
}


class LintCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        for name, text in CLEAN.items():
            self.write(name, text)
        (self.root / "hooks/guard.sh").chmod(0o755)

    def write(self, name: str, text: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    def edit(self, name: str, old: str, new: str) -> None:
        text = (self.root / name).read_text()
        self.assertIn(old, text)
        self.write(name, text.replace(old, new, 1))

    def messages(self) -> list[str]:
        return [f"{p.path.relative_to(self.root)}:{p.line}: {p.message}" for p in lint.lint(self.root)]

    def assertOneProblem(self, expected: str) -> None:
        found = self.messages()
        self.assertEqual(len(found), 1, found)
        self.assertIn(expected, found[0])


class Clean(LintCase):
    def test_clean_fixture_passes(self) -> None:
        self.assertEqual(self.messages(), [])

    def test_cli_exits_0_on_clean_and_1_with_file_line_message(self) -> None:
        run = lambda: subprocess.run(  # noqa: E731
            [sys.executable, str(SCRIPT), "--root", str(self.root)], capture_output=True, text=True, cwd=self.root,
        )
        self.assertEqual(run().returncode, 0)
        self.edit("agents/reader.md", "model: haiku", "model: gpt")
        result = run()
        self.assertEqual(result.returncode, 1)
        expected = "agents/reader.md:5: model 'gpt' is not one of haiku, inherit, opus, sonnet"
        self.assertEqual(result.stdout.strip(), expected)

    def test_the_repo_itself_passes(self) -> None:
        self.assertEqual([p.render() for p in lint.lint(ROOT)], [])


class Frontmatter(LintCase):
    def test_name_must_match_the_file(self) -> None:
        self.edit("agents/reader.md", "name: reader", "name: readr")
        self.assertOneProblem("agents/reader.md:2: name is 'readr', expected 'reader'")

    def test_skill_name_must_match_the_folder(self) -> None:
        self.edit("skills/start/SKILL.md", "name: start", "name: begin")
        self.assertOneProblem("skills/start/SKILL.md:2: name is 'begin', expected 'start'")

    def test_description_is_required(self) -> None:
        self.edit("skills/start/SKILL.md", "description: Starts things.", "description:")
        self.assertOneProblem("skills/start/SKILL.md:3: description is missing")

    def test_model_must_be_known(self) -> None:
        self.edit("agents/reader.md", "model: haiku", "model: gpt-4")
        self.assertOneProblem("model 'gpt-4' is not one of")

    def test_tools_must_be_known(self) -> None:
        self.edit("agents/reader.md", "tools: Read, Grep, Glob", "tools: Read, Grepp, mcp__x__y, Bash(git:*)")
        self.assertOneProblem("agents/reader.md:4: unknown tool name(s) in tools: Grepp")

    def test_block_list_tools_are_read(self) -> None:
        self.edit("agents/reader.md", "tools: Read, Grep, Glob", "tools:\n  - Read\n  - Serch")
        self.assertOneProblem("unknown tool name(s) in tools: Serch")

    def test_missing_frontmatter(self) -> None:
        self.write("agents/reader.md", "# Reader\n")
        self.assertOneProblem("agents/reader.md:1: no frontmatter")


class ReadOnly(LintCase):
    def test_read_only_agent_with_a_write_tool(self) -> None:
        self.edit("agents/reader.md", "tools: Read, Grep, Glob", "tools: Read, Edit, NotebookEdit")
        self.assertOneProblem("agents/reader.md:4: read-only agent lists write tools: Edit, NotebookEdit")

    def test_read_only_agent_without_a_tools_list(self) -> None:
        self.edit("agents/reader.md", "tools: Read, Grep, Glob\n", "")
        self.assertOneProblem("read-only agent has no tools list")

    def test_writer_agent_may_write(self) -> None:
        self.edit("agents/reader.md", "Read-only.", "Edits files.")
        self.edit("agents/reader.md", "tools: Read, Grep, Glob", "tools: Read, Write, Edit")
        self.assertEqual(self.messages(), [])


class References(LintCase):
    def test_unknown_foreman_reference(self) -> None:
        self.edit("skills/start/SKILL.md", "`foreman:reader`", "`/foreman:raeder`")
        self.assertOneProblem("skills/start/SKILL.md:7: foreman:raeder is not a foreman agent or skill")

    def test_unknown_labelled_bare_name(self) -> None:
        self.edit("skills/start/SKILL.md", "the `reader` agent", "the `writer` agent")
        self.assertOneProblem("no foreman agent is named `writer`")

    def test_labelled_name_of_the_wrong_kind(self) -> None:
        self.edit("agents/reader.md", "Body.", "Run skill `reader` first.")
        self.assertOneProblem("agents/reader.md:8: no foreman skill is named `reader`")

    def test_unlabelled_backticked_words_are_not_references(self) -> None:
        self.edit("agents/reader.md", "Body.", "Set `checks` and `lanes`.")
        self.assertEqual(self.messages(), [])


class Hooks(LintCase):
    def test_hook_path_must_exist(self) -> None:
        (self.root / "hooks/guard.sh").unlink()
        self.assertOneProblem("hooks/hooks.json:9: hook command path doesn't exist")

    def test_hook_must_be_executable(self) -> None:
        (self.root / "hooks/guard.sh").chmod(0o644)
        self.assertOneProblem("hook command isn't executable")


class Links(LintCase):
    def test_broken_relative_md_link(self) -> None:
        self.edit("skills/start/SKILL.md", "(../../README.md)", "(../README.md)")
        self.assertOneProblem("skills/start/SKILL.md:8: link target doesn't exist: ../README.md")

    def test_tests_folder_and_handover_are_skipped(self) -> None:
        self.write("tests/fixtures/notes.md", "[x](missing.md)\n")
        self.write("HANDOVER.md", "[x](missing.md)\n")
        self.assertEqual(self.messages(), [])


class Imports(LintCase):
    def test_third_party_import(self) -> None:
        self.edit("scripts/tool.py", "import os.path\n", "import os.path\nimport yaml\n")
        self.assertOneProblem("scripts/tool.py:3: imports yaml, which isn't in the standard library")

    def test_third_party_from_import(self) -> None:
        self.edit("scripts/helper.py", "import json\n", "def f():\n    from requests import get\n")
        self.assertOneProblem("scripts/helper.py:2: imports requests")


class Versions(LintCase):
    def test_readme_version_disagrees(self) -> None:
        self.edit("README.md", "1.2.3.", "1.2.2.")
        self.assertOneProblem("README.md:5: the README version line says 1.2.2, plugin.json says 1.2.3")

    def test_changelog_top_entry_disagrees(self) -> None:
        self.edit("CHANGELOG.md", "## 1.2.3 (2026-10-16)", "## 1.2.4 (2026-10-16)")
        self.assertOneProblem("CHANGELOG.md:7: the top numbered CHANGELOG entry says 1.2.4, plugin.json says 1.2.3")

    def test_plugin_json_bumped_alone(self) -> None:
        self.edit(".claude-plugin/plugin.json", "1.2.3", "1.3.0")
        found = self.messages()
        self.assertEqual(len(found), 2, found)

    def test_missing_readme_version(self) -> None:
        self.edit("README.md", "## Version", "## Versions")
        self.assertOneProblem("README.md:1: no version found in the README version line")


if __name__ == "__main__":
    unittest.main()
