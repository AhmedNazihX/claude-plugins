## Story workflow (parallel agents, `story-workflow` plugin)
- **Design:** `docs/DESIGN.md`. **Backlog:** `docs/BACKLOG.md`. **Layout:** `docs/LAYOUT.md`; every new file fits it.
  **Decisions:** `docs/decisions/`. Settings: `.claude/story-workflow.json`; its `checks` is the only list of the
  lint, type and test commands ("the global checks"): change them there.
- **Commands:** `/story-workflow:next` picks the right step. `/story-workflow:status` shows what's ready;
  `/story-workflow:story-start <IDs>` launches one `story-workflow:story-worker` per story, each in its own worktree;
  `/story-workflow:story-finish <ID>` has `story-workflow:dod-verifier` and the reviewers check the work, runs fix
  rounds, and merges only after the user confirms.
- **Worktrees:** `.claude/worktrees/` (gitignored). They branch from the local HEAD (`worktree.baseRef: head`). Each
  worker renames its branch to `story/<ID>-<slug>`.
- **Starting a story:** only after all its deps are merged into the base branch. `Solo` stories run with nothing else
  in flight. Stories sharing a `Resource:` never run at the same time.
- **The orchestrator owns the backlog.** Only the main session ticks `docs/BACKLOG.md` and adds hand-over notes,
  after a merge. Workers report their outcome in their final message.
- **Shared files:** keep edits to lockfiles, settings and env examples minimal and additive. If a lockfile conflicts,
  regenerate it rather than merging it by hand.
- **Files the worktree doesn't have:** gitignored files like `.env` aren't in new worktrees. The worker symlinks the
  files listed in `link_files` and exports `env` from the config.
- **Guards** (plugin hooks, configured in `.claude/story-workflow.json`): `gates` (no writes under a path until a file
  is committed), `lanes`/`stories` (a lane's `deny` folders are blocked on its story branches, and its worktree
  leaves them out), `format` (edited files are formatted with the project's formatter). File-tool checks are exact;
  shell-command checks are best effort. Project rules and their enforcement are listed under `guardrails`.
