---
name: handover
description: Makes the session safe to clear, compact or end — checks that nothing is in flight (worktrees, story branches, running agents, uncommitted or unpushed work), moves every open follow-up, user decision and reviewer "watch" item out of the conversation onto the backlog stories it affects (or into a decision record, the project's memory, or a handover file for work outside the backlog), and ends with the command the next session should start with. Use before /clear or /compact, before ending a long session, when the user asks for a handover note, or asks "can I clear now?".
---

# Handover

The conversation is about to lose its context. Anything that lives only in it is lost. Move it where the next
session reads it, then say what's left.

## 1. What's in flight

```bash
git status --porcelain                          # uncommitted work in the main checkout
git worktree list                               # story worktrees still open
git branch --list 'story/*' 'planning/*'        # branches not merged yet
git log --oneline origin/<base>..<base>         # unpushed commits
```

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workers.py list   # the story workers on record, their state and agent id
```

Also list agents you started that haven't reported (reviewers aren't in the registry). For each item in flight, say
what it is and what it waits on. Don't clear with an agent **running**: its report would arrive in a session that
doesn't know the story. A worker that has reported and waits on a review round, a recording or the user can be left
across a clear, but its agent id won't reach it from the next session: make sure it's in the registry with its
current state (`workers.py set <ID> <state> --note "<what it waits on>"`, `record` any that are missing) and has
committed everything, so the next session can continue the story with `/foreman:story-start --continue <ID>`.

## 2. Move what only the conversation knows

Go through the conversation since the last handover and collect:
- worker follow-ups, reviewer "watch" items and deferred minor findings;
- the user's decisions and answers (with the date), including ones not yet in a decision record;
- gaps found in the backlog (a missing dep, a story that can't finish, a new story);
- open questions waiting on the user.

Put each where the next reader finds it:

| What | Where | How |
| --- | --- | --- |
| Something a backlog story must know | that story | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py note <ID> --from <story> "<text>"` when it comes from a merged story; otherwise `note <ID> "**<Source> (<date>):** <text>"`, e.g. `**User decision (2026-09-30):** …`. One line per call |
| A missing dependency | the story's Deps | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py set-deps <ID> "<deps>"` (on a group's ID, not a sub-story's) |
| New work | a new story | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py add --after <ID>` (the entry on stdin) |
| A choice that changes the plan | a decision record | the `decision` skill |
| A rule | its enforcement | the `guardrails` skill |
| Work outside the backlog (tooling, a side project) | a `HANDOVER.md` in that repo | state, next step, open items, gotchas |
| How the user likes to work | the project's memory | one fact per memory file |

Then run `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py check` and commit the notes (`docs(backlog): hand over <topic>`). Don't push without asking.

## 3. Say what's left

End with a short list:
- **Safe to clear:** yes, or what must finish first.
- **Written:** each note, record and file, one line each.
- **Not pushed:** the commits, if any (offer to push).
- **Next:** the exact first command for the next session (usually `/foreman:next` or
  `/foreman:status`) and what it should recommend.
