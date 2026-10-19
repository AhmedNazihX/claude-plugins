#!/usr/bin/env python3
"""session-start: what a new session in an accio repo should know (DESIGN § 4.4, § 10; S-012's outcome).

Injects at most MAX_LINES lines as `additionalContext`: the board summary, the next step, and the plain-words rule
(plugins can't ship rules). With `CLAUDE_CODE_DISABLE_WORKFLOWS` set, `/accio:brew` doesn't exist, so it says the
build needs workflows and how to turn them on (decision 012: no fallback build in v1); the `disableWorkflows`
setting is invisible here (spike S-001), and `prophecy` and `map` catch that case. It runs `accio-hooks verify` quietly, so a path a plugin update made stale is rewritten at once,
and mentions only the problems verify can't fix; where no accio helper exists (hooks never installed, or
uninstalled) it writes nothing. No text from the repo's files reaches the context: problems are named by kind and
count, and `/accio:map` or `accio-hooks verify` show the details. Every line is one line of at most LINE_CHARS
characters. Prints nothing in a repo without `.accio/`, and never fails a session start.
"""
import json
import os
import pathlib
import sys

BIN = pathlib.Path(__file__).resolve().parents[1] / "bin"
sys.path.insert(0, str(BIN))

from accio_lib import board, githooks, nextstep, paths, story  # noqa: E402

MAX_LINES = 10
LINE_CHARS = 240
PLAIN_WORDS = ("accio: talk to the user in plain words: short sentences, no jargon, and say what a term means the "
               "first time you use it.")


def _cwd(raw):
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        payload = {}
    cwd = payload.get("cwd") if isinstance(payload, dict) else None
    return cwd if isinstance(cwd, str) else os.getcwd()


def _board_lines(accio, workflows_off):
    try:
        stories = board.load_stories(accio)
        status = board.statuses(stories, board.read_overrides(accio))
    except (board.BoardError, story.StoryError, OSError):
        return ["accio: the board can't be read (a story file or run/status.json has a problem); run /accio:map to "
                "see which."]
    sentence = nextstep.next_step(accio, status, workflows_off)["sentence"]
    return [f"accio: {board.summary(status)}.", f"accio: next, {sentence}"]


def _hook_lines(root):
    """Where accio's helper exists, run verify (it rewrites a stale helper itself); a line for what it can't fix."""
    try:
        if githooks.read_helper(root) is None:
            return []
        count = len(githooks.verify(root, BIN / "accio-hooks")[0])
    except githooks.HooksError:
        count = 1
    if not count:
        return []
    return [f"accio-hooks: accio's git hooks have {count} problem{'' if count == 1 else 's'} verify can't fix; run "
            "`accio-hooks verify` to see what to do."]


def _short(line):
    """One line of at most LINE_CHARS characters."""
    line = " ".join(line.split())
    return line if len(line) <= LINE_CHARS else line[:LINE_CHARS - 1] + "…"


def context_lines(root, accio, environ):
    workflows_off = bool(environ.get("CLAUDE_CODE_DISABLE_WORKFLOWS"))
    lines = _board_lines(accio, workflows_off) + [PLAIN_WORDS]
    if workflows_off:
        lines.append("accio: workflows are off (CLAUDE_CODE_DISABLE_WORKFLOWS), and accio's build needs them: unset "
                     "it, then use /accio:brew.")
    return [_short(line) for line in lines + _hook_lines(root)][:MAX_LINES]


def main():
    cwd = _cwd(sys.stdin.read())
    try:
        accio = paths.accio_dir(cwd) if os.path.isdir(cwd) else None
    except (OSError, ValueError):
        accio = None
    if accio is None:
        return 0
    try:
        lines = context_lines(accio.parent, accio, os.environ)
    except Exception as error:  # noqa: BLE001 — a session must start whatever goes wrong here
        lines = [f"accio: session-start couldn't read the project ({type(error).__name__}); run /accio:map."]
    print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart",
                                             "additionalContext": "\n".join(lines)}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
