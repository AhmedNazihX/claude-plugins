# Changelog

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
