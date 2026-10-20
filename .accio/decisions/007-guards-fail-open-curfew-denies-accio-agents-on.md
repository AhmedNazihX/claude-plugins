# 007 — Guards fail open; curfew denies accio agents on its own start-up crash

Date: 2026-10-20 · Status: decided by the user (A, of 3 options)

## What was decided
How accio's guards (curfew checks every tool call, protego shell commands, fidelius file writes) behave when they
can't run. S-028 gave them `"onFailure": "block"`. A side agent pointed out that accio is installed for the whole
account, so these guards run in every session and project: one start-up crash (for example a broken update that
makes `from accio_lib import …` fail) would block every tool call everywhere, and on `PermissionRequest` turn every
permission prompt into a no. It was the user's to decide because it trades build safety against the risk of
freezing Claude in every project.

## Options
| Option | What happens when a guard can't run | Pros | Cons |
|---|---|---|---|
| A. Fail open everywhere; curfew catches its own start-up crash | `onFailure` removed; curfew's start-up imports move inside a `try`; on failure it reads the caller with plain JSON and denies an accio agent, lets anyone else through | a broken update can't freeze the main chat or other projects; accio agents still get a deny on a crash | a missing Python or a guard past its time limit lets the call through, as before S-028 |
| B. Keep S-028 | every guard blocks on any failure, everywhere | strictest for builds | one bad update freezes Claude in every project until the plugin is disabled by hand |
| C. Undo S-028 only | as before S-028 | no work | a curfew start-up crash can leave an agent on a permission prompt and hang the build |

Costs:
- A, coding agents' tokens: one small story (curfew's start-up, `hooks.json`, a test), security track
- B, coding agents' tokens: none
- C, coding agents' tokens: none
- A, the user's time: one more build and review, then the restart on 0.6.1

## Decision
A. "yes", to the recommendation.

## Why
It keeps what S-028 was for (an accio agent never waits on a permission prompt) without risking the user's main
chat and other projects.

## Consequences
0.6.0 is installed but must not be restarted into; 0.6.1 replaces it. A broken guard is tested by hand before the
restart. Recovery if a guard ever blocks everything: `claude plugin disable accio@nazihx` in a terminal, or
`/plugin`.
