"""Parse a story file (DESIGN § 5.1): a strict frontmatter subset plus numbered DoD lines.

Frontmatter rules:
- one `key: value` per line, only the keys in KEYS; a line starting with `#` is a comment
- list keys (`deps`, `files`) are written `[a, b]`; `budget_tokens` is a whole number
- a trailing ` # comment` is stripped from every key except the free-text ones (`title`, `dropped`)

The `## Definition of Done` section is required and holds only lines like `- [ ] S-012/1 WHEN …`, optionally
grouped under `###` sub-headings; the section ends at the next `#` or `##` heading. Every problem
raises StoryError as `<file>:<line>: <what>`, so a person can fix it; nothing is skipped silently.
"""
import dataclasses
import re
import types

from accio_lib.frozen import freeze

STATUSES = ("backlog", "ready", "doing", "review", "done", "blocked", "dropped")
TRACKS = ("quick", "story", "feature")
COMMIT_TYPES = ("feat", "fix", "refactor", "perf", "docs", "test", "build", "ci", "chore", "style", "revert")
REQUIRED = ("id", "title", "track", "status")
LIST_KEYS = ("deps", "files")
TEXT_KEYS = ("title", "dropped")
KEYS = ("id", "title", "type", "track", "status", "deps", "files", "risk", "budget_tokens", "dropped")
ENUMS = {"status": STATUSES, "track": TRACKS, "type": COMMIT_TYPES}
MARKER = "---"
DOD_HEADING = "## Definition of Done"
NO_TEST = "(no test)"
STORY_ID = re.compile(r"^S-\d{3,}$")
TRAILING_COMMENT = re.compile(r"\s+#\s.*$")
WHOLE_NUMBER = re.compile(r"^\d+$")
DOD_LINE = re.compile(r"^- \[( |x)\] (\S+) (.+)$")
SECTION_HEADING = re.compile(r"^#{1,2} ")
SUBHEADING = re.compile(r"^#{3,} ")


class StoryError(Exception):
    """A story file problem, as `<file>:<line>: <what>`."""


@dataclasses.dataclass(frozen=True)
class DodLine:
    id: str
    text: str
    testable: bool
    done: bool


@dataclasses.dataclass(frozen=True)
class Story:
    path: object
    meta: types.MappingProxyType
    dod: tuple
    body: str


def _fail(path, line, message):
    raise StoryError(f"{path}:{line}: {message}")


def _value(path, number, key, raw):
    if key in LIST_KEYS:
        if not (raw.startswith("[") and raw.endswith("]")):
            _fail(path, number, f"{key} must be a list like [S-010], got {raw!r}")
        return tuple(item.strip() for item in raw[1:-1].split(",") if item.strip())
    if key == "budget_tokens":
        if not WHOLE_NUMBER.match(raw):
            _fail(path, number, f"budget_tokens must be a whole number, got {raw!r}")
        return int(raw)
    return raw


def _entry(path, number, raw):
    """One frontmatter line as (key, value), or None for a blank or comment line."""
    if not raw.strip() or raw.strip().startswith("#"):
        return None
    key, separator, value = raw.partition(":")
    key = key.strip()
    if not separator or not key:
        _fail(path, number, f"expected 'key: value', got {raw.strip()!r}")
    if key not in KEYS:
        _fail(path, number, f"unknown key {key!r}; known keys are {', '.join(KEYS)}")
    value = value.strip() if key in TEXT_KEYS else TRAILING_COMMENT.sub("", value).strip()
    return key, _value(path, number, key, value)


def _frontmatter(path, lines):
    """Return (meta, line number of each key, index of the closing marker)."""
    if not lines or lines[0].strip() != MARKER:
        _fail(path, 1, f"a story file must start with a {MARKER} line")
    meta, where = {}, {}
    for index, raw in enumerate(lines[1:], start=1):
        if raw.strip() == MARKER:
            return meta, where, index
        entry = _entry(path, index + 1, raw)
        if entry is None:
            continue
        key, value = entry
        if key in meta:
            _fail(path, index + 1, f"{key} is set twice")
        meta[key], where[key] = value, index + 1
    _fail(path, 1, f"the frontmatter has no closing {MARKER} line")


def _validate(path, meta, where):
    missing = [key for key in REQUIRED if key not in meta]
    if missing:
        _fail(path, 1, f"missing required key {', '.join(missing)}")
    if not STORY_ID.match(meta["id"]):
        _fail(path, where["id"], f"id must look like S-012, got {meta['id']!r}")
    for key, allowed in ENUMS.items():
        if key in meta and meta[key] not in allowed:
            _fail(path, where[key], f"{key} must be one of {', '.join(allowed)}, got {meta[key]!r}")
    bad_deps = [dep for dep in meta.get("deps", ()) if not STORY_ID.match(dep)]
    if bad_deps:
        _fail(path, where["deps"], f"deps must be story ids like S-010, got {', '.join(bad_deps)}")


def _dod_line(path, number, story_id, raw):
    match = DOD_LINE.match(raw)
    if not match:
        _fail(path, number, f"a DoD line must read '- [ ] {story_id}/1 WHEN …', got {raw.strip()!r}")
    mark, line_id, text = match.groups()
    prefix, _, suffix = line_id.partition("/")
    if prefix != story_id or not suffix.isdigit():
        _fail(path, number, f"DoD id {line_id!r} must be {story_id}/<number>")
    testable = not text.startswith(NO_TEST)
    clean = text if testable else text[len(NO_TEST):].strip()
    return DodLine(id=line_id, text=clean, testable=testable, done=mark == "x")


def _dod(path, story_id, lines, first_number):
    """Every non-blank line of the DoD section must be a DoD line; the section must exist and not be empty."""
    found, seen, inside, heading_at = [], set(), False, None
    for offset, raw in enumerate(lines):
        number = first_number + offset
        if SECTION_HEADING.match(raw):
            inside = raw.strip() == DOD_HEADING
            heading_at = number if inside else heading_at
            continue
        if not inside or not raw.strip() or SUBHEADING.match(raw):
            continue
        line = _dod_line(path, number, story_id, raw)
        if line.id in seen:
            _fail(path, number, f"DoD id {line.id} appears twice")
        seen.add(line.id)
        found.append(line)
    if heading_at is None:
        _fail(path, first_number, f"the story has no '{DOD_HEADING}' section")
    if not found:
        _fail(path, heading_at, f"the '{DOD_HEADING}' section has no DoD lines")
    return tuple(found)


def section(parsed, heading):
    """The text under `## <heading>` in the story body, up to the next `#` or `##` heading ("" when absent)."""
    found, inside = [], False
    for raw in parsed.body.splitlines():
        if SECTION_HEADING.match(raw):
            inside = raw.strip() == f"## {heading}"
            continue
        if inside:
            found.append(raw)
    return "\n".join(found).strip()


def _read(path):
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise StoryError(f"{path}:1: cannot read the story file: {error}") from error


def parse(path):
    """Parse one story file; raises StoryError naming the file and line."""
    lines = _read(path)
    meta, where, closing = _frontmatter(path, lines)
    _validate(path, meta, where)
    body_lines = lines[closing + 1:]
    dod = _dod(path, meta["id"], body_lines, first_number=closing + 2)
    return Story(path=path, meta=freeze(meta), dod=dod, body="\n".join(body_lines))
