---
name: accio
description: The conductor (accio): one command that carries the work from wherever the board stands to a pushed, CI-checked result. It reads accio's next step, runs that step's skill in this chat (design, stories, plan, build, review) and repeats, stopping only at real decisions.
when_to_use: When the user runs /accio, or says "continue", "carry on", "what's next, do it", or "take it from here" in a repo with an .accio/ folder or a design to start from. Not for running one named step by hand (the step skills do that).
allowed-tools: Read, Skill, Workflow, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board next *)
---

# accio: one command, the whole loop

You carry the work forward. Python decides the next step; you only follow it. Typing `/accio` is the user's
opt-in for every step, the build included. Plain words. Run the script as its own Bash command by its full path,
with no variables and no `&&` or `;` chains.

## Loop
1. Run `${CLAUDE_PLUGIN_ROOT}/bin/accio-board next --json` before anything else. It gives
   `{"step", "auto", "sentence"}`. If it exits with an `accio-…:` error, say it in plain words and stop.
2. Do the step, then go back to 1. Never decide the step yourself and never skip step 1 after a step ends.

## The step
- `wand`, `sort`, `prophecy`, `owl`: load that step's skill with the Skill tool (`accio:<step>`) and follow it in
  this chat.
- `brew`: there is no brew skill. Load `accio:brew` and start the build yourself with the Workflow tool.
- `wait`: a build is running. Say so in one line, then stop and carry on at the build's end notice.
- `done`: no skill. Say the `sentence`, ask what to design next, and stop.

## Auto and the user
- When `auto` is true, run that step's skill and read the board again, with no question in between.
- When `auto` is false, the step will need the user. Still run that step's skill, up to its first question to the
  user, and stop there: that question is the stop. After the answer, carry on with the skill, then read the board
  again.

## The end notice
When the build ends, its end notice wakes this chat. Read the board again with step 1: it says `owl`, so go on
to the review. Never say to the user "type" and a step's slash command: you run the step, whatever its name.
