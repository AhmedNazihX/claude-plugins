# Spike S-015: what freezes a workflow agent, and what a hook can answer

Date: 2026-10-18 · Claude Code 2.1.302 · Status: **done** (applied in S-015)

**Why.** An agent inside a workflow waits forever on a permission question (spike S-001, finding 6). The hooks
docs say the stricter answer wins when hooks disagree (`deny > defer > ask > allow`), and that settings `ask` and
`deny` rules apply whatever a hook answers. So `curfew`'s `allow` can be overruled. The docs also describe a
`PermissionRequest` hook that "runs when Claude Code is about to ask you for permission", which might answer for
the agent. This spike checks what really happens inside a workflow agent.

**Method.**
- **Probe plugin** (throwaway, not committed): a named agent `pr-probe:probe` (Haiku) that runs one command;
  one workflow per case; a hook script on PreToolUse and PermissionRequest that logs each payload. On
  PermissionRequest it answers `deny` (or `allow` in run 2) in the documented `hookSpecificOutput.decision` form.
- **Runs:** `claude -p "/pr-probe:<case>" --plugin-dir … --allowedTools Workflow --permission-mode default` in a
  scratch git repo, stopped after 100 to 240 s.
- **Evidence:** the hook log, the agent transcript (`agent-<id>.jsonl`: did the tool call get a result?), the
  workflow journal, and the files the commands should have made.

## Findings

| # | Case | What happened |
|---|---|---|
| 1 | `touch` with no rule and no hook answer | `PermissionRequest` **fired**, with `agent_id` and `agent_type` (`pr-probe:probe`). Its `deny` **was ignored**: the tool call never got a result and the run hung. |
| 2 | The same, with `PermissionRequest` answering `allow` | **Also ignored:** hung, and the file wasn't made. Inside a workflow agent, a `PermissionRequest` answer has no effect. |
| 3 | Another hook's PreToolUse answers `ask` (`echo ASKME`) | **No freeze.** The agent got the hook's reason back at once, like a deny, and the workflow finished. `PermissionRequest` did not fire. |
| 4 | A settings `ask` rule (`--settings` with `Bash(echo RULE)`) | **Froze.** `PermissionRequest` fired (and its deny was ignored). |
| 5 | Our PreToolUse answers `allow` for Write and Edit | Both ran with no prompt and no `PermissionRequest` (S-015/8: decision 010's finding 14 holds beyond Bash). |

## What this means for `curfew`
- **Answer every call** for accio's agents (decision 010). An unanswered call freezes (1).
- **Another plugin's `ask` hook can't freeze a build** (3). It fails fast with that hook's reason, so it becomes a
  BLOCKED question at `owl` like any deny.
- **A settings `ask` rule freezes a build** (4), and nothing can answer it once it is asked (1, 2). But a hook's
  `deny` beats a rule's `ask`, so `curfew` denies, with the rule named, any call by an accio agent that matches
  an `ask` rule in the user's, project's, local or managed settings. The agent reports BLOCKED instead of
  freezing.
- **`PermissionRequest` is only a detector.** It still fires with the agent's name (1, 4), so `curfew` records
  the agent, tool and command in `run/stuck.json`, and `map` and `owl` can say what froze.
- **Setup warns** about settings `ask` rules, so the user can remove them before a build meets one.
