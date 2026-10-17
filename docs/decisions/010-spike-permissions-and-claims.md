# 010 — After spike S-001: accio's hook answers permissions; agents claim their worktree

Date: 2026-10-17 · Status: decided by the user (after spike S-001, verdict GO)

## Context
Spike S-001 (`docs/research/spike-s001.md`) showed:
- A plugin workflow runs accio's named agents in script-made worktrees, and plugin hooks fire inside them. **GO**,
  no fallback needed.
- An agent that reaches a permission prompt in an unattended run **waits forever**, and `stallMs` doesn't end it.
- A PreToolUse hook that answers `permissionDecision: allow` or `deny` replaces the prompt: `allow` runs at once,
  `deny` fails fast with the reason.
- The hook payload names the caller (`agent_id`, `agent_type`). Its `cwd` is the main repo for script-made
  worktrees, and `transcript_path` is the main session's.

## Decision
**D1 — accio's hook answers every permission question for accio's agents.** `curfew` runs on every tool call and
answers only when `agent_type` is `accio:*`. Other callers (the user, the main chat) get no answer from it, and
the normal permission flow applies. The project's `.claude/settings.json` gets no allow rules. The one remaining
approval is the workflow launch itself ("don't ask again", once). Each agent's frontmatter keeps its tool list
short, because a tool `curfew` doesn't answer would fall through to a prompt.

**D1b — an allow list that learns, for `house-elf`.**
- The hook splits a Bash command at `&&`, `;` and `|`. It allows it only when every part starts with a known
  program: the project's checks, git except push, read-only tools, and the project's run/build/test commands, plus
  `agent_allow` from `config.json`.
- Anything it can't read safely (`$(…)`, backticks, `sh -c`, `eval`) is denied.
- A denial becomes a BLOCKED question at `owl`: allow once, allow from now on, or no. "From now on" adds the command
  to `agent_allow`.
- The other agents get an exact list each.

**D2 — `house-elf` claims its worktree.**
- Its first command is `accio-claim <ID>`. `curfew` records that `agent_id` → that story's worktree in
  `run/claims.json`.
- Before the claim, it may not write.
- After the claim, Write/Edit is allowed only inside its worktree, plus `.accio/run/<ID>/`. Bash commands that touch
  files must start with `cd <its worktree> &&` or use `git -C <its worktree>`. A denial names the fix, so the agent
  corrects itself within the turn.
- Worktrees stay as designed: outside the repo, on `story/<ID>`, one per story.

**Settled by the spike's facts:**
- **Workflows off:** the command vanishes. `prophecy` and `map` check for the `Workflow` tool in their tool list
  and point to `brew-by-hand`. `session-start` can only check `CLAUDE_CODE_DISABLE_WORKFLOWS`.
- **Budgets:** `agent()` reports no usage. The 2× stop is `maxTurns`, and `accio-cost` reads `agent-<id>.jsonl`
  grouped by the label in `agent-<id>.meta.json`.
- **Scripts on PATH:** `bin/` is on PATH in workflow agents and `${CLAUDE_PLUGIN_ROOT}` is not set there, so briefs
  give absolute paths.
- **The run lock:** workflow scripts have no file access, so `portkey` takes `run/brew.lock` at step 0
  (`accio-board lock`), and a final `portkey` call in a `finally` block releases it.
- **`brew-by-hand` (S-027):** built only for users who have workflows switched off.

## Options compared
| Topic | Chosen | Rejected, and why |
|---|---|---|
| Permissions (D1) | accio's hook decides for `accio:*` agents | settings allow rules: any command not listed hangs the run, and the rules widen the user's own sessions; both: two places to keep in sync |
| Breadth (D1b) | allow list that learns (fails safe) | deny list: fails open, and it is the command-text arms race decision 004 rejected |
| Worktree identity (D2) | claim step | platform `isolation: 'worktree'`: inside the repo, locked, `worktree-*` branches, and remove/recreate on every fix round and for stacking; any accio worktree: no protection between stories or for the main checkout |

## Consequences
- §12.1 setup no longer proposes allow rules.
- `curfew` grows from a write guard into the permission policy for accio's agents, about 1 story.
- Run 4 tested the hook answer for Bash. The D1 story must also prove it for Write and Edit.
