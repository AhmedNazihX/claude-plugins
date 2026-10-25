"""Find the main checkout and its `.accio/` from the main checkout or any worktree (DESIGN § 4.6).

Story worktrees live outside the repo, so a linked worktree resolves through git's common dir, never the current
folder. Submodules and `--separate-git-dir` checkouts resolve through their own top level. Not supported: a linked
worktree of a `--separate-git-dir` repo, because git doesn't record that repo's main checkout (setup warns, S-012).
Any failure gives None, so hooks can exit silently and never crash.
"""
import os
import pathlib
import shutil
import subprocess

ACCIO_DIR_NAME = ".accio"
WORKTREE_ROOT_SUFFIX = "-accio-wt"
REPORTS_DIR_NAME = ".reports"  # house-elf's reports, beside the story worktrees (S-082)
REPORT_NAME = "build-report.md"  # house-elf writes it; a name Claude Code lets a subagent write (S-023)
EARLIER_REPORT_NAME = "earlier-build-report.md"  # an older build's report, moved beside a newer one (S-082)
RUN_PROBE = ".accio/run/x"  # git checks a path inside the run folder


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


def reports_dir(main):
    """Where house-elf's reports live: beside the story worktrees, so no reviewer's search of the main checkout or
    of a worktree passes over them (S-082)."""
    return worktree_root(main) / REPORTS_DIR_NAME


def report_path(main, story_id):
    """House-elf's report for one story: `<worktree root>/.reports/<ID>/build-report.md` (S-082)."""
    return reports_dir(main) / story_id / REPORT_NAME


def move_old_reports(main):
    """Move each report an older accio left in `.accio/run/<folder>/` (any letter case) to its place in `.reports/`,
    so the run folder, which a search from the main checkout passes over, never holds one (S-082). When that place
    already holds a report, the old one goes beside it as EARLIER_REPORT_NAME. Returns the new paths; an OSError is
    left to the caller."""
    run = pathlib.Path(main) / ACCIO_DIR_NAME / "run"
    if not run.is_dir():
        return []
    moved = []
    for folder in sorted(item for item in run.iterdir() if item.is_dir() and not item.is_symlink()):
        for old in sorted(item for item in folder.iterdir() if item.name.casefold() == REPORT_NAME):
            target = report_path(main, folder.name)
            if os.path.lexists(target):
                target = target.with_name(EARLIER_REPORT_NAME)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old), str(target))
            moved.append(target)
    return moved


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
