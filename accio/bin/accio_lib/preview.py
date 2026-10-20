"""A story's preview: the user's `preview: {command, url}` run in the story's worktree (decision 008, R8).

`start` runs the command as a detached process group, records it in `run/<ID>/preview.json` and returns once the URL
answers. One preview runs at a time, because they share a port: it holds `run/preview.lock` until `stop`, and a
second `start` waits for it. `stop` kills the group and then whatever still listens on the URL's port, so it works
after a `start` that crashed too. A lock whose owner process is gone is stale and is replaced.
"""
import json
import os
import signal
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

from accio_lib import runlock

LOCK_NAME = "preview.lock"
STATE_NAME = "preview.json"
LOGIN_NAME = "preview-login.json"  # the login the next story writes; stop removes it with the preview
LOG_NAME = "preview.log"
DEFAULT_WAIT = 300      # seconds a second start waits for the first preview to stop
DEFAULT_TIMEOUT = 60    # seconds the URL gets to answer
POLL = 0.2
STOP_GRACE = 5          # seconds between the polite kill and the hard one
REQUEST_TIMEOUT = 2


class PreviewError(Exception):
    """A preview problem, written for the user."""


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path, data):
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _try_lock(run_dir, story_id):
    """Create the lock; False while a live owner holds it."""
    path = run_dir / LOCK_NAME
    with runlock.guard(run_dir):
        held = _read_json(path)
        if held is not None and isinstance(held.get("pid"), int) and _alive(held["pid"]):
            return False
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
        except OSError as error:
            raise PreviewError(f"cannot write {path}: {error}") from error
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"story": story_id, "pid": os.getpid()}) + "\n")
    return True


def _lock_wait(run_dir, story_id, seconds):
    deadline = time.monotonic() + seconds
    while not _try_lock(run_dir, story_id):
        if time.monotonic() >= deadline:
            held = _read_json(run_dir / LOCK_NAME) or {}
            raise PreviewError(f"another preview ({held.get('story', 'unknown')}) holds {run_dir / LOCK_NAME}; "
                               f"waited {seconds}s. Stop it with `accio-preview {held.get('story', '<ID>')} stop`")
        time.sleep(POLL)


def _answers(url):
    try:
        urllib.request.urlopen(url, timeout=REQUEST_TIMEOUT).close()
    except urllib.error.HTTPError:
        return True  # the server answered, even if with an error page
    except (urllib.error.URLError, OSError, ValueError):
        return False
    return True


def _wait_for_url(url, process, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise PreviewError(f"the preview command exited with {process.returncode} before {url} answered")
        if _answers(url):
            return
        time.sleep(POLL)
    raise PreviewError(f"{url} did not answer within {seconds}s")


def _group_alive(pid):
    try:
        os.killpg(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _kill_group(pgid):
    """SIGTERM the group, then SIGKILL what is left after the grace period."""
    sent = False
    for sig, patience in ((signal.SIGTERM, STOP_GRACE), (signal.SIGKILL, STOP_GRACE)):
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        except PermissionError as error:
            if sent:
                return  # macOS refuses a group whose leader is a zombie its parent has yet to reap: it is dead
            raise PreviewError(f"cannot stop process group {pgid}: {error}") from error
        sent = True
        deadline = time.monotonic() + patience
        while time.monotonic() < deadline:
            if not _group_alive(pgid):
                return
            time.sleep(0.05)


def _listeners(port):
    """Pids listening on a local port (empty when lsof is missing)."""
    try:
        result = subprocess.run(["lsof", "-ti", f"tcp:{port}", "-sTCP:LISTEN"], capture_output=True, text=True,
                                check=False)
    except OSError:
        return []
    return [int(word) for word in result.stdout.split() if word.isdigit()]


def _port(url):
    parsed = urllib.parse.urlparse(url)
    return parsed.port or (443 if parsed.scheme == "https" else 80)


def _free_port(url):
    for pid in _listeners(_port(url)):
        try:
            pgid = os.getpgid(pid)
        except ProcessLookupError:
            continue
        if pgid == os.getpgrp():
            continue
        _kill_group(pgid)


def _clear(run_dir, story_id):
    for path in (run_dir / story_id / STATE_NAME, run_dir / story_id / LOGIN_NAME):
        path.unlink(missing_ok=True)
    held = _read_json(run_dir / LOCK_NAME)
    if held is not None and held.get("story") == story_id:
        (run_dir / LOCK_NAME).unlink(missing_ok=True)


def _require_test_data(settings):
    if settings.get("test_data") is not True:
        raise PreviewError('preview needs "test_data": true in .accio/config.json: accio cannot check the app holds '
                           "only test data, so you say so")


def _login(settings):
    """The login details from the environment variables `preview.login` names, or None without a login."""
    login = settings.get("login")
    if login is None:
        return None
    names = (login["username_env"], login["password_env"])
    missing = [name for name in names if name not in os.environ]
    if missing:
        raise PreviewError(f"preview.login names environment variable(s) that are not set: {', '.join(missing)}")
    return {"username": os.environ[names[0]], "password": os.environ[names[1]]}


def _write_login(path, login):
    """Write the login file readable by its owner only."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(login) + "\n")


def start(run_dir, worktree, story_id, settings, wait=DEFAULT_WAIT, timeout=DEFAULT_TIMEOUT):
    """Start the preview and return its URL once it answers. Raises PreviewError, leaving nothing running."""
    if settings is None:
        raise PreviewError('no preview in .accio/config.json; add {"preview": {"command": "...", "url": "http://..."}}')
    _require_test_data(settings)
    login = _login(settings)
    if not worktree.is_dir():
        raise PreviewError(f"no worktree for {story_id} at {worktree}")
    (run_dir / story_id).mkdir(parents=True, exist_ok=True)
    _lock_wait(run_dir, story_id, wait)
    try:
        if login is not None:
            _write_login(run_dir / story_id / LOGIN_NAME, login)
        log = open(run_dir / story_id / LOG_NAME, "ab")
        with log:
            process = subprocess.Popen(settings["command"], shell=True, cwd=worktree, start_new_session=True,
                                       env={**os.environ, **settings.get("env", {})}, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT)
    except OSError as error:
        _clear(run_dir, story_id)
        raise PreviewError(f"cannot run the preview command: {error}") from error
    _write_json(run_dir / LOCK_NAME, {"story": story_id, "pid": process.pid})
    _write_json(run_dir / story_id / STATE_NAME,
                {"story": story_id, "pid": process.pid, "url": settings["url"], "command": settings["command"]})
    try:
        _wait_for_url(settings["url"], process, timeout)
    except PreviewError:
        stop(run_dir, story_id, settings)
        process.wait()
        raise
    return settings["url"]


def stop(run_dir, story_id, settings):
    """Kill the preview's process group and whatever still listens on its port; remove its files and lock."""
    with runlock.guard(run_dir):  # no start can take the lock until the port is free and the lock is gone
        return _stop_locked(run_dir, story_id, settings)


def _another_story_holds_lock(held, story_id):
    return (held is not None and held.get("story") != story_id
            and isinstance(held.get("pid"), int) and _alive(held["pid"]))


def _stop_locked(run_dir, story_id, settings):
    state = _read_json(run_dir / story_id / STATE_NAME)
    held = _read_json(run_dir / LOCK_NAME)
    owns_lock = held is not None and held.get("story") == story_id
    if state is None and not owns_lock:
        return False
    if state is not None and isinstance(state.get("pid"), int) and state["pid"] > 1:
        _kill_group(state["pid"])
    url = (state or {}).get("url") or (settings or {}).get("url")
    if url and not _another_story_holds_lock(held, story_id):
        _free_port(url)  # the port is another story's while it holds the lock
    _clear(run_dir, story_id)
    return True
