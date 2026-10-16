#!/usr/bin/env python3
"""Lint the foreman plugin: frontmatter, references, hooks, links, imports and versions. Stdlib only.

Usage (from anywhere):
  lint.py [--root PATH]    lint the plugin at PATH (default: the plugin this script belongs to)

Prints one `file:line: message` per problem and exits 1 if there are any, 0 otherwise.

Checks:
  - frontmatter of agents/<name>.md and skills/<name>/SKILL.md: `name` is the file or folder name, `description`
    is present, `model` (if set) is haiku, sonnet, opus or inherit, and every `tools` / `allowed-tools` entry is a
    known tool name (or an `mcp__` tool);
  - an agent whose description says "read-only" has a `tools` list (without one it gets every tool), and that list
    has none of Write, Edit, MultiEdit, NotebookEdit;
  - in agents and skills, every `foreman:<name>` names a foreman agent or skill, and every backticked bare name
    labelled as one ("the `doc-reader` agent", "skill `kickoff`") names a foreman agent or skill of that kind
    (outside skills the plugin credits, listed in EXTERNAL, are allowed);
  - every hook command in hooks/hooks.json points at a file that exists and is executable;
  - every relative link to a `.md` file, in the plugin's Markdown files, resolves (tests/ and the untracked
    HANDOVER.md are skipped);
  - scripts/*.py import only standard-library modules (`sys.stdlib_module_names`) or sibling scripts;
  - the version in .claude-plugin/plugin.json, the line under README.md's "## Version" and the top numbered
    "## X.Y.Z" entry of CHANGELOG.md agree ("## Unreleased" is ignored).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

MODELS = {"haiku", "sonnet", "opus", "inherit"}
KNOWN_TOOLS = {
    "Agent", "Task", "Bash", "BashOutput", "KillShell", "Read", "Write", "Edit", "MultiEdit", "NotebookEdit",
    "NotebookRead", "Glob", "Grep", "LS", "WebFetch", "WebSearch", "TodoWrite", "Skill", "SlashCommand",
    "SendMessage", "ExitPlanMode", "ToolSearch", "Monitor", "TaskStop", "LSP",
}
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
TOOL_KEYS = ("tools", "allowed-tools")
EXTERNAL = {"grilling"}  # outside skills the plugin credits by name (README › Credits)
SKIPPED_MD = {"HANDOVER.md"}  # untracked maintainer notes

FOREMAN_REF_RE = re.compile(r"\bforeman:([a-z][a-z0-9-]*)")
LABELLED_RE = re.compile(
    r"`(?P<a>[a-z][a-z0-9-]*)` (?P<ka>agent|skill)s?\b|\b(?P<kb>agent|skill)s? `(?P<b>[a-z][a-z0-9-]*)`"
)
MD_LINK_RE = re.compile(r"\]\((?P<target>[^)\s#]+\.md)(?:#[^)\s]*)?\)")
VERSION_RE = re.compile(r"\d+\.\d+\.\d+")
CHANGELOG_ENTRY_RE = re.compile(r"^## (\d+\.\d+\.\d+)\b")


@dataclass(frozen=True)
class Problem:
    path: Path
    line: int
    message: str

    def render(self) -> str:
        return f"{os.path.relpath(self.path)}:{self.line}: {self.message}"


@dataclass(frozen=True)
class Frontmatter:
    fields: dict[str, str]
    lines: dict[str, int]  # key -> line number in the file


def parse_frontmatter(text: str) -> Frontmatter | None:
    """The `key: value` pairs between the opening `---` lines; a block list (`- item`) joins with commas."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fields: dict[str, str] = {}
    numbers: dict[str, int] = {}
    key = None
    for number, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return Frontmatter(fields, numbers)
        item = re.match(r"^\s+-\s+(.*)$", line)
        if item and key:
            fields[key] = ", ".join(filter(None, [fields[key], item.group(1).strip()]))
            continue
        pair = re.match(r"^([A-Za-z][\w-]*):\s*(.*)$", line)
        if pair:
            key = pair.group(1)
            fields[key] = pair.group(2).strip().strip("\"'")
            numbers[key] = number
    return None  # no closing ---


def tool_names(value: str) -> list[str]:
    """`Bash, Read` or `[Bash, Read]` -> names, with permission specifiers like `Bash(git:*)` dropped."""
    names = (part.strip().strip("\"'") for part in value.strip("[]").split(","))
    return [re.sub(r"\(.*\)$", "", name) for name in names if name]


def components(root: Path) -> list[tuple[str, str, Path]]:
    """(kind, expected name, file) for every agent file and skill folder."""
    agents = [("agent", p.stem, p) for p in sorted((root / "agents").glob("*.md"))]
    skills = [("skill", p.parent.name, p) for p in sorted((root / "skills").glob("*/SKILL.md"))]
    return agents + skills


def check_frontmatter(kind: str, expected: str, path: Path) -> list[Problem]:
    fm = parse_frontmatter(path.read_text())
    if fm is None:
        return [Problem(path, 1, "no frontmatter (--- ... ---) at the top")]
    at = lambda key: fm.lines.get(key, 1)  # noqa: E731
    problems = []
    if fm.fields.get("name") != expected:
        problems.append(Problem(path, at("name"), f"name is {fm.fields.get('name')!r}, expected {expected!r}"))
    if not fm.fields.get("description"):
        problems.append(Problem(path, at("description"), "description is missing"))
    model = fm.fields.get("model")
    if model is not None and model not in MODELS:
        problems.append(Problem(path, at("model"), f"model {model!r} is not one of {', '.join(sorted(MODELS))}"))
    for key in TOOL_KEYS:
        unknown = [t for t in tool_names(fm.fields.get(key, "")) if t not in KNOWN_TOOLS and not t.startswith("mcp__")]
        if unknown:
            problems.append(Problem(path, at(key), f"unknown tool name(s) in {key}: {', '.join(unknown)}"))
    if kind == "agent":
        problems.extend(check_read_only(path, fm))
    return problems


def check_read_only(path: Path, fm: Frontmatter) -> list[Problem]:
    if "read-only" not in fm.fields.get("description", "").lower():
        return []
    if "tools" not in fm.fields:
        return [Problem(path, fm.lines.get("description", 1), "read-only agent has no tools list (it gets every tool)")]
    writers = [t for t in tool_names(fm.fields["tools"]) if t in WRITE_TOOLS]
    if writers:
        return [Problem(path, fm.lines["tools"], f"read-only agent lists write tools: {', '.join(writers)}")]
    return []


def check_references(path: Path, names: dict[str, set[str]]) -> list[Problem]:
    known = names["agent"] | names["skill"]
    problems = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        for match in FOREMAN_REF_RE.finditer(line):
            if match.group(1) not in known:
                problems.append(Problem(path, number, f"foreman:{match.group(1)} is not a foreman agent or skill"))
        for match in LABELLED_RE.finditer(line):
            name, kind = match.group("a") or match.group("b"), match.group("ka") or match.group("kb")
            if name not in names[kind] and name not in EXTERNAL:
                problems.append(Problem(path, number, f"no foreman {kind} is named `{name}`"))
    return problems


def check_hooks(root: Path) -> list[Problem]:
    path = root / "hooks" / "hooks.json"
    if not path.exists():
        return []
    text = path.read_text()
    try:
        config = json.loads(text)
    except json.JSONDecodeError as error:
        return [Problem(path, error.lineno, f"invalid JSON: {error.msg}")]
    problems = []
    for command in hook_commands(config):
        expanded = command.replace("${CLAUDE_PLUGIN_ROOT}", str(root))
        try:
            target = Path(shlex.split(expanded)[0])
        except (ValueError, IndexError):
            problems.append(Problem(path, line_of(text, command), f"can't parse hook command {command!r}"))
            continue
        if not target.is_file():
            problems.append(Problem(path, line_of(text, command), f"hook command path doesn't exist: {command}"))
        elif not os.access(target, os.X_OK):
            problems.append(Problem(path, line_of(text, command), f"hook command isn't executable: {command}"))
    return problems


def hook_commands(config: dict) -> list[str]:
    groups = (group for event in config.get("hooks", {}).values() for group in event)
    return [hook["command"] for group in groups for hook in group.get("hooks", []) if hook.get("type") == "command"]


def line_of(text: str, needle: str) -> int:
    """The line where `needle` (as JSON-encoded in the file) first appears; 1 if not found."""
    encoded = json.dumps(needle)[1:-1]
    index = text.find(encoded)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.md")
        if p.name not in SKIPPED_MD and "tests" not in p.relative_to(root).parts
    )


def check_links(path: Path) -> list[Problem]:
    problems = []
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        for match in MD_LINK_RE.finditer(line):
            target = match.group("target")
            if re.match(r"^[a-z]+:", target) or target.startswith("/"):
                continue  # a URL or an absolute path, not a relative link
            if not (path.parent / target).exists():
                problems.append(Problem(path, number, f"link target doesn't exist: {target}"))
    return problems


def check_imports(path: Path, siblings: set[str]) -> list[Problem]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError as error:
        return [Problem(path, error.lineno or 1, f"syntax error: {error.msg}")]
    allowed = set(sys.stdlib_module_names) | siblings
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules = [node.module]
        else:
            continue
        for module in modules:
            if module.split(".")[0] not in allowed:
                problems.append(Problem(path, node.lineno, f"imports {module}, which isn't in the standard library"))
    return problems


def plugin_version(root: Path) -> tuple[str | None, Path, int]:
    path = root / ".claude-plugin" / "plugin.json"
    text = path.read_text()
    version = json.loads(text).get("version")
    number = next((i for i, line in enumerate(text.splitlines(), start=1) if '"version"' in line), 1)
    return version, path, number


def readme_version(root: Path) -> tuple[str | None, Path, int]:
    path = root / "README.md"
    lines = path.read_text().splitlines()
    heading = next((i for i, line in enumerate(lines) if line.strip() == "## Version"), None)
    if heading is None:
        return None, path, 1
    for number in range(heading + 1, len(lines)):
        if lines[number].strip():
            match = VERSION_RE.match(lines[number].strip())
            return (match.group(0) if match else None), path, number + 1
    return None, path, heading + 1


def changelog_version(root: Path) -> tuple[str | None, Path, int]:
    path = root / "CHANGELOG.md"
    for number, line in enumerate(path.read_text().splitlines(), start=1):
        match = CHANGELOG_ENTRY_RE.match(line)
        if match:
            return match.group(1), path, number
    return None, path, 1


def check_versions(root: Path) -> list[Problem]:
    sources = {
        "plugin.json": plugin_version(root),
        "the README version line": readme_version(root),
        "the top numbered CHANGELOG entry": changelog_version(root),
    }
    missing = [
        Problem(path, line, f"no version found in {label}")
        for label, (version, path, line) in sources.items()
        if not version
    ]
    if missing:
        return missing
    expected = sources["plugin.json"][0]
    return [
        Problem(path, line, f"{label} says {version}, plugin.json says {expected}")
        for label, (version, path, line) in sources.items()
        if version != expected
    ]


def lint(root: Path) -> list[Problem]:
    found = components(root)
    names = {kind: {name for k, name, _ in found if k == kind} for kind in ("agent", "skill")}
    siblings = {p.stem for p in (root / "scripts").glob("*.py")}
    problems: list[Problem] = []
    for kind, expected, path in found:
        problems += check_frontmatter(kind, expected, path)
        problems += check_references(path, names)
    problems += check_hooks(root)
    for path in markdown_files(root):
        problems += check_links(path)
    for path in sorted((root / "scripts").glob("*.py")):
        problems += check_imports(path, siblings)
    problems += check_versions(root)
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Lint the foreman plugin.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="the plugin folder")
    args = parser.parse_args(argv)
    if not args.root.is_dir():
        print(f"lint.py: {args.root} is not a folder", file=sys.stderr)
        return 2
    try:
        problems = lint(args.root.resolve())
    except (OSError, json.JSONDecodeError) as error:
        print(f"lint.py: can't read the plugin: {error}", file=sys.stderr)
        return 2
    for problem in problems:
        print(problem.render())
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
