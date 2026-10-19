---
description: "/accio on a design with no stories reads the board, then runs sort itself, and never tells the user to type a step command"
tags: [accio, ci]
runs: 2
model: sonnet
max_turns: 40
timeout_seconds: 900
allowed_tools: [Read, Glob, Skill, Agent]
---

/accio
