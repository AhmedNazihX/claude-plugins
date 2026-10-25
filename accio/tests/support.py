"""Shared test helpers: make bin/ importable, and drive throwaway git repos."""
import errno
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))


REMOVE_ATTEMPTS = 5
REMOVE_WAIT = 0.2
_BUSY_ERRORS = (errno.ENOTEMPTY, errno.EBUSY)


def remove_tree(path, rmtree=shutil.rmtree, attempts=REMOVE_ATTEMPTS, wait=REMOVE_WAIT):
    """Delete a folder, retrying when git is still writing into it ("Directory not empty" or busy).

    Any other error, or a folder that stays busy after the last try, raises.
    """
    for attempt in range(1, attempts + 1):
        try:
            rmtree(path)
            return
        except OSError as error:
            if error.errno not in _BUSY_ERRORS or attempt == attempts:
                raise
            time.sleep(wait)


def remove_tmp(tmp):
    """Clean up a tempfile.TemporaryDirectory with the retrying delete (use in tearDown)."""
    if pathlib.Path(tmp.name).exists():
        remove_tree(tmp.name)
    _plain_cleanup(tmp)


_plain_cleanup = tempfile.TemporaryDirectory.cleanup
# Every test module imports this file, so every `self.tmp.cleanup()` gets the retrying delete.
tempfile.TemporaryDirectory.cleanup = remove_tmp


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def commit_all(cwd, message="snapshot"):
    git(cwd, "add", "-A")
    git(cwd, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def init_repo(path):
    """A git repo with one commit on main."""
    write(path / "README.md", "test repo\n")
    git(path, "init", "-q", "-b", "main")
    # an identity of its own: accio's scripts commit, rebase and merge, and a CI runner may have none (Linux)
    git(path, "config", "user.name", "t")
    git(path, "config", "user.email", "t@example.com")
    commit_all(path, "init")
    return path
