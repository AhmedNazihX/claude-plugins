---
name: owl
description: Reviews accio's last build with the user. Shows each ready story and each blocked question from one short summary, takes one batch answer (accept, reject or drop each story, answer the questions, push or not), merges what was accepted, and records the iteration.
when_to_use: When the user asks to review the build, see what brew built, accept or reject stories, answer the build's questions, merge and push, or runs /accio:owl, in a repo with an .accio/ folder. Not for planning (prophecy) or building (/accio:brew).
allowed-tools: Read, Glob, Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-summary *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-owl *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-merge *), Bash(${CLAUDE_PLUGIN_ROOT}/bin/accio-hooks verify)
---

# owl: review the build

You walk the user through one review: show what the build produced, take one batch answer, apply it, push if they
say so. Plain words; scripts do the work. Run each script as its own Bash command, by its full path
(`${CLAUDE_PLUGIN_ROOT}/bin/<script> …`): no shell variables, no `&&` or `;` chains, so your permissions match it.
Read files with the Read tool.

## 1. Gather (no questions yet)
1. `accio-hooks verify`. Each problem it prints becomes a question in step 2 (re-install the hooks, or carry on
   without that check).
2. `accio-summary --latest` writes `.accio/run/owl.md`. Read only that file: never the reports, diffs or story
   files. If it shows no story in review and no question, say there is nothing to review and stop.

## 2. Ask for one batch answer
Show owl.md as it is (each ready story: what changed, how to try it, risks, cost; each blocked question), then
everything you need, in one message, using `${CLAUDE_SKILL_DIR}/references/batch-answer.md`:
- each story in review: accept, reject (with a reason) or drop (with a reason). A story stacked on another goes in
  only with it; one stacked on a rejected or dropped story goes back to Ready by itself and needs no answer
- each blocked question: its answer (`--answer`; a blocked story is never accepted or rejected). A question that says `needs override: <command>` (accio's guard refused a
  command) asks: allow once (next build only), allow from now on, or no
- each hook problem from step 1
- push to the base branch after the merge: yes or no

Wait for the answer. Ask again only about what is missing or unclear, never the whole batch.

## 3. Check the answer
Run `accio-owl check` with the answer as flags: `--accept <ID>`, `--reject <ID> "<reason>"`, `--drop <ID>
"<reason>"`, `--answer <ID> "<text>"`, `--allow "<command>"`, `--allow-once "<command>"`. If it refuses (for example
"S-002 is built on S-001"), say it in plain words, ask only about that story, and check again. A "no" to an override
is an answer too: `--answer <ID> "no: don't run <command>; find another way"`.

## 4. Merge what was accepted
If anything was accepted, run `accio-merge <N> <IDs in the order check gave>`, where N is the newest file in
`.accio/iterations/`. Read its `result`:
- `merged`: every accepted story is in the base branch
- `checks_failed` or `conflict`: nothing was merged; `culprit` broke it. Tell the user which story and why (the
  failing checks), and ask once whether to merge the rest. If yes, merge again without the culprit and the stories
  stacked on it. The culprit goes back to Ready with the failure.
- `needs_user`: ask its `question`, then merge again

## 5. Record it
Run `accio-owl close` with the same answer flags, plus `--merged <ID>` for each merged story and, after a failed
merge, `--culprit <ID> "<the failing checks>"`. It writes every change and makes one commit,
`chore(accio): iteration <N> review`. If it reports `leftovers` (a worktree it couldn't remove) or a
`commit_error`, say so with the fix.

## 6. Push, only if the user said yes
If something was merged: `accio-owl push-ok` (it refuses while a build runs), then `git push origin <base>` with the
base it names. If the push fails, show why; never force it.

End in the report format:

```
What happened: <merged k stories, sent back m, dropped d, answered q; pushed or not>
What I need from you: <nothing | type /accio:prophecy to plan the next iteration>
My recommendation: <one line>
```

If the user asked to build the answered stories now, the second line says to type `/accio:brew`.
