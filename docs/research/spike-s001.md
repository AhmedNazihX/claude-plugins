# Spike S-001: workflow, named agents, worktree

Date: 2026-10-17 · Claude Code 2.1.302 · Status: **done: verdict GO** (decisions in 010)

**Method.**
- **Probe plugin:** `spike/accio-spike/` (throwaway, not committed). It has:
  - a named agent `probe` (Haiku, with a codeword in its system prompt)
  - a `bin/spike-wt` script that creates a worktree
  - a PreToolUse hook that logs its payload and blocks writes to `forbidden.txt`
  - three workflows: `probe`, `stall` and `policy`
- **Runs:** each run is a nested `claude -p "/accio-spike:<workflow>" --plugin-dir …` in a scratch git repo.
- **Evidence:** the facts below come from each run's `journal.jsonl`, the agent transcripts, the hook log and
  `git worktree list`, not from the nested model's own summary.

## Findings

| # | Question (DESIGN § 10) | Answer | Evidence |
|---|---|---|---|
| 1 | Can a plugin workflow call the plugin's named agents? | **Yes:** `agent(prompt, {agentType: '<plugin>:<agent>'})`. The agent's own system prompt is used, and `model` in the options is honoured. | run 1: codeword `NIMBUS-7` returned; `agent-*.meta.json` has `"agentType":"accio-spike:probe"`, `"model":"haiku"` |
| 2 | Can agents work in a worktree a script created? | **Yes,** through absolute paths. An agent runs the script through Bash (scripts have no shell). The worktree sat outside the repo on `story/S-999`, and the agent wrote with absolute paths and committed with `git -C`. **The agent's cwd stays in the main repo.** | run 1: commit `2ef8040` on `story/S-999` |
| 3 | `isolation: 'worktree'` in `agent()` | **Works, but not accio's layout.** The worktree goes *inside* the repo at `.claude/worktrees/<runId>-<n>`, on branch `worktree-<runId>-<n>` from main's HEAD. It is **locked**, and it is kept when it has changes. The agent's cwd and the hook's `cwd` are the worktree. | run 1, step d |
| 4 | Does `agent()` report token usage? (Correction, S-009 review: each API response is written as several lines that repeat its usage, so count once per `message.id` + `requestId`; the per-agent figures below summed every line and are too high.) | **No,** the return value has none. Per-agent usage is in `<transcriptDir>/agent-<id>.jsonl` (each assistant message's `usage`), and the label is in `agent-<id>.meta.json` (`description`). `budget.spent()` gives output tokens for the whole turn only (workflow reference). | run 1 transcripts: e.g. 4 agents at 572–800 output tokens each |
| 5 | Opt-in and permission when the user types `/accio:brew` | Typing the command makes the main loop call the `Workflow` tool with the workflow's name. **In default permission mode the launch waits for approval; headless (`-p`), it hangs instead of failing.** With `--allowedTools Workflow` it launches. The interactive prompt and its "don't ask again" were **not tested**; that needs a human at a terminal. | run 2: no progress after 10+ min, stopped; run 2b: launched |
| 6 | Do agents inside a workflow prompt for tool permissions? | **Yes, in default mode.** A Bash command that needs permission **waits forever**; read-only commands such as `echo` run without asking. In auto mode (the user's setting) everything ran. | run 2b: agent a's Bash call never got a result; run 2c: `echo` ran; run 2c2: `touch` waited |
| 7 | Does `stallMs` end an agent stuck on a permission prompt? | **No.** With `stallMs: 30000`, the agent was still waiting at 240 s. | run 2c2 |
| 8 | Is `bin/` on PATH inside workflow agents? | **Yes.** | run 1: `command -v spike-wt` found the plugin's `bin/spike-wt` |
| 9 | Is `${CLAUDE_PLUGIN_ROOT}` set? | **Not in the agent's Bash environment; set in the hook's environment.** | run 1: `root=UNSET` in Bash; hook log `env_plugin_root_set: true` |
| 10 | Do plugin hooks fire inside workflow agents? | **Yes.** PreToolUse fired on Bash and Write, and exit 2 blocked the Write. The agent reported the block word for word and did not work around it. **The payload includes `agent_id` and `agent_type`** (`accio-spike:probe`), plus `cwd`, `permission_mode`, `transcript_path`, `tool_input`, `tool_name`, `tool_use_id`, `prompt_id`, `effort`, `hook_event_name`, `session_id`. | run 1 hook log |
| 11 | Is `CLAUDECODE=1` set inside workflow agents? | **Yes,** in the agent's Bash environment and in the hook's environment. | run 1 |
| 12 | What does `/accio:brew` do when workflows are disabled? | **The command doesn't exist.** With `disableWorkflows: true` or `CLAUDE_CODE_DISABLE_WORKFLOWS=1`, the `Workflow` tool and every workflow command vanish, while the plugin and its agents stay loaded. The model just says the command "isn't installed". **A SessionStart hook can't see this:** its payload is only `cwd`, `hook_event_name`, `session_id`, `source`, `transcript_path`, and it sees the env variable but not the setting. **A skill's model can see it,** because the `Workflow` tool is missing from its tool list. | run 3 (setting), run 3b (env variable); names found in the 2.1.302 binary |
| 13 | Do allow rules apply inside workflow agents? | **Yes.** In default mode with `--allowedTools Workflow Bash Write Edit`, the probe completed exactly like run 1. Narrow rules such as `Bash(git commit:*)` were not tested. | run 2d |
| 14 | Can a PreToolUse hook answer the permission question for an agent? | **Yes.** In default mode with no Bash allow rule, a hook returning `permissionDecision: allow` let `touch` run at once (the same command hung in run 2c2). `deny` failed fast, and the agent got the hook's reason and didn't retry. | run 4 |
| 15 | Does the hook payload's `transcript_path` point at the agent's transcript? | **No,** it points at the main session's transcript. The agent is identified only by `agent_id` and `agent_type`. | run 4 hook log |

## Verdict: GO
A plugin workflow can run accio's named agents (1) in worktrees made by accio's own script (2), and the hooks fire
and block inside those agents (10). **No fallback is needed.** `brew-by-hand` (S-027) stays conditional: it only
matters for users who have workflows switched off (12).

## What this means for the design
**Settled by facts (to apply):**
- **Workflows off:** `prophecy` and `map` check for the `Workflow` tool in their own tool list, and point to
  `brew-by-hand` when it is missing. `session-start` checks only `CLAUDE_CODE_DISABLE_WORKFLOWS` (12). This replaces
  "the fallback message comes from the `session-start` hook".
- **Token budgets (§ 8.6):** a live per-story stop at 2× isn't possible (4). The hard stop is `maxTurns`, and
  `accio-cost` reads `agent-<id>.jsonl` grouped by the label in `agent-<id>.meta.json`.
- **Briefs use absolute paths or PATH, never `${CLAUDE_PLUGIN_ROOT}`,** inside agents (8, 9).
- **The workflow launch needs the user's approval once** in default mode ("don't ask again" for a named plugin
  workflow); a headless run needs `--allowedTools Workflow` (5).

**Open, for the user to decide:**
- **D1, permissions for accio's agents.** Without a rule, an agent hangs on a prompt and `stallMs` doesn't catch it
  (6, 7). Allow rules in settings fix it (13). So would accio's own PreToolUse hook answering `allow` or `deny` for
  `accio:*` agents (14), which means no prompt and no hang, ever.
- **D2, how `curfew` knows an agent's worktree.** The hook's `cwd` is the main repo for script-made worktrees (2),
  and `transcript_path` is the main session's (15). Candidates:
  - (a) the agent's first command is `accio-claim <ID>`, so the hook links its `agent_id` to that worktree
  - (b) `isolation: 'worktree'`, so the cwd is the worktree (3), but it sits inside the repo with its own branch names
  - (c) `house-elf` may write in any accio worktree (weaker)

## Closed
- D1, D1b and D2 were decided by the user: decision 010. They are applied in `DESIGN.md` and `docs/BACKLOG.md`.
- The interactive permission prompt (typing the command in a live session) was not tried by hand. That is
  optional; the documented behaviour is one prompt per run, with "don't ask again" for named plugin workflows.
- The probe plugin `spike/` was deleted. This report and the run evidence summarised above are what remain.
