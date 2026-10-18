---
description: a requirement nobody owns is deleted, and wand says so
tags: [wand]
runs: 2
model: sonnet
max_turns: 20
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Design a tool that reminds my team about overdue invoices. It's for our finance team (owner: me, I run finance).
Requirements: read invoices from a CSV export each morning (owner: me); email each account manager their overdue
invoices (owner: the account managers). I also thought of a Slack bot for it, but nobody has asked for one and
nobody would use it. After this ships, no invoice stays overdue a week without its manager being told, and we'd
know because the weekly overdue report shows none older than 7 days without a reminder.
