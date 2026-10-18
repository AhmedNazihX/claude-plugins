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
- Tags: `prophecy`, `owl`, `sort`, `map`, `vow`. The workflows-off cases have their own tags,
  `prophecy-workflows-off` and `map-workflows-off`, run with `--disallow-tools Workflow`.
- `prophecy/workflows-off` (S-021/6) has its own tag, because it needs the `Workflow` tool taken away for the whole
  run: add `--tag prophecy-workflows-off --disallow-tools Workflow` instead of `--tag prophecy`.

## In CI, and the baseline (S-026)

- The `evals` job in `.github/workflows/ci.yml` runs only by hand (`workflow_dispatch`), since it spends API credit:
  the six cases tagged `ci` (one per skill), one run each, free graders only, `--max-cost-usd 2`. It needs the
  `ANTHROPIC_API_KEY` secret. `tests/test_evals.py` keeps the graders free, the cap in place and every skill covered.
- **Baseline, 2026-10-18** (Claude Code 2.1.302, Sonnet under test, run on macOS): the `ci` cases all scored 1.00
  in about 2 minutes for **$0.61**. One run of every case (all tags) costs about **$2** (wand's options case alone
  about $0.40, since wandmaker is Opus).
- **Always-on context:** about **1,864 tokens** for every accio description (`claude --plugin-dir . plugin details
  accio`), within DESIGN § 8.5's target of about 2k.
