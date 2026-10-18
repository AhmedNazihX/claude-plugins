"""The guards accio's git hooks run (DESIGN § 4.5, § 6; decisions 004, 009): the staged-secret check and the push
guard.

`pre-push` blocks force-pushes and deleting base for everyone. A push to base is blocked by where and when
(decision 009): during a build (a fresh `run/brew.lock`) and from a story worktree, always; when `CLAUDECODE=1`,
unless the `owl` token (`run/push-ok`, the confirmed sha) names it, which allows one fast-forward push of that sha,
then goes. A token never opens a build or a story worktree: a check runs code an agent wrote, so an agent could
write the token mid-build (S-015, S-022).
The refs come only from git's own list on stdin; when another hook already read it and a guard applies, the push
is blocked rather than guessed at. A story worktree is told by its git dir, so pointing git at another work tree
doesn't hide it.
"""
import dataclasses
import pathlib
import re

from accio_lib import config, githooks, paths, runlock, secret_scan

TOKEN_NAME = "push-ok"
ZERO_SHA = re.compile(r"^0+$")
LOCK_MINUTES = runlock.STALE_SECONDS // 60


@dataclasses.dataclass(frozen=True)
class Push:
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str


def run_pre_commit(repo):
    """Messages for each staged secret (empty when the commit may go ahead)."""
    try:
        result = secret_scan.scan_staged(repo)
    except secret_scan.SecretScanError as error:
        return (f"accio: the secret scan failed, so the commit is stopped: {error}",)
    by_path = {}
    for finding in result.findings:
        by_path = {**by_path, finding.path: (*by_path.get(finding.path, ()), finding)}
    messages = tuple(_describe(path, findings) for path, findings in by_path.items())
    return messages + ((result.output,) if messages and result.output else ())


def _describe(path, findings):
    if any(f.name == secret_scan.SECRET_FILE_NAME for f in findings):
        return (f"accio: {path} is a file meant to hold secrets. Unstage it (`git restore --staged {path}`) and add "
                "it to .gitignore.")
    if not path:
        return f"accio: {findings[0].name}."
    return secret_scan.describe(path, findings)


def parse_pushes(stdin_text):
    """The refs git is pushing, one line each: `<local ref> <local sha> <remote ref> <remote sha>`."""
    rows = [line.split() for line in stdin_text.splitlines() if line.strip()]
    if any(len(row) != 4 for row in rows):
        raise githooks.HooksError("pre-push got a line it doesn't understand from git; the push is stopped to be safe")
    return tuple(Push(*row) for row in rows)


def _is_fast_forward(cwd, push):
    if ZERO_SHA.match(push.remote_sha):
        return True
    return githooks.run_git(cwd, "merge-base", "--is-ancestor", push.remote_sha, push.local_sha).returncode == 0


def in_story_worktree(root, cwd):
    """True when git is working on a story worktree's repo: its git dir records a checkout under the worktree root."""
    git_dir = githooks.git_out(cwd, "rev-parse", "--path-format=absolute", "--absolute-git-dir")
    try:
        checkout = pathlib.Path((pathlib.Path(git_dir) / "gitdir").read_text(encoding="utf-8").strip()).parent
    except (OSError, TypeError, UnicodeDecodeError):  # the main checkout's git dir has no `gitdir` file
        return False
    return checkout.resolve().is_relative_to(paths.worktree_root(root).resolve())


def _guards(root, accio, cwd, environ, base):
    """(why a push to base is blocked whatever the token, why a tokenless one is, notes)."""
    run_dir = accio / "run"
    lock = runlock.lock_path(run_dir)
    notes = ((f"accio: {lock} hasn't been refreshed for {LOCK_MINUTES} min, so it's treated as stale (a build that "
              "stopped) and no build counts as running."),) if runlock.is_stale(lock) else ()
    always = []
    if runlock.is_held(run_dir):
        always.append(f"a build is running ({lock} was refreshed in the last {LOCK_MINUTES} min), so pushes to "
                       f"{base} wait for your confirmation at `owl`")
    if in_story_worktree(root, cwd):
        always.append(f"this is a story worktree, and pushes to {base} never come from one (stories reach {base} "
                       "through `owl`)")
    unconfirmed = []
    if environ.get("CLAUDECODE") == "1":
        unconfirmed.append(f"Claude is pushing (CLAUDECODE=1) to {base} without your confirmation at `owl`. To push "
                           "yourself, run `git push` in your own terminal")
    return tuple(always), tuple(unconfirmed), notes


def _token(run_dir):
    try:
        return (run_dir / TOKEN_NAME).read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as error:
        raise githooks.HooksError(f"cannot read {run_dir / TOKEN_NAME}: {error}") from error


def _use_token(run_dir):
    try:
        (run_dir / TOKEN_NAME).unlink(missing_ok=True)
    except OSError as error:
        raise githooks.HooksError(f"cannot remove the used token {run_dir / TOKEN_NAME}: {error}") from error


def _blocked_for_everyone(pushes, base, base_ref, cwd):
    for push in pushes:
        if ZERO_SHA.match(push.local_sha):
            if push.remote_ref == base_ref:
                return f"accio: deleting {base} on the remote is blocked for everyone."
        elif not _is_fast_forward(cwd, push):
            return (f"accio: force-pushing {push.remote_ref} is blocked for everyone. Fetch and merge (or rebase) "
                    "first, then push normally.")
    return None


def check_push(root, accio, cwd, pushes, environ):
    """(allowed, messages). Uses up the token when it is what lets the push through."""
    base = config.load(accio)["base_branch"]
    base_ref = f"refs/heads/{base}"
    always, unconfirmed, notes = _guards(root, accio, cwd, environ, base)
    reasons = always + unconfirmed
    if not pushes:
        if not reasons:
            return True, notes
        return False, notes + (f"accio: can't see what is being pushed (another hook read git's list first), and "
                               f"{reasons[0]}. Move the `# accio` lines to the top of the pre-push hook.",)
    blocked = _blocked_for_everyone(pushes, base, base_ref, cwd)
    if blocked:
        return False, notes + (blocked,)
    to_base = [push for push in pushes if push.remote_ref == base_ref and not ZERO_SHA.match(push.local_sha)]
    if not to_base or not reasons:
        return True, notes
    if always:
        return False, notes + tuple(f"accio: {reason}." for reason in always)
    token = _token(accio / "run")
    if token and all(push.local_sha == token for push in to_base):
        _use_token(accio / "run")
        return True, notes + (f"accio: pushing {token[:12]} to {base}, as confirmed at `owl`.",)
    stale = f" ({TOKEN_NAME} is for {token[:12]}, not {to_base[0].local_sha[:12]})" if token else ""
    return False, notes + tuple(f"accio: {reason}.{stale}" for reason in reasons)
