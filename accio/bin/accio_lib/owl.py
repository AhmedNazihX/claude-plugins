"""owl's batch answer (DESIGN § 3.5, § 7.3, § 12.2): checked before the merge, applied in one commit after it.

- **check:** every story in review gets one verdict (accept, reject or drop), except a story stacked on a rejected or
  dropped one, which goes back to Ready on its own. Only a blocked story takes an answer, or an allowed command
  (`--allow` from now on, for every story; `--allow-once` for that story's next build only), which answers it too. A story is accepted only with
  each parent it is built on (done, or accepted too). Reasons fit on one line; commands must parse. The accepted
  stories come back in merge order.
- **paths (S-075):** a repo path in a reject reason or an answer (backticked or bare, with a `/` or a known source
  extension; a file that doesn't exist yet counts when its folder does) outside that story's `files:` (judged as
  prefect judges it: a folder entry covers what is under it, a test area is free) makes check refuse, unless
  `--widen <ID> <path>` names it. Close adds each widened path to the story's `files:`. Only a story with a reject or an
  answer can be widened.
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
import pathlib
import re
import shlex
import subprocess

from accio_lib import board, checks, globs, ledger, merge, paths, plan, pushguard, runlock, storyfiles

COMMIT_MESSAGE = "chore(accio): iteration {number} review"
PUSH_TOKEN = pushguard.TOKEN_NAME
QUESTIONS = "questions"
SENT_BACK_FROM = ("review", "blocked", "doing")
CONTROL = re.compile("[\x00-\x1f\x7f\x85\u2028\u2029]")  # with every other break str.splitlines knows
HEADING = re.compile(r"^(\s*)#")
NO_ITERATION_MESSAGE = "chore(accio): build review"


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
    widen: tuple = ()  # (id, path) pairs: a path added to that story's `files:`


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


SOURCE_EXTENSIONS = frozenset("py js mjs cjs ts tsx jsx swift kt java go rs rb sh md json yml yaml toml html css c h cpp "
                               "m mm sql txt plist".split())
WORD = re.compile(r"[^\s`'\"()\[\]<>{},;]+")
LOCATION = re.compile(r"(:\d+.*|::.*)$")
TRAILING = ".:!?*"


def _candidate(root, word):
    """The repo-relative path a word names, or None: it has a `/` or a source extension, stays inside the repo, and
    exists or has its folder."""
    word = LOCATION.sub("", word.rstrip(TRAILING)).removeprefix("./").rstrip("/")
    name = word.rsplit("/", 1)[-1]
    if not word or "://" in word or word.startswith(("/", "~", "-")) or ".." in word.split("/"):
        return None
    if "/" not in word and name.rpartition(".")[2].lower() not in SOURCE_EXTENSIONS:
        return None
    target = pathlib.Path(root) / word
    return word if target.exists() or target.parent.is_dir() else None


def answer_paths(root, text):
    """The repo paths a reject reason or answer names, in order, once each."""
    return list(dict.fromkeys(path for word in WORD.findall(text) if (path := _candidate(root, word))))


def _check_widen(stories, status, answers, verdicts):
    for sid, path in answers.widen:
        if not path.strip() or CONTROL.search(path) or path.startswith(("/", "~")) or ".." in path.split("/"):
            raise OwlError(f"--widen {sid} {path!r}: give a path inside the repo, such as src/app.py or src/")
        if sid not in stories:
            raise OwlError(f"--widen {sid}: there is no story {sid}")
        if verdicts.get(sid) not in ("reject", "answer"):
            here = f"{verdicts[sid]} here" if sid in verdicts else "not in this review"
            raise OwlError(f"--widen {sid} {path}: only a story rejected or answered at this review can be widened "
                           f"({sid} is {_state(status[sid])}, {here})")


def _check_paths(stories, answers, root):
    """Refuse a reject reason or answer that sends the builder to a file its story may not touch."""
    widened = {}
    for sid, path in answers.widen:
        widened.setdefault(sid, []).append(path.removeprefix("./"))
    for sid, text in (*answers.reject, *answers.answer):
        allowed = [*stories[sid].meta.get("files", ()), *widened.get(sid, ())]
        outside = [path for path in answer_paths(root, text)
                   if not checks.in_test_area(path) and not globs.matches_any(path, allowed)]
        if outside:
            names = ", ".join(f"`{path}`" for path in outside)
            flags = " ".join(f"--widen {sid} {path}" for path in outside)
            raise OwlError(f"the answer for {sid} names {names}, outside {sid}'s files, so its builder would be "
                           f"stopped as out of bounds. Add them with {flags}, or reword the answer")


def _widened_files(stories, answers):
    """{story id: new `files:` value} for the stories widened, paths already covered left out."""
    added = {}
    for sid, path in answers.widen:
        path = path.removeprefix("./")
        current = [*stories[sid].meta.get("files", ()), *added.get(sid, ())]
        if not globs.matches_any(path, current):
            added.setdefault(sid, []).append(path)
    return {sid: f"[{', '.join([*stories[sid].meta.get('files', ()), *new])}]" for sid, new in added.items()}


def _sent_back(stories, status, answers):
    gone = [sid for sid, _ in answers.reject + answers.drop]
    return {sid for sid in _children(stories, gone) if status[sid] in SENT_BACK_FROM}


def check(stories, status, answers, root=None):
    """The accepted stories in merge order; raises OwlError naming what is wrong. With `root` (the repo), the paths
    the answers name are checked against the stories' files."""
    verdicts = _verdicts(answers)
    _check_text(answers)
    unknown = [sid for sid in verdicts if sid not in stories]
    if unknown:
        raise OwlError(f"there is no story {', '.join(unknown)}")
    _check_widen(stories, status, answers, verdicts)
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
    if root is not None:
        _check_paths(stories, answers, root)
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
    """Outside text, kept inside one section: every line break becomes `\\n` (the story parser splits on all that
    str.splitlines knows), and a line starting with `#` can't become a heading."""
    return "\n".join(HEADING.sub(r"\1\\#", line) for line in text.splitlines())


def _story_text(parsed, new_status, note, question, answered, dropped, files=None):
    fields = {"status": new_status, **({"dropped": dropped} if dropped else {}), **({"files": files} if files else {})}
    text = storyfiles.with_fields(parsed.path, fields)
    if note:
        text = storyfiles.with_section(text, "Review notes", f"- {_escaped(note)}", append=True)
    if question or answered:
        body = "\n\n".join(filter(None, [question or "(the build left no question file)", *answered]))
        text = storyfiles.with_section(text, "Blocked question", _escaped(body))
    return text


ROW = re.compile(r"^\|\s*(S-\d+)\s*\|(.*)\|\s*$")


def _kept_rows(text):
    """{story id: outcome words} from the rows already in the iteration's Outcome table."""
    rows, inside = {}, False
    for line in text.splitlines():
        if re.match(r"^#{1,2}\s", line):
            inside = line.strip() == "## Outcome"
        match = ROW.match(line.strip()) if inside else None
        if match:
            rows[match.group(1)] = match.group(2).strip()
    return rows


def _iteration_text(path, outcomes):
    """The iteration with this pass's rows added to the Outcome table: a story already there is replaced by id."""
    text = path.read_text(encoding="utf-8")
    rows = {**_kept_rows(text), **{sid: words for sid, (_, words, _, _) in outcomes.items()}}
    body = "\n".join(f"| {sid} | {words} |" for sid, words in sorted(rows.items()))
    return storyfiles.with_section(text, "Outcome", f"| Story | Outcome |\n|---|---|\n{body}")


FINDING_FIELD = re.compile(r"^\s*(?:-\s+)?(id|status|severity|ruling):\s*(.*?)\s*$")
ROUND_DIR = re.compile(r"^fix-(\d+)$")
LINE_KEY = re.compile(r"^([^:]*):")
BLOCK_KIND = re.compile(r"^\((accio|user)\)\s*:?\s*", re.IGNORECASE)
LOG_HEADING = "Findings and blocks"


def _findings_in(folder):
    """{finding id: {status, severity, ruling}} from the *-findings.md files in a folder (findings template)."""
    found = {}
    for path in sorted(folder.glob("*-findings.md")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError) as error:
            raise OwlError(f"cannot read the findings file {path}: {error}") from error
        current = None
        for line in lines:
            match = FINDING_FIELD.match(line)
            if not match:
                continue
            key, value = match.groups()
            if key == "id":
                current = found.setdefault(value, {})
            elif current is not None:
                current[key] = value
    return found


def _finding_line(sid, fid, held, latest, has_last):
    """The log line for one finding. `held` is [(round, fields)] for the rounds that were given it, `latest` its
    fields in the last files (None when gone)."""
    details = {**(held[-1][1] if held else {}), **(latest or {})}
    head = f"{sid} {fid} {details.get('severity', 'unrated')}:"
    status = (latest or {}).get("status", "")
    if status == "dismissed":
        return f"{head} dismissed: {_escaped(details.get('ruling') or 'no ruling written')}"
    if latest is not None and status != "resolved":
        return f"{head} open"
    if latest is None and not has_last:
        return f"{head} open (no later findings file to say otherwise)"
    return f"{head} fixed in round {held[-1][0]}" if held else f"{head} fixed"


def _rounds(folder):
    found = []
    for path in folder.glob("fix-*"):
        match = ROUND_DIR.match(path.name)
        if match and path.is_dir():
            found.append((int(match.group(1)), _findings_in(path)))
    return sorted(found, key=lambda pair: pair[0])


def _finding_lines(run_dir, sid):
    folder = run_dir / sid
    if not folder.is_dir():
        return []
    rounds, last = _rounds(folder), _findings_in(folder)
    has_last = any(folder.glob("*-findings.md"))
    ids = dict.fromkeys([*(fid for _, found in rounds for fid in found), *last])
    return [_finding_line(sid, fid, [(number, found[fid]) for number, found in rounds if fid in found],
                          last.get(fid), has_last) for fid in ids]


def _block_line(run_dir, sid):
    text = _question(run_dir, sid)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first:
        return None
    match = BLOCK_KIND.match(first)
    kind = match.group(1).lower() if match else "user"
    return f"{sid} blocked ({kind}): {_escaped(first[match.end():] if match else first)}"


def _boggart_lines(run_dir, sid):
    """Log lines for the breaks boggart left in `run/<ID>/boggart/verdicts.json` (S-043): a kept break outside the DoD
    (a note for the backlog, no fix round), and a kept repro that can't load (a setup error on head). A kept break
    inside the DoD is handled by its fix rounds and its block, so it adds no line here."""
    path = run_dir / sid / "boggart" / "verdicts.json"
    try:
        repros = json.loads(path.read_text(encoding="utf-8"))["repros"]
    except (OSError, ValueError, KeyError, TypeError):
        return []
    lines = []
    for entry in repros:
        if not isinstance(entry, dict) or entry.get("verdict") != "kept":
            continue
        name = entry.get("file", "repro")
        if entry.get("cant_load") is True:  # set by breaker.py only for a setup error on head, never read from reason text
            lines.append(f"{sid} boggart {name}: repro can't load (setup error after a fix round)")
        elif not entry.get("in_dod"):
            lines.append(f"{sid} boggart {name} outside the DoD: {entry.get('claim', '')} ({entry.get('source', '')})")
    return lines


def _kept_log(text):
    """The lines already in the iteration's log section."""
    lines, inside = [], False
    for line in text.splitlines():
        if re.match(r"^#{1,2}\s", line):
            inside = line.strip() == f"## {LOG_HEADING}"
        elif inside and line.strip().startswith("- "):
            lines.append(line.strip()[2:])
    return lines


def _log_text(accio, stories, text, extra):
    """The iteration text with its log section: a line replaces an earlier one that starts the same way."""
    run_dir = board.run_dir(accio)
    ids = sorted(stories)
    fresh = [*(line for sid in ids for line in _finding_lines(run_dir, sid)),
             *filter(None, (_block_line(run_dir, sid) for sid in ids)),
             *(_escaped(" ".join(line.split())) for sid in ids for line in _boggart_lines(run_dir, sid)),
             *(_escaped(" ".join(line.split())) for line in extra if line.strip())]
    merged = {}
    for line in [*_kept_log(text), *fresh]:
        key = LINE_KEY.match(line)
        merged[key.group(1) if key else line] = line
    body = "\n".join(f"- {line}" for line in merged.values()) or "none"
    return storyfiles.with_section(text, LOG_HEADING, body)


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


SAFE_GIT = ("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null")


def _admin_dir(root, worktree):
    """The worktree's record in the main repo's git dir, found from the main side: the worktree's own `.git` file is
    something code a check ran could rewrite, so git never discovers the repo from inside it."""
    common = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    target = (worktree / ".git").resolve(strict=False)
    for record in sorted(pathlib.Path(common, "worktrees").glob("*")) if common else ():
        try:
            if pathlib.Path((record / "gitdir").read_text(encoding="utf-8").strip()).resolve(strict=False) == target:
                return record
        except OSError:
            continue
    return None


def _remove_worktree(root, sid):
    """Remove a dropped story's worktree when it holds nothing of its own; else return why it was kept."""
    worktree = paths.worktree_root(root) / sid
    if not worktree.exists():
        return None
    record = _admin_dir(root, worktree)
    if record is None:
        return f"{worktree} (kept: it isn't a worktree this repo knows)"
    own = _git(root, *SAFE_GIT, f"--git-dir={record}", f"--work-tree={worktree}", "status", "--porcelain",
               "--ignored", "--untracked-files=all").stdout.split("\n")
    own = [line[3:] for line in own if line.strip()]
    if own:
        return f"{worktree} (kept: it holds {', '.join(own[:3])}{' …' if len(own) > 3 else ''})"
    return None if _git(root, *SAFE_GIT, "worktree", "remove", str(worktree)).returncode == 0 else str(worktree)


def _texts(accio, stories, status, answers, outcomes, number, extra=()):
    run_dir = board.run_dir(accio)
    answered, dropped, widened = _answered(answers), dict(answers.drop), _widened_files(stories, answers)
    texts = {}
    for sid, (new_status, _, note, _) in outcomes.items():
        kept = status[sid] == "blocked" and (new_status == "blocked" or sid in answered)
        question = _question(run_dir, sid) if kept else ""
        texts[stories[sid].path] = _story_text(stories[sid], new_status, note, question, answered.get(sid, []),
                                               dropped.get(sid), widened.get(sid))
    if number is not None:
        iteration = accio / plan.ITERATIONS / f"{number}.md"
        texts[iteration] = _log_text(accio, stories, _iteration_text(iteration, outcomes), extra)
    texts[accio / board.BOARD_NAME] = board.render(stories, {**status, **{sid: change[0] for sid, change in
                                                                         outcomes.items()}})
    commands = [command for _, command in answers.allow]
    if commands:
        texts[accio / "config.json"] = _config_text(accio, commands)
    return texts


def _settle_run(accio, answers, outcomes, logged=False):
    """Right after the write: the run's statuses (only a crash's Doing stays), the grants for the next build, the
    question files that are answered or moot. Doing this first makes a second close refuse instead of repeating."""
    run_dir = board.run_dir(accio)
    doing = {sid: value for sid, value in board.read_overrides(accio).items()
             if value == "doing" and sid not in outcomes}
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
    if logged:  # the log holds them now; a kept question lives on in its story file
        for path in (run_dir / QUESTIONS).glob("*.md"):
            path.unlink()


def _tidy(accio, answers, outcomes, logged=False):
    """After the write: settle the run, clear ledger entries, remove dropped worktrees; returns leftovers."""
    try:
        _settle_run(accio, answers, outcomes, logged)
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


def close(accio, answers, base, merged=(), culprit=None, lines=()):
    """Apply the batch answer after the merge; `lines` are extra entries for the iteration's `## Findings and
    blocks` (such as a boggart break outside the DoD). Returns {iteration, outcomes, leftovers, commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise OwlError("a build is running (run/brew.lock); review it after it ends")
    _on_base(accio.parent, base)
    stories = board.load_stories(accio)
    status = board.statuses(stories, board.read_overrides(accio))
    accepted = check(stories, status, answers, accio.parent)
    _check_merge(stories, status, accepted, tuple(merged), culprit)
    iterations = plan.iterations(accio)
    number = iterations[-1][0] if iterations else None
    outcomes = _outcomes(stories, status, answers, tuple(merged), culprit)
    texts = _texts(accio, stories, status, answers, outcomes, number, tuple(lines))
    try:
        storyfiles.write_all(texts, "the review")
    except storyfiles.WriteError as error:
        raise OwlError(str(error)) from error
    leftovers = _tidy(accio, answers, outcomes, number is not None)
    message = COMMIT_MESSAGE.format(number=number) if number is not None else NO_ITERATION_MESSAGE
    commit, why = storyfiles.commit(accio.parent, list(map(str, texts)), message)
    return {"iteration": number, "outcomes": {sid: words for sid, (_, words, _, _) in sorted(outcomes.items())},
            "leftovers": leftovers, "commit": commit, "commit_error": why}


def push_ok(accio, base):
    """Write the one-time push token for base's head; returns {base, sha, prev}.

    prev is the old tip of origin/<base> as this checkout knows it (read before the push
    moves it), or None when that ref does not exist."""
    run_dir = board.run_dir(accio)
    if runlock.is_held(run_dir):
        raise OwlError("a build is running (run/brew.lock); push after it ends and you have reviewed it")
    _on_base(accio.parent, base)
    found = _git(accio.parent, "rev-parse", "--verify", "--quiet", f"refs/heads/{base}")
    sha = found.stdout.strip()
    if found.returncode != 0 or not sha:
        raise OwlError(f"can't find the head of {base}")
    old = _git(accio.parent, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{base}")
    prev = old.stdout.strip() if old.returncode == 0 and old.stdout.strip() else None
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / PUSH_TOKEN).write_text(sha + "\n", encoding="utf-8")
    except OSError as error:
        raise OwlError(f"cannot write {run_dir / PUSH_TOKEN}: {error}") from error
    return {"base": base, "sha": sha, "prev": prev}
