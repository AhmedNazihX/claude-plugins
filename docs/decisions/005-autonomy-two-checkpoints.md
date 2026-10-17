# 005 — Autonomy: two checkpoints per iteration

Date: 2026-10-17 · Status: decided by the user

## Decision
**The user takes part in each iteration at two points:**
1. **Plan:** the user approves the iteration with one "go".
2. **Review:** the user accepts or rejects the ready stories, answers the collected questions and confirms the push,
   all in one batch answer.

**Automatic, never asks:**
- builds
- checks
- reviews
- fix rounds
- judge rulings that need no human
- merging accepted stories into local main, in dependency order
- re-checks at merge time

**Always asks** (collected and asked at the review checkpoint, never mid-build):
- pushing
- paid API calls on the user's key (default cap $0)
- a story marked needs-user
- an override of a safety block

## Options compared
Example iteration: 4 stories, 1 of them blocked.

| Option | User prompts per iteration |
|---|---|
| A, two checkpoints (chosen) | about 3 |
| B, hands-off (auto-merge to an iteration branch) | about 2; a bad story lands before the user sees it |
| C, careful (confirm every merge and push) | 7 or more; this is foreman's prompt fatigue |
