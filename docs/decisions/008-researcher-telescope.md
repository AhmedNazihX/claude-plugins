# 008 — Researcher: `telescope`, at fixed points

Date: 2026-10-17 · Status: decided by the user

## Decision
The skill `telescope` runs the `seeker` agent (Sonnet) to look for better ways of doing things. It runs at fixed
points only:
1. **In `prophecy` (v1).** It looks at the stories picked for the iteration and adds a "better way?" note to a
   story when it finds a maintained library, a simpler pattern or a known pitfall. Each note cites its source. The
   user accepts or skips the notes inside the planning checkpoint, as part of the bundled confirmation.
2. **In `pensieve` (v2).** It scans new Claude Code features and ecosystem plugins for improvements to accio
   itself. It writes proposals to `.accio/research/`, and the user accepts or rejects each one. **It never changes
   accio on its own.**
3. **On demand.** `/accio:telescope <topic>`.

Cost: about 30–60k tokens per run (a rough estimate; today's web research took about 87k). There is one run per
iteration by default, and it shows in the cost report.

## Options compared
- A, fixed points (chosen): findings arrive when the user can act on them, with no extra prompts.
- B, a weekly scheduled routine: about 50–100k tokens a week whether or not the user works. It can be added in v2.
- C, always on: open-ended cost, and findings pile up unread.
