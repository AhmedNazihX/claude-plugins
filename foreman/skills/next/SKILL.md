---
name: next
description: The single entry point of the story workflow. Looks at which planning files exist in the repo and runs the right step — kickoff (no design yet), work-breakdown (no backlog), the backlog review (backlog never reviewed), setup (no workflow config), or status (everything in place). Use when the user says "what's next", "continue", "pick up where we left off", or starts a session on a project that uses this plugin.
---

# Next step

**One planning branch.** Kickoff, work-breakdown, the backlog review, setup and guardrails all commit on one branch,
`planning/<yyyy-mm-dd>`, created from the base branch by the first of them. Workers branch from the base branch, so
nothing can start until that branch is merged: row 7 does it, with the user's go-ahead.

Check, from the repo root, in this order, and run the **first** step whose condition holds. Say in one line which
step you picked and why, then load that skill and follow it.

**Keep going.** When a step finishes, check this table again and run the next step yourself: don't end with
"shall I run <step>?". Stop only for what is the user's to decide: approving the design (kickoff), a question a
step asks, the settings diff (setup), merging the planning branch (row 7), and anything that costs money. Before
each step, say in one line which step comes next and why.

| # | Condition | Step |
| --- | --- | --- |
| 0 | The project has its own `.claude/skills/status/SKILL.md` and no `.claude/foreman.json` | it runs its own copy of the workflow: say so, and use its `/status` (and its `/story-start`, `/story-finish`). Don't run `setup` there unless the user asks to move the project onto the plugin |
| 1 | No `docs/DESIGN.md` (and no other design document the user names) | `kickoff` |
| 2 | `docs/DESIGN.md` has a Status line (for example `- **Status:** draft`) that doesn't say `approved` | `kickoff` (finish and approve the design) |
| 3 | No `docs/BACKLOG.md` | `work-breakdown` with `docs/DESIGN.md` |
| 4 | `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py check` fails | fix the backlog (show the errors) |
| 5 | The backlog has no `Reviewed:` line under its title | launch the `foreman:backlog-reviewer` agent, then add `Reviewed: <date>` once its findings are handled |
| 6 | No `.claude/foreman.json` | `setup` |
| 7 | A `planning/*` branch has commits the base branch lacks | show `git log --oneline <base>..planning/<date>`, ask the user to merge it (`git merge --no-ff`), then run the checks |
| 8 | Otherwise | `status` |

Projects that started before this plugin may name their design differently (for example an "Init Document"):
if `CLAUDE.md` names the design's source of truth, use that file for rows 1–3.

Row 2's Status line is one line: get it with `grep -m1 -i 'status:' <design file>` (the file resolved above —
`docs/DESIGN.md`, or whatever `CLAUDE.md` names instead), not by reading the whole file (a design document can be
long, and a configured `docs` guard blocks a whole over-limit `.md` file anyway).

Read-only until the chosen skill runs.
