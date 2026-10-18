"""The iteration plan behind `prophecy` (DESIGN § 3.3; decision 009): what to propose, and what "go" writes.

- A candidate is a story in Backlog or Ready. It is eligible when each dep is done, or is itself eligible and the
  chain stays within `stack_depth` levels. A dep in any other state (in review, blocked, dropped) holds it back.
- The proposal takes eligible stories in dependency order (level, then id), up to `iteration_max`. A child comes
  only with its parent, and only with one parent from the same iteration (brew runs the second in a later run).
- Stories with a dropped dep are listed apart: the user drops them too, or removes the dep.
- "go" re-checks the chosen set the same way, then sets each story's `status: ready` (and any track override) in
  its story file, writes `iterations/<N>.md` and `board.md`, and returns the files to commit. It refuses during a
  build: then run/status.json, not the story file, holds the status.
"""
import os
import re
import tempfile

from accio_lib import board, runlock, story

CANDIDATE = ("backlog", "ready")
ITERATIONS = "iterations"
ITERATION_FILE = re.compile(r"^(\d+)\.md$")
TWO_PARENTS = "it stacks on 2 stories of this iteration; it can go in the next one"


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


def _parents_in(stories, status, story_id):
    return [dep for dep in stories[story_id].meta.get("deps", ()) if status[dep] != "done"]


def propose(stories, status, settings, candidates=None):
    """{proposed: [item], held: [{id, why}], dropped_deps: [{id, dropped}]}, items as in `accio-board ready`."""
    if candidates is None:
        candidates = {sid for sid in stories if status[sid] in CANDIDATE}
    levels = _levels(stories, status, settings["stack_depth"], candidates)
    order = sorted((sid for sid, level in levels.items() if level is not None), key=lambda sid: (levels[sid], sid))
    proposed, held = [], []
    for sid in order:
        parents = _parents_in(stories, status, sid)
        if len(parents) > 1:
            held.append({"id": sid, "why": TWO_PARENTS})
        elif len(proposed) >= settings["iteration_max"] or not set(parents) <= set(proposed):
            held.append({"id": sid, "why": f"an iteration holds at most {settings['iteration_max']} stories, "
                                          "with each child after its parent"})
        else:
            proposed.append(sid)
    dropped = [{"id": sid, "dropped": [dep for dep in stories[sid].meta.get("deps", ()) if status[dep] == "dropped"]}
               for sid in sorted(candidates)]
    return {"proposed": [board.item(stories[sid], status, levels[sid]) for sid in proposed], "held": held,
            "dropped_deps": [entry for entry in dropped if entry["dropped"]]}


def next_iteration(accio):
    numbers = [int(match.group(1)) for path in (accio / ITERATIONS).glob("*.md")
               if (match := ITERATION_FILE.match(path.name))]
    return max(numbers, default=0) + 1


def _checked(stories, status, settings, chosen, tracks):
    unknown = [sid for sid in chosen if sid not in stories]
    if unknown:
        raise PlanError(f"there is no story {', '.join(unknown)}")
    wrong = [f"{sid}={track}" for sid, track in tracks.items() if sid not in chosen or track not in story.TRACKS]
    if wrong:
        raise PlanError(f"a track override must name a chosen story and one of {', '.join(story.TRACKS)}: "
                        f"{', '.join(wrong)}")
    candidates = {sid for sid in chosen if status[sid] in CANDIDATE}
    plan = propose(stories, status, settings, candidates)
    left_out = [sid for sid in chosen if sid not in {item["id"] for item in plan["proposed"]}]
    if left_out:
        raise PlanError(f"these can't go in this iteration: {', '.join(left_out)} (not in Backlog or Ready, a dep "
                        "is not done and not chosen, a stack deeper than allowed, 2 chosen parents, or over the cap)")
    return plan["proposed"]


def _with_fields(path, changes):
    """The story file's text with some frontmatter values replaced; every other line is kept as it was."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    where = story.key_lines(path)
    for key, value in changes.items():
        lines[where[key] - 1] = f"{key}: {value}\n"
    return "".join(lines)


def _replace(path, text):
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        stream.write(text)
    os.replace(temporary, path)


def _iteration_text(number, items, tracks):
    rows = [f"| {item['id']} | {item['title']} | {tracks.get(item['id'], item['track'])} | "
            f"{', '.join(item['parents']) or '—'} |" for item in items]
    return (f"# Iteration {number}\n\nPlanned with `/accio:prophecy`. Stories in build order:\n\n"
            "| Story | Title | Track | Stacked on |\n|---|---|---|---|\n" + "\n".join(rows) +
            "\n\n## Outcome\n\nWritten by `/accio:owl`.\n")


def go(accio, settings, chosen, tracks):
    """Make `chosen` the next iteration; returns {iteration, path, stories, files}."""
    if runlock.lock_path(board.run_dir(accio)).exists():
        raise PlanError("a build is running (run/brew.lock); plan the next iteration after it ends")
    stories = board.load_stories(accio)
    status = board.statuses(stories, board.read_overrides(accio))
    items = _checked(stories, status, settings, list(dict.fromkeys(chosen)), tracks)
    texts = {stories[item["id"]].path: _with_fields(stories[item["id"]].path,
                                                   {"status": "ready", **({"track": tracks[item["id"]]}
                                                                          if item["id"] in tracks else {})})
             for item in items}
    number = next_iteration(accio)
    iteration = accio / ITERATIONS / f"{number}.md"
    try:
        iteration.parent.mkdir(parents=True, exist_ok=True)
        for path, text in texts.items():
            _replace(path, text)
        _replace(iteration, _iteration_text(number, items, tracks))
        stories = board.load_stories(accio)
        _replace(accio / board.BOARD_NAME, board.render(stories, board.statuses(stories, board.read_overrides(accio))))
    except OSError as error:
        raise PlanError(f"cannot write the iteration: {error}") from error
    files = [str(path) for path in texts] + [str(iteration), str(accio / board.BOARD_NAME)]
    return {"iteration": number, "path": str(iteration), "stories": [item["id"] for item in items], "files": files}


def describe(plan):
    """The plan as plain lines, for `accio-board plan` without --json."""
    lines = [f"{item['id']}  {item['track']:<8} level {item['level']}  {item['title']}" for item in plan["proposed"]]
    lines += [f"held: {entry['id']} ({entry['why']})" for entry in plan["held"]]
    lines += [f"dropped dep: {entry['id']} needs {', '.join(entry['dropped'])}" for entry in plan["dropped_deps"]]
    return "\n".join(lines) or "Nothing to plan: no story is in Backlog or Ready"

