# 009 — Check fixes and review fixes share the two fix rounds

Date: 2026-10-20 · Status: decided by the user (accepted the recommendation)

## What was decided
Group B sends a failed check (a failing test command, a DoD line with no tagged test, a weak test, a file outside
the story) into a fix round instead of asking the user. A story gets at most 2 fix rounds today, used only by review
findings. The question was whether check fixes draw from the same 2 rounds or get their own. It was the user's to
decide because it sets how much one story can spend before it stops and asks.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| Shared 2 rounds | a failed test uses round 1, a review finding round 2; a later boggart break stops and asks, with its repro | keeps today's cap; a story that keeps failing stops before it burns tokens | a story with a failed test and a review finding has no round left for a late break |
| Separate 2 + 2 | checks get their own 2 rounds, reviews keep theirs | more chances to finish without asking | a story stuck in a loop can spend up to twice as much |

Costs:
- Shared, tokens: at most 2 builder runs per story, as today
- Separate, tokens: up to 4 builder runs per story
- Shared, interruptions: one rare new stop, a break found after both rounds; the new findings log counts it
- Separate, interruptions: fewer of those rare stops

## Decision
Shared 2 rounds.

## Why
Today a failed check costs a stop and a whole rebuild, so even a shared round is a large saving; if the log shows
stories often run out of rounds, the cap is raised from data, not a guess.

## Consequences
`main_changed` (the main checkout changed during the build) and `remote_moved` (origin moved) still block, because
nothing in the story's worktree can fix them; their cause is logged.
