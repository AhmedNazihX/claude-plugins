# 005 — accio starts a re-run’s rebase itself; house-elf only continues it

Date: 2026-10-20 · Status: decided by the user (A, of 2 options)

## What was decided
How a story that is built again catches up with newer code on its base. Today the brief tells house-elf (the
builder) to run `git rebase --onto …`, but curfew (the guard that answers every tool call of accio's agents) only
allows `git rebase --continue`, `--abort` or `--skip`. So the step in DESIGN § 12.3 where house-elf resolves a
rebase conflict can't happen. It was the user's to decide because one option changes a security guard.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A. accio starts the rebase itself | portkey's `accio-brief` runs the rebase. On a conflict it leaves the rebase in progress; house-elf fixes the files and runs `git rebase --continue`, which curfew already allows | no change to the guard; simpler | a worktree can be left mid-rebase if house-elf fails; the next prepare step already notices a rebase in progress |
| B. curfew allows the exact command | curfew lets through the one rebase command the brief named | the brief stays as it is | opens a gap in a security guard; the brief and the guard must share state |

Costs:
- A, coding agents' tokens: a small change; not measured
- B, coding agents' tokens: a small change; not measured
- A and B, the user's time: none extra

## Decision
A. "A and A."

## Why
It fixes the contradiction without widening what curfew lets an agent do.

## Consequences
`accio-brief` also commits changes an earlier build left uncommitted as a checkpoint before it rebases, and any
other rebase failure goes to Blocked with one plain question. DESIGN § 12.3 is updated to match.
