"""Merge accepted stories at `owl` (DESIGN § 3.5 Merge, § 12.3 steps 3–4, decision 009).

1. Rebuild `accio/integrate-<N>` from base in its own worktree (a leftover from a crash is discarded first).
2. Merge each accepted story `--no-ff`, in dependency order, as `<type>(<ID>): <title>`.
3. Run every check once on the result.
4. Green: fast-forward main (never a reset). From then on nothing raises: story worktrees are removed without
   `--force` and branches deleted with `-d`; anything that can't be removed is reported as a leftover.
   Red: main is untouched; the checks are first run on base (a failure there blames no story), then on the result
   after each merge in turn, and the first one that fails names the culprit.
Uncommitted, untracked or ignored files in the main checkout stop the merge with one question when the merge
would touch them. Any error before the fast-forward discards accio's own integration worktree and branch.
The check commands come from the project's own committed `config.json` and run through the shell, with the same
trust as the project's test scripts (`npm test && npm run lint` needs a shell).
"""
import os
import pathlib
import signal
import subprocess

from accio_lib import board, paths

INTEGRATION_PREFIX = "accio/integrate-"
CHECK_TIMEOUT_SECONDS = 30 * 60
OUTPUT_TAIL_CHARS = 2000


class MergeError(Exception):
    """A merge problem, written for the user."""


def _git(cwd, *args, check=True):
    try:
        raw = subprocess.run(["git", *args], cwd=cwd, capture_output=True, check=False)
    except OSError as error:
        raise MergeError(f"git could not run in {cwd}: {error}") from error
    result = subprocess.CompletedProcess(raw.args, raw.returncode, raw.stdout.decode("utf-8", errors="replace"),
                                         raw.stderr.decode("utf-8", errors="replace"))
    if check and result.returncode != 0:
        raise MergeError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result


def _branch_exists(cwd, branch):
    return _git(cwd, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _current_branch(main):
    return _git(main, "branch", "--show-current").stdout.strip()


def merge_order(stories, status, accepted):
    """Accepted ids in dependency order; every dependency must be done or accepted too."""
    for story_id in accepted:
        if story_id not in stories:
            raise MergeError(f"there is no story {story_id}")
        for dep in stories[story_id].meta.get("deps", ()):
            if dep not in accepted and status[dep] != "done":
                raise MergeError(f"{story_id} needs {dep}, which is neither done nor accepted; accept {dep} too")
    ordered, placed = [], set()
    while len(ordered) < len(accepted):
        ready = sorted(sid for sid in accepted if sid not in placed
                       and all(dep in placed or dep not in accepted for dep in stories[sid].meta.get("deps", ())))
        if not ready:
            raise MergeError("the accepted stories depend on each other in a cycle")
        ordered.append(ready[0])
        placed.add(ready[0])
    return tuple(ordered)


def _registered(main):
    _git(main, "worktree", "prune", check=False)
    lines = _git(main, "worktree", "list", "--porcelain").stdout.splitlines()
    return {pathlib.Path(line.split(" ", 1)[1]).resolve() for line in lines if line.startswith("worktree ")}


def _discard_integration(main, worktree, branch):
    """Throw away accio's own temporary integration worktree and branch (never a story branch)."""
    if worktree.resolve() in _registered(main):
        _git(main, "worktree", "remove", "--force", str(worktree), check=False)
    if _branch_exists(main, branch):
        _git(main, "branch", "-D", branch, check=False)


def start_integration(main, base_branch, number):
    worktree = paths.worktree_root(main) / f"integrate-{number}"
    branch = f"{INTEGRATION_PREFIX}{number}"
    _discard_integration(main, worktree, branch)
    _git(main, "worktree", "add", "-q", str(worktree), "-b", branch, base_branch)
    return worktree, branch


def merge_stories(worktree, stories, ordered):
    """Merge each story; returns (merged [(id, commit)], conflicting id or None). Other failures raise."""
    merged = []
    for story_id in ordered:
        meta = stories[story_id].meta
        branch = f"story/{story_id}"
        if not _branch_exists(worktree, branch):
            raise MergeError(f"{story_id} has no branch {branch}")
        message = f"{meta.get('type', 'feat')}({story_id}): {meta['title']}"
        result = _git(worktree, "merge", "--no-ff", "-q", "-m", message, branch, check=False)
        if result.returncode != 0:
            if _git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).stdout.strip():
                return tuple(merged), story_id
            raise MergeError(f"merging {branch} failed (not a conflict): {(result.stderr or result.stdout).strip()}")
        merged.append((story_id, _git(worktree, "rev-parse", "HEAD").stdout.strip()))
    return tuple(merged), None


def _run_check(worktree, command, timeout):
    """(passed, output tail); a timeout kills the whole process group."""
    process = subprocess.Popen(command, shell=True, cwd=worktree, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
        timed_out = False
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        timed_out = True
    text = output.decode("utf-8", errors="replace")[-OUTPUT_TAIL_CHARS:]
    if timed_out:
        text += f"\n(stopped after {_duration(timeout)})"
    return process.returncode == 0 and not timed_out, text


def _duration(seconds):
    return f"{round(seconds / 60)} min" if seconds >= 60 else f"{round(seconds)} s"


def run_checks(worktree, commands, timeout=CHECK_TIMEOUT_SECONDS):
    """{command: output tail} for every command that fails or runs past `timeout` seconds."""
    failing = {}
    for command in commands:
        passed, output = _run_check(worktree, command, timeout)
        if not passed:
            failing[command] = output
    return failing


def _reset_to(worktree, commit):
    """Put accio's own integration worktree exactly at a commit (checks may have edited or added files)."""
    _git(worktree, "checkout", "-q", "--force", "--detach", commit)
    _git(worktree, "clean", "-q", "-fd")


def find_culprit(worktree, base_commit, merged, failing):
    """(culprit id or None, base_failing). Checks that already fail on base blame no story; the others are
    replayed after each merge in turn, and the first state where one fails names the culprit."""
    _reset_to(worktree, base_commit)
    broken_on_base = run_checks(worktree, failing)
    replay = tuple(command for command in failing if command not in broken_on_base)
    for story_id, commit in merged if replay else ():
        _reset_to(worktree, commit)
        if run_checks(worktree, replay):
            return story_id, bool(broken_on_base)
    return None, bool(broken_on_base)


def _nul_paths(output):
    return [part for part in output.split("\0") if part]


def status_entries(main):
    """(status code, path) for every uncommitted, untracked (expanded) or ignored path in a checkout; a rename or
    copy gives its source too, with the same code. An ignored folder is one entry, without its trailing `/`."""
    entries = _nul_paths(_git(main, "status", "--porcelain", "-z", "--untracked-files=all",
                              "--ignored=matching").stdout)
    found, index = [], 0
    while index < len(entries):
        code, path = entries[index][:2], entries[index][3:]
        found.append((code, path.rstrip("/")))
        if code[0] in "RC" and index + 1 < len(entries):
            found.append((code, entries[index + 1]))
            index += 1
        index += 1
    return found


def _dirty_paths(main):
    """Every uncommitted, untracked or ignored path in the main checkout, rename sources included."""
    return {path for _, path in status_entries(main)}


def _blocking_changes(main, base_branch, new_head):
    """Main-checkout paths the fast-forward would overwrite, or () when main isn't checked out there."""
    if _current_branch(main) != base_branch:
        return ()
    changed = set(_nul_paths(_git(main, "diff", "--name-only", "-z", "--no-renames", base_branch, new_head).stdout))
    dirty = _dirty_paths(main)
    folders = tuple(folder + "/" for folder in dirty if (main / folder).is_dir())
    hits = {path for path in changed if path in dirty or path.startswith(folders)}
    return tuple(sorted(hits))


def fast_forward(main, base_branch, branch):
    if _git(main, "merge-base", "--is-ancestor", base_branch, branch, check=False).returncode != 0:
        raise MergeError(f"{base_branch} moved while merging; run the merge again")
    if _current_branch(main) == base_branch:
        _git(main, "merge", "--ff-only", "--no-overwrite-ignore", "-q", branch)
    else:
        _git(main, "fetch", "-q", ".", f"{branch}:{base_branch}")


def clean_up(main, worktree, branch, ordered):
    """After main moved; never raises. Returns what couldn't be removed."""
    leftovers = []
    registered = _registered(main)
    for story_id in ordered:
        story_worktree = paths.worktree_root(main) / story_id
        if story_worktree.resolve() in registered and _git(
                main, "worktree", "remove", str(story_worktree), check=False).returncode != 0:
            leftovers.append(str(story_worktree))
            continue
        if _git(worktree, "branch", "-d", f"story/{story_id}", check=False).returncode != 0:
            leftovers.append(f"story/{story_id}")
    _git(worktree, "checkout", "-q", "--force", "--detach", check=False)
    if _git(worktree, "branch", "-d", branch, check=False).returncode != 0:
        leftovers.append(branch)
    _discard_integration(main, worktree, branch)
    return tuple(leftovers)


def _before_fast_forward(main, worktree, branch, stories, ordered, settings, reply):
    """Merge and check; returns the final reply, or None when the fast-forward may go ahead."""
    base_commit = _git(main, "rev-parse", settings["base_branch"]).stdout.strip()
    merged, conflict = merge_stories(worktree, stories, ordered)
    if conflict:
        return {**reply, "result": "conflict", "culprit": conflict}
    failing = run_checks(worktree, [check["command"] for check in settings["checks"]])
    if failing:
        culprit, base_failing = find_culprit(worktree, base_commit, merged, tuple(failing))
        return {**reply, "result": "checks_failed", "culprit": culprit, "base_failing": base_failing,
                "failing": list(failing), "failure_output": failing}
    blocking = _blocking_changes(main, settings["base_branch"], branch)
    if blocking:
        question = (f"Your main checkout has uncommitted, untracked or ignored files the merge would overwrite: "
                    f"{', '.join(blocking)}. Commit, move or stash them, then say \"merge again\".")
        return {**reply, "result": "needs_user", "question": question}
    return None


def merge(main, accio, number, accepted, settings):
    """Run the whole merge; returns the reply owl reads."""
    stories = board.load_stories(accio)
    ordered = merge_order(stories, board.statuses(stories, board.read_overrides(accio)), tuple(accepted))
    base = settings["base_branch"]
    worktree, branch = start_integration(main, base, number)
    reply = {"result": "", "main": _git(main, "rev-parse", base).stdout.strip(), "culprit": None,
             "base_failing": False, "failing": [], "failure_output": {}, "question": None, "merged": [],
             "leftovers": []}
    try:
        stopped = _before_fast_forward(main, worktree, branch, stories, ordered, settings, reply)
        if stopped is None:
            fast_forward(main, base, branch)
    except MergeError:
        _discard_integration(main, worktree, branch)
        raise
    if stopped is not None:
        _discard_integration(main, worktree, branch)
        return stopped
    leftovers = clean_up(main, worktree, branch, ordered)
    return {**reply, "result": "merged", "main": _git(main, "rev-parse", base).stdout.strip(),
            "merged": list(ordered), "leftovers": list(leftovers)}
