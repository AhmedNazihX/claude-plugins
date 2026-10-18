# 013 — accio lives in the marketplace repo, like git-guardrails

Date: 2026-10-18 · Status: decided by the user (option A of three)

## What was decided
Where accio's source lives, and how a change reaches the copy Claude Code installs. It was the user's to decide
because it sets how they work on accio from now on, starting with v2. Until then the source was its own repo
(`~/Workspace/Projects/Plugin`), and `scripts/publish.py` copied a clean subset into the release marketplace.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A. The git-guardrails way | source in `~/Workspace/claude-plugins/accio` with its history; the release repo pulls it; `publish.py` retired | one way to work for both plugins; one place to edit; no publish step | the installed copy carries tests and docs (about 1 MB; nothing extra loads into Claude); the root CI gains accio's jobs |
| B. Move, keep `publish.py` | source in the marketplace, a clean copy in the release repo | the installed copy stays minimal | two `accio` folders in two repos that sync from each other: the next pull conflicts |
| C. Stay separate | source stays in its own repo | no migration | two ways of working for two plugins |

Costs:
- A or B, time: about 30 to 45 minutes (estimate)

## Decision
A: "A".

## Why
It matches how git-guardrails is already developed and released, removes a publish step, and keeps the whole
history.

## Consequences
accio's history was merged in as `accio/` (the import commit's second parent is the old repo's last commit). Its CI
jobs (tests on Linux and macOS, evals by hand) are in the marketplace's `.github/workflows/test.yml`. `publish.py`
and its test are gone; S-002/3 (publishing by script) no longer applies.
