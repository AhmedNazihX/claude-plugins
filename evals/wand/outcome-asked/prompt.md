---
description: when everything but the outcome is given, wand asks the outcome question
tags: [wand]
runs: 2
model: sonnet
max_turns: 20
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Design a tool that reminds my team about overdue invoices. It's for our finance team (owner: me, I run finance).
Requirements: read invoices from a CSV export each morning (owner: me); email each account manager their overdue
invoices (owner: the account managers). Out of scope: paying invoices, a web UI. Must run on our one Linux server.
