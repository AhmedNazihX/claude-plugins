# claude-plugins

A Claude Code plugin marketplace (`nazihx`) with two plugins:

| Plugin | What it does |
| --- | --- |
| [`foreman`](foreman/README.md) | Idea → design → backlog → parallel worktree agents, verified and reviewed before every merge |
| [`git-guardrails`](git-guardrails/README.md) | Blocks destructive git commands, asks before every push, keeps secrets out of the transcript and commits |

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins     # from GitHub
# or, from a local clone (for development): claude plugin marketplace add ./claude-plugins
claude plugin install foreman@nazihx
```

`foreman` depends on `git-guardrails`, so installing it installs both. The hooks need `jq` and `git`;
`foreman`'s backlog script needs `python3` (standard library only).

Tests: `python3 -m unittest discover -s foreman/tests`, `bash foreman/hooks/test-guards.sh`,
`bash foreman/hooks/test-format.sh`,
`bash foreman/hooks/test-doc-guard.sh`, `bash git-guardrails/tests/test-guards.sh`, and `claude plugin validate`
on the root and each plugin.

Licence: MIT (`LICENSE`). Code adapted from upstream keeps its own notice in each plugin's `LICENSE-upstream`.
