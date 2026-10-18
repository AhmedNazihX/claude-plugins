---
name: wand
description: Designs what to build with the user. Sets accio up on first use, interviews the user one question at a time (every requirement needs an owner; the outcome question is always asked), has seeker check the facts and wandmaker propose 2–3 options, settles the choice, then writes .accio/design.md and records each decision.
when_to_use: When the user wants to design or start a new project or feature, "plan the architecture", "help me design X", "I want to build …", "write the design", "add a design note for …", or runs /accio:wand, in a git repo. It records the design's decisions itself. Not for turning a design into stories (sort), planning an iteration (prophecy), building (/accio:brew) or reviewing (owl).
allowed-tools: Read, Glob, Grep, Write, Edit, Agent, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board init), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board record-design), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-hooks install), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-vow *)
---

# wand: design what to build

You design one project or feature with the user, then write it down for `sort`. Run each script as its own Bash
command by its full path (`${CLAUDE_PLUGIN_ROOT}/bin/<script> …`), with no variables or chains. If a script exits
with an `accio-…:` error, say it in plain words and stop. Call agents one at a time.

## 1. Set up (first use only)
If there is no `.accio/` folder: run `accio-board init`, then `accio-hooks install` (accio's git hooks: no secrets
in commits, no unconfirmed pushes). For lefthook or the pre-commit framework it prints a snippet: show it for the
user to paste. If install reports a problem (hooks switched off, a hook it can't edit), tell the user in one line
with its fix, and go on: the design doesn't depend on it, and brew checks the hooks again. If `.accio/design.md` exists, this is a **design note**: you add one `##` section for the new feature
and change nothing else in the file.

## 2. Interview, one question at a time
Read the user's idea, `intent.md` if there is one, and glance at the existing code (Glob, Read). Then ask, one
question per message, in the format of `${CLAUDE_SKILL_DIR}/references/interview.md`, until the requirements are
clear. Always ask, in these words: **"After this ships, what should be true, and how would you know?"** Every
requirement needs an owner (the person or role who needs it); when one has none, say you're deleting it, and do.

## 3. Check the facts
Call the `accio:seeker` agent with the facts the design depends on (libraries, services, prices, limits, what the
code already has): "Answer these, writing to .accio/run/wand/seeker-notes.md: …". A capability it reports as
`unavailable` is out of the design unless the user wants a spike first.

## 4. Get options
Call the `accio:wandmaker` agent: "Write options to .accio/run/wand/wandmaker-options.md for these requirements
(with owners): …; outcome: …; research: .accio/run/wand/seeker-notes.md; code: <where>." Read its file.

## 5. Settle the choice
Show the options in the decisions format (what each looks like, pros, cons, costs one per line, what breaks first,
wandmaker's recommendation), then ask one question: which one. Grill the choice the same way, one question at a
time, until nothing a builder would have to guess is left. Never choose for the user.

## 6. Write and record
1. Write `.accio/design.md` (or add the design note) in the format of
   `${CLAUDE_SKILL_DIR}/references/design-template.md`. Its Evidence section takes wandmaker's fourth depth answer:
   it seeds the stories' DoD lines.
2. Record each real decision (the option chosen, and any other choice between real alternatives) with
   `accio-vow next '<title>'`, writing the record in the format of
   `${CLAUDE_PLUGIN_ROOT}/skills/vow/references/decision-format.md`, then `accio-vow record <path>`, one at a time.
3. Run `accio-board record-design` to commit the design. If its reply has `"commit": null`, say why.

End:

```
What happened: <the design in one sentence>; <k> decisions recorded
What I need from you: type /accio:sort to turn the design into stories
My recommendation: <one line>
```
