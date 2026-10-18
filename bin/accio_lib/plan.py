"""The iteration plan behind `prophecy` (DESIGN § 3.3; decision 009): what to propose, and what "go" writes.

- A candidate is a story in Backlog or Ready. It is eligible when each dep is done, or is itself eligible and the
  chain stays within `stack_depth` levels. A dep in any other state holds it back: dropped (listed apart, for a
  question) or still in progress (listed as waiting).
- The proposal takes eligible stories in dependency order (level, then id), up to `iteration_max`. A child comes
  only with its parent, and only with one parent from the same iteration (brew runs the second in a later run).
- "go" makes the chosen set exactly the iteration: it re-checks the set the same way, sets each chosen story's
  `status: ready` (and any track override) in its story file, and returns any other Ready story to Backlog, so the
  build never takes a story the user left out. An iteration planned but not built yet (its outcome is still the
  placeholder and its stories are still Ready) is planned again under its own number. It writes
  `iterations/<N>.md` and `board.md`, all or nothing, then commits exactly those files plus the story files the
  skill edited (`--also`), with `git commit --only`, so nothing else the user staged goes in (each listed file goes
  in whole, hand edits included). Files that already match HEAD need no commit. A commit git refuses (a hook, no
  repo) leaves the plan written, unstaged, and says why. It refuses while a build holds the run lock: then
  run/status.json, not the story file, holds the status.
- Values are changed in place: a line's trailing comment, the file's line endings and its mode are kept.
"""
import pathlib
import re

from accio_lib import board, runlock, story, storyfiles

CANDIDATE = ("backlog", "ready")
ITERATIONS = "iterations"
ITERATION_FILE = re.compile(r"^(\d+)\.md$")
ITERATION_ROW = re.compile(r"^\| (S-\d{3,}) \|", re.MULTILINE)
OUTCOME_PLACEHOLDER = "Written by `/accio:owl`."
TWO_PARENTS = "it stacks on 2 stories of this iteration; it can go in the next one"
COMMIT_MESSAGE = "chore(accio): plan iteration {number}"


class PlanError(Exception):
    """A plan problem, written for the user."""


def _levels(stories, status, stack_depth, candidates):
    """Each candidate's stacking level (1 = no parent in the iteration), or None when it isn't eligible."""
    levels = {}

    def level(story_id):
        if story_id in levels:
            return levels[story_id]
        levels[story_id] = None
        parents = []
        for dep in stories[story_id].meta.get("deps", ()):
            if status[dep] == "done":
                continue
            if dep not in candidates or level(dep) is None:
                return None
            parents.append(dep)
        depth = 1 + max((levels[parent] for parent in parents), default=0)
        levels[story_id] = depth if depth <= stack_depth else None
        return levels[story_id]

    return {story_id: level(story_id) for story_id in sorted(candidates)}


def _open_deps(stories, status, story_id):
    return [dep for dep in stories[story_id].meta.get("deps", ()) if status[dep] != "done"]


def _choose(order, stories, status, limit):
    proposed, held = [], []
    for sid in order:
        parents = _open_deps(stories, status, sid)
        missing = [parent for parent in parents if parent not in proposed]
        if len(parents) > 1:
            held.append({"id": sid, "why": TWO_PARENTS})
        elif missing:
            held.append({"id": sid, "why": f"it stacks on {missing[0]}, which can't go in this iteration"})
        elif len(proposed) >= limit:
            held.append({"id": sid, "why": f"an iteration holds at most {limit} stories"})
        else:
            proposed.append(sid)
    return proposed, held


def _blocked(stories, status, candidates, levels, stack_depth):
    """Candidates that can't go at all: (stories with a dropped dep, stories waiting on unfinished work)."""
    dropped, waiting = [], []
    for sid in sorted(sid for sid in candidates if levels[sid] is None):
        deps = _open_deps(stories, status, sid)
        gone = [dep for dep in deps if status[dep] == "dropped"]
        if gone:
            dropped.append({"id": sid, "dropped": gone})
            continue
        unfinished = [f"{dep} ({status[dep]})" for dep in deps if status[dep] not in CANDIDATE]
        waiting.append({"id": sid, "waits_on": unfinished or [f"a chain deeper than {stack_depth} levels"]})
    return dropped, waiting


def propose(stories, status, settings, candidates=None):
    """{proposed: [item], held: [{id, why}], dropped_deps: [{id, dropped}], waiting: [{id, waits_on}]}."""
    if candidates is None:
        candidates = {sid for sid in stories if status[sid] in CANDIDATE}
    levels = _levels(stories, status, settings["stack_depth"], candidates)
    order = sorted((sid for sid, level in levels.items() if level is not None), key=lambda sid: (levels[sid], sid))
    proposed, held = _choose(order, stories, status, settings["iteration_max"])
    dropped, waiting = _blocked(stories, status, candidates, levels, settings["stack_depth"])
    return {"proposed": [board.item(stories[sid], status, levels[sid]) for sid in proposed], "held": held,
            "dropped_deps": dropped, "waiting": waiting}


def iterations(accio):
    return sorted((int(match.group(1)), path) for path in (accio / ITERATIONS).glob("*.md")
                  if (match := ITERATION_FILE.match(path.name)))


def open_iteration(accio, status):
    """The newest iteration when it is planned but not built: no outcome yet, and every story still Ready."""
    found = iterations(accio)
    if not found:
        return None
    number, path = found[-1]
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise PlanError(f"cannot read {path}: {error}") from error
    listed = ITERATION_ROW.findall(text)
    if OUTCOME_PLACEHOLDER not in text or not all(status.get(sid) == "ready" for sid in listed):
        return None
    return number


def next_iteration(accio):
    return max((number for number, _ in iterations(accio)), default=0) + 1


def _checked(stories, status, settings, chosen, tracks):
    unknown = [sid for sid in chosen if sid not in stories]
    if unknown:
        raise PlanError(f"there is no story {', '.join(unknown)}")
    wrong = [f"{sid}={track}" for sid, track in tracks.items() if sid not in chosen or track not in story.TRACKS]
    if wrong:
        raise PlanError(f"a track override must name a chosen story and one of {', '.join(story.TRACKS)}: "
                        f"{', '.join(wrong)}")
    plan = propose(stories, status, settings, {sid for sid in chosen if status[sid] in CANDIDATE})
    reasons = {entry["id"]: entry["why"] for entry in plan["held"]}
    reasons.update({entry["id"]: f"its dependency {', '.join(entry['dropped'])} was dropped"
                    for entry in plan["dropped_deps"]})
    reasons.update({entry["id"]: f"it waits on {', '.join(entry['waits_on'])}, not chosen or not done"
                    for entry in plan["waiting"]})
    left_out = [f"{sid} ({reasons.get(sid, f'it is {status[sid]}, not in Backlog or Ready')})"
                for sid in chosen if sid not in {item["id"] for item in plan["proposed"]}]
    if left_out:
        raise PlanError(f"these can't go in this iteration: {'; '.join(left_out)}")
    return plan["proposed"]


def _iteration_text(number, items, tracks):
    rows = [f"| {item['id']} | {item['title'].replace('|', chr(92) + '|')} | {tracks.get(item['id'], item['track'])} "
            f"| {', '.join(item['parents']) or '—'} |" for item in items]
    return (f"# Iteration {number}\n\nPlanned with `/accio:prophecy`. Stories in build order:\n\n"
            "| Story | Title | Track | Stacked on |\n|---|---|---|---|\n" + "\n".join(rows) +
            f"\n\n## Outcome\n\n{OUTCOME_PLACEHOLDER}\n")


def _story_files(accio, also):
    """The `--also` paths, each an existing story file under .accio/stories/."""
    folder = board.stories_dir(accio).resolve()
    checked = []
    for given in also:
        path = pathlib.Path(given).resolve()
        if path.parent != folder or not board.STORY_FILE.match(path.name) or not path.is_file():
            raise PlanError(f"--also takes story files in {folder}, got {given}")
        checked.append(path)
    return checked


def go(accio, settings, chosen, tracks, also=()):
    """Make `chosen` exactly the next iteration and commit it; returns {iteration, path, stories, returned, files,
    commit, commit_error}."""
    if runlock.is_held(board.run_dir(accio)):
        raise PlanError("a build is running (run/brew.lock); plan the next iteration after it ends")
    edited = _story_files(accio, also)
    stories = board.load_stories(accio)
    status = board.statuses(stories, board.read_overrides(accio))
    items = _checked(stories, status, settings, list(dict.fromkeys(chosen)), tracks)
    ids = [item["id"] for item in items]
    returned = sorted(sid for sid in stories if status[sid] == "ready" and sid not in ids)
    changes = {**{sid: {"status": "ready", **({"track": tracks[sid]} if sid in tracks else {})} for sid in ids},
               **{sid: {"status": "backlog"} for sid in returned}}
    number = open_iteration(accio, status) or next_iteration(accio)
    iteration = accio / ITERATIONS / f"{number}.md"
    texts = {stories[sid].path: storyfiles.with_fields(stories[sid].path, change) for sid, change in changes.items()}
    texts[iteration] = _iteration_text(number, items, tracks)
    texts[accio / board.BOARD_NAME] = board.render(
        stories, {**status, **{sid: change["status"] for sid, change in changes.items()}})
    try:
        iteration.parent.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise PlanError(f"cannot create {iteration.parent} ({error}); nothing was changed") from error
    try:
        storyfiles.write_all(texts, "the iteration")
    except storyfiles.WriteError as error:
        raise PlanError(str(error)) from error
    files = list(dict.fromkeys([*map(str, texts), *map(str, edited)]))
    commit, why = storyfiles.commit(accio.parent, files, COMMIT_MESSAGE.format(number=number))
    return {"iteration": number, "path": str(iteration), "stories": ids, "returned": returned, "files": files,
            "commit": commit, "commit_error": why}


def describe(plan):
    """The plan as plain lines, for `accio-board plan` without --json."""
    lines = [f"{item['id']}  {item['track']:<8} level {item['level']}  {item['title']}" for item in plan["proposed"]]
    lines += [f"held: {entry['id']} ({entry['why']})" for entry in plan["held"]]
    lines += [f"dropped dep: {entry['id']} needs {', '.join(entry['dropped'])}" for entry in plan["dropped_deps"]]
    lines += [f"waiting: {entry['id']} waits on {', '.join(entry['waits_on'])}" for entry in plan["waiting"]]
    return "\n".join(lines) or "Nothing to plan: no story is in Backlog or Ready"
