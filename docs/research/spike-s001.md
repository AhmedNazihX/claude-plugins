# Spike S-001: workflow, named agents, worktree (in progress)

Date: 2026-10-17 · Claude Code 2.1.302 · Status: **paused, 2 checks left** (see the end)

**Method.**
- **Probe plugin:** `spike/accio-spike/` (throwaway, not committed). It has:
  - a named agent `probe` (Haiku, with a codeword in its system prompt)
  - a `bin/spike-wt` script that creates a worktree
  - a PreToolUse hook that logs its payload and blocks writes to `forbidden.txt`
  - two workflows, `probe` and `stall`
- **Runs:** each run is a nested `claude -p "/accio-spike:<workflow>" --plugin-dir …` in a scratch git repo.
- **Evidence:** the facts below come from each run's `journal.jsonl`, the agent transcripts, the hook log and
  `git worktree list`, not from the nested model's own summary.

## Findings

| # | Question (DESIGN § 10) | Answer | Evidence |
|---|---|---|---|
| 1 | Can a plugin workflow call the plugin's named agents? | **Yes:** `agent(prompt, {agentType: '<plugin>:<agent>'})`. The agent's own system prompt is used, and `model` in the options is honoured. | run 1: codeword `NIMBUS-7` returned; `agent-*.meta.json` has `"agentType":"accio-spike:probe"`, `"model":"haiku"` |
| 2 | Can agents work in a worktree a script created? | **Yes,** through absolute paths. An agent runs the script through Bash (scripts have no shell). The worktree sat outside the repo on `story/S-999`, and the agent wrote with absolute paths and committed with `git -C`. **The agent's cwd stays in the main repo.** | run 1: commit `2ef8040` on `story/S-999` |
| 3 | `isolation: 'worktree'` in `agent()` | **Works, but not accio's layout.** The worktree goes *inside* the repo at `.claude/worktrees/<runId>-<n>`, on branch `worktree-<runId>-<n>` from main's HEAD. It is **locked**, and it is kept when it has changes. The agent's cwd and the hook's `cwd` are the worktree. | run 1, step d |
| 4 | Does `agent()` report token usage? | **No,** the return value has none. Per-agent usage is in `<transcriptDir>/agent-<id>.jsonl` (each assistant message's `usage`), and the label is in `agent-<id>.meta.json` (`description`). `budget.spent()` gives output tokens for the whole turn only (workflow reference). | run 1 transcripts: e.g. 4 agents at 572–800 output tokens each |
| 5 | Opt-in and permission when the user types `/accio:brew` | Typing the command makes the main loop call the `Workflow` tool with the workflow's name. **In default permission mode the launch waits for approval; headless (`-p`), it hangs instead of failing.** With `--allowedTools Workflow` it launches. The interactive prompt and its "don't ask again" were **not tested**; that needs a human at a terminal. | run 2: no progress after 10+ min, stopped; run 2b: launched |
| 6 | Do agents inside a workflow prompt for tool permissions? | **Yes, in default mode.** A Bash command that needs permission **waits forever**; read-only commands such as `echo` run without asking. In auto mode (the user's setting) everything ran. | run 2b: agent a's Bash call never got a result; run 2c: `echo` ran; run 2c2: `touch` waited |
| 7 | Does `stallMs` end an agent stuck on a permission prompt? | **No.** With `stallMs: 30000`, the agent was still waiting at 240 s. | run 2c2 |
| 8 | Is `bin/` on PATH inside workflow agents? | **Yes.** | run 1: `command -v spike-wt` found the plugin's `bin/spike-wt` |
| 9 | Is `${CLAUDE_PLUGIN_ROOT}` set? | **Not in the agent's Bash environment; set in the hook's environment.** | run 1: `root=UNSET` in Bash; hook log `env_plugin_root_set: true` |
| 10 | Do plugin hooks fire inside workflow agents? | **Yes.** PreToolUse fired on Bash and Write, and exit 2 blocked the Write. The agent reported the block word for word and did not work around it. **The payload includes `agent_id` and `agent_type`** (`accio-spike:probe`), plus `cwd`, `permission_mode`, `transcript_path`, `tool_input`, `tool_name`, `tool_use_id`, `prompt_id`, `effort`, `hook_event_name`, `session_id`. | run 1 hook log |
| 11 | Is `CLAUDECODE=1` set inside workflow agents? | **Yes,** in the agent's Bash environment and in the hook's environment. | run 1 |
| 12 | What does `/accio:brew` do when workflows are disabled? | **Not tested yet.** | — |
| 13 | Do allow rules apply inside workflow agents? | **Not tested yet** (run 2d: default mode plus allow rules for Workflow, Bash, Write and Edit). | — |

## What this means for the design (not applied; for the user to decide)
- **No fallback needed so far.** Named agents and script-made worktrees both work (1, 2). The verdict waits for
  checks 12 and 13.
- **Allow rules are mandatory, and `brew` needs a preflight** (5, 6, 7). Before starting any agent, `brew` must check
  the permission mode or the allow rules. A missing rule doesn't fail: the run hangs, and `stallMs` doesn't catch
  it. This strengthens § 12.1 and adds a step-0 check.
- **`curfew` can't use the hook's `cwd`** with script-made worktrees (2, 10). The cwd is the main repo. The payload
  does carry `agent_type`, so the hook knows when the caller is `accio:house-elf`. To know *which* worktree that is,
  there are two candidates:
  - (a) a small map from `agent_id` to worktree, written when the agent starts. How to learn the id early is open;
    `transcript_path` may lead to it.
  - (b) `isolation: 'worktree'`, so the cwd *is* the worktree. That gives up the design's location (outside the
    repo) and its branch names, unless the agent switches to `story/<ID>` at its base first.
- **Token budgets (§ 8.6):** a live per-story stop at 2× isn't possible (4). This confirms decision 006's fallback:
  the hard stop is `maxTurns`, and `accio-cost` reads `agent-<id>.jsonl` grouped by label.
- **Briefs use absolute paths or PATH, never `${CLAUDE_PLUGIN_ROOT}`** inside agents (8, 9).

## Left to do (resume here)
1. Run 2d: default mode with `--allowedTools Workflow Bash Write Edit`. Does the probe complete as in run 1?
2. Workflows disabled: run with `disableWorkflows` set. What does the user see? (Confirm the setting's exact name
   first.)
3. (Human, optional) Type `/accio-spike:probe` in an interactive session started with
   `claude --plugin-dir spike/accio-spike`, in a scratch repo, and note the permission prompt.
4. Write the verdict, decide the `curfew` mechanism with the user, then delete `spike/`.
