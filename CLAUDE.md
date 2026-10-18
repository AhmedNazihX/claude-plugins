# claude-plugins

The `nazihx` marketplace: one folder per plugin, each listed in `.claude-plugin/marketplace.json`.

- **`git-guardrails/`:** hooks in `git-guardrails/hooks/`, tests in `git-guardrails/tests/test-guards.sh`.
- **Published plugins:** a plugin built in its own repo is copied here by that repo's publish script (for accio,
  `scripts/publish.py` in `~/Workspace/Projects/Plugin`). Don't edit a published plugin's folder by hand; change
  its source repo and publish again.
- **Checks:** `bash git-guardrails/tests/test-guards.sh`, `claude plugin validate .`, and
  `claude plugin validate <plugin>` for each plugin. CI (`.github/workflows/test.yml`) runs the same.
- **Writing:** plain English, short sentences, no jargon.
