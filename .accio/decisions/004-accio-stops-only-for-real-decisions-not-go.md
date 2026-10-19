# 004 — /accio stops only for real decisions, not go or clean accepts

Date: 2026-10-19 · Status: decided by the user (fewer stops, of two options)

## What was decided
Where the `/accio` conductor (decision 003) stops for the user. The first version of its design kept two stops from
DESIGN § 7.3 (decision 005 of accio's own design): "go" before each build, and accepting each finished story at owl.
It was the user's to decide because it sets how often accio waits on them. The user's words: "try not to get blocked
on me going forward", after "i feel the workflow right now is blocking on me".

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| Keep go and accept | `/accio` waits for "go" before each build and for accept or reject on each finished story | the user sees every batch before it builds and every story before it merges | the loop waits on the user at least twice per iteration even when nothing needs a decision |
| Fewer stops | `/accio` takes the plan's low-stakes defaults and builds; it accepts and merges locally every story that passed its checks and reviews; it reports each of these | the loop runs until a real decision; matches how the user asked to work | the user sees a batch and a merged story only in the report, after the fact |

Costs:
- Keep go and accept, interruptions: about 2 per iteration, plus k planning questions (DESIGN § 7.3)
- Fewer stops, interruptions: only real questions, failed stories, and the push
- Fewer stops, risk: small; nothing leaves the machine without the push confirm, and a merged story can be reverted
  locally before the push

## Decision
Fewer stops. The user forwarded the note that the design still stopped at "go" and accept, after saying "try not to
get blocked on me going forward".

## Why
The hard stops that protect the user stay: push and release, paid calls, safety overrides, denied commands, failed
stories and real design or story questions. "go" and accepting a story that passed every check and review add waiting
without adding a decision.

## Consequences
- Typing `/accio` is the opt-in for every build it starts; spike S1 tests whether a skill may start the build.
- DESIGN § 7.3's touchpoint count changes for `/accio` runs; the single commands keep today's stops.
