---
name: story-finish
description: Finishes a backlog story — verifies its Definition of Done and reviews the diff (plus any lane-specific reviewers) in parallel, runs fix rounds with the worker until the reviews are clean, then, with the user's go-ahead, merges the story branch into the base branch, runs the checks, ticks the backlog with an outcome note, hands follow-ups over to the stories they affect, and removes the worktree. Use when a story-worker reports DONE (start the reviews without asking), or when the user says to finish, review, verify or merge a story ("/story-finish C1").
argument-hint: "<ID> [ID ...]"
---

# Finish stories: $ARGUMENTS

You are the orchestrator, in the main checkout, on the base branch. Settings: `.claude/foreman.json`
(`base_branch`, `checks`, `reviewers`, `lanes.<lane>.reviewers`). Handle each ID in turn. Run the review agents in
parallel. The user is asked only at the merge, and for decisions that are theirs.

Run every git command from the main checkout. For checks inside a worktree, use `git -C <worktree>` and
`uv run --directory <worktree>` (or the project's equivalent); never `cd` into it, or the next command runs there.

## 1. Locate the story

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py info <ID>
git branch --list 'story/<ID>-*'                # exactly one branch expected
git worktree list                               # that branch's worktree path, if it still exists
git log --oneline <base>..story/<ID>-<slug>     # at least one commit
git status --porcelain                          # in the worktree: uncommitted work means the worker isn't done
git merge-base --is-ancestor <base> story/<ID>-<slug> || echo "base has moved on"
git merge-tree --write-tree <base> story/<ID>-<slug> >/dev/null && echo "merges cleanly"
```

If there's no branch or no commits, stop and report. If `merge-tree` reports conflicts, ask the worker (SendMessage,
or `story-start --continue <ID>` when its agent id no longer answers) to run `git merge <base>` in its worktree, resolve the conflicts, rerun `checks` and
commit; then review the new diff. Never rebase a story branch.
If the diff touches `.claude/foreman.json`, `.claude/settings*.json` or `.claude/hooks/`, say so to the user
before the merge: `checks` and `format` are commands the hooks and agents run. If the worker's commit was blocked, give the user the exact
commands as one `!` line (see `story-start` › Tell the user). If the base branch has moved on, say so: the merge will
be a real merge, which is fine unless files conflict.

## 2. Review: launch these in one message, without asking

- **`foreman:dod-verifier`**: "Verify story `<ID>` at worktree `<path>` (branch `story/<ID>-<slug>`). User approvals so
  far: <each approval the user gave for this story, with its date, or 'none'>. Known failures that aren't this
  story's: <if any, with why>."
- Every agent in `reviewers`: "Review the diff `<base>...story/<ID>-<slug>`." Run it in the worktree, if one exists.
- Every agent in `lanes.<lane>.reviewers` for this story's lane: "Audit branch `story/<ID>-<slug>`."
- **`foreman:test-auditor`**, when the DoD rests on tests: "Audit whether the tests of story `<ID>` (worktree
  `<path>`) prove its DoD." Run it again after a fix round that changed tests or the code they cover.

Relay each result as it arrives, in a few lines: the verdict, then the critical and major findings.

## 3. Fix rounds

When any review is back with a FAIL, a critical or major finding, or minor findings worth fixing:
- Wait for all the reviews of this round, then send **one** message to the worker with every finding: file and
  line, the failure, and the fix direction. Include the user's decisions on the worker's questions, and anything a
  later story now needs. Find the worker with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workers.py show <ID>` and
  SendMessage to its `agent_id` (this only works in the session that launched it). If that fails ("No
  transcript found", after a `/clear` or in a new session), follow `story-start` › Continue (`--continue <ID>`)
  with the findings as the task. Mark the round with
  `workers.py set <ID> fix-round`, and `set <ID> reported` when the worker reports back.
- Decisions that belong to the user (a trade-off, a label, a wording, a paid run) go to the user first, **one
  question at a time**, with your recommendation and why. Legal or domain decisions quote the source verbatim
  with its page and heading.
- When the fixes come back: read the fix diff and rerun the relevant tests yourself. If a finding was major or the
  fix is large, run the diff reviewer again on the fix commits only (`<previous head>..<new head>`), and ask it to
  look for regressions the fixes introduced. When a fix answers a security finding, also run
  `foreman:security-reviewer` on the fix commits, and ask it to confirm the finding is fixed and to look for
  regressions.
- Severity labels (the security reviewer's) map onto this: CRITICAL and HIGH are major and are fixed before the
  merge; MEDIUM is fixed, or deferred with the user's agreement; LOW is minor.
- Repeat until the DoD is DONE and no critical or major finding is open. Minor findings the user agrees to defer
  go to the backlog in step 5.

## 4. Merge with the user's go-ahead

Summarise in a small table: the DoD verdict, the reviews (findings per round, and "fixed"), the lane reviews. Name
anything that will fail after the merge but isn't this story's. Then ask the user to confirm the merge. Merge from
the main checkout, on the base branch (`git -C <main checkout> status` shows where you are).

```bash
git merge --no-ff story/<ID>-<slug> -m "merge: story <ID> <title>"
```

If the story added `docs/decisions/NNN-<slug>.md`, rename it to the next free number (and fix references to it)
before running the checks.

Then run every command in `checks` on the base branch. **Only if they all pass** (or the only failures are ones
already known and not this story's, which you name), tick the story (the commit comes with the hand-over notes in step 5):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py tick <ID> "<one-line outcome, from the worker's report>"
```

If the checks fail after the merge, don't tick. Tell the user what failed. The merge is local and not pushed, so the
user decides whether to fix forward or undo it (`git reset --merge ORIG_HEAD` while it is the last commit and
unpushed, else `git revert -m 1 <merge>`; `reset --hard` is blocked by the guards). For a sub-story of a grouped entry, `tick` only adds a note. Tick the
group once every sub-story is merged.

## 5. Hand over

Before committing the tick, put every follow-up where the next worker will read it: a short note on each story it
affects (the dependent stories, the stories a reviewer said to "watch", the stories the user's decisions change),
with `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py note <target> --from <ID> "<text>"` (it writes the line
`**From <ID> (merged):** …` and refuses to break the backlog). New dependencies go in with `set-deps <target>
"<deps>"`, new stories with `add --after <ID>` (the entry on stdin). Include: the contracts and names this story created
that others must use, deferred minor findings, the user's decisions, and new risks. Run
`python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py check` and commit the tick and the notes together:
`docs(backlog): tick <ID>; hand over to <IDs>`.

A decision that changes the plan gets a record (the `decision` skill), not just a note. A decision or review
finding that adds or changes a **rule** ("always", "never", "only", "before") goes through the `guardrails` skill
for that rule, so its mechanism and test change with it.

## 6. Clean up and point to what's next

```bash
git worktree remove <path>
git branch -d story/<ID>-<slug>       # lowercase -d refuses to delete an unmerged branch
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/workers.py forget <ID>
```

Worktrees branch from the local HEAD, so dependent stories can start without a push. Offer to push the base branch;
after a push, watch the CI run (`gh run watch <id> --exit-status`) and report its result per job. Then run
`backlog.py status` and name the stories this merge has just unblocked.
