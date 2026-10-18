# accio's skill evals

`claude plugin eval` cases, one folder per skill (DESIGN § 9; decision 006). Free graders only (`regex`,
`tool_used`, `tool_order`, `file_exists`); S-026 wires them into CI with `--max-cost-usd 2`.

Run them from the plugin root:

```bash
PATH="$(xcode-select -p)/usr/bin:$PATH" claude plugin eval . --tag prophecy --tag owl --scaffold --trust-plugin \
  --allow-tools Edit "Bash(*/bin/accio-* *)" --max-cost-usd 2
```

- `--scaffold` runs each case's script: prophecy's `backlog.sh` builds a small git repo with an `.accio/` backlog,
  owl's `after-build.sh` one just after a build. A scaffold script must sit inside its case folder, so the other
  cases of a skill link to the first one's.
- owl's cases never merge: `accio-merge` makes its integration worktree beside the repo, outside the eval's
  workspace, which the sandbox refuses. The merge is covered by `tests/test_merge.py`.
- **macOS:** `/usr/bin/git` is Apple's `xcrun` shim, and inside the eval's OS sandbox it can't write its cache under
  `/var/folders`, so every git call fails. Putting the real binary's folder first on `PATH` (the command above)
  fixes the scripts, `accio-board go`'s commit included (the skill never runs git itself).
- `sort/split` checks a too-big part ends up as small stacked stories. quill usually splits it while writing, so the
  score's split flag (the safety net) rarely fires in a run; that path is in the skill and `tests/test_sort.py`.
- Skills call accio's scripts as `${CLAUDE_PLUGIN_ROOT}/bin/<script>`: the plugin's `bin/` is not on `PATH` in eval
  runs.
- `prophecy/workflows-off` (S-021/6) has its own tag, because it needs the `Workflow` tool taken away for the whole
  run: add `--tag prophecy-workflows-off --disallow-tools Workflow` instead of `--tag prophecy`.
