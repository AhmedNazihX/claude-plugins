# claude-plugins

The `nazihx` marketplace: `foreman/` (the story workflow plugin) and `git-guardrails/` (its dependency).

- **Design and plan:** `docs/DESIGN.md` (foreman 0.11–0.13), `docs/BACKLOG.md` (the stories),
  `docs/decisions/` (decision records).
- **Layout:** `docs/LAYOUT.md` is the source of truth for where files go. In short: agents in
  `foreman/agents/<name>.md`, skills in `foreman/skills/<name>/SKILL.md`, hooks in `foreman/hooks/<name>.sh` with a
  `test-<name>.sh` next to each, stdlib Python scripts in `foreman/scripts/` with tests in `foreman/tests/`.
- **Checks:** listed once, in `.claude/foreman.json` › `checks`. Don't copy them elsewhere.
- **Versions:** only release stories change `foreman/.claude-plugin/plugin.json`'s version and the README version
  line; other changes add a line under `## Unreleased` in `foreman/CHANGELOG.md`.
- **The installed plugin** comes from a separate release copy (backlog story H1), not this working tree: a merge
  here reaches sessions only after a release and a `git pull` there.
- **Writing:** plain English, short sentences, no jargon, matching the existing skills.

## Story workflow (parallel agents, `foreman` plugin)
- **Design:** `docs/DESIGN.md`. **Backlog:** `docs/BACKLOG.md`. **Layout:** `docs/LAYOUT.md`; every new file fits it.
  **Decisions:** `docs/decisions/`. Settings: `.claude/foreman.json`; its `checks` is the only list of the
  lint, type and test commands ("the global checks"): change them there.
- **Commands:** `/foreman:next` picks the right step. `/foreman:status` shows what's ready;
  `/foreman:story-start <IDs>` launches one `foreman:story-worker` per story, each in its own worktree;
  `/foreman:story-finish <ID>` has `foreman:dod-verifier` and the reviewers check the work, runs fix
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
- **Guards** (plugin hooks, configured in `.claude/foreman.json`): `gates` (no writes under a path until a file
  is committed), `lanes`/`stories` (a lane's `deny` folders are blocked on its story branches, and its worktree
  leaves them out), `format` (edited files are formatted with the project's formatter). File-tool checks are exact;
  shell-command checks are best effort. Project rules and their enforcement are listed under `guardrails`.
- **Shared files in this repo:** `foreman/CHANGELOG.md` takes one line per story under `## Unreleased` (merged with
  `merge=union`); the `Resource:` tags in the backlog name the other shared files (story-finish, story-worker,
  workers.py, backlog.py, hooks.json, the reviewers, the config template).
