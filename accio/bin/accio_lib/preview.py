"""A story's preview: the user's `preview: {command, url}` run in the story's worktree (decision 008, R8).

`start` runs the command as a detached process group, records it in `run/<ID>/preview.json` and returns once the URL
answers. One preview runs at a time, because they share a port: it holds `run/preview.lock` until `stop`, and a
second `start` waits for it. `stop` kills the group and then whatever still listens on the URL's port, so it works
after a `start` that crashed too. A lock whose owner process is gone is stale and is replaced.

`evidence` is a native app's stand-in for a preview (S-068): it runs `ui_evidence.command` once on mad-eye's steps
file and leaves screenshots for mad-eye to judge (see the section at the end).
"""
import contextlib
import json
import os
import pathlib
import shlex
import shutil
import signal
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

from accio_lib import checks, config, globs, runlock

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


# A preview check connects directly: no proxy from the environment or (on macOS) the system settings.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOG_TAIL_LINES = 20


def _answers(url):
    try:
        DIRECT.open(url, timeout=REQUEST_TIMEOUT).close()
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
    except PreviewError as error:
        tail = _log_tail(run_dir / story_id / LOG_NAME)  # stop deletes the log, so read it first
        stop(run_dir, story_id, settings)
        process.wait()
        if tail and "did not answer" in str(error):
            raise PreviewError(f"{error}\nlast output of the preview command:\n{tail}") from error
        raise
    return settings["url"]


def _log_tail(path):
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-LOG_TAIL_LINES:])


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


# --- ui_evidence: screenshots of a native app's real window (S-068) ------------------------------------------------
# mad-eye writes a steps file, accio writes it to run/<ID>/ui-steps.txt, and `evidence` runs the project's command on
# it in a fresh detached checkout of the story's head, removed afterwards (S-073), so nothing the builder left in its
# worktree (ignored files, files `assume-unchanged` or `skip-worktree` hide from `git status`) reaches the evidence;
# `fresh_checkout: false` runs it in the live worktree instead. The folder is accio's own, emptied first, so nothing
# the builder left there counts; the stamp ties what the command made to the commit it ran on. Every problem is a skip
# with its reason, never a block.

EVIDENCE_FOLDER = "ui-evidence"
STEPS_NAME = "ui-steps.txt"
STAMP_NAME = "ui-evidence.head"
EVIDENCE_LOG = "ui-evidence.log"
DEFAULT_EVIDENCE_TIMEOUT = config.EVIDENCE_TIMEOUT_MAX  # seconds, under prefect's Bash limit (S-070)
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
TAKES_OVER = ("ui_evidence.takes_over_screen is true: its command takes over the screen (mouse, keyboard or focus), "
              "so it can't run in an unattended build")
FNV_OFFSET = 0x811C9DC5
FNV_PRIME = 0x01000193
WORD_MASK = 0xFFFFFFFF
STATUS_WIDTH = 3  # `git status --porcelain` puts "XY " before each path
MAX_NAMED_FILES = 20  # a skip note names this many files not committed, then counts the rest
CHECKOUT_PREFIX = "accio-evidence-"  # the temporary folder that holds the clean checkout (S-073)
CHECKOUT_NAME = "checkout"
NO_HOOKS = ("-c", "core.hooksPath=/dev/null")  # no hook the story could have set runs when the checkout is made


def steps_sum(text):
    """32-bit FNV-1a over the text's code points, as 8 hex digits. brew.js computes the same over mad-eye's steps
    (stepsSum), so a ui-steps.txt prefect changed while copying is caught; a copying mistake, not an attacker."""
    value = FNV_OFFSET
    for char in text:
        value = ((value ^ ord(char)) * FNV_PRIME) & WORD_MASK
    return f"{value:08x}"


def evidence_timeout(settings):
    return settings.get("timeout", DEFAULT_EVIDENCE_TIMEOUT)


def _steps_problem(steps, wanted):
    """'' when the steps file's text has the checksum the workflow passed (or none was passed), else why not."""
    if wanted is None:
        return ""
    try:
        got = steps_sum(steps.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError):
        got = "unreadable"
    if got == wanted:
        return ""
    return (f"the steps file {STEPS_NAME} was changed: its checksum is {got}, not the {wanted} of the steps mad-eye "
            "wrote, so the evidence command did not run")


def evidence_files(run_dir, worktree, story_id, settings, base_branch, head="HEAD"):
    """(files, problem): the files the story's diff up to `head` touches that match `evidence_globs` (S-069), the files
    that make the evidence. No globs, no git work. If git can't say, problem says why and the evidence is not
    trusted."""
    patterns = list(settings.get("evidence_globs", []))
    if not patterns:
        return [], ""
    if not base_branch:
        return [], f"no base branch to compare {story_id} with, so its evidence can't be trusted"
    try:
        origin = checks.diff_start(run_dir / story_id, worktree, base_branch)
        listed = subprocess.run(["git", "diff", "--name-only", "-z", "--no-renames", origin, head], cwd=worktree,
                                capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (checks.CheckError, subprocess.CalledProcessError, OSError) as error:
        return [], f"can't tell which files {story_id} changes ({error}), so its evidence can't be trusted"
    # Without letter case (S-071): the default macOS disk ignores it, so `app/walk.swift` is `App/Walk.swift`.
    return sorted(path for path in listed.split("\0")
                  if path and globs.matches_any(path, patterns, ignore_case=True)), ""


def evidence_not_trusted(files):
    return ("the story changes how its evidence is made (" + ", ".join(files) + "); a person should look")


def worktree_changes(worktree):
    """(files, problem): the worktree's changed, staged and untracked files (not ignored ones), S-071. The evidence
    command runs on the worktree as it is, so a file not committed would be in the evidence but not in the diff that
    evidence_files checks. If git can't say, problem says why."""
    try:
        listed = subprocess.run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--no-renames"],
                                cwd=worktree, capture_output=True, check=True).stdout.decode("utf-8", "replace")
    except (subprocess.CalledProcessError, OSError) as error:
        return [], (f"can't tell whether the worktree at {worktree} has files that are not committed ({error}), so "
                    "the evidence command did not run")
    return sorted({entry[STATUS_WIDTH:] for entry in listed.split("\0") if len(entry) > STATUS_WIDTH}), ""


def not_committed(story_id, files):
    """The skip reason for a worktree with files not committed, naming the first MAX_NAMED_FILES of them."""
    named = ", ".join(files[:MAX_NAMED_FILES])
    more = f", and {len(files) - MAX_NAMED_FILES} more" if len(files) > MAX_NAMED_FILES else ""
    return (f"the worktree of {story_id} has files that are not committed ({named}{more}), so the evidence command "
            "did not run: it would show more than the story's commits")


def evidence_plan(settings):
    """What the workflow needs to know before it asks mad-eye for steps."""
    if settings is None:
        return {"ui_evidence": False}
    return {"ui_evidence": True, "takes_over_screen": settings["takes_over_screen"],
            "steps_doc": settings["steps_doc"], "themes": list(settings.get("themes", []))}


def _skip(reason):
    return {"skipped": True, "reason": reason}


def _fresh_folder(story_dir):
    """Empty the evidence folder and remove the old stamp."""
    folder = story_dir / EVIDENCE_FOLDER
    if folder.is_symlink() or folder.is_file():
        folder.unlink()
    elif folder.exists():
        shutil.rmtree(folder)
    folder.mkdir(parents=True)
    (story_dir / STAMP_NAME).unlink(missing_ok=True)
    return folder


def _fill(command, steps, folder):
    return command.replace("{steps}", shlex.quote(str(steps))).replace("{folder}", shlex.quote(str(folder)))


def _run_command(settings, worktree, steps, folder, log_path):
    """Run the filled-in command in the worktree; '' when it exited 0, else why not."""
    timeout = evidence_timeout(settings)
    see_log = f"see {log_path}"
    try:
        with open(log_path, "wb") as log:
            process = subprocess.Popen(_fill(settings["command"], steps, folder), shell=True, cwd=worktree,
                                       start_new_session=True, stdin=subprocess.DEVNULL, stdout=log,
                                       stderr=subprocess.STDOUT)
    except OSError as error:
        return f"the evidence command could not start: {error}"
    try:
        code = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        code = None
    _kill_group(process.pid)  # the app it opened, or what is left after a timeout
    process.wait()
    if code is None:
        return f"the evidence command ran past its timeout of {timeout}s and was stopped ({see_log})"
    return f"the evidence command exited with {code} ({see_log})" if code else ""


def _is_png(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(len(PNG_SIGNATURE)) == PNG_SIGNATURE
    except OSError:
        return False


def _screenshots(folder):
    return [path for path in folder.rglob("*") if path.suffix.lower() == ".png" and path.is_file() and _is_png(path)]


def _write_stamp(story_dir, worktree):
    """Write the worktree's head commit as the evidence stamp; no stamp when git can't say."""
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=worktree, capture_output=True, text=True, check=False)
    head = result.stdout.strip()
    if result.returncode == 0 and head:
        (story_dir / STAMP_NAME).write_text(head + "\n", encoding="utf-8")


def stamp_problem(run_dir, story_id, head):
    """'' when run/<ID>/ui-evidence.head names `head`, else why the evidence is refused (both commits named)."""
    try:
        stamped = (run_dir / story_id / STAMP_NAME).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        stamped = ""
    if not stamped:
        return f"the evidence stamp {STAMP_NAME} is missing (none), so it is refused: the story's head is {head[:12]}"
    if stamped != head:
        return f"the evidence is of commit {stamped[:12]} but the story's head is {head[:12]}, so it is refused"
    return ""


def _untrusted(run_dir, worktree, story_id, settings, head):
    """Why the worktree's evidence can't be trusted, or '': files not committed (S-071), or a diff up to `head` that
    touches an `evidence_globs` file (S-069), with the base branch read from config.json."""
    pending, problem = worktree_changes(worktree)
    if problem or pending:
        return problem or not_committed(story_id, pending)
    if not settings.get("evidence_globs"):
        return ""
    try:
        base_branch = config.load(run_dir.parent)["base_branch"]
    except config.ConfigError as error:
        return f"can't read config.json ({error}), so the evidence of {story_id} can't be trusted"
    touched, problem = evidence_files(run_dir, worktree, story_id, settings, base_branch, head)
    return problem or (evidence_not_trusted(touched) if touched else "")


def _git_quiet(worktree, *args):
    """Run git in the worktree; (exit code, its error output). An OSError counts as a failure."""
    try:
        result = subprocess.run(["git", *NO_HOOKS, *args], cwd=worktree, capture_output=True, text=True, check=False)
    except OSError as error:
        return 1, str(error)
    return result.returncode, result.stderr.strip()


def _remove_checkout(worktree, checkout, holder):
    """Remove the checkout and its temporary folder, and git's record of it, whatever state the command left."""
    code, _ = _git_quiet(worktree, "worktree", "remove", "--force", "--force", str(checkout))
    shutil.rmtree(holder, ignore_errors=True)
    if code:
        _git_quiet(worktree, "worktree", "prune")  # forgets the checkout, now that its folder is gone


@contextlib.contextmanager
def _command_folder(worktree, head, settings):
    """Yields (folder, problem): where the command runs. By default a fresh detached checkout of `head` in a temporary
    folder, removed afterwards, also when the command fails or times out (S-073); with `fresh_checkout: false`, the
    live worktree."""
    if settings.get("fresh_checkout", True) is False:
        yield worktree, ""
        return
    holder = pathlib.Path(tempfile.mkdtemp(prefix=CHECKOUT_PREFIX)).resolve()
    checkout = holder / CHECKOUT_NAME
    try:
        code, error = _git_quiet(worktree, "worktree", "add", "--detach", "--quiet", str(checkout), head)
        if code:
            yield None, (f"can't check out {head[:12]} into a clean folder ({error or 'git failed'}), so the "
                         "evidence command did not run")
        else:
            yield checkout, ""
    finally:
        _remove_checkout(worktree, checkout, holder)


def _make_evidence(run_dir, story_id, settings, steps, ran_in, head):
    """Run the command in `ran_in`, count its screenshots and stamp them; the result."""
    story_dir = run_dir / story_id
    folder = _fresh_folder(story_dir)
    problem = _run_command(settings, ran_in, steps, folder, story_dir / EVIDENCE_LOG)
    if problem:
        return _skip(problem)
    shots = _screenshots(folder)
    if not shots:
        return _skip(f"the evidence command left no PNG screenshots in {folder}")
    _write_stamp(story_dir, ran_in)
    problem = stamp_problem(run_dir, story_id, head)
    if problem:
        return _skip(problem)
    return {"ok": True, "folder": str(folder), "head": head, "screenshots": len(shots)}


def evidence(run_dir, worktree, story_id, settings, head, steps_checksum=None):
    """Run `ui_evidence.command` on the steps file; {ok, folder, head, screenshots} or {skipped, reason}. With
    `steps_checksum` (brew.js passes it), a steps file whose steps_sum differs never runs (S-070). A worktree with files
    not committed (S-071), or a story whose diff touches an `evidence_globs` file (S-069), never runs it either. It
    runs in a fresh checkout of `head` unless `fresh_checkout` is false (S-073)."""
    if settings is None:
        return _skip("config.json has no `ui_evidence`")
    if settings["takes_over_screen"]:
        return _skip(TAKES_OVER)
    if not worktree.is_dir():
        return _skip(f"no worktree for {story_id} at {worktree}")
    problem = _untrusted(run_dir, worktree, story_id, settings, head)
    if problem:
        return _skip(problem)
    steps = run_dir / story_id / STEPS_NAME
    if not steps.is_file():
        return _skip(f"no steps file at {steps}: mad-eye's steps were not written")
    problem = _steps_problem(steps, steps_checksum)
    if problem:
        return _skip(problem)
    with _command_folder(worktree, head, settings) as (ran_in, problem):
        if problem:
            return _skip(problem)
        return _make_evidence(run_dir, story_id, settings, steps, ran_in, head)
