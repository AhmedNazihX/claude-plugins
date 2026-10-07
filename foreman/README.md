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
| Agents | `story-worker` (one story, own worktree), `dod-verifier`, `diff-reviewer`, `security-reviewer`, `backlog-reviewer`, `lane-auditor`, `test-auditor`, `doc-reader` (looks up a fact in a long `.md` file instead of loading it whole) |
| Hooks | `gate.sh` (nothing under a path until a file is committed), `lane-guard.sh` (a lane never sees some folders), `format.sh` (formats edited files with the project's formatter, per folder), `worker-guard.sh` (a worker subagent never pushes, rebases, merges other branches or edits the backlog), `doc-guard.sh` (a long `.md` file is never `Read` whole) |
| Scripts | `scripts/backlog.py`: check, plan, status, show, deps, info, tick, note, set-deps, add, graph; `scripts/workers.py`: a registry of the story workers in flight (agent id, base, worktree, brief, state) in `.claude/worktrees/workers.json`, so a cleared session can find them and continue their stories with `story-start --continue` (stdlib only) |

## Long documents stay out of context

A backlog, a design document or a decision log grows over a project's life — a backlog alone can pass 150 KB
(about 38k tokens), which is real context budget spent before any work starts. Two things keep that out of an
agent's context:

- **`doc-reader`** (an agent, read-only, no Bash, so only the main session can launch it): answer a question about
  a long `.md` document by searching it (Grep) and quoting only the relevant passages with `file:line`, instead of
  reading the whole thing. Subagents can't start it, so they search with `rg` and `Read` a line range themselves.
- **`doc-guard.sh`** (a hook): once `.claude/foreman.json` has a `docs` key (`{"max_bytes": 20000, "exclude": []}`,
  written by `setup`), it blocks `Read`ing a `.md` file whole past `max_bytes`, in the main session or a subagent
  alike; a ranged `Read` (`offset`/`limit`) under the limit is fine. It guards the `Read` tool only — it does not
  look at `Bash` at all, so a shell command that cats or greps a file isn't checked. Parsing shell commands for
  this (quoting, redirects, pipes, `cd`, subshells, …) kept finding a new bypass or a new performance cliff without
  ever becoming exact, for a part of the guard that was never the main point: `doc-reader` and the project's own
  rule against reading a long file whole are what cover a shell-based lookup instead.

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
python3 -m unittest discover -s tests     # backlog.py, workers.py
bash hooks/test-guards.sh                 # gate and lane-guard hooks
bash hooks/test-format.sh                 # formatter hook
bash hooks/test-doc-guard.sh              # doc guard hook
claude plugin validate .
```

## Status

Draft 0.5.0. See `docs/foreman-merge-plan.md` (marketplace root) for what is ported, what is new and what is left.

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
