# accio's skill evals

`claude plugin eval` cases, one folder per skill (DESIGN § 9; decision 006). Free graders only (`regex`,
`tool_used`, `tool_order`, `file_exists`); S-026 wires them into CI with `--max-cost-usd 2`.

Run them from the plugin root:

```bash
PATH="$(xcode-select -p)/usr/bin:$PATH" claude plugin eval . --tag prophecy --scaffold --trust-plugin \
  --allow-tools "Bash(*/bin/accio-board *)" "Bash(git add *)" "Bash(git commit *)" --max-cost-usd 2
```

- `--scaffold` runs each case's `backlog.sh`, which builds a small git repo with an `.accio/` backlog. A scaffold
  script must sit inside its case folder, so `go/backlog.sh` is a symlink to `propose/backlog.sh`.
- **macOS:** `/usr/bin/git` is Apple's `xcrun` shim, and inside the eval's OS sandbox it can't write its cache under
  `/var/folders`, so every git call fails. Putting the real binary's folder first on `PATH` (the command above)
  fixes the scripts. The Claude under test still runs `git commit` through its own shell and may hit the shim:
  the `commits` grader only checks the command was run after `accio-board go`, not that it succeeded.
- Skills call accio's scripts as `${CLAUDE_PLUGIN_ROOT}/bin/<script>`: the plugin's `bin/` is not on `PATH` in eval
  runs.
- Not covered by a case: prophecy with workflows off (S-021/6). Check it by hand, or run a case with
  `--disallow-tools Workflow`.
