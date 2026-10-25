---
description: S-081/6 a design note that contradicts a recorded decision gets the clash question (replace the decision, or change the note)
tags: [wand]
runs: 1
model: sonnet
max_turns: 30
timeout_seconds: 900
allowed_tools: [Read, Glob, Grep, Skill, Agent]
---

Add a design note for Slack reminders: each morning, also post every overdue invoice (customer name and amount) to
the #finance Slack channel, through a Zapier workflow that reads our CSV export. It's for me (I run finance), so I
see the overdue list without opening email. After this ships, every overdue invoice is in #finance by 8:00, and
we'd know because the channel's morning post matches the weekly overdue report.
