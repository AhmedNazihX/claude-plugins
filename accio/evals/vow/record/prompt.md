---
description: vow writes a numbered decision record with options, pros, cons and costs, and commits it
tags: [vow, ci]
runs: 2
model: sonnet
max_turns: 15
allowed_tools: [Read, Skill]
---

Record this decision: we're going with Postgres instead of SQLite. SQLite would be one file with nothing to run and
free, but only one writer at a time. Postgres is a managed server, many writers at once, about $15 a month. We
picked Postgres because several background workers write at the same time.
