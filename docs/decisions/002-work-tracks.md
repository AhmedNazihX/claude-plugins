# 002 — Work tracks: Quick / Story / Feature, picked by the plugin

Date: 2026-10-17 · Status: decided by the user

## Decision
Every work item goes on one of three tracks:

| Track | Example | Process |
|---|---|---|
| Quick | fix a typo in an error message | no story file; one agent → checks → one cheap reviewer → merge |
| Story | add password reset | story file with a checkable DoD; build workflow, 2 reviewers, ≤ 2 fix rounds |
| Feature | add billing | one-page design note, grilled during planning, then split into stories |

The plugin picks the track from a score: files touched, risk, new dependencies. **Risky paths always go on the
Story track or higher, whatever their size.** Risky paths are auth, payments, migrations, secrets and CI config,
plus whatever the project adds to that list. The tracks appear once, in the iteration plan, where the user can
override any of them.

## Options compared
- A, plugin picks with override (chosen): adds no extra questions, but it can misjudge, which the risky-path rule
  limits.
- B, user always picks: adds one question per item, the prompt fatigue foreman had.
- C, two tracks only: simplest, but big features get no design step.

Rough cost per item, guessed from foreman's runs (not measured): Quick ~20–50k tokens, Story ~150–400k.

## Amendment (2026-10-17, design review)
- **A Quick item inside an iteration gets a minimal story file:** frontmatter plus 1–3 DoD lines. The board, the
  budgets and the ledger need one.
- **`reparo` stays file-free.** It runs outside iterations and uses a `Q-<n>` ID only in the ledger.
