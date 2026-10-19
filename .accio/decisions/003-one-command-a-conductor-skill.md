# 003 — One command: a conductor skill

Date: 2026-10-19 · Status: decided by the user (accepted the recommendation)

## What was decided
How accio gives the user one command (`/accio`) that carries the work through design, stories, plan, build and
review on its own, instead of each step ending with "type /accio:X". It was the user's to decide because it sets
where accio stops for them and how much of the flow is hidden. The user's words: "i feel the workflow right now is
blocking on me ... I don't have to keep calling everything. we should try to make it a single entry for the user and
things just work."

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A, conductor skill | a skill named `accio` runs `accio-board next --json`, runs that step's skill, and repeats while the step needs no decision | smallest change; Python decides "continue or stop"; the single commands keep working | the loop is prompt-driven, so a model may stop early; one chat holds every step and can compact |
| B, Stop-hook loop | `/accio` starts a chain; a Python Stop hook pushes Claude on to the next step after each turn | deterministic, tested Python; survives compaction | hidden control flow; a hook bug can loop in every accio session; needs an extra spike |
| C, terminal driver | a shell `accio` script starts one Claude session per step and runs the build headless | no spikes for the build and the wake; fresh context per step | the user must `/exit` each session, which misses the outcome; the entry is a shell command, not `/accio` |

Costs:
- A, time: about 4 to 5 stories, 2 to 3 hours of agent work (wandmaker's estimate)
- A, money: about the same main-chat tokens as typing each command today (wandmaker's estimate)
- A, risk: medium; the build and wake steps depend on spikes
- B, time: about 6 to 8 stories, 4 to 5 hours (wandmaker's estimate)
- B, money: same as A (wandmaker's estimate)
- B, risk: medium-high until its spikes pass
- C, time: about 6 to 7 stories, about 4 hours (wandmaker's estimate)
- C, money: a few thousand tokens per step for each new session (wandmaker's estimate)
- C, risk: high on the user experience and on whether a script typing `/accio:brew` keeps the opt-in's intent

## Decision
Option A, the conductor skill. The user approved the draft design with "Ok".

## Why
It meets the requirements with the least new machinery. Python still decides when to go on, and each failed spike
falls back to the user typing one command, never to a skipped safety check.

## Consequences
- The "what's next" rule moves into one place (`accio-board next`), used by the session-start hook, `map` and `/accio`.
- Two spikes come first. S1: can a skill start the build after the user's "go"? If not, the go message says to type
  `/accio:brew`. The wake (S2, S3 or S5): does the chat continue by itself when the build ends? If not, the user types
  `/accio` after the build.
- wand keeps its one-question interview (decision 009); the user chose that over a draft to edit.
- Revisit with option B if A's loop stops early in real use.
