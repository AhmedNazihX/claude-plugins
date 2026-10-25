"""Setting accio up in a repo and recording its design (DESIGN § 3.1, § 12.1, § 12.2).

`init` creates `.accio/` in the main checkout (an empty `config.json`, which means every default, and a `stories/`
folder) and makes git ignore `.accio/run/`, the build's runtime state: it asks git whether that folder is ignored,
and only when it isn't appends one line to `.gitignore`, keeping the file's bytes and line endings. It never changes
what is already there, and it refuses a setup file that is a link pointing outside the repo (a cloned repo can carry
one), so a second run is harmless and nothing outside the repo is ever written.

`record_design` commits `.accio/design.md`, plus the setup files while the setup isn't committed yet (an untracked
`config.json`, a `.gitignore` whose committed version doesn't ignore `.accio/run/`), and nothing else the user
staged. The design needs an `## Outcome` with real text, outside any code block (decision 011). It refuses during a
build.
"""
import json
import os
import subprocess
import tempfile

from accio_lib import board, paths, runlock, storyfiles

RUN_IGNORE = ".accio/run/"
RUN_PROBE = paths.RUN_PROBE  # git checks a path inside the folder
DESIGN_NAME = "design.md"
UNSORTED_NAME = "unsorted.json"  # in run/: the new design headings sort hasn't turned into stories yet
OUTCOME = "## Outcome"
PLACEHOLDER = "<what should be true>"
COMMIT_MESSAGE = "docs(accio): design"


class DesignError(Exception):
    """A setup or design problem, written for the user."""


def _git(root, *args):
    try:
        return subprocess.run(["git", *args], cwd=root, capture_output=True, check=False)
    except OSError as error:
        raise DesignError(f"git could not run in {root}: {error}") from error


def _inside(root, path):
    """Refuse a setup file (or folder) that is a link leading outside the repo."""
    if os.path.lexists(path) and not os.path.realpath(path).startswith(os.path.realpath(root) + os.sep):
        raise DesignError(f"{path} links outside the repo ({os.path.realpath(path)}); accio won't write through it. "
                          "Replace the link with a plain file, then run setup again.")


def _ignore_text(root):
    """The new bytes of `.gitignore` when git doesn't ignore `.accio/run/` yet, else None."""
    if _git(root, "check-ignore", "-q", RUN_PROBE).returncode == 0:
        return None
    path = root / ".gitignore"
    try:
        current = path.read_bytes() if os.path.lexists(path) else b""
    except OSError as error:
        raise DesignError(f"cannot read {path}: {error}") from error
    eol = b"\r\n" if b"\r\n" in current else b"\n"
    return current + (b"" if not current or current.endswith(b"\n") else eol) + RUN_IGNORE.encode() + eol


def init():
    """Set accio up in this repo; returns {accio, created}."""
    root = paths.main_root()
    if root is None:
        raise DesignError("this folder isn't in a git repo; accio needs one (run `git init` first)")
    accio = root / paths.ACCIO_DIR_NAME
    for path in (accio, accio / "config.json", accio / "stories", root / ".gitignore"):
        _inside(root, path)
    if os.path.lexists(accio) and not accio.is_dir():
        raise DesignError(f"{accio} exists but isn't a folder; move it away and run setup again")
    created = not os.path.lexists(accio)
    texts = {}
    if not os.path.lexists(accio / "config.json"):
        texts[accio / "config.json"] = "{}\n"
    ignore = _ignore_text(root)
    if ignore is not None:
        texts[root / ".gitignore"] = ignore
    try:
        (accio / "stories").mkdir(parents=True, exist_ok=True)
        if texts:
            storyfiles.write_all(texts, "accio's setup")
    except (OSError, storyfiles.WriteError) as error:
        raise DesignError(f"cannot set accio up in {root}: {error}") from error
    return {"accio": str(accio), "created": created}


def _check_outcome(design, text):
    body = storyfiles.sections(text).get(OUTCOME)
    if not body or PLACEHOLDER in body:
        raise DesignError(f"{design} needs an `{OUTCOME}` section with real text (outside any code block): what "
                          "should be true after it ships, and how we'd know (decision 011)")


def _setup_files(accio):
    """The setup files that aren't committed yet: a config.json that is untracked or changed (S-089: check commands
    a design note adds go in with it), a .gitignore that HEAD doesn't have ignoring .accio/run/."""
    root = accio.parent
    files = []
    config = accio / "config.json"
    if config.exists() and _git(root, "status", "--porcelain", "--", str(config)).stdout.strip():
        files.append(config)
    ignore = root / ".gitignore"
    committed = _git(root, "show", "HEAD:.gitignore")
    lines = committed.stdout.decode("utf-8", "replace").splitlines() if committed.returncode == 0 else []
    if ignore.exists() and RUN_IGNORE not in (line.strip() for line in lines):
        files.append(ignore)
    return files


def _new_headings(accio, text):
    """The `## ` headings of `text` that the committed design.md lacks; all of them when none is committed."""
    committed = _git(accio.parent, "show", f"HEAD:.accio/{DESIGN_NAME}")
    old = storyfiles.sections(committed.stdout.decode("utf-8", "replace")) if committed.returncode == 0 else {}
    return [heading for heading in storyfiles.sections(text) if heading not in old]


def write_unsorted(accio, headings):
    """Write the headings sort hasn't turned into stories yet to run/unsorted.json (an empty list when none)."""
    path = board.run_dir(accio) / UNSORTED_NAME
    try:  # a temp file swapped in replaces a symlink at `path` instead of writing through it
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(list(headings)) + "\n")
        os.replace(temporary, path)
    except OSError as error:
        raise DesignError(f"cannot write {path}: {error}") from error


def _read_unsorted(accio):
    """The headings already waiting for sort; none when the file is missing or unreadable."""
    try:
        listed = json.loads((board.run_dir(accio) / UNSORTED_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [item for item in listed if isinstance(item, str)] if isinstance(listed, list) else []


def record_design(accio):
    """Commit the design (and the setup files the first time); returns {files, commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise DesignError("a build is running (run/brew.lock); record the design after it ends")
    design = accio / DESIGN_NAME
    try:
        text = design.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise DesignError(f"there is no {design} to record yet") from error
    except (OSError, UnicodeDecodeError) as error:
        raise DesignError(f"cannot read {design}: {error}") from error
    _check_outcome(design, text)
    files = [str(path) for path in (design, *_setup_files(accio))]
    waiting = _read_unsorted(accio)
    fresh = [heading for heading in _new_headings(accio, text) if heading not in waiting]
    commit, why = storyfiles.commit(accio.parent, files, COMMIT_MESSAGE)
    write_unsorted(accio, [*waiting, *fresh])
    return {"files": files, "commit": commit, "commit_error": why}
