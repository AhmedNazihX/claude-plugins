---
name: map
description: Board (map): shows accio's board, what the last build left stuck, and the next step, without changing anything.
when_to_use: When the user asks "show the board", "where are we", "what's next" or "is the build still running", or runs /accio:map, in a repo with an .accio/ folder. Not for planning (prophecy), building or reviewing (owl).
allowed-tools: Read, Glob, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board board --print), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board status), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board next)
---

# map: show the board

You show where the work stands, and change nothing (a build may be running). Run each script as its own Bash
command by its full path (`${CLAUDE_PLUGIN_ROOT}/bin/accio-board …`), with no variables or chains.

1. Run `accio-board board --print` (the board as a table, from the story files and the running build; it writes
   nothing), then `accio-board status` (one line of counts). If either exits with an `accio-board:` error, say it
   in plain words and stop: if it names a story file, that file needs fixing; with no `.accio/` folder, accio isn't
   set up here.
2. Show the board as it is.
3. Read `.accio/run/stuck.json` (skip this if it doesn't exist): each entry is a build agent that froze on a
   permission question. Name its `agent_type`, `tool` and `detail`, one line each.
4. Run `accio-board next` and say its sentence as the next step, in one line. The script holds the rule; don't
   restate it.

   If no tool named `Workflow` appears anywhere in your tools, including tools listed only by name, workflows are
   switched off, and accio's build needs them: where the sentence says to build, say to turn them on instead (the
   `disableWorkflows` setting off, the `CLAUDE_CODE_DISABLE_WORKFLOWS` variable unset), then build.
