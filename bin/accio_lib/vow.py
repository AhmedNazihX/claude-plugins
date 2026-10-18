"""Decision records, `.accio/decisions/NNN-<slug>.md` (DESIGN § 3.7, § 12.2): numbered, checked, committed alone.

`next_record` gives the path for a new record: one past the highest number on any numbered file there, and a short
slug of the title (ASCII letters and digits, dashes between words; `decision` when the title has none of those).
`record` checks a record before committing it: no build is running (nothing commits to main during one), its file is
under `.accio/decisions/`, no other record has its number, its heading carries that number, and every section a
decision needs is there and has text (a heading inside a ``` block doesn't count). It commits only that file.
"""
import re
import unicodedata

from accio_lib import runlock, storyfiles

DECISIONS = "decisions"
RECORD_FILE = re.compile(r"^(\d{3,})-[a-z0-9-]+\.md$")
NUMBERED = re.compile(r"^(\d+)\D")
FALLBACK_SLUG = "decision"
SLUG_CHARS = 60
SECTIONS = ("## What was decided", "## Options", "## Decision", "## Why")
COMMIT_MESSAGE = "docs(accio): decision {number} {title}"
SLUG_WORDS = 8


class VowError(Exception):
    """A decision-record problem, written for the user."""


def slug(title):
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", plain)[:SLUG_WORDS]
    return "-".join(words)[:SLUG_CHARS].strip("-") or FALLBACK_SLUG


def _no_build(accio):
    if runlock.is_held(accio / "run"):
        raise VowError("a build is running (run/brew.lock), and nothing new reaches the main checkout during one; "
                       "record the decision after it ends")


def next_record(accio, title):
    _no_build(accio)
    folder = accio / DECISIONS
    numbers = [int(match.group(1)) for path in folder.iterdir() if (match := NUMBERED.match(path.name))] \
        if folder.is_dir() else []
    number = max(numbers, default=0) + 1
    return {"number": number, "path": str(folder / f"{number:03d}-{slug(title)}.md")}


def _checked(accio, path):
    if path.resolve().parent != (accio / DECISIONS).resolve() or not RECORD_FILE.match(path.name):
        raise VowError(f"a decision record is .accio/decisions/NNN-<slug>.md, not {path}")
    number = RECORD_FILE.match(path.name).group(1)
    twins = sorted(other.name for other in path.parent.iterdir() if other.name != path.name
                   and (match := NUMBERED.match(other.name)) and int(match.group(1)) == int(number))
    if twins:
        raise VowError(f"{', '.join(twins)} already has number {number}; run `accio-vow next` for a free one")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise VowError(f"cannot read {path}: {error}") from error
    heading = re.match(rf"^# {number} — (.+)$", text.split("\n", 1)[0].rstrip("\r"))
    if not heading:
        raise VowError(f"{path.name} must start with the heading `# {number} — <title>`")
    found = storyfiles.sections(text)
    missing = [section for section in SECTIONS if section not in found]
    if missing:
        raise VowError(f"{path.name} lacks {', '.join(missing)}; a decision record needs {', '.join(SECTIONS)}")
    empty = [section for section in SECTIONS if not found[section]]
    if empty:
        raise VowError(f"in {path.name}, {' and '.join(empty)} is empty")
    return number, heading.group(1).strip()


def record(accio, path):
    """Commit one complete decision record; returns {path, commit, commit_error}."""
    _no_build(accio)
    number, title = _checked(accio, path)
    commit, why = storyfiles.commit(accio.parent, [str(path)], COMMIT_MESSAGE.format(number=number, title=title))
    return {"path": str(path), "commit": commit, "commit_error": why}
