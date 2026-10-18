"""Where a shell word points, judged without running anything (protego's `rm` check, S-013; curfew's worktree
check, S-015).

A word is expanded as bash would before it is judged: brace lists (`{a,b}`) give every alternative, `~` and
`$VAR` are filled in, `$PWD` is the folder being judged, and `$OLDPWD`, a variable assigned anywhere in the command
(or `~` once `HOME` is) and anything else unknowable count as unknowable. `cd`/`pushd` move the folder; one to a
folder that can't be known gives None, except `cd "$(git rev-parse --show-toplevel)"`, which is the repo root.
"""
import os
import pathlib
import re
import tempfile

from accio_lib import paths

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
VARIABLE = re.compile(r"\$(?:\{(\w+)\}|(\w+))")
UNRESOLVABLE = re.compile(r"[$`{]|^~")
BRACE_LIST = re.compile(r"\{([^{}]*,[^{}]*)\}")
MAX_ALTERNATIVES = 64
WHOLE_FOLDER_GLOBS = ("*", ".*")
TEMP_ROOTS = tuple(dict.fromkeys(pathlib.Path(os.path.realpath(folder))
                                 for folder in (tempfile.gettempdir(), "/tmp", "/var/tmp")))
TOPLEVEL = "$(git rev-parse --show-toplevel)"
CD_OPTIONS = {"-L", "-P", "-e", "-@"}
PUSHD_STACK = re.compile(r"^[+-]\d+$")
READERS = {"read", "mapfile", "readarray"}


def assigned_names(segment_words):
    """Every variable the command itself sets, so its value is unknowable here."""
    names = set()
    for words in segment_words:
        names |= {word.partition("=")[0] for word in words if ASSIGNMENT.match(word)}
        if len(words) > 1 and words[0] == "for":
            names.add(words[1])
        if words and words[0] in READERS:
            names |= {word for word in words[1:] if NAME.match(word)}
    return frozenset(names)


def expand(text, cwd, assigned=frozenset()):
    def value(match):
        name = match.group(1) or match.group(2)
        if name in assigned or name == "OLDPWD":
            return match.group(0)
        if name == "PWD":
            return cwd or match.group(0)
        return os.environ.get(name, match.group(0))
    text = VARIABLE.sub(value, text)
    return text if text.startswith("~") and "HOME" in assigned else os.path.expanduser(text)


def brace_alternatives(word):
    """bash's brace expansion of comma lists; too many alternatives leaves the word as written (unknowable)."""
    match = BRACE_LIST.search(word)
    if not match:
        return (word,) if word else ()
    results = []
    for option in match.group(1).split(","):
        results.extend(brace_alternatives(word[:match.start()] + option + word[match.end():]))
        if len(results) > MAX_ALTERNATIVES:
            return (word,)
    return tuple(dict.fromkeys(results))


def target_path(target, cwd, assigned=frozenset()):
    """Where a target points, symlinks resolved (all the way for a bare `*` or a trailing `/`, which act on the
    folder's contents; else up to the last part, so a symlink is judged by where it sits); None if unknowable."""
    expanded = expand(target, cwd, assigned)
    if UNRESOLVABLE.search(expanded):
        return None
    contents = target.endswith("/") or os.path.basename(expanded) in WHOLE_FOLDER_GLOBS
    if os.path.basename(expanded) in WHOLE_FOLDER_GLOBS:
        expanded = os.path.dirname(expanded) or "."
    try:
        joined = os.path.normpath(os.path.join(cwd, expanded))
        if contents:
            return pathlib.Path(os.path.realpath(joined))
        return pathlib.Path(os.path.realpath(os.path.dirname(joined))) / os.path.basename(joined)
    except (ValueError, OSError):  # a NUL, or a folder that can't be read
        return None


def is_temp_scratch(path, root):
    """Inside a temp folder, but away from the repo: not its parent folder (siblings, worktrees) or above it."""
    in_temp = any(path != temp and path.is_relative_to(temp) for temp in TEMP_ROOTS)
    return in_temp and not path.is_relative_to(root.parent) and not root.is_relative_to(path)


def deletable(target, cwd, root, assigned=frozenset()):
    """True for a path strictly inside the repo or one of its story worktrees (never a `.git`), or temp scratch.
    With the folder unknowable (cwd None), a relative target counts as outside."""
    if cwd is None and not os.path.isabs(expand(target, None, assigned)):
        return False
    path = target_path(target, cwd or "/", assigned)
    if path is None:
        return False
    worktrees = paths.worktree_root(root)
    areas = [root] + ([worktrees / path.relative_to(worktrees).parts[0]]
                      if path != worktrees and path.is_relative_to(worktrees) else [])
    inside = any(path != area and path.is_relative_to(area) and not path.is_relative_to(area / ".git")
                 for area in areas)
    return inside or is_temp_scratch(path, root)


def cd(cwd, argv, root, assigned=frozenset()):
    """The folder after `cd`/`pushd` (argv includes the command name), or None when it can't be known."""
    args = list(argv[1:])
    if os.path.basename(argv[0]) == "pushd" and (not args or args[0] == "-n" or PUSHD_STACK.match(args[0])):
        return None
    while args and args[0] in CD_OPTIONS:
        args = args[1:]
    args = args[1:] if args[:1] == ["--"] else args
    raw = args[0] if args else "~"
    if raw == TOPLEVEL:
        return str(root)
    target = expand(raw, cwd, assigned)
    if cwd is None or target == "-" or UNRESOLVABLE.search(target):
        return None
    try:
        return os.path.normpath(os.path.join(cwd, target))
    except ValueError:
        return None
