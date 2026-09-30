# story-workflow

A Claude Code plugin that takes a project from an idea to merged work:

```
kickoff ──► work-breakdown ──► backlog-reviewer ──► setup ──► status ──► story-start ──► story-finish
intent →      DESIGN.md →        critique            config     what's      one worktree     verify, review,
DESIGN.md     BACKLOG.md                                        ready       agent per story  merge, hand over
```

`/story-workflow:next` looks at the repo and runs the right step, so it is the only command you need to remember.

## What's in it

| Part | Items |
| --- | --- |
| Skills | `next`, `kickoff`, `work-breakdown`, `setup`, `guardrails`, `status`, `story-start`, `story-finish`, `decision`, `handover` |
| Agents | `story-worker` (one story, own worktree), `dod-verifier`, `diff-reviewer`, `security-reviewer`, `backlog-reviewer`, `lane-auditor`, `test-auditor` |
| Hooks | `gate.sh` (nothing under a path until a file is committed), `lane-guard.sh` (a lane never sees some folders), `format.sh` (formats edited files with the project's formatter, per folder), `worker-guard.sh` (a worker subagent never pushes, rebases, merges other branches or edits the backlog) |
| Script | `scripts/backlog.py`: check, plan, status, show, deps, info, tick, note, set-deps, add, graph (stdlib only) |

Each project keeps only its own facts: `docs/DESIGN.md`, `docs/BACKLOG.md`, `docs/decisions/`,
`.claude/story-workflow.json`, and any project-specific skills, agents and rules.

## Install

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins     # from GitHub
# or, from a local clone (for development): claude plugin marketplace add ./claude-plugins
claude plugin install story-workflow@nazihx     # also installs git-guardrails (a dependency)
```

Then, in a repo: `/story-workflow:next`.

## Tests

```bash
python3 -m unittest discover -s tests     # backlog.py
bash hooks/test-guards.sh                 # gate and lane-guard hooks
bash hooks/test-format.sh                 # formatter hook
claude plugin validate .
```

## Status

Draft 0.3.5. See `docs/story-workflow-merge-plan.md` (marketplace root) for what is ported, what is new and what is left.

## Credits

`kickoff`'s stress-test step adapts the design-tree method of the `grilling` skill from Matt Pocock's skills
collection (MIT, see `LICENSE-upstream`), asking one question at a time instead of a round.

This plugin is MIT-licensed (`LICENSE`).
