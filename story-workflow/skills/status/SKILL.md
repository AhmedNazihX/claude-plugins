---
name: status
description: Shows the backlog status — which stories are done, in progress (a story/<ID>-* branch exists), ready (all deps done) or blocked, where the critical path stands and what the next wave is — plus unpushed commits and the latest CI run, then recommends what to launch. Use when the user asks for status, progress, what's next, what can run in parallel, or which stories are ready.
argument-hint: "[lane or story ID to focus on]"
---

# Backlog status

Settings: `.claude/story-workflow.json` (`base_branch`, `max_review_stories`, default 2).

1. From the repo root, run:
   ```bash
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py status
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/backlog.py plan
   git worktree list
   git log --oneline origin/<base>..<base>        # unpushed commits
   gh run list --branch <base> --limit 1          # the latest CI run (skip if gh or a remote is missing)
   ```
2. Check that each story you might recommend can actually **finish**. `status` marks a story
   *ready to build, not to finish* when its Input or DoD names another open story, or a file another open story's
   Output creates, that isn't among its Deps. Also read `backlog.py show <ID>` for inputs the parser can't see
   (a decision, an approval, an account). Name the missing input and the story that makes it, and offer to add
   that dep to the backlog.
3. Present it compactly:
   - One line with the totals and the next story on the critical path. If `status` says that story is waiting on
     something, say so: that is the real next step.
   - **Repo:** unpushed commits and the latest CI result, only when there is something to say.
   - **Rules:** any entry in the config's `guardrails` with an empty `enforced_by` and no `note`, and any decision
     record newer than the registry that states a rule. Offer the `guardrails` skill for them.
   - **In progress:** each story with its worktree path, if it has one.
   - **Ready:** a table with ID, title, type and lane. Mark `human` and `mixed` stories (they need the user's
     time), stories with a `<resource>?` hint (they may change a shared resource: read the story to confirm), and
     stories that can't finish yet. Show any "check" notes as conditions to confirm, not as ready work.
   - **Blocked:** summarise it, naming only the stories one step away from ready.
4. Recommend a launch set, based on the first wave from `plan`:
   - Put the critical path first (or what it waits on), then stories that unblock many others, then long `human`
     stories that should start early.
   - `plan` already respects `Solo` and `Resource:` tags; also keep hinted resources to one story each.
   - Put at most `max_review_stories` `mixed` or `human` stories in one set unless the user asks for more, and say
     which one reaches the user first.
   - Leave out stories that can't finish yet, unless the user wants them built early.
   - End with the exact command, for example `/story-workflow:story-start F2 F3 F4`.
5. If `$ARGUMENTS` names a lane or a story, focus on it. For a story, also show `backlog.py show <ID>` and
   `backlog.py deps <ID>`.

This skill is read-only. It never changes files or branches.
