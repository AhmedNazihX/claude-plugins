# 003 · A plugin Stop hook can drive the autopilot loop

- **Date:** 2026-10-16
- **Story:** X3 (docs/BACKLOG.md)
- **Status:** proposed (waiting for the user). Only headless runs were made, autopilot starts from an interactive
  session, and the result departs from the design: X3 assumed the loop stops on `stop_hook_active`, and this record
  rejects that.

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
the repo, `--model haiku`, `--allowedTools Bash` (plus `Agent` for runs 4 to 7). No interactive session was run.
The plugin has one `Stop` hook, registered in its `hooks/hooks.json` as
`bash "${CLAUDE_PLUGIN_ROOT}/hooks/loop.sh"`. The hook:

- reads `x3-state.json` in the session's `cwd` (`iteration`, `max_iterations`, and switches for each run);
- with no state file, exits 0 (the session stops);
- when `iteration >= max_iterations`, renames the state file to `x3-state.done.json` and exits 0;
- otherwise writes `iteration + 1` (temp file, then `mv`) and prints
  `{"decision": "block", "reason": "Loop iteration N of M. Run exactly this Bash command: echo tick N >> ticks.txt ; then reply with the single word: done."}`;
- logs every call, with the hook input's `stop_hook_active`, `background_tasks` and `last_assistant_message`, as
  one JSON line in `x3-hook.log`.

Each run started with the prompt "Reply with the single word: ok." unless the table says otherwise.

**Run 1: four iterations, ending on the state file.** State `{"iteration":0,"max_iterations":4}`. Session
`<session>`, exit 0, `num_turns` 9, result `done`. The hook log:

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
| 5 | As run 4, but the hook exits 0 (no block, no count) while `background_tasks` is not empty; `max_iterations` 3 | Two Stops while work ran in the background (the hook stood aside). The second listed only two `shell` tasks that the subagent had started. The session waited, woke when the subagent reported at 23:39:37 with an empty `background_tasks`, then ran iterations 1 to 3 and stopped on the state file. |
| 6, 7 | Foreground subagent (`run_in_background` false) that waits 45 s | Run 6: the subagent's `sleep 45` was refused by the local harness, so it proved nothing. Run 7 waited with `python3 -c "import time; time.sleep(45)"`: `duration_ms` 61400, no Stop fired during the wait, then iterations 1 to 3 and a clean stop. |
| 8 | `hookSpecificOutput.additionalContext` instead of `decision: "block"`, `max_iterations` 3 | Same loop: iterations 1 to 3, then a stop on the state file. |

All eight runs exited 0. The CLI was signed in with a claude.ai subscription, so no API key was billed.

## Answers

Answers 2 to 4 rest on headless runs only. An interactive session may differ, above all in how a session idles and
wakes for a background subagent (runs 4 and 5) and in `stop_hook_active` resetting on that wake.

1. **Yes.** `decision: "block"` with a `reason` continues the same session, and Claude takes the `reason` as its
   next instruction (runs 1, 3, 5, 7). `additionalContext` works the same way and is labelled as feedback, not as an
   error (run 8).
2. **`stop_hook_active` is a flag, not a counter (headless).** It is `false` on the first Stop of a turn and `true`
   on every Stop after a hook continued that turn (run 1). In run 4 it went back to `false` on the turn that a
   background subagent's report started. So the hook must keep its own count in the state file. Stopping whenever
   `stop_hook_active` is `true` would allow one iteration only.
3. **A foreground subagent wait is fine; a background one is not, unless the hook checks for it (headless).** A
   foreground subagent keeps the turn open, and no Stop fires until it returns (run 7, a 45 s wait). A background
   subagent ends the turn while it works, and Stop fires with it listed in `background_tasks`. If the hook blocks
   then, Claude starts the next step while the subagent still runs (run 4). If the hook stands aside, the session
   waits and wakes when it reports, and the loop picks up (run 5). `story-start` does not say `run_in_background`,
   but the Agent tool of this Claude Code version runs subagents in the background by default; its description in
   this session reads: "Subagents run in the background; you'll be notified when one completes."
4. **Only deleting the state file cancels (headless).** The next Stop finds nothing and lets the session end
   (run 3). Pressing Esc only pauses: the docs say Stop does not run after a user interrupt, so the state file
   survives, and the loop resumes when the user's next turn ends. The cap is a safety net, not a cancel: it ends a
   turn after 8 continuations in a row without a tool call (run 2), and the hook is not told.

## Options

| Option | What was compared or measured | Result | Source |
| --- | --- | --- | --- |
| Plugin `Stop` hook with `decision: "block"` | Run 1: 4 blocks, `stop_hook_active` false, true, true, true; `tick 1` to `tick 4` written; 5th Stop ended on `iteration >= max_iterations` | Works | run 1; runs 3, 5, 7 |
| Plugin `Stop` hook with `additionalContext` | Same loop, shown as feedback rather than an error | Works | run 8; docs "Stop decision control" |
| Stop on `stop_hook_active`, as X3 assumed | `true` from the second Stop of a turn on | One iteration only | run 1 |
| Built-in `/goal` | A session-scoped, prompt-based Stop hook | Not tested: the model, not a script, judges the end, and D17 needs script-checked stop reasons | docs "Stop" (tip) |

## Decision

Go for B4: a plugin `Stop` hook that blocks with a fixed prompt and counts iterations in
`.claude/foreman-autopilot.json`, under the conditions below. The rule that decided it is X3's own question
(docs/DESIGN.md › Early experiments): "Does a plugin `Stop` hook with `decision: block` loop reliably, and stop on
`stop_hook_active`?" It loops reliably; it must not stop on `stop_hook_active`.

**Conditions for B4.** Each is written to be lifted into B4's DoD.

- **B4-1 Count in the state file.** The hook never reads `stop_hook_active` to stop or to count. Test: with
  `stop_hook_active: true` and `iteration` below `max_iterations`, the hook blocks and bumps `iteration`.
- **B4-2 Stand aside while subagents run.** When `background_tasks` has an entry of `type` `subagent`, the hook
  exits 0 without blocking and without bumping `iteration`, and appends a line `waiting: <n> background subagents`
  to the state file's log. Entries of other types (`shell`, `monitor`, and so on) do not count: a subagent's
  leftover shells (run 5) or a long-lived dev server would otherwise stall the loop. The `foreman:ci-watcher` that
  story-finish starts after a push is a subagent, so autopilot waits for it. If `background_tasks` is missing (the
  docs say it is present only "when the task registry is reachable"), the hook stops the loop with the reason
  `no task registry`, because it can't tell idle from busy. `session_crons` is ignored. Tests: one subagent entry
  exits 0 with `iteration` unchanged; only `shell` entries block and bump; a missing `background_tasks` stops with
  `no task registry`.
- **B4-3 Leave a trace when idle.** Every exit records why, in the state file or its log: the stop reason when the
  loop ends, and `waiting: …` when it stands aside. An idle session that nothing wakes then still shows where it
  stopped. Test: each exit path writes its line.
- **B4-4 Tie the state to one session, failing closed.** The autopilot skill writes `session_id` from
  `CLAUDE_CODE_SESSION_ID` when it creates the state file (ralph-loop's `scripts/setup-ralph-loop.sh`, line 144,
  does `session_id: ${CLAUDE_CODE_SESSION_ID:-}`). The hook exits 0 unless the stored `session_id` is non-empty and
  equals the hook input's `session_id`. Note: ralph-loop's `hooks/stop-hook.sh` (lines 30 to 33) skips the check
  when the stored id is empty; B4 must not. Tests: an empty `session_id` exits 0; another session's id exits 0.
  Open for B4: what happens to the id on `/clear` or a resumed session is unknown.
- **B4-5 Validate the state, fail closed.** Each field is type- and range-checked: `iteration`, `max_iterations`
  and `max_stories` are non-negative integers, `deadline` is an ISO 8601 time, `merge_policy` is `integration` or
  `stop-at-ready`. `max_iterations` and `deadline` are required. Any failed check deletes the file and stops.
  Optionally, the limits are capped at the defaults in `.claude/foreman.json`, so a worker that edits the state
  file can't raise them. Tests: one per bad field, and one for each missing required field.
- **B4-6 A constant prompt.** The `reason` is a literal constant ("Run /foreman:next in autopilot mode."). A number
  from the state file goes into it only after the integer check of B4-5; no other state text ever does.
- **B4-7 Keep the cap.** Never set `CLAUDE_CODE_STOP_HOOK_BLOCK_CAP=0`. Bump `iteration` only when blocking, and
  expect it to run one ahead if the cap overrides a block (run 2); each autopilot step calls tools, so this should
  be rare.

**For B5.** The cancel command deletes `.claude/foreman-autopilot.json` and reports the `iteration` it held. It says
that Esc only pauses: the loop resumes when the next turn ends unless the file is deleted.

## Consequences

- **B4:** its Output and DoD take conditions B4-1 to B4-7, with their tests. Whether to answer with
  `decision: "block"` or `additionalContext` is B4's call: both loop; `additionalContext` avoids a hook-error notice
  on every step.
- **B5:** the cancel command as above.
- **Open for B4:** how `budget_usd` would be measured; the Stop input has no cost field (DESIGN.md › Risks already
  leaves it out of B4).
- **Not tested:** an interactive session; more than eight iterations with tool calls (the cap resets on every tool
  call).
- **Revisit when:**
  - B4's DoD includes one interactive run of at least 3 iterations, including a wake by a background subagent.
    Whether that run gates B4 is the user's call.
  - A Claude Code release changes the Stop input (`stop_hook_active`, `background_tasks`), the continuation cap,
    or how background agents wake a session.
