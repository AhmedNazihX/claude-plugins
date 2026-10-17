"""The verdict ledger, `run/ledger.tsv` (DESIGN § 12.4): never pay twice for a verdict on the same work.

key = sha256(work digest + sha(config checks) + panel id + sha(the story's DoD))
work digest = sha256(the tree at `from` + the exact diff from..head)
from = the merge-base with base, or the parent's head for a stacked child.

The diff covers the whole range, so the same change split into different commits gets the same key, while any
byte of difference (whitespace included) or a moved base gives a new one. The diff comes from plumbing with every
display setting off, so the user's git config can't change it. A worktree with uncommitted work is refused: the
checks would see work the key doesn't. Each ledger line is `<id> TAB <key> TAB <verdict>`; the latest line for an
(id, key) pair wins.
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import tempfile

from accio_lib import runlock

LEDGER_NAME = "ledger.tsv"
VERDICTS = ("pass", "fail")
LEDGER_ID = re.compile(r"^[SQ]-\d+$")
KEY_TEXT = re.compile(r"^[0-9A-Za-z]+$")
DIFF_COMMAND = ("diff-tree", "-r", "-p", "--binary", "--full-index", "--no-textconv", "--no-ext-diff", "--no-color",
                "--no-renames")


class LedgerError(Exception):
    """A ledger problem, written for the user."""


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _git_bytes(worktree, *args):
    """Run git and return its raw stdout bytes (diffs are never decoded, so any file encoding is fine)."""
    try:
        result = subprocess.run(["git", *args], cwd=worktree, capture_output=True, check=False)
    except OSError as error:
        raise LedgerError(f"git could not run in {worktree}: {error}") from error
    if result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise LedgerError(f"git {' '.join(args)} failed in {worktree}: {message}")
    return result.stdout


def _git(worktree, *args):
    return _git_bytes(worktree, *args).decode("utf-8", errors="replace")


def diff_base(worktree, base_branch, parent=None):
    """The commit the story's diff starts from: the parent's head when stacked, else the merge-base with base."""
    if parent:
        return _git(worktree, "rev-parse", "--verify", f"{parent}^{{commit}}").strip()
    return _git(worktree, "merge-base", base_branch, "HEAD").strip()


def work_digest(worktree, start, head="HEAD"):
    """sha256 of the tree at `start` and the exact diff start..head; refuses a worktree with uncommitted work."""
    if _git(worktree, "status", "--porcelain", "--untracked-files=all").strip():
        raise LedgerError(f"the worktree {worktree} has uncommitted changes; commit them before keying a verdict")
    start_tree = _git(worktree, "rev-parse", f"{start}^{{tree}}").strip()
    diff = _git_bytes(worktree, *DIFF_COMMAND, start, head)
    return hashlib.sha256(start_tree.encode("ascii") + b"\n" + diff).hexdigest()


def dod_digest(parsed_story):
    return _sha("\n".join(f"{line.id}|{line.testable}|{line.text}" for line in parsed_story.dod))


def key(work, checks, panel, parsed_story):
    checks_text = json.dumps([dict(check) for check in checks], sort_keys=True)
    return _sha("\n".join((work, _sha(checks_text), panel, dod_digest(parsed_story))))


def _ledger_path(run_dir):
    return run_dir / LEDGER_NAME


def _validate(story_id, entry_key, verdict=None):
    if not LEDGER_ID.match(story_id):
        raise LedgerError(f"ledger id must look like S-012 or Q-3, got {story_id!r}")
    if not KEY_TEXT.match(entry_key):
        raise LedgerError(f"key must be letters and digits only, got {entry_key!r}")
    if verdict is not None and verdict not in VERDICTS:
        raise LedgerError(f"verdict must be one of {', '.join(VERDICTS)}, got {verdict!r}")


def entries(run_dir):
    """Every ledger line as (id, key, verdict); raises LedgerError naming a corrupt line."""
    path = _ledger_path(run_dir)
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError) as error:
        raise LedgerError(f"{path} cannot be read: {error}") from error
    found = []
    for number, line in enumerate(lines, start=1):
        fields = line.split("\t")
        if len(fields) != 3 or fields[2] not in VERDICTS:
            raise LedgerError(f"{path}:{number}: expected '<id> TAB <key> TAB <verdict>', got {line!r}")
        found.append(tuple(fields))
    return tuple(found)


def has_pass(run_dir, story_id, entry_key):
    """True when the latest verdict recorded for this exact key is a pass."""
    verdicts = [verdict for sid, k, verdict in entries(run_dir) if sid == story_id and k == entry_key]
    return bool(verdicts) and verdicts[-1] == "pass"


def record(run_dir, story_id, entry_key, verdict):
    _validate(story_id, entry_key, verdict)
    with runlock.guard(run_dir):
        try:
            with _ledger_path(run_dir).open("a", encoding="utf-8") as stream:
                stream.write(f"{story_id}\t{entry_key}\t{verdict}\n")
        except OSError as error:
            raise LedgerError(f"cannot write {_ledger_path(run_dir)}: {error}") from error


def clear(run_dir, story_id):
    """Delete every entry for one story (a rejection at owl does this); readers see the old file or the new one."""
    if not LEDGER_ID.match(story_id):
        raise LedgerError(f"ledger id must look like S-012 or Q-3, got {story_id!r}")
    with runlock.guard(run_dir):
        kept = [entry for entry in entries(run_dir) if entry[0] != story_id]
        path = _ledger_path(run_dir)
        temporary = None
        try:
            handle, temporary = tempfile.mkstemp(dir=run_dir, prefix=f".{LEDGER_NAME}.")
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write("".join("\t".join(entry) + "\n" for entry in kept))
            os.replace(temporary, path)
        except OSError as error:
            if temporary:
                pathlib.Path(temporary).unlink(missing_ok=True)
            raise LedgerError(f"cannot write {path}: {error}") from error
