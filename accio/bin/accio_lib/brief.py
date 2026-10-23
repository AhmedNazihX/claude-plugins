"""Prepare a story for its implementer (DESIGN § 3.4 step 1, § 12.3): the worktree and branch, the rebase, the brief.

- No branch yet: `git worktree add <wt>/<ID> -b story/<ID> <onto>`, where onto is base or the parent's head.
- Branch exists: reuse it (re-adding a removed or hand-deleted worktree) and rebase it. The commit it was built on
  is kept in `run/<ID>/base`, so the rebase is `--onto <new> <old>` and a rewritten parent's old commits are never
  replayed into its child.
- Never loses work: uncommitted work is committed as a checkpoint first. A conflict leaves the rebase in progress
  and the brief names the files and `git rebase --continue` (house-elf finishes it; curfew allows only
  --continue, --abort and --skip). A rebase already in progress is left alone. Any other failure aborts the rebase
  this run started and raises a BriefError whose message is one question (brew then blocks the story).
- Existing code to reuse: the story's `## Reuse` section, plus its listed files that already exist at `onto`.
- Paths in shell commands are shell-quoted (curfew's `cd <worktree> &&` check expects that form).
- A relative `core.hooksPath` (husky) is shared with the worktree, so accio's git hooks run there too (S-012).
"""
import pathlib
import shlex
import string
import subprocess

from accio_lib import config, githooks, globs, paths, story, summary

TEMPLATES = pathlib.Path(__file__).resolve().parent / "templates"
BIN = pathlib.Path(__file__).resolve().parents[1]
BASE_RECORD = "base"


class BriefError(Exception):
    """A brief problem, written for the user."""


def _git(cwd, *args, check=True):
    try:
        result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as error:
        raise BriefError(f"git could not run in {cwd}: {error}") from error
    if check and result.returncode != 0:
        raise BriefError(f"git {' '.join(args)} failed in {cwd}: {result.stderr.strip()}")
    return result


def branch_name(story_id):
    return f"story/{story_id}"


def resolve_onto(main, base_branch, parent=None):
    """The commit a story starts from: the parent's head when stacked, else the base branch."""
    rev = parent or base_branch
    result = _git(main, "rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}", check=False)
    if result.returncode != 0:
        raise BriefError(f"{rev} is not a branch or commit in {main}")
    return result.stdout.strip()


def _registered(main):
    _git(main, "worktree", "prune")
    lines = _git(main, "worktree", "list", "--porcelain").stdout.splitlines()
    return {pathlib.Path(line.split(" ", 1)[1]).resolve() for line in lines if line.startswith("worktree ")}


def has_worktree(main, story_id):
    worktree = paths.worktree_root(main) / story_id
    return worktree.is_dir() and worktree.resolve() in _registered(main)


def _branch_exists(main, branch):
    return _git(main, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0


def _record_base(run_dir, onto):
    from accio_lib import checks  # late: checks imports this module
    write_file(run_dir / BASE_RECORD, onto + "\n")
    log = run_dir.parent / checks.BASE_WRITES_LOG
    try:
        with log.open("a", encoding="utf-8") as handle:
            handle.write(f"{run_dir.name} {onto}\n")
    except OSError as error:
        raise BriefError(f"cannot write {log}: {error}") from error


def recorded_base(run_dir):
    try:
        return (run_dir / BASE_RECORD).read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None


def prepare_worktree(main, run_dir, story_id, onto):
    """Create or reuse the story's worktree; returns (worktree, notes for the brief)."""
    worktree = paths.worktree_root(main) / story_id
    branch = branch_name(story_id)
    if not _branch_exists(main, branch):
        _git(main, "worktree", "add", "-q", str(worktree), "-b", branch, onto)
        _record_base(run_dir, onto)
        _share_hooks(main, worktree)
        return worktree, ()
    if worktree.resolve() not in _registered(main):
        if worktree.exists():
            raise BriefError(f"{worktree} exists but is not a git worktree; move it away and run again")
        _git(main, "worktree", "add", "-q", str(worktree), branch)
    notes = rebase(worktree, onto, recorded_base(run_dir))
    # Even when the rebase stops on a conflict: `checks.trusted_base` only trusts a base that is an ancestor of HEAD,
    # so an aborted rebase falls back to the merge-base, and a finished one diffs from `onto`.
    _record_base(run_dir, onto)
    _share_hooks(main, worktree)
    return worktree, notes


def _share_hooks(main, worktree):
    try:
        githooks.share_with_worktree(main, worktree)
    except githooks.HooksError as error:
        raise BriefError(str(error)) from error


def _rebase_in_progress(worktree):
    for name in ("rebase-merge", "rebase-apply"):
        location = _git(worktree, "rev-parse", "--git-path", name).stdout.strip()
        if (worktree / location).exists():
            return True
    return False


def rebase(worktree, onto, old_base=None):
    """Rebase onto `onto` (from old_base when known); on any obstacle leave the branch as it was and explain."""
    quoted = shlex.quote(str(worktree))
    usable_old = old_base and _git(worktree, "merge-base", "--is-ancestor", old_base, "HEAD", check=False).returncode == 0
    args = ("rebase", "-q", "--onto", onto, old_base) if usable_old else ("rebase", "-q", onto)
    continue_command = f"git -C {quoted} rebase --continue"
    if _rebase_in_progress(worktree):
        return (f"A rebase in progress was found in the worktree. Resolve the conflicts, `git add` the files, and "
                f"run `{continue_command}` (or `git -C {quoted} rebase --abort`).",)
    if _git(worktree, "status", "--porcelain").stdout.strip():
        _commit_checkpoint(worktree)
    if _git(worktree, "merge-base", "--is-ancestor", onto, "HEAD", check=False).returncode == 0:
        return ()
    result = _git(worktree, *args, check=False)
    if result.returncode == 0:
        return ()
    conflicted = _git(worktree, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
    if conflicted and _rebase_in_progress(worktree):
        return (f"Rebase conflict: rebasing onto {onto[:12]} conflicts in {', '.join(conflicted)}, and the rebase is "
                f"in progress in the worktree. Resolve each file, `git add` it, run `{continue_command}`, and "
                f"repeat until it finishes, then go on.",)
    if _rebase_in_progress(worktree):
        _git(worktree, "rebase", "--abort", check=False)
    reason = " ".join(result.stderr.split()) or "git gave no reason"
    raise BriefError(f"Rebasing {branch_of(worktree)} onto {onto[:12]} failed ({reason}). "
                     f"Can you look at the branch and say how to go on?")


def branch_of(worktree):
    return _git(worktree, "branch", "--show-current", check=False).stdout.strip() or "the story branch"


def _commit_checkpoint(worktree):
    """Keep an earlier build's uncommitted work: commit it so the rebase can run."""
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-q", "-m", "checkpoint: uncommitted work from an earlier build")


def scoped_checks(checks, files):
    """Checks whose glob matches a story file; all checks when it lists none or lists a folder."""
    if not files or any(path.endswith("/") for path in files):
        return tuple(checks)
    return tuple(check for check in checks if any(globs.match(path, check["glob"]) for path in files))


def existing_files(main, onto, files):
    return tuple(path for path in files if _git(main, "cat-file", "-e", f"{onto}:{path}", check=False).returncode == 0)


def bullets(items, empty="none"):
    return "\n".join(f"- {item}" for item in items) or f"- {empty}"


def fill(name, values):
    return string.Template((TEMPLATES / name).read_text(encoding="utf-8")).substitute(values)


def common(parsed, worktree, accio):
    story_id = parsed.meta["id"]
    return {"story_id": story_id, "title": parsed.meta["title"], "worktree": worktree,
            "worktree_q": shlex.quote(str(worktree)), "branch": branch_name(story_id),
            "claim_command": f"{shlex.quote(str(BIN / 'accio-claim'))} {story_id}",
            "report": accio / "run" / story_id / summary.REPORT_NAME, "report_sections": summary.report_sections()}


def dod_lines(parsed):
    return "\n".join(f"- {line.id} {'(no test) ' if not line.testable else ''}{line.text}" for line in parsed.dod)


def earlier_commits(worktree, onto, old_base):
    """One line per commit on the story branch past its base (the rebased `onto`, else the recorded old base)."""
    if not pathlib.Path(worktree).is_dir():
        return ()
    for base in (onto, old_base):
        if base and _git(worktree, "merge-base", "--is-ancestor", base, "HEAD", check=False).returncode == 0:
            return tuple(_git(worktree, "log", "--format=%h %s", f"{base}..HEAD").stdout.splitlines())
    return ()


def earlier_work(parsed, worktree, onto, old_base):
    """The "Your earlier work" section: a rebuild's old commits, not accepted, and why (S-012)."""
    commits = earlier_commits(worktree, onto, old_base)
    if not commits:
        return ""
    reasons = [f"### {name}\n{text}" for name in ("Review notes", "Blocked question")
               for text in filter(None, [story.section(parsed, name)])]
    return ("\n## Your earlier work\nThis branch already holds commits from an earlier build. They were not "
            "accepted, so do not hand them back as done. Check each against the Definition of Done and the "
            "reasons below, then fix or redo what falls short.\n" + bullets(f"`{line}`" for line in commits)
            + "".join(f"\n\n{reason}" for reason in reasons) + "\n")


def render_brief(parsed, accio, worktree, onto, checks, reuse_files, notes):
    dod = dod_lines(parsed)
    reuse = [*filter(None, [story.section(parsed, "Reuse")]), *(f"`{path}`" for path in reuse_files)]
    values = {**common(parsed, worktree, accio), "base": onto[:12], "dod": dod,
              "files": bullets(f"`{path}`" for path in parsed.meta.get("files", ())),
              "reuse": bullets(reuse), "checks": bullets(f"`{check['command']}`" for check in checks),
              "scripts": bullets(f"`{shlex.quote(str(path))}`" for path in sorted(BIN.glob("accio-*"))),
              "context": story.section(parsed, "Context") or "none",
              "review_notes": story.section(parsed, "Review notes") or "none",
              "answered": "".join(f"\n## The question from the last build, and its answer\n{text}\n"
                                  for text in filter(None, [story.section(parsed, "Blocked question")])),
              "notes": "".join(f"\n## Before you start\n{note}\n" for note in notes),
              "earlier": earlier_work(parsed, worktree, onto, recorded_base(accio / "run" / parsed.meta["id"]))}
    return fill("brief.md", values)


class FindingsText(str):
    """The text of one findings file, remembering the file's name so a fix round can keep a copy of it."""
    name = ""


def next_fix_dir(run_dir):
    """run/<ID>/fix-<N>/ with N one past the highest round kept so far."""
    rounds = [int(path.name[4:]) for path in run_dir.glob("fix-*") if path.name[4:].isdigit()]
    return run_dir / f"fix-{max(rounds, default=0) + 1}"


def copy_findings(run_dir, findings):
    """Keep the findings a fix round was given in run/<ID>/fix-<N>/ (owl's log reads them); returns the folder."""
    target = next_fix_dir(run_dir)
    for index, text in enumerate(findings, 1):
        name = getattr(text, "name", "") if isinstance(text, FindingsText) else ""
        write_file(target / (name or f"given-{index}-findings.md"), str(text) + "\n")
    return target


def render_fix(parsed, accio, worktree, findings):
    files = parsed.meta.get("files", ())
    copy_findings(accio / "run" / parsed.meta["id"], findings)
    checks = scoped_checks(config.load(accio)["checks"], files)
    values = {**common(parsed, worktree, accio), "findings": "\n\n".join(findings),
              "story_brief": accio / "run" / parsed.meta["id"] / "brief.md",
              "files": bullets(f"`{path}`" for path in files),
              "checks": bullets(f"`{check['command']}`" for check in checks)}
    return fill("fix-brief.md", values)


def write_file(path, text):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError as error:
        raise BriefError(f"cannot write {path}: {error}") from error
    return path


def read_findings(paths_given):
    texts = []
    for path in paths_given:
        try:
            text = FindingsText(path.read_text(encoding="utf-8").strip())
            text.name = path.name
            texts.append(text)
        except (OSError, UnicodeDecodeError) as error:
            raise BriefError(f"cannot read the findings file {path}: {error}") from error
    return tuple(texts)
