"""The build's run lock, `run/brew.lock`, and the guard that serialises every run-state write (DESIGN § 4.5).

`portkey` takes the lock at step 0 and releases it in a `finally` block; every status move refreshes it. A lock with
no refresh for STALE_SECONDS counts as stale, so a crash can't block the user's pushes for ever. The `pre-push`
hook reads the same rule. Up to three stories move at once, so `take` and every status write hold `guard()`.
"""
import contextlib
import fcntl
import json
import os
import time

LOCK_NAME = "brew.lock"
CLAIMS_NAME = "claims.json"
ALLOW_ONCE_NAME = "allow-once.json"  # commands owl allowed once, per story, until its next build (S-022)
STATUS_NAME = "status.json"  # the build's statuses (accio_lib.board writes it)
GUARD_NAME = ".guard"
STALE_SECONDS = 30 * 60


class LockError(Exception):
    """The lock can't be taken or written, written for the user."""


def lock_path(run_dir):
    return run_dir / LOCK_NAME


@contextlib.contextmanager
def guard(run_dir):
    """Hold an exclusive OS lock on run/.guard while changing run state."""
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        handle = open(run_dir / GUARD_NAME, "a", encoding="utf-8")
    except OSError as error:
        raise LockError(f"cannot write {run_dir}: {error}") from error
    with handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def is_stale(path, now=None):
    """True when the lock exists but has not been refreshed for STALE_SECONDS."""
    try:
        age = (time.time() if now is None else now) - path.stat().st_mtime
    except FileNotFoundError:
        return False
    return age > STALE_SECONDS


def is_held(run_dir, now=None):
    """True while a build holds a fresh lock."""
    path = lock_path(run_dir)
    return path.exists() and not is_stale(path, now)


def release_claim(run_dir, story_id):
    """Drop every claim on a story, so the house-elf of its next brief (a fix round) can claim it (S-015)."""
    path = run_dir / CLAIMS_NAME
    with guard(run_dir):
        try:
            claims = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise LockError(f"cannot read {path}: {error}") from error
        kept = {agent: held for agent, held in claims.items()
                if not (isinstance(held, dict) and held.get("story") == story_id)} if isinstance(claims, dict) else {}
        try:
            temporary = path.with_name(f".{path.name}.tmp")
            temporary.write_text(json.dumps(kept, indent=2) + "\n", encoding="utf-8")
            os.replace(temporary, path)
        except OSError as error:
            raise LockError(f"cannot write {path}: {error}") from error


def take(run_dir):
    """Take the lock (holding the guard) and clear old worktree claims; returns a note if a stale lock was replaced."""
    path = lock_path(run_dir)
    with guard(run_dir):
        if is_held(run_dir):
            raise LockError(f"a build is already running ({path} was refreshed in the last {STALE_SECONDS // 60} min)")
        note = f"replaced a stale lock left by an earlier build ({path})" if path.exists() else ""
        try:
            path.write_text(f"{os.getpid()}\n", encoding="utf-8")
        except OSError as error:
            raise LockError(f"cannot write {path}: {error}") from error
        try:
            (run_dir / CLAIMS_NAME).unlink(missing_ok=True)
            _expire_grants(run_dir)  # a crashed build's stories used theirs
        except OSError as error:
            path.unlink(missing_ok=True)
            raise LockError(f"cannot start the build's run state in {run_dir}: {error}") from error
    return note


def _expire_grants(run_dir):
    """owl's one-build grants last until their story is built: drop those for the stories this build (or a crashed
    one) touched, which are the ones in run/status.json."""
    path = run_dir / ALLOW_ONCE_NAME
    try:
        grants = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return
    except (UnicodeDecodeError, ValueError):
        path.unlink(missing_ok=True)
        return
    try:
        built = json.loads((run_dir / STATUS_NAME).read_text(encoding="utf-8"))
    except FileNotFoundError:
        built = {}
    except (UnicodeDecodeError, ValueError):
        built = None  # can't tell which stories were built: drop every grant rather than keep a used one
    stories = grants.get("stories") if isinstance(grants, dict) else None
    left = {sid: commands for sid, commands in stories.items() if sid not in built} if (
        isinstance(stories, dict) and isinstance(built, dict)) else {}
    if left:
        path.write_text(json.dumps({"stories": left}) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)


def refresh(run_dir):
    """Mark the build as alive; does nothing when no lock is held."""
    try:
        os.utime(lock_path(run_dir))
    except FileNotFoundError:
        pass


def release(run_dir):
    """End the build: the grants of the stories it built are used up, then the lock goes."""
    try:
        _expire_grants(run_dir)
        lock_path(run_dir).unlink(missing_ok=True)
    except OSError as error:
        raise LockError(f"cannot end the build in {run_dir}: {error}") from error
