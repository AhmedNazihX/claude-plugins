#!/usr/bin/env python3
"""doc-size: the PreToolUse Read guard for long Markdown files (DESIGN § 4.4; analysis.md § 3.1).

A Markdown file (`.md`, `.markdown`, `.mdx`) over LIMIT_BYTES read whole fills the context with text the task
mostly doesn't need. Such a read is blocked with a pointer to the `librarian` agent (quotes with `file:line`) or to
reading by section. A section is a read with a `limit` of at most SECTION_LINES lines: an offset alone, or a large
limit, still loads up to 2000 lines, which is most of such a file. A shorter file, or any other file, passes. The repo is found from the session's folder or the
file's (`paths.guarding_accio_dir`). Exits 0 silently in a repo without `.accio/` and on bad input.
"""
import json
import math
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))

from accio_lib import paths  # noqa: E402

BLOCK_EXIT = 2
LIMIT_BYTES = 40 * 1024
SECTION_LINES = 400
MARKDOWN = (".md", ".markdown", ".mdx")


def _target(raw):
    """The file a whole read would load, or None when this call isn't one doc-size checks."""
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None, None
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    if not isinstance(tool_input, dict) or not isinstance(tool_input.get("file_path"), str):
        return None, None
    limit = tool_input.get("limit")
    if isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= SECTION_LINES:
        return None, None
    path = tool_input["file_path"]
    return (path, payload.get("cwd")) if path.lower().endswith(MARKDOWN) else (None, None)


def main():
    path, cwd = _target(sys.stdin.read())
    if path is None or paths.guarding_accio_dir(cwd, path) is None:
        return 0
    try:
        size = os.path.getsize(path)
    except (OSError, ValueError):
        return 0
    if size <= LIMIT_BYTES:
        return 0
    print(f"doc-size (accio's long-document guard): {os.path.basename(path)} is {math.ceil(size / 1024)} KB, too long to read whole (over "
          f"{LIMIT_BYTES // 1024} KB). Ask the accio:librarian agent for the parts you need (it quotes them with "
          f"file:line), or read it by section: Grep for the heading, then Read with an offset and a limit of at most "
          f"{SECTION_LINES} lines.", file=sys.stderr)
    return BLOCK_EXIT


if __name__ == "__main__":
    sys.exit(main())
