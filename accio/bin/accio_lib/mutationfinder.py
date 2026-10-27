#!/usr/bin/env python3
"""S-091: name the mutation tool that fits a repo, for wand's setup question (decision 011).

Reads the repo's marker files and prints the tool for each language it shows (comma separated), or "none known".
It writes nothing: wand asks the user, and writes `"mutation": false` on a no.

Run as `mutationfinder.py [repo]`.
"""
import os
import pathlib
import sys

NONE_KNOWN = "none known"
SKIPPED_FOLDERS = {"node_modules", "venv", "env", "target", "build", "dist", "site-packages"}
# (tool, marker file names, marker suffixes), in the order the tools are printed
TOOLS = (
    ("mutmut", ("pyproject.toml", "setup.py"), (".py",)),
    ("Stryker", ("package.json",), ()),
    ("cargo-mutants", ("Cargo.toml",), ()),
    ("Muter", ("Package.swift",), (".xcodeproj",)),
)


def _entries(repo):
    """Every file and folder name in the repo, leaving out hidden and dependency folders."""
    for folder, subfolders, files in os.walk(repo):
        subfolders[:] = [name for name in subfolders
                         if not name.startswith(".") or name.endswith(".xcodeproj")]
        yield from files
        yield from subfolders
        subfolders[:] = [name for name in subfolders if name not in SKIPPED_FOLDERS]


def find(repo):
    """The tools that fit the repo, each once, in a fixed order."""
    names = set(_entries(pathlib.Path(repo)))
    return [tool for tool, markers, suffixes in TOOLS
            if names & set(markers) or any(name.endswith(suffixes) for name in names if suffixes)]


def describe(tools):
    return ", ".join(tools) if tools else NONE_KNOWN


def main(argv):
    print(describe(find(argv[1] if len(argv) > 1 else ".")))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
