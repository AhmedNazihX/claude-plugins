---
description: "/accio on a backlog with no checks in config.json runs prophecy once, and when accio-board go refuses for no checks it stops and passes the message on instead of running prophecy again (S-087)"
tags: [accio]
runs: 2
model: sonnet
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Skill, Bash]
---

/accio
