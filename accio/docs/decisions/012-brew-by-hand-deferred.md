# 012 — No fallback build in v1: `brew-by-hand` deferred to v1.1

Date: 2026-10-18 · Status: decided by the user (option B of three)

## What was decided
Whether v1 ships `brew-by-hand` (S-027), a build that runs brew's steps as plain subagents for users who have
Claude Code's workflows switched off. It was the user's to decide because it sets v1's scope. Until then,
`prophecy`, `map` and the `session-start` hook pointed such users to `/accio:brew-by-hand`, which didn't exist.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A. Build it now | with workflows off, the user types `/accio:brew-by-hand` and the main chat runs the build steps, one story at a time | users who can't turn workflows on can still build | the largest skill in the plugin; one story at a time; the build's progress lands in the main chat; hard to eval |
| B. Defer it; fix the pointers | with workflows off, accio says its build needs them and how to turn them on | small and honest; no command that doesn't exist; workflows are on by default and spike S-001 found they work | users whose organisation blocks workflows can't build with accio in v1 |
| C. Leave it | the pointers stay | no work | users are sent to a command that doesn't exist |

Costs:
- A, time: about 2 to 3 hours of agent work (estimate)
- A, money: about $2 to $5 of eval runs (estimate from the other skills' evals)
- B, time: about 20 minutes (estimate)
- B, money: under $0.20 of eval runs (estimate)

## Decision
B: "GO with B".

## Why
Workflows are on by default, and spike S-001 confirmed accio's build runs in them, so a fallback reaches few users
at the cost of the plugin's largest skill. Removing the broken pointer now keeps v1 honest, and the fallback can come
in v1.1 if users need it.

## Consequences
With `CLAUDE_CODE_DISABLE_WORKFLOWS` set or the `Workflow` tool missing, `session-start`, `prophecy` and `map` say
that accio's build needs workflows and how to turn them on (the `disableWorkflows` setting off, the variable unset).
S-027 stays in the backlog, deferred to v1.1.
