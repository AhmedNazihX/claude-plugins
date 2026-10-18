---
name: prophecy
description: Plan accio's next iteration. Proposes up to 8 ready-to-build stories from the backlog, settles their open questions one at a time, and on the user's "go" moves them to Ready and commits the plan.
when_to_use: When the user wants to plan or start the next iteration, sprint or batch of accio stories, or asks what to build next in a repo with an .accio/ folder.
allowed-tools: Read, Edit, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board *), Bash(git add *), Bash(git commit *)
---

# prophecy: plan the next iteration

You plan one iteration with the user: propose the batch, settle its open questions, wait for "go", then record it.
Talk in plain words; the user may not know accio's terms. Run accio's board script by its full path,
`${CLAUDE_PLUGIN_ROOT}/bin/accio-board` (written `accio-board` below).

## 1. Check how the build will run
Look at your own tool list. If the `Workflow` tool is missing, workflows are switched off in this Claude Code: the
build will be `/accio:brew-by-hand`, not `/accio:brew`. Say so once, in a plain sentence, when you give the next step.

## 2. Get the proposal
Run `accio-board plan --json`. It returns the next iteration number and:
- `proposed`: the stories to build, in build order, each with its track and the parent it stacks on, if any
- `held`: eligible stories left out, with why (the cap of 8, or two parents in this iteration)
- `dropped_deps`: stories whose dependency was dropped

Never add a story the script didn't propose, and never propose a dropped one. If it fails because there is no
`.accio/` folder, say accio isn't set up here and stop. If nothing is proposed, say why (held, dropped deps, or an
empty backlog) and stop.

Read each proposed story file (`.accio/stories/<ID>.md`) to spot an unclear Definition of Done or a decision the
story leaves open.

## 3. Show the batch
One short table: ID, title, track, stacked on. Then one line each for held stories and dropped deps, if any.

## 4. Settle the open questions, one at a time
Ask in this order, one question per message, in the format of `${CLAUDE_SKILL_DIR}/references/question-format.md`:
1. **A story whose dependency was dropped:** drop it too, or remove the dependency. Apply the answer with Edit on
   its frontmatter (`status: dropped` plus `dropped: <reason>`, or the dep taken out of `deps:`), then run the plan
   again.
2. **A real decision** a story needs before it can be built (an unclear DoD line, two possible behaviours).
3. **Low-stakes defaults**, all bundled into one confirmation ("I'll assume A, B and C; say if any is wrong").

Wait for each answer before the next question. Skip what has no question.

## 5. Wait for "go"
Ask once: "Say go to plan these, or change any track or leave out any story." The user may:
- change a track (`quick`, `story` or `feature`): pass it as `--track <ID>=<track>`
- leave out a story: don't pass it (its children then can't go either; `accio-board go` says so)

Nothing is written before "go".

## 6. Record it
On "go":
1. `accio-board go <ID> <ID> … [--track <ID>=<track> …]`. It checks the set again, sets each story to Ready, and
   writes `.accio/iterations/<N>.md` and `.accio/board.md`. If it refuses, tell the user why in plain words and go
   back to step 5.
2. Commit exactly the files it lists: `git add <files>` then
   `git commit -m "chore(accio): plan iteration <N>"`. Never skip the hooks. If the commit fails, show why.
3. End with the next step, in the report format:

```
What happened: iteration <N> is planned: <k> stories are Ready (<IDs>).
What I need from you: type /accio:brew to build them (it runs unattended; review the result with /accio:owl).
My recommendation: <one line>
```

When workflows are off, the second line names `/accio:brew-by-hand` instead. Never start the build yourself: typing
the command is the user's opt-in.
