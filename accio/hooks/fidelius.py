#!/usr/bin/env python3
"""fidelius: the PreToolUse Write/Edit guard (DESIGN § 4.4, § 6).

Blocks key-shaped values (the patterns of `accio_lib.secret_scan`, S-011) before they reach a file, and never
echoes the secret: a finding shows only its first characters. A Write's whole content is checked. An Edit or
MultiEdit is checked as the file would read after it, so a key split across pieces or finished by an edit is caught,
and a secret already in the file blocks nothing (an edit that removes one passes; the commit scan still refuses it).
A file that isn't UTF-8 is read byte for byte. When the file is over MAX_FILE_BYTES or an old string isn't found
(even with curly quotes folded), the new strings are checked joined both ways; the commit scan backs that up. A
NotebookEdit's new source is checked; list-valued text is joined. A guarded call the hook fails to check is blocked.

A real `.env` file is where secrets belong, so one is exempt when its real path has a `.env` name
(`secret_scan.is_secret_file`) with no template word in it (`example`, `sample`, `template`, `dist`), and git ignores
it (an untracked, ignored file, checked from its nearest existing folder). Symlinks are judged by their target. The
repo is found from the payload's `cwd` (the hook's folder when that is missing) and from the file's folder; either
one having `.accio/` turns the guard on. Exits 0 silently otherwise, for other tools and on bad input.
"""
import json
import os
import pathlib
import re
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "bin"))

from accio_lib import paths, secret_scan  # noqa: E402

BLOCK_EXIT = 2
PATH_KEYS = ("file_path", "notebook_path")
MAX_FILE_BYTES = 2_000_000
QUOTES = str.maketrans("\u2018\u2019\u201c\u201d", "''\"\"")
TEMPLATE_WORDS = frozenset({"example", "sample", "template", "dist"})
NAME_PARTS = re.compile(r"[._-]")


def target_path(tool_input):
    return next((tool_input[key] for key in PATH_KEYS if isinstance(tool_input.get(key), str)), "")


def _text(value):
    """A string, or a list of strings joined; anything else is empty."""
    if isinstance(value, list):
        return "".join(part for part in value if isinstance(part, str))
    return value if isinstance(value, str) else ""


def _edits(tool_name, tool_input):
    if tool_name == "Edit":
        return [tool_input]
    edits = tool_input.get("edits")
    return [edit for edit in edits if isinstance(edit, dict)] if isinstance(edits, list) else []


def _read(target):
    try:
        if os.path.getsize(target) > MAX_FILE_BYTES:
            return None
        return pathlib.Path(target).read_bytes().decode("utf-8", "surrogateescape")
    except (OSError, ValueError):
        return None


def _replace(text, old, new, every):
    """`text` with `old` replaced (the first, or `every` one), or None when it isn't there. Like the Edit tool, an
    old string with straight quotes also finds curly ones; folding keeps every length, so positions line up."""
    haystack, needle = (text, old) if old in text else (text.translate(QUOTES), old.translate(QUOTES))
    parts, start = [], 0
    while (found := haystack.find(needle, start)) != -1:
        parts += [text[start:found], new]
        start = found + len(needle)
        if not every:
            break
    return "".join(parts) + text[start:] if parts else None


def _apply(before, edits):
    """The file after these edits, or None when an old string isn't there (the tool would fail or create)."""
    text = before
    for edit in edits:
        old, new = _text(edit.get("old_string")), _text(edit.get("new_string"))
        text = _replace(text, old, new, edit.get("replace_all") is True) if old else None
        if text is None:
            return None
    return text


def written_text(tool_name, tool_input, target):
    """(text to check, secrets already in the file), or None for a tool fidelius doesn't check."""
    if tool_name == "Write":
        return _text(tool_input.get("content")), None
    if tool_name == "NotebookEdit":
        return _text(tool_input.get("new_source")), None
    if tool_name not in ("Edit", "MultiEdit"):
        return None
    edits = _edits(tool_name, tool_input)
    before = _read(target) if target else None
    after = _apply(before, edits) if before is not None else None
    if after is not None:
        return after, secret_scan.secret_values(before)
    pieces = [_text(edit.get("new_string")) for edit in edits]
    return "\n".join(pieces) + "\n" + "".join(pieces), None


def is_private_env_file(target):
    """A real, gitignored, untracked `.env` file (by its resolved path)."""
    try:
        real = pathlib.Path(os.path.realpath(target))
    except (OSError, ValueError):
        return False
    if not secret_scan.is_secret_file(real.name) or TEMPLATE_WORDS & set(NAME_PARTS.split(real.name.lower())):
        return False
    folder = paths.existing_folder(real)
    try:
        result = subprocess.run(["git", "-C", str(folder), "check-ignore", "-q", "--", os.path.relpath(real, folder)],
                                capture_output=True, check=False)
    except OSError:
        return False
    return result.returncode == 0


def check(payload):
    """The block message for this tool call, or None."""
    tool_input = payload["tool_input"]
    target = target_path(tool_input)
    checked = written_text(payload.get("tool_name"), tool_input, target)
    if checked is None or not checked[0]:
        return None
    if target and is_private_env_file(target):
        return None
    text, known = checked
    findings = secret_scan.find_secrets(text, target, known)
    return secret_scan.describe(os.path.basename(target) or "this file", findings) if findings else None


def is_guarded(payload):
    """True when the session's folder or the file's folder is in a repo with `.accio/`."""
    return paths.guarding_accio_dir(payload.get("cwd"), target_path(payload["tool_input"])) is not None


def _payload(raw):
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) and isinstance(payload.get("tool_input"), dict) else None


def main():
    payload = _payload(sys.stdin.read())
    if payload is None or not is_guarded(payload):
        return 0
    try:
        reason = check(payload)
    except Exception as error:  # noqa: BLE001 — a guard that crashes must stop the write, not wave it through
        reason = (f"could not check this write ({type(error).__name__}), so it is stopped. Write the file without "
                  "secrets, or ask the user to look at the hook.")
    if reason:
        print(f"fidelius (accio's secret keeper): {reason}", file=sys.stderr)
        return BLOCK_EXIT
    return 0


if __name__ == "__main__":
    sys.exit(main())
