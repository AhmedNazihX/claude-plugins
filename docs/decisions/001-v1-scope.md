# 001 — Version 1 scope: the core loop

Date: 2026-10-17 · Status: decided by the user

## Decision
Version 1 covers the core loop:
- a light design step (a one-page architecture note plus decision records)
- iteration planning with the user
- building stories: build, verify, review and merge, with the safety layer

Deferred to later versions: a deep stack/architecture workshop, and retro flow metrics and cost dashboards.

## Options compared
| Option | Rough size | Feedback | Main risk |
|---|---|---|---|
| A: core loop (chosen) | ~15–20 stories | early | planning and retro are basic at first |
| B: full lifecycle | ~35–45 stories (foreman reached 45) | late | repeats foreman's ceremony before any real use |
| C: build engine only | ~8–10 stories | early but partial | doesn't test the iteration and grilling ideas |

Story counts are estimates, based on foreman's 45-story backlog (`~/Workspace/claude-plugins/docs/BACKLOG.md`).

## Why
Foreman's big design ran ahead of feedback. A puts a usable loop in front of the user first, and the rest
follows as later iterations.

## Amendment (2026-10-17, design grilling, decision 009)
- **Recount:** the design had grown to about 31 v1 stories, close to option B's size.
- **Moved to v1.1:** `telescope`, `reparo`, `lumos`, `doc-size` with `librarian`, and the plain output style.
- **Conditional:** `brew-by-hand` is built only if spike S-001 needs it.
- **v1 is now about 24–25 stories.** It keeps the whole loop: `wand` (with `wandmaker`), `sort`, `prophecy`,
  `brew`, `owl`, `map`, `vow`, plus the safety layer.
