---
description: wand has seeker check the facts and wandmaker propose 2-3 options with what breaks first, then asks which one
tags: [wand]
runs: 1
model: sonnet
max_turns: 40
timeout_seconds: 1200
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Design a tool that reminds my team about overdue invoices. It's for our finance team (owner: me, I run finance).
Requirements: read invoices from a CSV export each morning (owner: me); email each account manager their overdue
invoices (owner: the account managers). Out of scope: paying invoices, a web UI. Must run on our one Linux server.
After this ships, no invoice stays overdue for more than a week without its account manager being told, and we'd
know because the weekly overdue report shows no invoice older than 7 days with no reminder sent. That's all the
requirements: check the facts and show me the options.
