# foreman

A Claude Code plugin that takes a project from an idea to merged work:

```
kickoff ──► work-breakdown ──► backlog-reviewer ──► setup ──► status ──► story-start ──► story-finish
intent →      DESIGN.md →        critique            config     what's      one worktree     verify, review,
DESIGN.md     BACKLOG.md                                        ready       agent per story  merge, hand over
```

`/foreman:next` looks at the repo and runs the right step, so it is the only command you need to remember.

## What's in it

| Part | Items |
| --- | --- |
| Skills | `next`, `kickoff`, `work-breakdown`, `setup`, `guardrails`, `status`, `story-start`, `story-finish`, `decision`, `handover` |
| Agents | `story-worker` (one story, own worktree), `dod-verifier`, `diff-reviewer`, `security-reviewer`, `backlog-reviewer`, `lane-auditor`, `test-auditor` |
| Hooks | `gate.sh` (nothing under a path until a file is committed), `lane-guard.sh` (a lane never sees some folders), `format.sh` (formats edited files with the project's formatter, per folder), `worker-guard.sh` (a worker subagent never pushes, rebases, merges other branches or edits the backlog) |
| Script | `scripts/backlog.py`: check, plan, status, show, deps, info, tick, note, set-deps, add, graph (stdlib only) |

Each project keeps only its own facts: `docs/DESIGN.md`, `docs/BACKLOG.md`, `docs/decisions/`,
`.claude/foreman.json`, and any project-specific skills, agents and rules.

## Install

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins     # from GitHub
# or, from a local clone (for development): claude plugin marketplace add ./claude-plugins
claude plugin install foreman@nazihx     # also installs git-guardrails (a dependency)
```

Then, in a repo: `/foreman:next`.

## Tests

```bash
python3 -m unittest discover -s tests     # backlog.py
bash hooks/test-guards.sh                 # gate and lane-guard hooks
bash hooks/test-format.sh                 # formatter hook
claude plugin validate .
```

## Status

Draft 0.4.0. See `docs/foreman-merge-plan.md` (marketplace root) for what is ported, what is new and what is left.

## Renamed from story-workflow (0.4.0)

This plugin was released as `story-workflow` up to 0.3.5. In 0.4.0 the plugin, its namespace (`story-workflow:` →
`foreman:`) and its config file (`.claude/story-workflow.json` → `.claude/foreman.json`) were renamed. The old
config file is not read any more, so an existing project needs these steps:

1. `git mv .claude/story-workflow.json .claude/foreman.json`
2. Replace `story-workflow:` with `foreman:` in the config's `reviewers` (and any `lanes.<lane>.reviewers` or
   `guardrails` › `enforced_by` entries) and in the project's CLAUDE.md section.
3. Reinstall: `claude plugin uninstall story-workflow@nazihx`, then `claude plugin install foreman@nazihx`.

## Credits

`kickoff`'s stress-test step adapts the design-tree method of the `grilling` skill from Matt Pocock's skills
collection (MIT, see `LICENSE-upstream`), asking one question at a time instead of a round.

This plugin is MIT-licensed (`LICENSE`).
