# 003 · A plugin Stop hook can drive the autopilot loop

- **Date:** 2026-10-16
- **Story:** X3 (docs/BACKLOG.md)
- **Status:** accepted (experiment result; B4 is a go, with the conditions under Decision)

## Question

Can a plugin `Stop` hook keep a session going, one step at a time, until a state file says stop? D17's autopilot
(docs/DESIGN.md › Wave 3, D17; › Early experiments, X3) rests on it. We needed four answers:

1. Does `decision: "block"` with a `reason` continue the session?
2. How does `stop_hook_active` behave across iterations?
3. Does a long subagent wait inside a turn get in the way?
4. How is the loop cancelled?

## What the docs say

From the hooks reference, `https://code.claude.com/docs/en/hooks.md`, section "Stop", fetched 2026-10-16:

> Runs when the main Claude Code agent has finished responding. Does not run if the stoppage occurred due to a
> user interrupt. API errors fire StopFailure instead.

> The `stop_hook_active` field is `true` when Claude Code is already continuing as a result of a stop hook. Check
> this value or process the transcript to avoid blocking on a condition that will never resolve.

> Claude Code applies an 8-consecutive-continuation cap: after stop hooks have continued the turn eight times in a
> row, Claude Code overrides the next block and ends the turn. The count of consecutive continuations resets each
> time Claude calls a tool. To raise the cap, set `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP`.

> The `background_tasks` and `session_crons` arrays let hooks distinguish "session is done" from "session is
> paused waiting for background work to wake it back up". Both arrays are present when the task registry is
> reachable and are empty when nothing is in flight or scheduled.

From "Stop decision control":

> | `decision` | `"block"` prevents Claude from stopping. Omit to allow Claude to stop |
> | `reason` | Required when `decision` is `"block"`. Tells Claude why it should continue |
> | `hookSpecificOutput.additionalContext` | Non-error feedback for Claude. The conversation continues so Claude
> can act on it, but unlike `decision: "block"` it is shown in the transcript as hook feedback rather than a hook
> error |

> Use `additionalContext` when the hook is working as designed and giving Claude guidance [...]. It keeps the
> conversation going through the same loop protections as `decision: "block"`, namely the `stop_hook_active` input
> and the 8-consecutive-continuation cap, but the transcript labels it `Stop hook feedback` and no hook error
> notification is shown

From the env-vars page, `https://code.claude.com/docs/en/env-vars.md`:

> `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP` | Maximum number of consecutive times a Stop or SubagentStop hook may block the
> turn from ending before Claude Code overrides it and ends the turn anyway (default: 8). Set to `0` to disable the
> cap.

## The live runs

**Setup.** Claude Code 2.1.302, `claude -p` (headless) with `--plugin-dir` pointing at a throwaway plugin outside
the repo, `--model haiku`, `--allowedTools Bash` (plus `Agent` for runs 4 to 7). The plugin has one `Stop` hook,
registered in its `hooks/hooks.json` as `bash "${CLAUDE_PLUGIN_ROOT}/hooks/loop.sh"`. The hook:

- reads `x3-state.json` in the session's `cwd` (`iteration`, `max_iterations`, and switches for each run);
- with no state file, exits 0 (the session stops);
- when `iteration >= max_iterations`, renames the state file to `x3-state.done.json` and exits 0;
- otherwise writes `iteration + 1` (temp file, then `mv`) and prints
  `{"decision": "block", "reason": "Loop iteration N of M. Run exactly this Bash command: echo tick N >> ticks.txt ; then reply with the single word: done."}`;
- logs every call, with the hook input's `stop_hook_active`, `background_tasks` and `last_assistant_message`, as
  one JSON line in `x3-hook.log`.

Each run started with the prompt "Reply with the single word: ok." unless the table says otherwise.

**Run 1: four iterations, ending on the state file.** State `{"iteration":0,"max_iterations":4}`. Session
`11b58cf8-d969-4c9f-a5a5-4c1f742f034f`, exit 0, `num_turns` 9, result `done`. The hook log:

| Time | Iteration before | `stop_hook_active` | Last message | Hook did |
| --- | --- | --- | --- | --- |
| 23:35:53 | 0 | false | ok | block (iteration 1) |
| 23:35:56 | 1 | true | done | block (iteration 2) |
| 23:35:58 | 2 | true | done | block (iteration 3) |
| 23:36:00 | 3 | true | done | block (iteration 4) |
| 23:36:02 | 4 | true | done | stop: `iteration >= max_iterations`, state file renamed |

`ticks.txt` held `tick 1` to `tick 4`: Claude ran each `reason` as its next instruction.

**The other runs.**

| Run | What it tested | Result |
| --- | --- | --- |
| 2 | No tool calls, `max_iterations` 12: each `reason` says "Do not use any tools. Reply with the single word: again." | 9 blocks logged (iterations 1 to 9); the session ended after the 8th continuation. The 9th block was overridden by the cap, and the hook's state still said `iteration: 9`. |
| 3 | Cancel: at iteration 3 the `reason` says "run `rm x3-state.json`" | Blocks at iterations 1 and 2 (two ticks), then Claude deleted the file; the next Stop found no state and the session ended, result `cancelled`. |
| 4 | Background subagent: the prompt launches a `general-purpose` subagent with `run_in_background` true that waits 60 s; the hook blocks regardless | The first Stop came while the subagent was running (`background_tasks: [{"type":"subagent","status":"running"}]`). The hook blocked twice and Claude ran both iterations while the subagent was still at work. When the subagent reported, the session woke for a new turn, and that turn's Stop had `stop_hook_active: false`. |
| 5 | As run 4, but the hook exits 0 (no block, no count) while `background_tasks` is not empty; `max_iterations` 3 | Two Stops while work ran in the background (the hook stood aside). The session waited, woke when the subagent reported at 23:39:37 with an empty `background_tasks`, then ran iterations 1 to 3 and stopped on the state file. |
| 6, 7 | Foreground subagent (`run_in_background` false) that waits 45 s | Run 6: the subagent's `sleep 45` was refused by the local harness, so it proved nothing. Run 7 waited with `python3 -c "import time; time.sleep(45)"`: `duration_ms` 61400, no Stop fired during the wait, then iterations 1 to 3 and a clean stop. |
| 8 | `hookSpecificOutput.additionalContext` instead of `decision: "block"`, `max_iterations` 3 | Same loop: iterations 1 to 3, then a stop on the state file. |

All eight runs exited 0. Their `total_cost_usd` adds up to $0.091, but the CLI was signed in with a claude.ai
subscription (`claude auth status`: `authMethod: claude.ai`), so no API key was billed.

## Answers

1. **Yes.** `decision: "block"` with a `reason` continues the same session, and Claude takes the `reason` as its
   next instruction (runs 1, 3, 5, 7). `additionalContext` works the same way and is labelled as feedback, not as an
   error (run 8).
2. **`stop_hook_active` is a flag, not a counter.** It is `false` on the first Stop of a turn and `true` on every
   Stop after a hook continued that turn (run 1). It goes back to `false` when the session starts a new turn, for
   example when a background subagent wakes it (runs 4 and 5). So the hook must keep its own count in the state
   file. Stopping whenever `stop_hook_active` is `true` would allow one iteration only.
3. **A foreground subagent wait is fine; a background one is not, unless the hook checks for it.** A foreground
   subagent keeps the turn open, and no Stop fires until it returns (run 7, a 45 s wait). Background agents (which
   is how `story-start` launches workers) end the turn while they work. Stop then fires with `background_tasks`
   listing them. If the hook blocks then, Claude starts the next step while the workers still run (run 4). If the
   hook stands aside, the session waits and wakes when they report, and the loop picks up (run 5).
4. **Cancel by deleting the state file.** The next Stop finds nothing and lets the session end (run 3). Pressing
   Esc also stops a turn, and the docs say Stop does not run after a user interrupt. The cap is a safety net, not a
   cancel: it ends a turn after 8 continuations in a row without a tool call (run 2), and the hook is not told.

## Options

| Option | What was compared or measured | Result | Source |
| --- | --- | --- | --- |
| Plugin `Stop` hook with `decision: "block"` | Loops, stops on a state file, cancels by deletion | Works | runs 1, 3, 5, 7 |
| Plugin `Stop` hook with `additionalContext` | Same loop, shown as feedback rather than an error | Works | run 8; docs "Stop decision control" |
| Built-in `/goal` | A session-scoped, prompt-based Stop hook | Not tested: the model, not a script, judges the end, and D17 needs script-checked stop reasons | docs "Stop" (tip) |
| Headless runner on the Agent SDK | Out of scope for now | Not tested | DESIGN.md › Non-goals |

## Decision

**Go for B4.** A plugin `Stop` hook that blocks with a fixed prompt and counts iterations in
`.claude/foreman-autopilot.json` works, with these conditions:

- **Count in the state file.** Never use `stop_hook_active` to stop or to count.
- **Stand aside while work runs in the background.** When `background_tasks` is not empty, exit 0 without
  blocking and without bumping `iteration`. The session wakes when a worker reports, and the next Stop continues
  the loop. If nothing ever wakes it, the session simply idles: a safe failure.
- **Bump the count only when blocking,** and expect it to run one ahead in a rare case: if 8 continuations in a row
  make no tool call, the cap ends the turn after the hook has already bumped the count (run 2). Each autopilot
  step calls tools, so the cap should not be reached.
- **Tie the state to one session.** Store `session_id` in the state file and exit 0 for any other session. The
  state file is per project, and the Stop hook fires in every session open in it, including `claude -p` runs. The
  `ralph-loop` plugin does the same.
- **Cancel by deleting the state file** (B5's cancel command), and report the iteration it held.

## Consequences

- **B4:** add the background check and the session check to its Output, and a test for each: "background tasks
  running: exit 0, iteration unchanged" and "another session: exit 0". Whether to answer with `decision: "block"`
  or `additionalContext` is B4's call: both loop; `additionalContext` avoids a hook-error notice on every step.
- **B5:** the cancel command deletes the state file and reports its `iteration`.
- **Not tested:** an interactive session (the runs were headless, `claude -p`); the docs describe one Stop event
  for both. Long runs of more than eight iterations with tool calls were not tried either, since the cap resets on
  every tool call.
- **Revisit if** a Claude Code release changes the Stop input (`stop_hook_active`, `background_tasks`), the
  continuation cap, or how background agents wake a session.
