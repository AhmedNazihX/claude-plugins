---
name: prophecy
description: Plan (prophecy): plans the next accio iteration with the user. Proposes up to 8 buildable stories from .accio/'s backlog, settles their open questions one at a time, and on "go" marks them Ready and commits the plan.
when_to_use: When the user asks "what should we build next", "plan the next iteration/sprint", "pick the next batch of stories", or runs /accio:prophecy, in a repo with an .accio/ folder. Not for writing stories (sort), designing (wand), building (/accio:brew) or reviewing a build (owl).
allowed-tools: Read, Edit, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-board *)
---

# prophecy: plan the next iteration

You plan one iteration with the user: propose the batch, settle its open questions, wait for "go", then record it.
Run each script as its own Bash command by its full path, with no variables or `&&` chains. Talk in plain words;
the user may not know accio's terms. Explain a term the first time: a *track* is how much
review a story gets (quick, story, feature); a story *stacked on* another is built on top of it in this batch.

## 1. Check how the build will run
If no tool named `Workflow` appears anywhere in your tools, including tools listed only by name, workflows are
switched off: say in the final "What happened" line that accio's build needs them and how to turn them on (the
`disableWorkflows` setting off, the `CLAUDE_CODE_DISABLE_WORKFLOWS` variable unset).

## 2. Get the proposal
Run `${CLAUDE_PLUGIN_ROOT}/bin/accio-board plan --json`. It returns:
- `proposed`: the stories to build, in build order, each with its track and `parents` (what it stacks on)
- `held`: eligible stories left out, with why (the cap, 8 by default, or a parent that can't go)
- `dropped_deps`: stories whose dependency was dropped; `waiting`: stories waiting on unfinished work
- `open_iteration`: set when the last iteration is planned but not built yet

Never add a story the script didn't propose. If there is no `.accio/` folder, say accio isn't set up here and stop.
If nothing is proposed, say why from the reply (held, dropped deps, waiting on stories still in review, which means
`/accio:owl` comes next, or an empty backlog) and stop. If `open_iteration` is set and the user didn't ask to
re-plan, say that iteration is planned but not built and hand over `/accio:brew` instead.

Read the proposed story files (`.accio/stories/<ID>.md`). Ask only where a builder would otherwise have to guess;
most stories have no question.

## 3. Show the batch
One short table (ID, title, track, stacked on), then a line each for held, waiting and dropped-dep stories. Send it
in the same message as the first question of step 4, or the go question of step 5 if there is none. When a re-plan
changes the batch, show the new table first.

## 4. Settle the open questions, one at a time
One question per message, in the format of `${CLAUDE_SKILL_DIR}/references/question-format.md`, in this order:
1. **Each story whose dependency was dropped** (unless the user already left it out): drop it too, or remove the
   dependency. Apply the answer with Edit on its frontmatter (`status: dropped` plus `dropped: <reason>`, or the dep
   taken out of `deps:`) and run the plan again.
2. **A real decision** a story needs before it can be built (an unclear DoD line, two possible behaviours).
3. **Low-stakes defaults**, all bundled into one confirmation ("I'll assume A, B and C; say if any is wrong").

Write each answer from 2 and 3 into its story file with Edit: a sentence under `## Context`, or a clearer DoD line
in the same `- [ ] S-012/1 …` form. The build runs unattended, so an answer kept only in the chat is lost. Keep a
list of every story file you edit; `go` commits them with the plan.

## 5. Wait for "go"
Ask: "Say go to plan these, or change any track or leave out any story." If the user already said go (in the
request, or with their last answer) and no question is open, don't ask again. The user may:
- change a track: pass `--track <ID>=<track>`
- leave out a story: don't pass it, and leave out the stories stacked on it too; tell the user which

Before "go", the only writes are the step-4 edits to story files. Never run `accio-board go` before.

## 6. Record it
On "go":
1. Run `${CLAUDE_PLUGIN_ROOT}/bin/accio-board go <ID> … [--track <ID>=<track> …] [--also <story file> …]`, with
   one `--also` per story file you edited in step 4. It sets the stories to Ready, returns any other Ready story to
   Backlog (`returned`: tell the user), writes the story, iteration and board files, all or nothing, and commits
   exactly those plus the `--also` files. If it refuses (`accio-board: …`):
   - a build is running, or the last one isn't reviewed: say so (review it with `/accio:owl` first), and stop
   - no `checks` in `.accio/config.json`: nothing was changed; show the message (it names the file and an example
     entry), ask the user to set `checks`, and run go again after
   - it cannot write: show the error and stop; nothing was changed, don't retry
   - a story can't go: say which and why, from the message, and ask for go again; never change the set yourself
   - a bad `--also`: you passed a file that isn't a story file; fix the list and run it again
2. If its reply has a `commit_error`, the plan is written but git didn't commit it (a hook refused, or no repo):
   report git's message with the fix as "What I need from you", and don't hand over the build until it is committed.
3. Otherwise end in the report format:

```
What happened: iteration <N> is planned: <k> stories are Ready (<IDs>).
What I need from you: type /accio:brew to build them (it runs unattended; review the result with /accio:owl).
My recommendation: <one line>
```

When workflows are off, the second line says to turn them on first, then type `/accio:brew`. Never start the build yourself: typing the
command is the user's opt-in.

When the `accio` conductor skill was loaded earlier in this chat and has not finished, `/accio` is driving: typing
`/accio` was the opt-in, so the second line says `next: brew (accio carries on)` instead of the "/accio:brew"
hand-over, and the conductor starts the build. When this skill runs alone, keep the "/accio:brew" ending above.
