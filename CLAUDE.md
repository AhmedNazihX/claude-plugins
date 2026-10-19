# claude-plugins

The `nazihx` marketplace: one folder per plugin, each listed in `.claude-plugin/marketplace.json`.

- **`git-guardrails/`:** hooks in `git-guardrails/hooks/`, tests in `git-guardrails/tests/test-guards.sh`.
- **`accio/`:** developed here, like git-guardrails (moved in from its own repo with its history, decision 013 in
  `accio/docs/decisions/`). Its guide is `accio/docs/DESIGN.md` and its backlog `accio/docs/BACKLOG.md`; tests run
  from `accio/` (`python3 tests/run_tests.py`, `node --test 'tests/workflow/**/*.test.mjs'`), and its
  skill evals by hand (`accio/evals/README.md`).
- **Releasing:** `~/Workspace/claude-plugins-release` (the folder Claude Code installs from) pulls this repo's main.
- **Checks:** `bash git-guardrails/tests/test-guards.sh`, accio's tests (above), `claude plugin validate .`, and
  `claude plugin validate <plugin>` for each plugin. CI (`.github/workflows/test.yml`) runs the same.
- **Writing:** plain English, short sentences, no jargon.
