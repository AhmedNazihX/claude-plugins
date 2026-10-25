---
description: S-081/6 the fresh reader (first-year) reads the written design; its undefined term becomes a question before record-design
tags: [wand]
runs: 1
model: sonnet
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Write the design for our overdue-invoice reminder; everything is decided, so no research and no options, just write
it and record the decision. It's for our finance team (owner: me, I run finance). Requirements: read invoices from a
CSV export each morning (owner: me); mark each invoice past its grace period as overdue and email its account
manager (owner: the account managers). Out of scope: paying invoices, a web UI. Runs on our one Linux server. After
this ships, no overdue invoice goes a week without its account manager being told, and we'd know because the weekly
overdue report shows none without a reminder. Decision: a Python script run by cron at 7:00, sending through our
existing SMTP server, chosen over a hosted workflow tool (Zapier, about $30/month) because the data stays on our
server. Evidence it works: a test with a sample CSV checks who gets which email.
