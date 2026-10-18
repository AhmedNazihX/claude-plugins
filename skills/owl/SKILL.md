---
name: owl
description: Reviews accio's last build with the user. Shows each finished story and each blocked question from one short summary, takes one batch answer (accept, reject or drop each story, answer the questions, push or not), merges what was accepted, and records the iteration.
when_to_use: When the user says "review the build", "what did brew do/build", "the build finished", "accept/reject/drop S-012", "answer the build's questions", "merge and push the build", or runs /accio:owl, in a repo with an .accio/ folder. Not for planning (prophecy), writing stories (sort), design (wand), building (/accio:brew), reviewing a code diff or PR, or merging a branch by hand.
allowed-tools: Read, Glob, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-summary *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-owl *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-merge *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-hooks verify), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-hooks install)
---

# owl: review the build

You walk the user through one review: show what the build produced, take one batch answer, apply it, push if they
say so. Plain words; scripts do the work. Run each script as its own Bash command, by its full path
(`${CLAUDE_PLUGIN_ROOT}/bin/<script> …`): no shell variables, no `&&` or `;` chains, so your permissions match it.
Put each reason or answer in single quotes (an apostrophe inside becomes `’`). Read files with the Read tool. If a
script exits with an `accio-…:` error, say it in plain words and stop: nothing after it ran.

## 1. Gather
1. `accio-hooks verify`. A missing, broken or switched-off hook, or an error from verify itself, becomes a question
   in step 2 (fix it as verify says, or carry on without that check); never stop on it. Any other note: one line.
2. `accio-summary --latest` writes `.accio/run/owl.md`. If it says a build is running, say to review after it ends,
   and stop. Read only owl.md: never the reports, diffs or story files. With no finished story and no question,
   say there is nothing to review, and stop.

## 2. Ask for one batch answer
Show owl.md as it is, then ask for everything in one message, as `${CLAUDE_SKILL_DIR}/references/batch-answer.md`
shows:
- each finished story (READY in owl.md): accept, reject (with a reason) or drop (with a reason). A story stacked on
  another goes in only with it; one stacked on a rejected or dropped story goes back to be built again by itself
- each blocked question: its answer. A blocked story is never accepted or rejected; the user may drop it, or leave
  the question for later (it is kept). A question saying `needs override: <command>` asks: allow once (this story's
  next build only), allow from now on (every story, every build), or no
- each hook problem from step 1, and whether to push to the base branch after the merge

If the request already answers all of this, don't ask: go to step 3. Ask again only about what is missing or
unclear. Before the answer, run nothing but the step-1 scripts and `accio-owl check` (it writes nothing).

## 3. Check the answer
If the user chose to re-install hooks, run `accio-hooks install`, then `accio-hooks verify`; for lefthook or the
pre-commit framework it prints a snippet: show it to paste. Then run `accio-owl check` with the answer as flags:
`--accept <ID>`, `--reject <ID> '<reason>'`, `--drop <ID> '<reason>'`, `--answer <ID> '<text>'`, and for an override
`--allow-once <ID> '<command>'`, `--allow <ID> '<command>'` (from now on) or `--answer <ID> 'no: find another way
than <command>'`. An allowed command answers its story. Push is not a flag (step 6). If check refuses (for example
"S-002 is built on S-001"), say it in plain words, ask only about that story, and check again.

## 4. Merge what was accepted
If anything was accepted, run `accio-merge <N> <IDs>`, N being the highest number in `.accio/iterations/<N>.md` and
the IDs check's `accept` list in its order. Its `result`:
- `merged`: done. `needs_user`: ask its `question` as it is, and merge again only when the user says so.
- `checks_failed` or `conflict` with `base_failing` true or no `culprit`: the base branch fails `failing` by itself;
  no story is to blame. Say so, and don't merge the rest; the accepted stories stay in review.
- otherwise `culprit` broke it (a conflict with the stories before it, or the `failing` checks). Ask once whether to
  merge the rest. If yes, merge again without the culprit and every story stacked on it; if that fails too, stop.

## 5. Record it
Run `accio-owl close` with the same flags as check (keep every `--accept`), plus `--merged <ID>` for each story the
merge took and, after a failed merge with a culprit, `--culprit <ID> '<the failing checks>'` (it goes back to be
built again). It writes everything and makes one commit, `chore(accio): iteration <N> review`. Report its
`leftovers` (a worktree it kept, and why) and any `commit_error`, with the fix.

## 6. Push, only on yes
Run `accio-owl push-ok`, then `git push origin <base>` with the base it names; your permission prompt for the push
is a deliberate last confirmation. If push-ok refuses (a build is running, or the checkout isn't on the base
branch), say why and don't push; never switch branches yourself. If the push fails, show why; never force it.

End in the report format:

```
What happened: <merged k, sent back m, dropped d, answered q; pushed or not; any accepted story not merged>
What I need from you: <nothing | the fix for an error or leftover | type /accio:prophecy for the next iteration>
My recommendation: <one line>
```

If the user asked to build the answered stories now, the second line says to type `/accio:brew`.
