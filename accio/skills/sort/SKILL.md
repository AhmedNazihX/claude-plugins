---
name: sort
description: Stories (sort): turns accio's design into a backlog of small, testable stories and commits them.
when_to_use: When the user asks to "turn the design into stories", "write the backlog", "sort the design", or runs /accio:sort, in a repo with .accio/design.md. Not for designing (wand), planning an iteration (prophecy), building (/accio:brew) or reviewing a build (owl).
allowed-tools: Read, Glob, Agent, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board new), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board board --print), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board record), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board record *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-score *)
---

# sort: from the design to stories

You turn the parts of `.accio/design.md` no story covers yet into story files, using accio's agents and scripts,
and show the user only a summary. Run each script as its own Bash command by its full path
(`${CLAUDE_PLUGIN_ROOT}/bin/<script> …`): no variables, no `&&` or `;` chains. Never write or edit a story yourself:
quill does. Call agents one at a time. If a script exits with an `accio-…:` error, say it in plain words and stop,
unless a step below says otherwise; when you stop after quill wrote files, name the files written but not committed.

## 1. Start
If `.accio/design.md` is missing, say the design comes first (`/accio:wand`) and stop. Run `accio-board new` for the
first free ID (it refuses while a build runs: then stop). Keep a list of **this run's stories**: every ID a quill
reply names.

## 2. Write
Read `.accio/run/unsorted.json` (a list of design headings; missing or empty means a first design) and run
`accio-board board --print` for the story list (ID, title, status). Call the `accio:quill` agent: "Write: turn
.accio/design.md into story files, numbering from <ID>. Design headings to cover: <the headings from unsorted.json,
or 'the whole design'>. Existing stories:" followed by the board's story list. Quill reads only those sections. Its reply is one
line, `stories: <n> (<IDs>) · summary: <path>`, maybe with `open:` and `question:`. Add its IDs to the list.

## 3. Score and split
Run `accio-score --apply --json <each story file in the list>`. It sets each track. If it refuses a file
(`accio-score: <file>:<line>: …`), call quill ("Fix: <message>") and score again: one fix per file; if the same file
is refused again, show it and stop. For each story with `"split": true`, one at a time: run `accio-board new` for a
<new ID>, then call quill: "Split: <ID> is too big (<the score's parts>); new stories from <new ID>." Add the IDs it
names, and score them as above. One round only: never split a part, or a story flagged again; list any still
flagged in the summary.

## 4. Ask, then check the backlog
If quill's replies named questions, ask each now, one at a time, with your recommendation; pass each answer to
quill ("Fix: <ID>: the user says …") and score what it changed as in step 3. Then call the `accio:examiner` agent: "Backlog check (sort): the stories <IDs> in .accio/stories/, from .accio/design.md; look for a counted file missing from a story's `files` (a file a test counts, such as `accio/README.md` for a new agent);
findings template ${CLAUDE_PLUGIN_ROOT}/references/findings-template.md; write your findings to
.accio/run/sort/examiner-findings.md." If its verdict is incomplete, call examiner once more with the same words; if
it is still incomplete, go on without its findings: never take it as a pass, and name the file in its `missing` in
the summary (step 6). If its verdict is fail, run `accio-board new` and call quill once: "Fix:
answer each finding in .accio/run/sort/examiner-findings.md; new stories, if a finding needs a split, from <ID>."
Add the IDs it names and score them as in step 3. Don't check a second time; findings quill leaves `open` go in the
summary. A question this fix raises is asked as above before step 5.

## 5. Record
Run `accio-board record <each story file in the list>`. It checks every story (ids, dependencies, no cycles), regenerates the board and commits those files. If the design note led to no new story, run `accio-board record` with no files: it
only empties `run/unsorted.json`, so `/accio` moves on. If it refuses:
- a build is running: the stories are written but not committed; give the exact `record` command to run after it
- "record takes story files in …": your list is wrong; fix it and record again
- a story problem in one of this run's files: call quill once ("Fix: <message>") and record again; if it still
  refuses, show it and stop. The same in any other story: show it and stop; it isn't sort's to change

If its JSON has `"commit": null`, the stories are written but not committed: give `commit_error` in plain words and
the `record` command to run again.

## 6. Show the summary only
Read `.accio/run/sort/quill-summary.md` and show it, with each story's track from its last score, any story still
flagged, and the findings left open. When the backlog check came back incomplete twice, say "backlog check
incomplete: examiner couldn't read <missing>, so the stories were not checked", and ask for that file in "What I need".
Never paste story files or DoD lines into the chat. End:

```
What happened: <n> stories written from the design (<IDs>), committed | written but not committed (<git's reason>)
What I need from you: <nothing | the fix | the file the backlog check couldn't read> — then /accio:prophecy to plan the first iteration
My recommendation: <one line>
```

When ARGUMENTS says `driven`, `/accio` is driving: the second line says `next: prophecy (accio carries on)`
instead of the "/accio:prophecy" hand-over. With no `driven` argument this skill runs alone: keep every question and
the "/accio:prophecy" ending above.
