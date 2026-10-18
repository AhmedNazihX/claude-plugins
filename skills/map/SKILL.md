---
name: map
description: Shows accio's board (the stories in each column, from a script) and what to do next, plus anything the last build left stuck.
when_to_use: When the user asks "show the board", "where are we", "what's the status of the stories", "what's next", or runs /accio:map, in a repo with an .accio/ folder. Not for planning (prophecy), building (/accio:brew) or reviewing (owl).
allowed-tools: Read, Glob, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board board), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board status)
---

# map: show the board

You show where the work stands. Run each script as its own Bash command by its full path
(`${CLAUDE_PLUGIN_ROOT}/bin/accio-board …`), with no variables or chains. Never change anything.

1. Run `accio-board board` (it regenerates `.accio/board.md` from the story files and the running build), then
   `accio-board status` (one line of counts). If either exits with an `accio-board:` error, say it in plain words
   and stop; a story file it names needs fixing.
2. Read `.accio/board.md` and show it as it is.
3. If `.accio/run/stuck.json` exists (Glob), a build agent froze on a permission question: name the agent, the tool
   and what it tried, in one line each.
4. Say the next step in one line, from the counts: stories in Review or Blocked → `/accio:owl`; stories in Ready →
   `/accio:brew`; stories in Backlog only → `/accio:prophecy`; no stories → `/accio:sort` (or `/accio:wand` without a
   design). If no tool named `Workflow` appears anywhere in your tools, including tools listed only by name,
   workflows are switched off: say `/accio:brew-by-hand` instead of `/accio:brew`.
