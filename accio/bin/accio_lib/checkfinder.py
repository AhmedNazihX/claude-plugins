#!/usr/bin/env python3
"""S-011: propose check commands for wand's setup step (design "Lessons from iteration 1", R2).

Looks at a repo's CI workflows, package.json scripts and pytest folders, and proposes commands in the shape of
config's `checks` entries ({command, glob}). It writes nothing: wand shows the proposals and saves the ones
the user keeps.

Run as `checkfinder.py [repo]`: prints the proposals as JSON, or says there are none.
"""
import json
import pathlib
import re
import sys

KEYWORDS = ("test", "lint", "check", "pytest", "unittest", "build")
NPM_SCRIPTS = (("test", "npm test"), ("lint", "npm run lint"))
TEST_FOLDERS = ("tests", "test")
DEFAULT_GLOB = "**"
NONE_FOUND = "No check commands found (no CI workflow, package.json scripts or pytest folder); none proposed."
_RUN_LINE = re.compile(r"^(\s*)(-\s+)?run:\s*(.*?)\s*$")
_BLOCK_MARKERS = ("|", ">", "|-", ">-", "|+", ">+")


def _indent(line):
    return len(line) - len(line.lstrip())


def _run_commands(text):
    lines = text.splitlines()
    found = []
    for number, line in enumerate(lines):
        match = _RUN_LINE.match(line)
        if not match:
            continue
        value = match.group(3)
        if value not in _BLOCK_MARKERS:
            found.append(value.strip("\"'"))
            continue
        key_indent = len(match.group(1)) + (2 if match.group(2) else 0)
        for body in lines[number + 1:]:
            if body.strip() and _indent(body) <= key_indent:
                break
            found.append(body.strip())
    return found


def _from_workflows(repo):
    folder = repo / ".github" / "workflows"
    if not folder.is_dir():
        return []
    found = []
    for path in sorted(folder.glob("*.yml")):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        found += [c for c in _run_commands(text) if c and any(k in c.lower() for k in KEYWORDS)]
    return found


def _from_package_json(repo):
    try:
        data = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    scripts = data.get("scripts") if isinstance(data, dict) else None
    if not isinstance(scripts, dict):
        return []
    return [command for name, command in NPM_SCRIPTS if name in scripts]


def _from_pytest_folder(repo):
    for name in TEST_FOLDERS:
        folder = repo / name
        if folder.is_dir() and (any(folder.glob("test_*.py")) or any(folder.glob("*_test.py"))):
            return [f"python3 -m pytest {name}"]
    return []


def propose(repo):
    """The proposed checks, each {command, glob}, without repeats."""
    repo = pathlib.Path(repo)
    commands = _from_workflows(repo) + _from_package_json(repo) + _from_pytest_folder(repo)
    return [{"command": command, "glob": DEFAULT_GLOB} for command in dict.fromkeys(commands)]


def describe(proposals):
    if not proposals:
        return NONE_FOUND
    return json.dumps(proposals, indent=2)


def main(argv):
    print(describe(propose(argv[1] if len(argv) > 1 else ".")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
