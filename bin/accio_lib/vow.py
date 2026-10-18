"""Decision records, `.accio/decisions/NNN-<slug>.md` (DESIGN § 3.7, § 12.2): numbered, checked, committed alone.

`next_record` gives the path for a new record: one past the highest number already there, and a slug of the title
(ASCII letters and digits, dashes between words). `record` checks a record before committing it: its file is under
`.accio/decisions/`, its heading carries the same number as its name, and it has every section a decision needs.
It commits only that file (`git commit --only`).
"""
import re
import unicodedata

from accio_lib import storyfiles

DECISIONS = "decisions"
RECORD_FILE = re.compile(r"^(\d{3,})-[a-z0-9-]+\.md$")
SECTIONS = ("## What was decided", "## Options", "## Decision", "## Why")
COMMIT_MESSAGE = "docs(accio): decision {number} {title}"
SLUG_WORDS = 8


class VowError(Exception):
    """A decision-record problem, written for the user."""


def slug(title):
    plain = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode().lower()
    words = re.findall(r"[a-z0-9]+", plain)[:SLUG_WORDS]
    if not words:
        raise VowError(f"the title {title!r} has no letters or digits to name the file by")
    return "-".join(words)


def next_record(accio, title):
    folder = accio / DECISIONS
    numbers = [int(match.group(1)) for path in folder.glob("*.md") if (match := RECORD_FILE.match(path.name))]
    number = max(numbers, default=0) + 1
    return {"number": number, "path": str(folder / f"{number:03d}-{slug(title)}.md")}


def _checked(accio, path):
    if path.resolve().parent != (accio / DECISIONS).resolve() or not RECORD_FILE.match(path.name):
        raise VowError(f"a decision record is .accio/decisions/NNN-<slug>.md, not {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise VowError(f"cannot read {path}: {error}") from error
    number = RECORD_FILE.match(path.name).group(1)
    heading = re.match(rf"^# {number} — (.+)$", text.split("\n", 1)[0])
    if not heading:
        raise VowError(f"{path.name} must start with the heading `# {number} — <title>`")
    missing = [section for section in SECTIONS if not re.search(rf"^{re.escape(section)}\s*$", text, re.MULTILINE)]
    if missing:
        raise VowError(f"{path.name} lacks {', '.join(missing)}; a decision record needs {', '.join(SECTIONS)}")
    return number, heading.group(1).strip()


def record(accio, path):
    """Commit one complete decision record; returns {path, commit, commit_error}."""
    number, title = _checked(accio, path)
    commit, why = storyfiles.commit(accio.parent, [str(path)], COMMIT_MESSAGE.format(number=number, title=title))
    return {"path": str(path), "commit": commit, "commit_error": why}
