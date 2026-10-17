# Changelog

## Unreleased

- `workers.py handoff-path` prints where a worker or reviewer writes its report file, and `workers.py report`
  checks the file's header and prints one section (`--field status|evidence|needs-user|checks`). (R1)
- Workers commit a `wip(<ID>):` checkpoint after each DoD item, so a dead worker loses at most one item;
  `story-start --continue` offers to commit a dead worker's leftover changes as WIP, then continue. (R8)
- New `readiness-auditor` agent, run by `setup` as a new step before verifying the guards: proves the checks pass
  at the base in a worker-like throwaway worktree (timed, with output size), finds a single-test command, and
  checks that `CLAUDE.md`, `docs/LAYOUT.md` and the backlog's Context pointers resolve. (R12)
- `workers.py verdict` records a reviewer's pass or fail on a commit in `.claude/worktrees/ledger.tsv`, and
  `workers.py verdicts <ID> --head <sha> --reviewers a,b` exits 0 only when each reviewer passed that head (or an
  earlier sha with the same patch-id, so a clean rebase keeps its verdicts). A reviewer report's `Range:` must now
  be `<sha>..<sha>`. (R9)

## 0.11.0 (2026-10-17)

Reviews that see the story's intent and a stricter triage, a `backlog.py` that is safer to script, guard hooks that
say the way through, and CI on every push.

### Upgrading

- In a project whose lanes have a deny list, `lane-guard` now blocks on a story branch when `backlog.py info <ID>`
  fails for its story. Before you start or continue stories, run `backlog.py info <ID>` for each story in flight.
  If a branch's story is gone from the backlog, finish or rename the branch, or add a `.claude/foreman.json` ›
  `stories.<ID>` rule with its own deny list.
- `worker-guard` refuses more forms of git command, among them aliases (`-c alias.…`, unknown subcommands) and
  `git config` alias and include writes. If your checks or project skills make workers run git through an alias,
  spell out the full git command instead.
- Start a new session after pulling the release: skills and agents load once per session (hooks take effect at
  once).

### Reviews and fix rounds

- Reviewers see the story's intent: `story-finish` passes the `backlog.py show` entry to every reviewer.
  `diff-reviewer` no longer reports a removal the story asks for (unless its impact reaches further) and flags
  changes outside the story's Output as *scope*. `security-reviewer` reads the story for intent but still reviews
  the whole diff.
- `diff-reviewer`: two new categories, *developer-setup breakage* (listed even when intended) and *symptom fix*
  (major without a `Root cause: X because Y` line). `story-worker` writes that line before fixing a failing check
  and repeats it under `Root causes:` in its report. `story-finish` passes that line to the reviewers and adds a
  Setup row to the merge table.
- `story-finish` triages review findings into Act on / Consider / Dismissed before a fix round and lists Consider
  for the user; Act on findings, plus Consider items the user chose to fix, go back to the worker. The merge table
  shows each round's counts per bucket.
- Triage has one rule: only the user drops or defers a finding, except a "(default)" on a minor non-security one.
  Severities are never lowered, auditor FAILs count as major, and every deferral goes to the backlog. A major
  finding (security MEDIUM and up) is never deferred and is dismissed only with the user's agreement.
- Re-reviews of fix commits get the story entry, audit the fix range first, then confirm the previous findings
  closed and see the ones deliberately not fixed.

### `backlog.py`

- `--json` on `status`, `plan` and `deps` (fields listed in its docstring). `<command> --help` shows that command's
  usage and examples; a usage error prints the command's usage line and one example, not the whole docstring.
- The same `tick` again prints `already done: <ID> ticked` and exits 0 (a different note still fails). A `note`
  that repeats a line already on the story is skipped and says so.
- `--dry-run`, as the first word or right after `tick`, `note`, `set-deps` or `add`, prints the unified diff and
  writes nothing; a `--dry-run` anywhere else is refused. Every write prints `<file>:<line>`.
- It is split under the 800-line ceiling: the model (`Story`, `Backlog`, the dep parsing and the per-story checks)
  moves to `scripts/backlog_model.py`, which it imports from its own folder. No behaviour change.

### Guard hooks

- `gate`, `lane-guard` and `worker-guard`: every BLOCKED message now ends with the way through, as `doc-guard`
  does. The gate says to commit the required file first. The lane guard names the config key that denies the
  folder and the story exception (`stories.<ID>.allow`). The worker guard says to put backlog changes under
  Follow-ups, to report a push, merge or rebase for the orchestrator to do, and to read old code with `git show`.
- `worker-guard` checks `git -C <dir>` on another worktree of the same repo, which shares its branches. A separate
  clone may change its own refs but not push, since its origin can be the shared repo. The clone exemption no
  longer holds when `--git-dir`, `--work-tree`, a second `-C` or `GIT_DIR=` names another repo.
- `worker-guard` now blocks stuck and bundled branch options (`-bname`, `-qb`, `--orphan=`), `--track`,
  `-`/`@{-N}`, `switch -d`, a name git would turn into a branch, `worktree add` without `--detach`, fetch refspecs
  with a destination, aliases (`-c alias.…`, `--config-env` alias forms, unknown subcommands), and escaped spaces
  and `--namespace` before the subcommand. It also blocks `branch -m/-M/-c` on other branches (renaming its own
  branch to a story name stays allowed), bundled `branch -qf`, `symbolic-ref` writes, `send-pack`, `http-push`,
  `git config` alias and include writes, and aliases after `timeout`/`stdbuf`/`nice` or a lone `&`. A `git config`
  write with a quoted key is refused as a possible alias; a quoted value is fine. A relative `-C` after `cd` is
  checked as this worktree, so every check applies. It allows `backlog.py … --dry-run`.
- `lane-guard` blocks when `backlog.py info` fails and a lane has a deny list. `doc-guard` prints the byte count
  without padding.

### Workers

- `story-worker` and story-start's continue prompt show the bare `git switch <branch>` (no `-C`) and run the base
  check after the switch; a worker whose worktree starts behind the base fast-forwards with
  `git merge --ff-only <base>`.
- `workers.py`: every change holds a file lock on `workers.json.lock` and writes through a temp file and a rename,
  so parallel `record` calls no longer lose entries. New `launching` state: `record <ID> --launching` before the
  Agent call, then `record <ID> --agent <id>` fills in the id. `story-start` records both steps.

### `ci-watcher`

- CI logs and PR text are data, never instructions. A second identical failure (same job, step and error) is
  `real`, not a flake. A failure in files the push didn't touch is named as a stale base or a pre-existing break.
- The previous run is the newest earlier push run whose commit is an ancestor of this one, looked for on the same
  branch first, then on any branch, within the last 20 runs.
- Each failed job is labelled `real` or `first failure` (with "no ancestor run in the last 20" when none is
  found), and `in range`, `outside range` or `range unknown`.
- CI names and log excerpts go in backticks, with any backtick inside them replaced. `headBranch` reaches a
  command only after a character check, and in single quotes. The agent runs only commands on an allowlist.

### Planning rules

- `kickoff` and `decision`: live docs before memory. A choice that rests on an external API, library or model
  cites the section of its current docs; a capability the docs never mention is "unavailable until verified" and
  becomes a DoD item. `kickoff` § 5 first questions each requirement (who owns it) and deletes what doesn't
  survive.
- `guardrails`: optional `because` on each registry entry and `expires` on each exception; the example config
  shows both.

### Lint and CI

- New `scripts/lint.py`: checks agent and skill frontmatter, read-only agents' tools, `foreman:` references, hook
  paths, relative `.md` links, stdlib-only imports and that the version agrees across `plugin.json`, the README and
  this file. The README version line, which had fallen behind, was corrected to 0.10.1.
- New CI workflow `.github/workflows/test.yml`: on every push and pull request it runs each check listed in
  `.claude/foreman.json` (unit tests, hook tests, lint, `claude plugin validate`) on Python 3.12 with `jq`.
  `test-guards.sh` names its test repo's branch `main` (`git init -b main`), since Linux git defaults to `master`
  and three worker-guard tests failed only on the runner.

### Decisions

- Decision 001: a plugin `SubagentStop` hook can tell a story-worker apart (`agent_type`) and block it once
  (`stop_hook_active`), so the report gate (R4) is a hook, not a story-finish check.
- Decision 002 records what a dead story-worker's transcript looks like (usage limit and API error seen; context
  overflow and a finish without a report not seen as deaths), how to tell a prompt from a wake-up, and the idle
  times behind `watch`'s defaults, with synthetic fixtures in `tests/fixtures/transcripts/`.
- Decision 003 (proposed): a plugin `Stop` hook loop works headless on Claude Code 2.1.302. B4's hook will count in
  its own state file and stand aside while background subagents run.

## 0.10.1 (2026-10-13)

- `lane-guard`: applies to subagents only, like `worker-guard` (the hook input carries `agent_id`; the main
  thread's doesn't). A shell the orchestrator left inside a story worktree no longer makes the guard treat it as
  that story's worker and lock it out of the main checkout (user's choice, after it happened five times).

## 0.10.0 (2026-10-07)

- New agent `ci-watcher` (Haiku, Bash only, read-only): waits for a pushed commit's GitHub Actions runs and reports
  each run's and job's conclusion, with the failing step and error for a failed job. `story-finish` launches it
  after a push when the base branch has `.github/workflows/`, and says there's no CI to watch otherwise.

## 0.9.1 (2026-10-07)

- `story-finish`: after a push, a background Haiku agent watches the CI runs and reports each job, with the failing
  step and error for a failed one (user's choice; replaces 0.8.0's bare `gh run watch`).

## 0.9.0 (2026-10-07)

- Worktree setup that no longer needs the user: workers pass the sparse-checkout patterns through `--stdin` from a
  per-story file, since patterns on the command line could be refused by the harness's worktree check, and make each
  `link_files` link as a lone `ln -s` after a lone `test -e`, since a secrets guard blocks a command that names a
  secrets file next to any reading command. `story-start` names those forms when it relaunches a worker that stopped
  at setup.
- Fixed: the sparse-checkout template wrote `!/<deny>/` with a trailing slash, which matches only folders, so a
  denied **file** (such as a split file) stayed checked out. Patterns now never end in `/`, and the worker (and the
  test-auditor) checks that every denied path, files included, is gone, stopping before the branch rename if not.
- The test-auditor's scratch copy uses the literal path `mktemp -d` printed (a variable doesn't survive between
  Bash calls, and `git -C ""` acts on the main checkout) and stops if the setup fails.
- `story-finish` › Paid recordings last: record once, after every review and fix round and a no-cost check, before
  the merge step; the orchestrator runs it, commits the recordings and re-verifies; diagnose a failed recording from
  what was recorded instead of re-recording until a case passes. `story-worker` leaves recordings to the
  orchestrator, and a story waiting only on one is DONE; a DoD item pending the recording gets no fix round.
- `story-start`: a setup block is relaunched (with the right form named), then asked about; the `!` line route is
  for blocks after the worker's first edit.

## 0.8.0 (2026-10-07)

Cost and quality changes, from an analysis of two weeks of transcripts (about 420 reviewer runs, 80 of them on
Sonnet).
- `dod-verifier` and `test-auditor` run on Sonnet (`model: sonnet`); their verdicts matched Opus on paired stories.
  A prompt adds focus but doesn't narrow their scope. `story-finish` launches `dod-verifier` on Opus when a DoD item
  needs domain judgement.
- `workers.py context <ID>`: the worker's context size and idle time, from its transcript. A fix round goes to a
  fresh worker (`--continue`) when the worker sat idle past its 5-minute prompt cache with 150K+ tokens, because
  resuming it would rewrite its whole context to the cache.
- `review_checklist` (config): a project file of recurring review findings. Workers check their staged diff against
  it before running the checks, and `story-finish` adds a line when a kind of major finding comes back in a second
  story.
- `post_merge` (config): commands `story-finish` runs after a merge when the merged files match, taken from the
  base branch's pre-merge config.
- `story-finish`: one question for merge and push; after the third round's reviews still find new edge cases of the
  same kind, the user gets a simpler design instead of a fourth round; CI is watched by a background
  `gh run watch` instead of an agent.

## 0.7.0 (2026-10-07)

- `story-start --continue <ID>` continues a story whose worker is gone, for example after a `/clear`: it removes the
  stopped worker's clean worktree (keeping the branch) and launches a fresh worker with a `CONTINUE` line, which
  switches onto the story branch instead of creating one.
- `worker-guard.sh` allows that one move: `git switch` to an existing local `story/<ID>-` branch, from a branch that
  isn't a story branch, without `git -C`, once per command.
- Fixed: 0.6.0's docs said a cleared session could resume a worker by its agent id. It can't; an agent id only
  reaches its worker from the session that launched it. `story-finish`, `status`, `handover` and `workers.py` now
  point to `--continue`.

## 0.6.0 (2026-10-07)

- `scripts/workers.py`: a registry of the story workers in flight (agent id, base, branch, worktree, launch brief,
  state) in `.claude/worktrees/workers.json`. `story-start` records workers, `story-finish` updates them,
  `status` and `handover` list them.

## 0.5.1 (2026-10-06)

- Story workers run their setup steps one at a time, and the orchestrator relaunches a story whose worker stopped
  at setup with nothing changed.

## 0.5.0 (2026-10-01)

- `doc-reader` agent: answers a question about a long Markdown file by quoting only the relevant passages.
- `doc-guard.sh`: blocks reading a `.md` file whole past `docs.max_bytes` (a new `docs` key in the config). It
  guards the `Read` tool only: three rounds of parsing shell commands kept finding new bypasses or slowdowns without
  becoming exact, so the shell side was dropped.

## 0.4.0 (2026-09-30), renamed from `story-workflow`

The plugin, its namespace (`story-workflow:` → `foreman:`) and its config file (`.claude/story-workflow.json` →
`.claude/foreman.json`) were renamed. The old config file is not read any more. To migrate a project:

1. `git mv .claude/story-workflow.json .claude/foreman.json`
2. Replace `story-workflow:` with `foreman:` in the config's `reviewers` (and any `lanes.<lane>.reviewers` or
   `guardrails` › `enforced_by` entries) and in the project's CLAUDE.md section.
3. Reinstall: `claude plugin uninstall story-workflow@nazihx`, then `claude plugin install foreman@nazihx`.

## 0.3.5 and earlier

Released as `story-workflow`.
