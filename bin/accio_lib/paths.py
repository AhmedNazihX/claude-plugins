"""Find the main checkout and its `.accio/` from the main checkout or any worktree (DESIGN § 4.6).

Story worktrees live outside the repo, so a linked worktree resolves through git's common dir, never the current
folder. Submodules and `--separate-git-dir` checkouts resolve through their own top level. Not supported: a linked
worktree of a `--separate-git-dir` repo, because git doesn't record that repo's main checkout (setup warns, S-012).
Any failure gives None, so hooks can exit silently and never crash.
"""
import os
import pathlib
import subprocess

ACCIO_DIR_NAME = ".accio"
WORKTREE_ROOT_SUFFIX = "-accio-wt"


def _git(start, *args):
    try:
        result = subprocess.run(["git", *args], cwd=start, capture_output=True, text=True, check=False)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def main_root(start="."):
    """The main checkout's root, or None outside a git repo."""
    output = _git(start, "rev-parse", "--path-format=absolute", "--absolute-git-dir", "--git-common-dir")
    if output is None:
        return None
    git_dir, common_dir = (pathlib.Path(line) for line in output.splitlines()[:2])
    if git_dir == common_dir:
        top = _git(start, "rev-parse", "--show-toplevel")
        return pathlib.Path(top) if top else None
    configured = _git(start, "config", "--file", str(common_dir / "config"), "core.worktree")
    return (common_dir / configured).resolve() if configured else common_dir.parent


def worktree_root(main):
    """Where story worktrees live: outside the repo, so the project's tools never scan them (DESIGN § 5)."""
    return main.parent / f".{main.name}{WORKTREE_ROOT_SUFFIX}"


def accio_dir(start="."):
    """The main checkout's `.accio/`, or None when the repo has none (hooks then exit silently)."""
    root = main_root(start)
    if root is None:
        return None
    candidate = root / ACCIO_DIR_NAME
    return candidate if candidate.is_dir() else None


def existing_folder(path):
    folder = pathlib.Path(path).parent
    while not folder.is_dir() and folder != folder.parent:
        folder = folder.parent
    return folder


def guarding_accio_dir(cwd, target=""):
    """The `.accio/` that turns a Claude hook on: the session folder's (the hook's own folder when `cwd` is missing),
    else the file's (its nearest existing folder), so a call aimed into an accio repo is guarded from anywhere."""
    starts = [cwd if isinstance(cwd, str) and os.path.isdir(cwd) else os.getcwd()]
    if isinstance(target, str) and os.path.isabs(target):
        starts.append(existing_folder(target))
    for start in starts:
        try:
            found = accio_dir(start)
        except (ValueError, OSError):
            continue
        if found is not None:
            return found
    return None
