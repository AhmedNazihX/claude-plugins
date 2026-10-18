# 001 — howler reads gh JSON itself; curfew checks every argument

Date: 2026-10-19 · Status: decided by the user (Option A, of three options)

## What was decided
How howler, accio's CI watcher, gets each GitHub Actions result after owl's push: who reads gh's data (howler, gh's
own queries, or an accio script), and how curfew keeps CI text out of commands. It was the user's to decide because
it sets how much of the safety rule a test can prove, how much code there is, and what can break.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A: howler reads gh's JSON; curfew checks every argument | howler runs `gh run list/view/watch` and reads the JSON and the last 60 lines of each failed log; curfew allows only known flags, number ids, 40-character shas and a checked branch name | curfew tests prove "CI text never reaches a command"; little new code | Haiku reads the JSON and decides "failed the same way", which no test covers |
| B: gh cuts the data down with fixed queries | as A, but curfew allows `--jq` with a few fixed queries kept in `policy.py`; howler compares two short lines per job | less for Haiku to misread; slightly fewer tokens | two more unproven facts (gh's jobs fields, quoted queries passing curfew); a gh upgrade can break the queries silently; the benefit is small with one workflow of 3 jobs |
| accio script (`accio-howl`) | a stdlib script waits, parses and compares in tested Python; howler only words the report | the easiest design to test | needs an accio script added to howler's allowed commands (R5) |

Costs:
- A, money: none (gh uses the user's GitHub login) (wandmaker)
- A, agent tokens: some Haiku tokens per push, likely small; no measured figure (wandmaker's judgement)
- A, time: the story plus a spike, about a day (wandmaker's judgement)
- B, money: none (wandmaker)
- B, agent tokens: slightly fewer than A (wandmaker's judgement)
- B, time: A plus about half a day (wandmaker's judgement)
- B, risk: higher than A, two more unproven facts (wandmaker)
- accio script, money, tokens and time: not discussed

## Decision
Option A. "Go with A"

## Why
It meets all five requirements with the least new code, and curfew enforces the rule that CI text never reaches a
command, so a test proves it. B's gain is small for one workflow of 3 jobs and it adds two unproven facts
(wandmaker's recommendation, which the user took).

## Consequences
What breaks first is the 60-line log tail: with many failing tests, or both matrix jobs failing, the first error can
fall outside it. A spike must first show that owl, a skill, can start a background agent whose report reaches the
chat on its own; if it can't, no option meets the requirement as written.
