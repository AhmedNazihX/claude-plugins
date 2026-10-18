"""Shared test helpers: make bin/ importable, and drive throwaway git repos."""
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
if str(ROOT / "bin") not in sys.path:
    sys.path.insert(0, str(ROOT / "bin"))


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
    commit_all(path, "init")
    return path
