"""Path globs with `**` (DESIGN § 5.2 `risky_paths`, `checks`; the curfew hook later).

- `**/` matches any folders (or none); `*` and `?` stay inside one folder; everything else is literal.
- Like gitignore, a pattern that matches a folder covers everything inside it (`infra` and `infra/` both cover
  `infra/main.tf`; `**/*secret*` covers `config/secrets/prod.env`).
- Paths must be repo-relative: `./a` and `a//b` are normalised, absolute paths raise GlobError.
Works on Python 3.12 (CI) as well as later versions.
"""
import functools
import posixpath
import re


class GlobError(ValueError):
    """A path that can't be matched, written for the user."""


@functools.lru_cache(maxsize=256)
def _compile(pattern):
    parts, index = [], 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("".join(parts), re.DOTALL)


def normalise(path):
    """The repo-relative POSIX form of a path; raises GlobError for an absolute path."""
    if path.startswith("/"):
        raise GlobError(f"paths must be repo-relative, got {path!r}")
    clean = posixpath.normpath(path)
    if clean == ".." or clean.startswith("../"):
        raise GlobError(f"paths must stay inside the repo, got {path!r}")
    return clean


def match(path, pattern):
    """True when the path, or any folder above it, matches the glob."""
    compiled = _compile(pattern.rstrip("/"))
    segments = normalise(path).split("/")
    return any(compiled.fullmatch("/".join(segments[:end])) for end in range(len(segments), 0, -1))


def matches_any(path, patterns):
    return any(match(path, pattern) for pattern in patterns)
