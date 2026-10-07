# foreman

A Claude Code plugin that takes a project from an idea to merged, reviewed work. Agents build stories in parallel,
each in its own git worktree; every story is verified and reviewed before anything is merged, and you stay in charge
of the decisions, the spending and the merges.

```
kickoff ──► work-breakdown ──► backlog-reviewer ──► setup ──► status ──► story-start ──► story-finish ──► handover
intent →      DESIGN.md →        critique            config     what's      one worktree     verify, review,   safe to
DESIGN.md     BACKLOG.md                                        ready       agent per story  fix, merge        clear
```

`/foreman:next` looks at the repo and runs the right step, so it is the only command you need to remember.

## Quick start

Needs `git`, `jq` (the hooks) and `python3` (the scripts, standard library only).

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins
claude plugin install foreman@nazihx     # also installs git-guardrails, which foreman depends on
```

Then, in a repo: `/foreman:next`.

## How a project runs

**Planning.** `kickoff` interviews you, one question at a time, and writes `docs/DESIGN.md` for you to approve.
`work-breakdown` turns it into `docs/BACKLOG.md`: atomic stories, each with its deps, inputs, outputs and a
Definition of Done (DoD) that can be checked. `backlog-reviewer` critiques the backlog in a fresh context. `setup`
writes `.claude/foreman.json` (the project's checks, reviewers, lanes, gates and cost cap), and `guardrails` turns
the design's rules into hooks, tests or reviewer agents.

**Stories.** `status` shows what is done, in progress, ready and blocked, and suggests the next wave. `story-start`
launches one `story-worker` per story, each on a `story/<ID>-<slug>` branch in its own worktree, after checking deps,
shared resources (two stories that change the same database schema never run together) and solo stories.

## What a story goes through

When a worker reports DONE, `story-finish` runs the review panel in parallel, in fresh contexts:

| Reviewer | Checks |
| --- | --- |
| `dod-verifier` | every Output and DoD item against the repo, and the project's checks |
| `diff-reviewer` | dead code, duplication, over-engineering, silent behaviour changes |
| `security-reviewer` | the diff against the project's own threat model |
| `test-auditor` | that the tests prove the DoD: it breaks the code on purpose in a scratch copy and confirms a test fails |
| lane reviewers | per-lane rules from the config, e.g. `lane-auditor` for folders a lane must never read |

`dod-verifier` and `test-auditor` run on Sonnet; the others, and the workers, on the session's model.

Findings go back to the worker as **one** fix round; a major finding gets its fix re-reviewed for regressions, and
the loop repeats until the DoD is met and nothing major is open. A worker that has sat idle with a large context is
replaced by a fresh one for the fix round (`workers.py context` decides), and a third round that still opens new
edge cases goes to you with a simpler design. Workers check their diff against the project's `review_checklist`
before DONE, and the list grows when the same kind of major finding comes back in a second story. Paid recordings
(responses the tests replay) are made once, by the orchestrator, after every review round, so a fix never makes
them stale. Then you're asked to merge (and whether to push). After the merge, the config's `post_merge` steps
regenerate what the merge left stale, the checks run on the base branch, the story is ticked, and every follow-up
is written as a note on the backlog story it affects, so the next worker reads it. After a push, a Haiku agent
watches CI and reports each job.

## What stays with you

- Approving the design, and every decision a review raises that is yours: a trade-off, a label, a wording. They
  come one question at a time, each with a recommendation.
- Anything that costs money: a worker spends up to the config's `cost_cap_usd` without asking; above it, or for a
  full run, it stops and reports the estimate and the exact command for you to approve.
- Every merge and every push.

## Sessions: clear whenever you like

The conversation is not where the work lives. Before a `/clear`, `handover` moves open follow-ups and your decisions
onto the backlog stories they affect and checks that nothing is running. `scripts/workers.py` keeps a registry of
the workers in flight (`.claude/worktrees/workers.json`).

An agent can only be messaged from the session that launched it. To pick up a story in a new session, run
`/foreman:story-start --continue <ID>`: the stopped worker's clean worktree is removed (the branch stays), and a
fresh worker switches onto the story branch and carries on from its head.

Long documents stay out of context too: `doc-reader` answers a question about a long `.md` file by quoting only the
relevant passages, and `doc-guard.sh` blocks reading one whole past the config's `docs.max_bytes`.

## What's in it

| Part | Items |
| --- | --- |
| Skills | `next`, `kickoff`, `work-breakdown`, `setup`, `guardrails`, `status`, `story-start` (with `--continue`), `story-finish`, `decision`, `handover` |
| Agents | `story-worker`, `dod-verifier`, `diff-reviewer`, `security-reviewer`, `test-auditor`, `lane-auditor`, `backlog-reviewer`, `doc-reader` |
| Hooks | `gate.sh` (nothing under a path until a given file is committed), `lane-guard.sh` (a lane never sees its denied folders), `worker-guard.sh` (a worker never pushes, rebases, merges another branch, moves to another branch or edits the backlog; its one allowed move is `git switch` onto a story branch when continuing), `format.sh` (formats edited files with the project's formatter), `doc-guard.sh` (no whole `Read` of a long `.md` file) |
| Scripts | `backlog.py` (check, plan, status, show, deps, info, tick, note, set-deps, add, graph), `workers.py` (record, set, list, show, forget, context) |

Each project keeps only its own facts: `docs/DESIGN.md`, `docs/BACKLOG.md`, `docs/decisions/`,
`.claude/foreman.json`, and any project-specific skills, agents and rules.

## Known limits

- Claude Code loads skills and agent definitions once per session. After updating the plugin, start a new session
  before relying on new skill or agent behaviour (hooks take effect at once).
- `doc-guard.sh` guards the `Read` tool only; a shell command that prints a file isn't checked.
- In a lane with denied folders, the worker passes the sparse-checkout patterns through `--stdin` from a
  per-story file: Claude Code's worktree isolation check could refuse patterns on the command line. Each
  `link_files` link runs as a lone command, since the secrets guard refuses a command that names a secrets file
  next to any reading command.
- Hook checks of shell commands are best effort; file-tool checks are exact.

## Tests

```bash
python3 -m unittest discover -s tests     # backlog.py, workers.py
bash hooks/test-guards.sh                 # gate, lane-guard and worker-guard hooks
bash hooks/test-format.sh                 # formatter hook
bash hooks/test-doc-guard.sh              # doc guard hook
claude plugin validate .
```

## Version

0.9.1. See [CHANGELOG.md](CHANGELOG.md), which also has the migration steps for projects that used the plugin under
its old name, `story-workflow`.

## Credits

`kickoff`'s stress-test step adapts the design-tree method of the `grilling` skill from Matt Pocock's skills
collection (MIT, see `LICENSE-upstream`), asking one question at a time instead of a round.

This plugin is MIT-licensed (`LICENSE`).
