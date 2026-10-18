# claude-plugins

A Claude Code plugin marketplace (`nazihx`):

| Plugin | What it does |
| --- | --- |
| [`accio`](accio/README.md) | Plans, builds, reviews and safely merges your project's work in small iterations, asking you only at two checkpoints: when you plan, and when you review what it built |
| [`git-guardrails`](git-guardrails/README.md) | Blocks destructive git commands, asks before every push, keeps secrets out of the transcript and commits |

## Install

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins     # from GitHub
# or, from a local clone (for development): claude plugin marketplace add ./claude-plugins
claude plugin install accio@nazihx
claude plugin install git-guardrails@nazihx
```

Each plugin works on its own; they also work well together. accio guards only repos that use it (they have an
`.accio/` folder), and git-guardrails guards every repo.

**Needs:** `git` for both; `jq` for git-guardrails' hooks; Python 3.9 or later and Claude Code with workflows on for
accio.

## Development

- **Checks:** `bash git-guardrails/tests/test-guards.sh`; accio's tests from `accio/`
  (`python3 -m unittest discover -s tests` and `node --test 'tests/workflow/**/*.test.mjs'`); and
  `claude plugin validate .` plus `claude plugin validate <plugin>` for each plugin. CI
  (`.github/workflows/test.yml`) runs all of them on every push; accio's skill evals run there only by hand, since
  they spend API credit.
- See [`CLAUDE.md`](CLAUDE.md) for how each plugin is laid out and released.

Licence: MIT (`LICENSE`). Code adapted from upstream keeps its own notice in each plugin's `LICENSE-upstream`.
