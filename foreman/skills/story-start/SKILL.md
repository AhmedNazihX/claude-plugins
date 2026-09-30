---
name: story-start
description: Starts one or more backlog stories — checks their deps and the parallel-work rules (Solo, shared Resources, lane isolation), then launches one story-worker agent per story in its own git worktree on a story/<ID>-<slug> branch. Use when the user says to start, launch, kick off or work on a story or a wave ("/story-start C1", "start F2 F3 F4").
argument-hint: "<ID> [ID ...]"
---

# Start stories: $ARGUMENTS

You are the **orchestrator**, the main session. You don't implement stories. You check that each one can start,
then launch one `foreman:story-worker` agent per story. Settings: `.claude/foreman.json` (`base_branch`, `lanes`, `stories`).

## 1. Check the whole set before launching anything

From the main checkout:

```bash
git rev-parse --abbrev-ref HEAD      # must be the base branch
git status --porcelain               # must be empty: worktrees branch from HEAD, not from uncommitted work
git rev-parse HEAD                   # BASE_SHA
git branch --list 'story/*'          # stories already in flight
```

For each requested ID:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py info <ID>   # slug, lane, type, solo, resources, done, sub_stories
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py deps <ID>   # exit 1 = unmet deps
```

Refuse a story, and say why, if any of these hold:
- It's done (`"done": true`), or a `story/<ID>-*` branch already exists.
- It's a grouped entry's own ID (non-empty `sub_stories`). Start its sub-stories instead.
- It has unmet deps. List them.
- It has a `dep_notes` condition. Ask the user to confirm the condition holds before you start it.
- It's `solo` and anything else is in the set or in flight. Or something `solo` is already in flight.
- It shares a `resources` entry, or a `resource_hints` entry the story's text confirms, with another story in the
  set or in flight.
- Its `dod_input_gaps` isn't empty: it could start but can't pass its DoD. Name the missing input, and start it only
  if the user wants it built early.

Launch whatever passes, and report what was refused.

## 2. Human stories don't get an agent

For `Type: human` stories, show the story, list exactly what the user must do or provide, and offer to create the
branch for them. Launch `mixed` stories normally: the worker drafts, then reports what the user must review.

## 3. Launch the workers in a single message, so they run in parallel

For each story, work out `DENY` and `ALLOW`: take `stories[<ID>]` from the config if it exists, otherwise
`lanes[<lane>]`, otherwise leave both empty. Then call the Agent tool with `subagent_type: "foreman:story-worker"` (always the namespaced name: a project
or user agent called `story-worker` would otherwise be picked), which
runs in its own worktree. Use this prompt:

```
STORY: <branch_id>
SLUG: <slug>
BASE_SHA: <sha>
MAIN: <absolute path of the main checkout>
DENY: <comma-separated, or empty>
ALLOW: <comma-separated, or empty>
COST_CAP_USD: <cost_cap_usd from the config, or 0 for "ask before any paid call">
PARALLEL: <the other stories in this set, and whether any of them may change a shared resource>

Story entry:
<paste the full output of `backlog.py show <ID>`>

For a sub-story of a grouped entry, do only the part for <branch_id>.
Follow your agent instructions: set up the worktree, load context, implement, check, commit, report.
```

Never paste secret files, or the contents of denied folders, into a prompt.

## 4. Tell the user

Give one line per launched story, then any refused stories and why. Relay each worker's final status
(DONE / BLOCKED / NEEDS USER) as it arrives, and follow `story-finish` for a DONE (its reviews start without
asking). Don't merge anything here.

**When a worker is blocked by a permission check** (for example the sparse checkout in a worktree with a `DENY`
list), never run the command yourself to get past the check: give the user the exact command as **one** line
starting with `!`, with several commands chained by `&&` (lines pasted together after one `!` run as shell negation
and fail silently). After the user runs it, check its effect (for example `git sparse-checkout list` and that the
denied folders are gone), then tell the worker to continue.
