"""owl's batch answer (DESIGN § 3.5, § 7.3, § 12.2): checked before the merge, applied in one commit after it.

- **check:** every story in review gets one verdict (accept, reject or drop), except a story stacked on a rejected or
  dropped one, which goes back to Ready on its own. Only a blocked story takes an answer. A story is accepted only
  with each parent it is built on (done, or accepted too). The accepted stories come back in merge order.
- **close** (after `accio-merge`): merged → done. Rejected → Ready with the reason in its Review notes and its
  ledger entries cleared; a merge culprit likewise, with the failure. Each story stacked on one of those goes back
  to Ready too. Dropped → `dropped` with the reason, its worktree removed (never forced) and its branch kept.
  Answered → Ready, the question and answer in its Blocked question section. An unanswered question is kept in its
  story file; an accepted story that wasn't merged stays in review. Then run/status.json is folded into the story
  files and removed, the iteration's outcome and board.md are written, `agent_allow` grows by `--allow` and
  `run/allow-once.json` holds `--allow-once` for the next build only, and one commit records it all.
- **push-ok:** the one-time push token, the base branch's head, written only when no build runs and the main
  checkout is on the base branch (the pre-push guard never lets a token open a build: S-015, S-022).
"""
import dataclasses
import json
import subprocess

from accio_lib import board, ledger, merge, paths, plan, pushguard, runlock, storyfiles

COMMIT_MESSAGE = "chore(accio): iteration {number} review"
PUSH_TOKEN = pushguard.TOKEN_NAME
QUESTIONS = "questions"
SENT_BACK_FROM = ("review", "blocked")


class OwlError(Exception):
    """An answer or state problem, written for the user."""


@dataclasses.dataclass(frozen=True)
class Answers:
    accept: tuple = ()
    reject: tuple = ()  # (id, reason) pairs
    drop: tuple = ()
    answer: tuple = ()
    allow: tuple = ()
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


def _verdicts(answers):
    pairs = [(sid, "accept") for sid in answers.accept] + [(sid, kind) for kind in ("reject", "drop", "answer")
                                                           for sid, _ in getattr(answers, kind)]
    seen, twice = {}, []
    for sid, kind in pairs:
        if sid in seen:
            twice.append(sid)
        seen[sid] = kind
    if twice:
        raise OwlError(f"{', '.join(sorted(set(twice)))} has two answers; give each story one")
    return seen


def _sent_back(stories, status, answers):
    gone = [sid for sid, _ in answers.reject + answers.drop]
    return {sid for sid in _children(stories, gone) if status[sid] in SENT_BACK_FROM}


def check(stories, status, answers):
    """The accepted stories in merge order; raises OwlError naming what is wrong."""
    verdicts = _verdicts(answers)
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


def _question(run_dir, sid):
    try:
        return (run_dir / QUESTIONS / f"{sid}.md").read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeDecodeError) as error:
        raise OwlError(f"cannot read the question of {sid}: {error}") from error


def _outcomes(stories, status, answers, merged, culprit):
    """{story: (new status, outcome words, Review notes line or None, ledger cleared)} for the stories that change."""
    out = {sid: ("done", "merged", None, False) for sid in merged}
    for sid, reason in answers.reject:
        out[sid] = ("ready", "rejected", f"Rejected at owl: {reason}", True)
    if culprit:
        out[culprit[0]] = ("ready", "back to Ready (merge checks failed)", f"Merge checks failed: {culprit[1]}", True)
    for sid, reason in answers.drop:
        out[sid] = ("dropped", "dropped", None, False)
    for sid, _ in answers.answer:
        out[sid] = ("ready", "answered", None, False)
    for cause in [sid for sid, _ in answers.reject + answers.drop] + ([culprit[0]] if culprit else []):
        verb = "dropped" if cause in dict(answers.drop) else "rejected" if cause in dict(answers.reject) else "sent back"
        for child in sorted(_children(stories, [cause])):
            if status[child] in SENT_BACK_FROM and child not in out:
                out[child] = ("ready", f"back to Ready ({cause} was {verb})", f"{cause} was {verb} at owl; rebuild "
                              f"on its next version.", True)
    for sid in answers.accept:
        out.setdefault(sid, ("review", "carried over (accepted, not merged)", None, False))
    for sid in stories:
        if status[sid] == "blocked" and sid not in out:
            out[sid] = ("blocked", "blocked (question kept)", None, False)
    return out


def _story_text(parsed, new_status, note, question, answer, dropped):
    fields = {"status": new_status, **({"dropped": dropped} if dropped else {})}
    text = storyfiles.with_fields(parsed.path, fields)
    if note:
        text = storyfiles.with_section(text, "Review notes", f"- {note}", append=True)
    if question:
        body = question + (f"\n\nAnswer: {answer}" if answer else "")
        text = storyfiles.with_section(text, "Blocked question", body)
    return text


def _iteration_text(path, outcomes):
    rows = "\n".join(f"| {sid} | {words} |" for sid, (_, words, _, _) in sorted(outcomes.items()))
    body = f"| Story | Outcome |\n|---|---|\n{rows}"
    text = path.read_text(encoding="utf-8")
    return storyfiles.with_section(text, "Outcome", body)


def _config_text(accio, allow):
    path = accio / "config.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, ValueError) as error:
        raise OwlError(f"cannot read {path}: {error}") from error
    current = list(data.get("agent_allow", []))
    data["agent_allow"] = current + [command for command in dict.fromkeys(allow) if command not in current]
    return json.dumps(data, indent=2) + "\n"


def _remove_worktree(root, sid):
    worktree = paths.worktree_root(root) / sid
    if not worktree.exists():
        return None
    result = subprocess.run(["git", "worktree", "remove", str(worktree)], cwd=root, capture_output=True, text=True,
                            check=False)
    return None if result.returncode == 0 else str(worktree)


def _texts(accio, stories, status, answers, outcomes, number):
    run_dir = board.run_dir(accio)
    answered, dropped = dict(answers.answer), dict(answers.drop)
    texts = {}
    for sid, (new_status, _, note, _) in outcomes.items():
        question = _question(run_dir, sid) if status[sid] == "blocked" else ""
        texts[stories[sid].path] = _story_text(stories[sid], new_status, note, question, answered.get(sid),
                                               dropped.get(sid))
    iteration = accio / plan.ITERATIONS / f"{number}.md"
    texts[iteration] = _iteration_text(iteration, outcomes)
    after = {**status, **{sid: change[0] for sid, change in outcomes.items()}}
    texts[accio / board.BOARD_NAME] = board.render(stories, after)
    if answers.allow:
        texts[accio / "config.json"] = _config_text(accio, answers.allow)
    return texts


def _tidy(accio, root, answers, outcomes):
    """After the write: ledger entries, worktrees, question files and the run's statuses; returns leftovers."""
    run_dir = board.run_dir(accio)
    for sid, (_, _, _, clear) in outcomes.items():
        if clear:
            ledger.clear(run_dir, sid)
    leftovers = [left for sid, _ in answers.drop if (left := _remove_worktree(root, sid))]
    for sid, _ in answers.answer:
        (run_dir / QUESTIONS / f"{sid}.md").unlink(missing_ok=True)
    (run_dir / board.STATUS_NAME).unlink(missing_ok=True)
    if answers.allow_once:
        (run_dir / runlock.ALLOW_ONCE_NAME).write_text(json.dumps(list(dict.fromkeys(answers.allow_once))) + "\n",
                                                       encoding="utf-8")
    return leftovers


def close(accio, answers, merged=(), culprit=None):
    """Apply the batch answer after the merge; returns {iteration, outcomes, leftovers, commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise OwlError("a build is running (run/brew.lock); review it after it ends")
    stories = board.load_stories(accio)
    status = board.statuses(stories, board.read_overrides(accio))
    accepted = check(stories, status, answers)
    stray = [sid for sid in (*merged, *([culprit[0]] if culprit else ())) if sid not in accepted]
    if stray:
        raise OwlError(f"only accepted stories are merged or sent back by the merge, not {', '.join(stray)}")
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
    leftovers = _tidy(accio, accio.parent, answers, outcomes)
    commit, why = storyfiles.commit(accio.parent, list(map(str, texts)), COMMIT_MESSAGE.format(number=number))
    return {"iteration": number, "outcomes": {sid: words for sid, (_, words, _, _) in sorted(outcomes.items())},
            "leftovers": leftovers, "commit": commit, "commit_error": why}


def push_ok(accio, base):
    """Write the one-time push token for base's head; returns {base, sha}."""
    run_dir = board.run_dir(accio)
    if runlock.is_held(run_dir):
        raise OwlError("a build is running (run/brew.lock); push after it ends and you have reviewed it")
    root = accio.parent
    branch = subprocess.run(["git", "branch", "--show-current"], cwd=root, capture_output=True, text=True,
                            check=False).stdout.strip()
    if branch != base:
        raise OwlError(f"the main checkout is on {branch or 'a detached HEAD'}, not {base}; switch to {base} first")
    sha = subprocess.run(["git", "rev-parse", base], cwd=root, capture_output=True, text=True,
                         check=False).stdout.strip()
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / PUSH_TOKEN).write_text(sha + "\n", encoding="utf-8")
    except OSError as error:
        raise OwlError(f"cannot write {run_dir / PUSH_TOKEN}: {error}") from error
    return {"base": base, "sha": sha}

