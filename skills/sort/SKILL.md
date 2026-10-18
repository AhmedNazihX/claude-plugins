---
name: sort
description: Turns accio's design into a backlog of small, testable stories. The quill agent writes the story files, the score sets each track and flags stories to split, a backlog check finds weak stories and quill fixes them, then the stories are committed and the user sees a short summary.
when_to_use: When the user asks to "turn the design into stories", "write the backlog", "break this down into stories", "sort the design", or runs /accio:sort, in a repo with .accio/design.md. Not for designing (wand), planning an iteration (prophecy), building (/accio:brew) or reviewing a build (owl).
allowed-tools: Read, Glob, Agent, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board new), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board record *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-score *)
---

# sort: from the design to stories

You turn `.accio/design.md` into story files, using accio's agents and scripts, and show the user only a summary.
Run each script as its own Bash command by its full path (`${CLAUDE_PLUGIN_ROOT}/bin/<script> …`): no variables, no
`&&` or `;` chains. Never write or edit a story yourself: quill does. If a script exits with an `accio-…:` error, say
it in plain words and stop.

## 1. Start
If `.accio/design.md` is missing, say the design comes first (`/accio:wand`) and stop. Note the story files that
exist now (Glob `.accio/stories/S-*.md`): you will record only the ones quill writes or changes. Run
`accio-board new` for the first free ID.

## 2. Write
Call the `accio:quill` agent: "Write: turn .accio/design.md into story files, numbering from <ID>." It replies
`stories: <n> · summary: <path>`. The new and changed stories are the S-*.md files that weren't there before, or
whose content quill says it changed in its summary.

## 3. Score and split
Run `accio-score --apply --json <each new story file>`. It sets each track. For every story with `"split": true`,
run `accio-board new` and call quill: "Split: <ID> is too big (<the score's parts>); new stories from <next ID>."
Then score the split stories and the new parts again. Split each story at most once; if it is still flagged, say so
in the summary.

## 4. Check the backlog
Call the `accio:examiner` agent: "Backlog check (sort): the stories <IDs> in .accio/stories/; write your findings
to .accio/run/sort/examiner-findings.md." If its verdict is fail, call quill once: "Fix: answer each finding in
.accio/run/sort/examiner-findings.md." Score any story quill changed again. Don't check a second time.

## 5. Record
Run `accio-board record <every story file quill wrote or changed>`. It checks that every story is sound (ids,
dependencies, no cycles), regenerates the board and commits those files. If it refuses, call quill once with its
message ("Fix: <message>") and record again; if it still refuses, show the message and stop. If its reply has a
`commit_error`, the stories are written but not committed: show git's message with the fix.

## 6. Show the summary only
Read quill's summary file and show it, with the tracks from the score, any story still flagged, and anything the
backlog check left open. Never paste story files or DoD lines into the chat. Ask the user something only when the
design is truly ambiguous about a story (one question, with your recommendation). End:

```
What happened: <n> stories written from the design (<IDs>), committed
What I need from you: <nothing | the one question> — then /accio:prophecy to plan the first iteration
My recommendation: <one line>
```
