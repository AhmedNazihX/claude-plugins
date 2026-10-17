# 004 — Safety: layered, judged by effect

Date: 2026-10-17 · Status: decided by the user

## Decision
1. **Native git hooks, installed into each project. These are the main wall.**
   - `pre-commit` scans staged files for secrets. It uses gitleaks when it is installed, and built-in patterns
     otherwise. The built-in patterns are taken from `~/Workspace/claude-mods/secret-guard/hooks/patterns.ts`:
     decode a JWT's role, allow known example values, and never echo the secret.
   - `pre-push` blocks force-push and any direct push to the base branch.
2. **A narrow PreToolUse guard for Bash.** It is an early warning, not the boundary. It blocks a short list of
   clearly destructive commands: `reset --hard`, `clean -f`, `rm -rf` outside the repo, `--no-verify`, changes to
   `core.hooksPath`, and branch deletion. Every block names the safe alternative. When dcg is installed, the guard
   defers to it.
3. **A secret check on Write/Edit content**, so key-shaped values never reach a file.
4. **A one-time override granted by the user,** valid only for that exact command in that folder.

## Why
Foreman's guards matched command text, and every review round found new bypasses: aliases, `--git-dir`, `sh -c`,
`GIT_DIR=`. Git runs its own hooks whatever form the command takes. A narrow list keeps false blocks rare.
Session evidence: git-guardrails blocked a harmless `grep -r` because it *could* read `.env`.

## Options compared
- A, layered by effect (chosen).
- B, reuse git-guardrails as it is: text matching, over-broad.
- C, require dcg plus gitleaks: strong, but every user must install a Rust binary.

## Known limits
- `git commit --no-verify` bypasses the git hooks. The Claude guard blocks that flag.
- A human can still bypass everything. That is intended.
