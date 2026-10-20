# 006 — Step skills know /accio drives from a driven argument

Date: 2026-10-20 · Status: decided by the user (A, of 2 options)

## What was decided
How a step skill (owl, prophecy, sort, wand) knows that the `/accio` conductor called it. Today each one guesses
"when the accio conductor skill was loaded earlier in this chat and has not finished". In that mode owl accepts every
finished story without asking, so a hand-typed `/accio:owl` after `/accio` can skip the user's review. It was the
user's to decide because it sets when accio asks them.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A. A `driven` argument | `/accio` loads each step skill with the argument `driven`; Claude Code appends it as `ARGUMENTS: driven` (seen in this session when wand was loaded with arguments) | certain; a hand-typed step never has it, so it keeps every question | small edits to 5 skills |
| B. Keep the guess | no change | no work | a hand-typed `/accio:owl` after `/accio` can accept stories without asking |

Costs:
- A, coding agents' tokens: a small change; not measured
- B, coding agents' tokens: none
- A and B, the user's time: none extra

## Decision
A. "A and A."

## Why
A fact replaces a guess, and the safe path (every question asked) becomes the default.

## Consequences
Each step skill's driving clause becomes one line keyed on `ARGUMENTS`, replacing four differently worded copies.
