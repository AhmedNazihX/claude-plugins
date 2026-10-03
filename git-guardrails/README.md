# git-guardrails

Two PreToolUse hooks for Claude Code:

- **Git guard** (`hooks/block-dangerous-git.sh`, Bash): blocks force pushes (`--force`, `--force-with-lease`, `-f`,
  `+refspec`), `reset --hard`, `clean -f`, `branch -D` and `checkout .`/`restore .`; asks the user before any other
  `git push`.
- **Secrets guard** (`hooks/block-secrets.sh`, Read/Write/Edit/MultiEdit/NotebookEdit/Bash): blocks reading or
  editing secrets files (`.env`, `.env.*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, SSH keys, `credentials.json`,
  `service-account*.json`; templates such as `.env.example` are allowed), writing real-looking API keys into files,
  shell commands that print a secrets file, and staging or committing secrets. Copying or linking `.env` (to set up
  a worktree) is allowed.

  Searches that would read `.env` are blocked too, with the fix in the message: a recursive grep without
  `--exclude='.env*'` (including `rgrep`, GNU `ggrep` and `zgrep`/`bzgrep`/`xzgrep`), an `rg` over hidden or ignored
  files without `-g '!.env*'`, and `find` handing files to a reader (`| xargs grep`, `-exec cat`) unless it excludes
  `.env` by name or keeps to code files, with no `-o`. A disguised command word (`"grep"`, `\grep`, `gr''ep`) is
  still seen, and a `<<` inside quotes (`echo "<<EOF"`) is not taken for a heredoc.

  Only `.env*` or `*.env*` counts as excluding env files (`*environment*` or `dev.env` doesn't), and only an rg glob
  of `!.env*` or `!*.env*`. An `--include` or `find -name` makes a search safe only when every pattern is a code or
  docs file type (`*.ts`, `*.py`, `*.md`, …): `*`, `*.*` or `*.local` also match `.env` files.

  The secrets guard fails closed: a tool call it can't read, or a command its heredoc stripper can't process, is
  blocked rather than allowed.

The hooks guard only Claude's own tool calls. For commits made outside Claude, add a git pre-commit hook and a CI
check such as `gitleaks`.

## Install

```bash
claude plugin marketplace add AhmedNazihX/claude-plugins     # from GitHub
# or, from a local clone (for development): claude plugin marketplace add ./claude-plugins
claude plugin install git-guardrails@nazihx
```

If the same hooks are already installed globally (`~/.claude/hooks/block-*.sh` in `~/.claude/settings.json`),
remove those entries, or each hook runs twice (and a push asks twice).

## Tests

```bash
bash tests/test-guards.sh
```

## Credits

Based on the `git-guardrails-claude-code` skill from Matt Pocock's skills collection (MIT, see
`LICENSE-upstream`), extended with the secrets guard. Changes: packaged as plugin hooks; a key-file name must have a
basename before its extension, so jq's `.key` field no longer counts as a key file.

This plugin is MIT-licensed (`LICENSE`).
