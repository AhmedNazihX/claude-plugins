# claude-plugins

A Claude Code plugin marketplace (`nazihx`):

| Plugin | What it does |
| --- | --- |
| [`git-guardrails`](git-guardrails/README.md) | Blocks destructive git commands, asks before every push, keeps secrets out of the transcript and commits |

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins     # from GitHub
# or, from a local clone (for development): claude plugin marketplace add ./claude-plugins
claude plugin install git-guardrails@nazihx
```

The hooks need `jq` and `git`.

Tests: `bash git-guardrails/tests/test-guards.sh`, plus `claude plugin validate .` and
`claude plugin validate git-guardrails`.

Licence: MIT (`LICENSE`). Code adapted from upstream keeps its own notice in each plugin's `LICENSE-upstream`.
