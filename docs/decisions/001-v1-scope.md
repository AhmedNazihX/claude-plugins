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
| B: full lifecycle | ~35–45 stories | late | heavy ceremony before any real use |
| C: build engine only | ~8–10 stories | early but partial | doesn't test the iteration and grilling ideas |

Story counts are rough estimates.

## Why
A big design up front runs ahead of feedback. A puts a usable loop in front of the user first, and the rest
follows as later iterations.

## Amendment (2026-10-17, design grilling, decision 009)
- **Recount:** the design had grown to about 31 v1 stories, close to option B's size.
- **Moved to v1.1:** `telescope`, `reparo`, `lumos`, and the plain output style.
- **Kept in v1:** `doc-size` with `librarian`. Reading long docs whole floods the context (`analysis.md`
  §3.1), so cutting them would be a step back.
- **Conditional:** `brew-by-hand` is built only if spike S-001 needs it.
- **v1 is now about 27 stories** (the backlog count). It keeps the whole loop: `wand` (with `wandmaker`), `sort`,
  `prophecy`, `brew`, `owl`, `map`, `vow`, plus the safety layer and `doc-size`.
