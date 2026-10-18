---
description: "owl applies a batch with no accepted story (reject, its child going back too, drop, answer): one commit, no merge, no push"
tags: [owl]
runs: 2
model: sonnet
max_turns: 25
allowed_tools: [Read, Glob, Skill]
---

Review the build: reject S-001 because the email text is wrong (S-002 can go back with it), drop S-004 because we
don't need photos, and S-003: 5 tries per hour. Don't push.
