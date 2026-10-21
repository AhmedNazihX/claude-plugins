# 012 — Group B leftovers: mark new design notes, hide and fence off-preview pages

Date: 2026-10-21 · Status: decided by the user (accepted the recommendation, option B of 3 options)

## What was decided
Two parts of the Group B leftovers had real alternatives. First (L1): how `accio-board next` knows that a new
design note (a `## ` section in `.accio/design.md`) has no stories yet, so it says `sort` instead of `done`. Second
(L5): what happens when mad-eye, the agent that clicks through the app in a browser, clicks a link that leaves the
preview's address. The click can't be stopped before it happens (curfew checks only `browser_navigate`). It was the
user's to decide because it sets how the board decides the next step and how far mad-eye is trusted.

## Options
| Option | What it looks like | Pros | Cons |
|---|---|---|---|
| A. Match headings, report | the board looks for each note's heading quoted in a story's text; after an off-preview click a hook adds a reason and logs it | no new state; smallest | loops if quill rewords a heading or a note gets no stories; mad-eye still reads the foreign page |
| B. Mark at record time, hide and fence | `record-design` writes new note headings to `run/unsorted.json`, sort's `record` clears it; the hook replaces the foreign page's text with the reason and curfew allows only navigate back, screenshot or close until the page is on the preview again | can't loop; a foreign page can't feed mad-eye text or take more clicks; documented hook features only | the mark lives in git-ignored `run/` (lost if wand and sort run on different machines); curfew reads new state |
| C. Story metadata, require origin flags | stories gain a `design:` field (about 58 old stories filled in); mad-eye skipped unless Playwright runs with `--allowed-origins` | the link survives a fresh clone | most files; can still loop; Playwright says the flag is not a security boundary; mad-eye skips until the user sets the flag |

Costs:
- A, money: none
- A, tokens: about 0 per story (wandmaker's estimate)
- A, time: about 4 small stories (wandmaker's estimate)
- A, risk: medium (the sort loop)
- B, money: none
- B, tokens: about 0; saves tokens when the hook fires (wandmaker's estimate)
- B, time: about 5 small stories (wandmaker's estimate)
- B, risk: low to medium
- C, money: none
- C, tokens: about 10 per story for the field (wandmaker's estimate)
- C, time: about 6 stories (wandmaker's estimate)
- C, risk: medium to high

## Decision
Option B. The user answered "Yes, go with B (Recommended)".

## Why
A script sets the mark and recording the stories clears it, so the board can't loop on a note. Hiding and fencing is
the only option that keeps a foreign page from steering mad-eye, and it uses only documented hook features. The mark
being local matters little for one person on one machine.

## Consequences
A spike (S-L5, by hand) records a real PostToolUse payload after an off-origin click before the hook is built. A note
added to design.md by hand, without `record-design`, is never marked; `/accio:sort` by hand still works.
