"""The transcript folders of this repo's brew runs, for owl's costs (DESIGN § 3.5, § 8; spike S-001 finding 4).

Claude Code keeps each session under `<config>/projects/<slug>/<session>/`, where the slug is the project path with
every character but a letter or digit turned into `-`, and each workflow run in `subagents/workflows/wf_<id>/`. A
brew run is one whose agents include portkey's `load` (the label brew gives it). The config folder is
`$CLAUDE_CONFIG_DIR`, else `~/.claude`.
"""
import json
import os
import pathlib
import re

WORKFLOW_GLOB = "*/subagents/workflows/wf_*"
BREW_LOAD = {"agentType": "accio:portkey", "description": "load"}
NOT_SLUG = re.compile(r"[^A-Za-z0-9]")


def projects_dir(environ=os.environ):
    return pathlib.Path(environ.get("CLAUDE_CONFIG_DIR") or pathlib.Path.home() / ".claude").expanduser() / "projects"


def project_slug(root):
    return NOT_SLUG.sub("-", str(root))


def _is_brew(folder):
    for meta in folder.glob("agent-*.meta.json"):
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError):
            continue
        if isinstance(data, dict) and all(data.get(key) == value for key, value in BREW_LOAD.items()):
            return True
    return False


def brew_runs(root, since=0.0, environ=os.environ):
    """This repo's brew run folders changed at or after `since` (a timestamp), oldest first."""
    folders = set()
    for path in {str(root), os.path.realpath(root)}:
        folders.update((projects_dir(environ) / project_slug(path)).glob(WORKFLOW_GLOB))
    found = [folder for folder in folders if folder.is_dir() and folder.stat().st_mtime >= since and _is_brew(folder)]
    return sorted(found, key=lambda folder: (folder.stat().st_mtime, folder.name))
