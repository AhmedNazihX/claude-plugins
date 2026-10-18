# 002 — howler may use tail and no other shell program

Date: 2026-10-19 · Status: decided by the user (only `tail`, of three options)

## What was decided
Which ordinary shell programs howler may run besides its 7 git and gh commands. The requirement said "only reads",
which could mean the Read tool alone or also shell programs that only read. It was the user's to decide because it
sets how tight curfew's list for howler is. It matters because a failed job's log can be thousands of lines, and
howler keeps only its end with `gh run view … --log-failed | tail -60`, which needs `tail`.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| 1: add only `tail` | `gh run view 1 --log-failed --job 2 \| tail -60` passes; `cat`, `grep`, `ls` are denied | the narrowest list that keeps logs short; one more test row | one more program on the list |
| 2: every read-only shell program | also `cat`, `grep`, `find`, `ls`, `head` and the rest of accio's read-only set (`read_only=True`) | no new code; howler could `grep` a log | lets howler read any repo file through Bash, which it doesn't need (it has Read) |
| 3: no shell programs | the same command with `\| tail -60` is denied; howler gets the whole log | exactly the 7 commands | a big log fills Haiku's context, and the error can get lost |

Costs:
- 1, agent tokens: low (60 lines per log)
- 2, agent tokens: low
- 3, agent tokens: higher, maybe much higher on a big failure
- money and time for each option: not discussed

## Decision
Only `tail`. The user answered "1".

## Why
`tail` is the only extra program the design uses, and adding nothing else keeps curfew's list for howler as tight
as the requirement asks.

## Consequences
curfew's howler list is the 7 commands plus `tail` (not `read_only=True`).
