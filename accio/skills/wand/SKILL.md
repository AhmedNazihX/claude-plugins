---
name: wand
description: Design (wand): interviews the user one question at a time, checks the facts, settles the choice and writes .accio/design.md.
when_to_use: When the user wants to design a new project or feature ("help me design X", "plan the architecture", "write the design", "add a design note for …", "I want to build …"), or runs /accio:wand, in a git repo. Not for stories (sort), planning an iteration (prophecy), building (/accio:brew) or reviewing (owl).
allowed-tools: Read, Glob, Grep, Write, Edit, Agent, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board init), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board wand-reset), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board record-design), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-hooks install), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-vow *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/bin/accio_lib/checkfinder.py), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/bin/accio_lib/mutationfinder.py)
---

# wand: design what to build

You design one project or feature with the user, then write it down for `sort`. Run each script as its own Bash
command by its full path (`${CLAUDE_PLUGIN_ROOT}/bin/<script> …`), with no variables or chains. If `accio-board` or
`accio-vow` exits with an `accio-…:` error, say it in plain words and stop, except where a step below says to fix it
and run again; `accio-hooks` never stops wand. Call
agents one at a time.

## 1. Set up
If the repo has no `.accio/` and the user did not type `/accio:wand` or `/accio` (a plain "I want to build …" can
start wand), ask once before setting up: "This adds an `.accio/` folder and git hooks (no secrets in commits, no
unconfirmed pushes) to this repo. Set accio up?" Wait for the answer; on no, stop and change nothing. Then run
`accio-board init` (it changes nothing once accio is set up), then `accio-board wand-reset` (it removes the last
run's helper notes in `.accio/run/wand/`, so the notes read below are this run's; it refuses while a build runs:
say so and stop), then `accio-hooks install` (accio's git hooks: no
secrets in commits, no unconfirmed pushes). Whatever install prints or exits with (a snippet to paste, a warning,
hooks switched off), tell the user in one line, as a statement with its fix (never a question), and go on.

**Check commands.** So a build never skips its tests, find the commands that check this repo: run
`python3 ${CLAUDE_PLUGIN_ROOT}/bin/accio_lib/checkfinder.py` (it reads the `run:` lines of `.github/workflows/*.yml`
that hold `test`, `lint`, `check`, `pytest`, `unittest` or `build`, the test and lint scripts in `package.json`, and
pytest folders; it writes nothing). Skip this when `.accio/config.json` already has `checks`. Keep every
proposed command, without a stop: add them all to `checks` in `.accio/config.json` (Edit; each is
`{"command": …, "glob": "**"}`) and say in one line "I kept these check commands: …; say if one should go". If the
user later says one should go, remove it. If it finds nothing, say so in one line and write nothing.

**Mutation check.** When `.accio/config.json` has no `mutation` key, run
`python3 ${CLAUDE_PLUGIN_ROOT}/bin/accio_lib/mutationfinder.py` (it reads the repo's marker files and prints the tool
that fits, or "none known"; it writes nothing). Skip this when the key is there, whether `false` or a command. When it
names a tool, ask once, as one question in its own message: "Your tests aren't checked for weak spots. Turn on the
mutation check with <tool>?" (name each tool it printed). On no, write `"mutation": false` in `.accio/config.json`
(Edit), so accio never asks again. On yes, write nothing and say the steps in plain words: install the tool as a dev
dependency; give it a small wrapper that takes the story's diff file, mutates only the changed lines, and prints each
surviving mutant on its own line starting `file:line`; then set `mutation.command` to that wrapper with `{diff}` where
the diff file goes (decision 011). When it prints "none known", say in one line that no mutation tool is known for
this repo, and don't ask.

**New design or design note.** If `.accio/design.md` exists, this run adds a **design note**: one new `## <Feature>`
section at the end, with Edit; never Write the file, never change the rest of it.

## 2. Interview, one question at a time
Read the user's idea, `intent.md` at the repo root if there is one, and glance at the code (Glob, Read). Then ask,
one question per message, as `${CLAUDE_SKILL_DIR}/references/interview.md` says, until a builder would not have to
guess. Settle the outcome first: unless the user already said what should be true after it ships and how they'd
know, ask in exactly these words, on its own (no other question in that message): **"After this ships, what should be
true, and how would you know?"** For each requirement, find who needs it (a person or role, the user included) and
why; if nobody does, say "Nobody needs X, so I've taken it out", keep it out of the requirements, the options and
the stories, and list it under the design's Out of scope as `(no owner)`.

**Recorded decisions.** Read the titles of `.accio/decisions/*.md` (and the whole of any that bear on the idea).
When the new design or note contradicts one, say which and ask, as `interview.md` says: replace the decision
(record a new one with vow, its text saying "Replaces decision NNN"), or change the note.

## 3. Check the facts
Call the `accio:seeker` agent with the facts the design rests on (libraries, services, prices, limits, what the
code already has): "Answer these, writing to .accio/run/wand/seeker-notes.md: …". To check a new fact later, call
it again with every question, old and new. A capability it marks unavailable or not checked stays out of the
design; if the user still wants it, its spike (a small throwaway test of whether it works) goes under Open
questions. If its reply has no `findings:` line, or `.accio/run/wand/seeker-notes.md` is not there, say "the seeker didn't
run: <why>" and stop: the design rests on it. Skip steps 3–5 only when the user has already chosen the design, given the facts it rests on and said what would
show it works; then go to step 6.

## 4. Get options
Call the `accio:wandmaker` agent: "Write options to .accio/run/wand/wandmaker-options.md for these requirements
(with owners): …; outcome: …; must not change and limits: …; out of scope: …; unavailable (seeker): …; research:
.accio/run/wand/seeker-notes.md; code: <where, or none>." Read its file. If its reply has no `options:` line, or the file is not there, say "the wandmaker didn't run: <why>"
and stop: the design rests on it.

## 5. Settle the choice
Show the options in the format of `${CLAUDE_SKILL_DIR}/references/interview.md` (what each looks like, pros, cons,
costs one per line, what breaks first, wandmaker's recommendation), then ask which one. Grill the choice the same
way, one question at a time, until nothing a builder would have to guess is left. Never choose for the user.

## 6. Record and write
1. Record each real decision (the option chosen, and any other choice between real alternatives), one at a time,
   following `${CLAUDE_PLUGIN_ROOT}/skills/vow/SKILL.md` steps 3–5: `accio-vow next`, the record in the format of
   `${CLAUDE_PLUGIN_ROOT}/skills/vow/references/decision-format.md`, `accio-vow record`.
2. Write `.accio/design.md` (or add the design note) in the format of
   `${CLAUDE_SKILL_DIR}/references/design-template.md`, citing each decision by its number. Each part's "Checked by"
   and the Evidence section take the chosen option's fourth depth answer as settled with the user (or, when steps
   3–5 were skipped, the evidence the user gave): they seed the stories' DoD lines.
3. **Fresh reader.** Call the `accio:first-year` agent once, with only the design's path (and the note's heading
   for a note), nothing else from the interview: "Read .accio/design.md (note: `## <Feature>`); write your notes to
   .accio/run/wand/first-year-notes.md." If its reply has no `notes:` line, says `incomplete`, or `.accio/run/wand/first-year-notes.md` is not there, say
   "the fresh reader didn't run: <why>", never "found nothing", and go on without it. Otherwise read its notes; drop a point the interview already settled; put the small points (wording, a default with an obvious
   answer) in one line, "I'll assume A, B and C", and write those assumptions into the design with Edit; ask each real
   decision left as a question in the format of `${CLAUDE_SKILL_DIR}/references/interview.md`, one at a
   time; write each answer into the design with Edit (a clash with a decision is asked as step 2 says; an answer that
   settles a choice between real alternatives is recorded as in 1, and the design cites it). One read-back
   only: never call it twice in a run. With `driven`, these questions are still asked (they are real decisions).
   With no points left, go on and say "the fresh reader found nothing" in the What happened line (only when it ran and its notes say
   `nothing found`).
4. Run `accio-board record-design`. If it refuses an older design for a missing `## Outcome`, ask the user for the
   project's outcome and add `## Outcome` right under the `# Design:` title (the one change allowed outside a note),
   then run it again.

End:

```
What happened: <the design or note in one sentence>; <k> decisions recorded; <the fresh reader found nothing | the fresh reader didn't run: why | j fresh-reader questions asked> (<n> not committed: <why>, when any); design committed | written but not committed (<why>)
What I need from you: <nothing | the hooks fix or snippet | the commit fix> — then /accio:sort to turn it into stories
My recommendation: <one line, with why>
```

When ARGUMENTS says `driven`, `/accio` is driving: the second line says `next: sort (accio carries on)` instead of
the "/accio:sort" hand-over. With no `driven` argument this skill runs alone: keep every question and the
"/accio:sort" ending above.
