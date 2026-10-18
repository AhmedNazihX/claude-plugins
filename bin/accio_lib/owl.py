"""owl's batch answer (DESIGN § 3.5, § 7.3, § 12.2): checked before the merge, applied in one commit after it.

- **check:** every story in review gets one verdict (accept, reject or drop), except a story stacked on a rejected or
  dropped one, which goes back to Ready on its own. Only a blocked story takes an answer, or an allowed command
  (`--allow` from now on, for every story; `--allow-once` for that story's next build only), which answers it too. A story is accepted only with
  each parent it is built on (done, or accepted too). Reasons fit on one line; commands must parse. The accepted
  stories come back in merge order.
- **close** (after `accio-merge`, on the base branch): merged → done, each merged story's parents merged or done.
  Rejected → Ready with the reason in its Review notes and its ledger entries cleared; a merge culprit likewise, with
  the failure. Each story stacked on one of those goes back to Ready too. Dropped → `dropped` with the reason, its
  worktree removed only when it holds nothing of its own (never forced), its branch kept. Answered → Ready, the
  question and answer in its Blocked question section; an unanswered question is kept there. An accepted story that
  wasn't merged stays in review; one a crash left in Doing stays in Doing for the next build. Then the iteration's
  outcome, board.md and `agent_allow` are written, and one commit records it all. Text from outside (answers,
  questions) can't open a section: a line starting with `#` is escaped.
- **push-ok:** the one-time push token, the base branch's head, written only when no build runs and the main
  checkout is on the base branch (the pre-push guard never lets a token open a build: S-015, S-022).
"""
import dataclasses
import json
import re
import shlex
import subprocess

from accio_lib import board, ledger, merge, paths, plan, pushguard, runlock, storyfiles

COMMIT_MESSAGE = "chore(accio): iteration {number} review"
PUSH_TOKEN = pushguard.TOKEN_NAME
QUESTIONS = "questions"
SENT_BACK_FROM = ("review", "blocked")
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
HEADING_LINE = re.compile(r"^(\s*)#", re.MULTILINE)


class OwlError(Exception):
    """An answer or state problem, written for the user."""


@dataclasses.dataclass(frozen=True)
class Answers:
    accept: tuple = ()
    reject: tuple = ()  # (id, reason) pairs
    drop: tuple = ()
    answer: tuple = ()
    allow: tuple = ()  # (id, command) pairs
    allow_once: tuple = ()


def _state(status):
    return "in review" if status == "review" else status


def _children(stories, roots):
    """Every story stacked, directly or not, on one of `roots`."""
    found, frontier = set(), set(roots)
    while frontier:
        found |= frontier
        frontier = {sid for sid, parsed in stories.items() if set(parsed.meta.get("deps", ())) & frontier} - found
    return found - set(roots)


def _answered(answers):
    """{story: [lines for its Blocked question section]} from answers and allowed commands."""
    lines = {}
    for sid, text in answers.answer:
        lines.setdefault(sid, []).append(f"Answer: {text}")
    for kind, words in (("allow", "Allowed from now on"), ("allow_once", "Allowed for the next build")):
        for sid, command in getattr(answers, kind):
            lines.setdefault(sid, []).append(f"{words}: {command}")
    return lines


def _verdicts(answers):
    pairs = [(sid, "accept") for sid in answers.accept] + [(sid, kind) for kind in ("reject", "drop")
                                                           for sid, _ in getattr(answers, kind)]
    pairs += [(sid, "answer") for sid in _answered(answers)]
    seen, twice = {}, []
    for sid, kind in pairs:
        if sid in seen:
            twice.append(sid)
        seen[sid] = kind
    if twice:
        raise OwlError(f"{', '.join(sorted(set(twice)))} has two answers; give each story one")
    return seen


def _check_text(answers):
    for sid, reason in answers.reject + answers.drop:
        if CONTROL.search(reason) or not reason.strip():
            raise OwlError(f"the reason for {sid} must be one line of text")
    for sid, command in answers.allow + answers.allow_once:
        try:
            words = shlex.split(command)
        except ValueError:
            words = []
        if CONTROL.search(command) or not words:
            raise OwlError(f"the command allowed for {sid} can't be read as a command: {command!r}")


def _sent_back(stories, status, answers):
    gone = [sid for sid, _ in answers.reject + answers.drop]
    return {sid for sid in _children(stories, gone) if status[sid] in SENT_BACK_FROM}


def check(stories, status, answers):
    """The accepted stories in merge order; raises OwlError naming what is wrong."""
    verdicts = _verdicts(answers)
    _check_text(answers)
    unknown = [sid for sid in verdicts if sid not in stories]
    if unknown:
        raise OwlError(f"there is no story {', '.join(unknown)}")
    for sid, kind in verdicts.items():
        if kind in ("accept", "reject") and status[sid] != "review":
            raise OwlError(f"{sid} is {_state(status[sid])}: only a story in review is accepted or rejected")
        if kind == "answer" and status[sid] != "blocked":
            raise OwlError(f"{sid} is {_state(status[sid])}: only a blocked story takes an answer")
        if kind == "drop" and status[sid] in ("done", "dropped"):
            raise OwlError(f"{sid} is {status[sid]} already")
    for sid in answers.accept:
        for dep in stories[sid].meta.get("deps", ()):
            if status[dep] != "done" and verdicts.get(dep) != "accept":
                raise OwlError(f"{sid} is built on {dep}, so it can only go in with it: accept {dep} too, or "
                               f"reject or drop {sid}")
    sent_back = _sent_back(stories, status, answers)
    undecided = sorted(sid for sid in stories if status[sid] == "review" and sid not in verdicts
                       and sid not in sent_back)
    if undecided:
        raise OwlError(f"these stories in review have no answer yet: {', '.join(undecided)} (accept, reject or drop "
                       "each)")
    return merge.merge_order(stories, status, tuple(answers.accept))


def _check_merge(stories, status, accepted, merged, culprit):
    stray = [sid for sid in (*merged, *([culprit[0]] if culprit else ())) if sid not in accepted]
    if stray:
        raise OwlError(f"only accepted stories are merged or sent back by the merge, not {', '.join(stray)}")
    if culprit and CONTROL.sub(" ", culprit[1]).strip() == "":
        raise OwlError(f"say what failed when {culprit[0]} was merged")
    for sid in merged:
        for dep in stories[sid].meta.get("deps", ()):
            if status[dep] != "done" and dep not in merged:
                raise OwlError(f"{sid} is built on {dep}, which wasn't merged, so {sid} can't have been either")


def _question(run_dir, sid):
    try:
        return (run_dir / QUESTIONS / f"{sid}.md").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as error:
        raise OwlError(f"cannot read the question of {sid}: {error}") from error


def _sent_back_outcomes(stories, status, answers, culprit, out):
    causes = [(sid, "rejected") for sid, _ in answers.reject] + [(sid, "dropped") for sid, _ in answers.drop]
    causes += [(culprit[0], "sent back by the merge")] if culprit else []
    for cause, verb in causes:
        then = ("the next plan asks what to do with it" if verb == "dropped"
                else "rebuild it on the parent's next version")
        for child in sorted(_children(stories, [cause])):
            if status[child] in SENT_BACK_FROM and child not in out:
                out[child] = ("ready", f"back to Ready ({cause} was {verb})",
                              f"Its parent {cause} was {verb} at owl; {then}.", True)


def _outcomes(stories, status, answers, merged, culprit):
    """{story: (new status, outcome words, Review notes line or None, ledger cleared)} for the stories that change."""
    out = {sid: ("done", "merged", None, False) for sid in merged}
    for sid, reason in answers.reject:
        out[sid] = ("ready", "rejected", f"Rejected at owl: {reason}", True)
    if culprit:
        failure = CONTROL.sub(" ", culprit[1]).strip()
        out[culprit[0]] = ("ready", "back to Ready (merge checks failed)", f"Merge checks failed: {failure}", True)
    for sid, _ in answers.drop:
        out[sid] = ("dropped", "dropped", None, False)
    for sid in _answered(answers):
        out[sid] = ("ready", "answered", None, False)
    _sent_back_outcomes(stories, status, answers, culprit, out)
    for sid in answers.accept:
        out.setdefault(sid, ("review", "carried over (accepted, not merged)", None, False))
    for sid in stories:
        if status[sid] == "blocked" and sid not in out:
            out[sid] = ("blocked", "blocked (question kept)", None, False)
    return out


def _escaped(text):
    """Outside text, kept inside one section: a line starting with `#` can't become a heading."""
    return HEADING_LINE.sub(r"\1\\#", text)


def _story_text(parsed, new_status, note, question, answered, dropped):
    fields = {"status": new_status, **({"dropped": dropped} if dropped else {})}
    text = storyfiles.with_fields(parsed.path, fields)
    if note:
        text = storyfiles.with_section(text, "Review notes", f"- {_escaped(note)}", append=True)
    if question or answered:
        body = "\n\n".join(filter(None, [question or "(the build left no question file)", *answered]))
        text = storyfiles.with_section(text, "Blocked question", _escaped(body))
    return text


def _iteration_text(path, outcomes):
    rows = "\n".join(f"| {sid} | {words} |" for sid, (_, words, _, _) in sorted(outcomes.items()))
    return storyfiles.with_section(path.read_text(encoding="utf-8"), "Outcome", f"| Story | Outcome |\n|---|---|\n{rows}")


def _config_text(accio, allow):
    path = accio / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as error:
        raise OwlError(f"cannot read {path}: {error}") from error
    current = list(data.get("agent_allow", []))
    data["agent_allow"] = current + [command for command in dict.fromkeys(allow) if command not in current]
    return json.dumps(data, indent=2) + "\n"


def _git(cwd, *args):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as error:
        raise OwlError(f"git could not run in {cwd}: {error}") from error


def _remove_worktree(root, sid):
    """Remove a dropped story's worktree when it holds nothing of its own; else return why it was kept."""
    worktree = paths.worktree_root(root) / sid
    if not worktree.exists():
        return None
    own = _git(worktree, "status", "--porcelain", "--ignored", "--untracked-files=all").stdout.split("\n")
    own = [line[3:] for line in own if line.strip()]
    if own:
        return f"{worktree} (kept: it holds {', '.join(own[:3])}{' …' if len(own) > 3 else ''})"
    return None if _git(root, "worktree", "remove", str(worktree)).returncode == 0 else str(worktree)


def _texts(accio, stories, status, answers, outcomes, number):
    run_dir = board.run_dir(accio)
    answered, dropped = _answered(answers), dict(answers.drop)
    texts = {}
    for sid, (new_status, _, note, _) in outcomes.items():
        kept = status[sid] == "blocked" and (new_status == "blocked" or sid in answered)
        question = _question(run_dir, sid) if kept else ""
        texts[stories[sid].path] = _story_text(stories[sid], new_status, note, question, answered.get(sid, []),
                                               dropped.get(sid))
    iteration = accio / plan.ITERATIONS / f"{number}.md"
    texts[iteration] = _iteration_text(iteration, outcomes)
    texts[accio / board.BOARD_NAME] = board.render(stories, {**status, **{sid: change[0] for sid, change in
                                                                         outcomes.items()}})
    commands = [command for _, command in answers.allow]
    if commands:
        texts[accio / "config.json"] = _config_text(accio, commands)
    return texts


def _settle_run(accio, answers, outcomes, status):
    """Right after the write: the run's statuses (only a crash's Doing stays), the grants for the next build, the
    question files that are answered or moot. Doing this first makes a second close refuse instead of repeating."""
    run_dir = board.run_dir(accio)
    doing = {sid: value for sid, value in board.read_overrides(accio).items() if value == "doing"}
    path = run_dir / board.STATUS_NAME
    if doing:
        path.write_text(json.dumps(doing) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    once = {}
    for sid, command in answers.allow_once:
        once.setdefault(sid, []).append(command)
    if once:
        (run_dir / runlock.ALLOW_ONCE_NAME).write_text(json.dumps({"stories": once}) + "\n", encoding="utf-8")
    for sid, (new_status, _, _, _) in outcomes.items():
        if new_status != "blocked":  # answered, or moot: the story is done, dropped or built again
            (run_dir / QUESTIONS / f"{sid}.md").unlink(missing_ok=True)


def _tidy(accio, answers, outcomes, status):
    """After the write: settle the run, clear ledger entries, remove dropped worktrees; returns leftovers."""
    try:
        _settle_run(accio, answers, outcomes, status)
        for sid, (_, _, _, clear) in outcomes.items():
            if clear:
                ledger.clear(board.run_dir(accio), sid)
    except (OSError, ledger.LedgerError) as error:
        raise OwlError(f"the story files are written, but tidying the run failed ({error}); fix it and commit "
                       ".accio/ by hand") from error
    return [left for sid, _ in answers.drop if (left := _remove_worktree(accio.parent, sid))]


def _on_base(root, base):
    branch = _git(root, "branch", "--show-current").stdout.strip()
    if branch != base:
        raise OwlError(f"the main checkout is on {branch or 'a detached HEAD'}, not {base}; switch to {base} first")


def close(accio, answers, base, merged=(), culprit=None):
    """Apply the batch answer after the merge; returns {iteration, outcomes, leftovers, commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise OwlError("a build is running (run/brew.lock); review it after it ends")
    _on_base(accio.parent, base)
    stories = board.load_stories(accio)
    status = board.statuses(stories, board.read_overrides(accio))
    accepted = check(stories, status, answers)
    _check_merge(stories, status, accepted, tuple(merged), culprit)
    iterations = plan.iterations(accio)
    if not iterations:
        raise OwlError("there is no iteration to close (.accio/iterations/ is empty); plan one with prophecy")
    number = iterations[-1][0]
    outcomes = _outcomes(stories, status, answers, tuple(merged), culprit)
    texts = _texts(accio, stories, status, answers, outcomes, number)
    try:
        storyfiles.write_all(texts, f"iteration {number}'s review")
    except storyfiles.WriteError as error:
        raise OwlError(str(error)) from error
    leftovers = _tidy(accio, answers, outcomes, status)
    commit, why = storyfiles.commit(accio.parent, list(map(str, texts)), COMMIT_MESSAGE.format(number=number))
    return {"iteration": number, "outcomes": {sid: words for sid, (_, words, _, _) in sorted(outcomes.items())},
            "leftovers": leftovers, "commit": commit, "commit_error": why}


def push_ok(accio, base):
    """Write the one-time push token for base's head; returns {base, sha}."""
    run_dir = board.run_dir(accio)
    if runlock.is_held(run_dir):
        raise OwlError("a build is running (run/brew.lock); push after it ends and you have reviewed it")
    _on_base(accio.parent, base)
    found = _git(accio.parent, "rev-parse", "--verify", "--quiet", f"refs/heads/{base}")
    sha = found.stdout.strip()
    if found.returncode != 0 or not sha:
        raise OwlError(f"can't find the head of {base}")
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / PUSH_TOKEN).write_text(sha + "\n", encoding="utf-8")
    except OSError as error:
        raise OwlError(f"cannot write {run_dir / PUSH_TOKEN}: {error}") from error
    return {"base": base, "sha": sha}
