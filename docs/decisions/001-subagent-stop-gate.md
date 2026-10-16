# 001 · Can a SubagentStop hook gate a story-worker?

- **Date:** 2026-10-16
- **Story:** X1 (docs/BACKLOG.md)
- **Status:** accepted (no fork: the design's first choice works; the user can reverse it before R4 starts)

## Question

D9 wants a `SubagentStop` hook that stops a story-worker from finishing, once, when its report is missing or wrong.
That only works if the hook can tell a story-worker apart from other agents, and if blocking it once lets it stop
on the next try. If not, R4 falls back to a check at the top of story-finish § 1. See `docs/DESIGN.md` › Wave 2
(D9) and › Early experiments (X1).

## What the docs say

Source: the Claude Code hooks reference, <https://code.claude.com/docs/en/hooks.md>, fetched 2026-10-16, checked
against Claude Code 2.1.302 (`claude --version`).

Matchers, from › Configuration › Matcher patterns:

> | `SubagentStop` | agent type | same values as `SubagentStart` |

From › SubagentStart:

> For subagents shipped by a plugin, the agent type is the plugin-scoped identifier such as `my-plugin:reviewer`,
> not the bare frontmatter name. The colon places a plugin-scoped name on the regular-expression path, so anchor
> the matcher with `^` and `$` for an exact match: `^my-plugin:reviewer$`.

From › SubagentStop › SubagentStop input:

> In addition to the common input fields, SubagentStop hooks receive `stop_hook_active`, `agent_id`, `agent_type`,
> `agent_transcript_path`, and `last_assistant_message`. The `agent_type` field is the value used for matcher
> filtering. The `transcript_path` is the main session's transcript, while `agent_transcript_path` is the
> subagent's own transcript stored in a nested `subagents/` folder. The `last_assistant_message` field contains
> the text content of the subagent's final response, so hooks can access it without parsing the transcript file.

> A `matcher` that names agent types doesn't match an empty `agent_type`.

> On Claude Code v2.1.271 or later, a subagent that runs with the `SubagentHandback` tool delivers its report
> through that tool before it stops. The `last_assistant_message` field then holds the subagent's closing text, if
> any, which is not the delivered report.

> SubagentStop hooks use the same decision control format as Stop hooks [...] Returning `decision: "block"` with
> a `reason` keeps the subagent running and delivers `reason` to the subagent as its next instruction. A hook that
> blocks by exiting 2 delivers its stderr message the same way.

From › Stop input, on loops:

> The `stop_hook_active` field is `true` when Claude Code is already continuing as a result of a stop hook.

> Claude Code applies an 8-consecutive-continuation cap: after stop hooks have continued the turn eight times in a
> row, Claude Code overrides the next block and ends the turn.

## What a live run showed

A throwaway plugin `x1probe`, outside the repo (in the worker's scratch folder), with two agents (`worker`,
`other`) and two `SubagentStop` hooks: one with matcher `""` that logs every input, and one with matcher
`^x1probe:worker$` that returns `{"decision":"block","reason":"..."}` when `stop_hook_active` is `false` and
nothing otherwise. Three headless runs, each `claude -p --model haiku --permission-mode dontAsk --plugin-dir
<x1-plugin> "<prompt>"`, on Claude Code 2.1.302.

**Run 1** (launch `x1probe:worker`, then `x1probe:other`). The session printed `worker done after gate` and
`other done`. The gate fired twice, both for the worker, and never for `other`:

```
gate fired: agent_type=x1probe:worker stop_hook_active=false
gate fired: agent_type=x1probe:worker stop_hook_active=true
```

The logged inputs (paths shortened: `<projects>` is `~/.claude/projects/<session folder>`, `<scratch>` the
worker's scratch folder; nothing else changed):

```json
{"session_id":"03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7","transcript_path":"<projects>/03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7.jsonl","cwd":"<scratch>/x1-run","prompt_id":"662470fa-1de2-4297-a1ca-ca76d605e197","permission_mode":"dontAsk","agent_id":"a29ef99e9fa30467b","agent_type":"x1probe:worker","effort":{"level":"medium"},"hook_event_name":"SubagentStop","stop_hook_active":false,"agent_transcript_path":"<projects>/03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7/subagents/agent-a29ef99e9fa30467b.jsonl","last_assistant_message":"worker done","background_tasks":[],"session_crons":[]}
{"session_id":"03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7","transcript_path":"<projects>/03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7.jsonl","cwd":"<scratch>/x1-run","prompt_id":"662470fa-1de2-4297-a1ca-ca76d605e197","permission_mode":"dontAsk","agent_id":"a29ef99e9fa30467b","agent_type":"x1probe:worker","effort":{"level":"medium"},"hook_event_name":"SubagentStop","stop_hook_active":true,"agent_transcript_path":"<projects>/03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7/subagents/agent-a29ef99e9fa30467b.jsonl","last_assistant_message":"worker done after gate","background_tasks":[],"session_crons":[]}
{"session_id":"03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7","transcript_path":"<projects>/03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7.jsonl","cwd":"<scratch>/x1-run","prompt_id":"662470fa-1de2-4297-a1ca-ca76d605e197","permission_mode":"dontAsk","agent_id":"aabde499dff8ca635","agent_type":"x1probe:other","effort":{"level":"medium"},"hook_event_name":"SubagentStop","stop_hook_active":false,"agent_transcript_path":"<projects>/03ce35f6-b62b-4ddc-a148-48d1f5d9d8c7/subagents/agent-aabde499dff8ca635.jsonl","last_assistant_message":"other done","background_tasks":[],"session_crons":[]}
```

**Run 2** (the worker launched with `isolation: "worktree"`, from a scratch git repo). Same block-once pattern.
The hook's `cwd` was the subagent's own worktree, named after its `agent_id`:

```json
{"cwd":"<scratch>/x1-run2/.claude/worktrees/agent-aa518d00a599e0aa0","agent_id":"aa518d00a599e0aa0","agent_type":"x1probe:worker","stop_hook_active":false}
{"cwd":"<scratch>/x1-run2/.claude/worktrees/agent-aa518d00a599e0aa0","agent_id":"aa518d00a599e0aa0","agent_type":"x1probe:worker","stop_hook_active":true}
```

**Run 3** (an agent told to report with `SubagentHandback`). The headless session didn't give it that tool, so it
answered in text; the gate blocked it once, and the parent received one result, the text written after the block
(`worker done after gate`). So the parent waits until the gate lets the subagent stop. Whether a block after a
`SubagentHandback` call holds back the report already handed over was **not** tested (see Consequences).

## Options

| Option | What was compared or measured | Result | Source |
| --- | --- | --- | --- |
| A. `SubagentStop` hook in the plugin, matcher `^foreman:story-worker$` | Does the input name the agent type? Does a matcher pick one type? Does block-once work? | Yes to all three: `agent_type` is `x1probe:worker`; `other` never reached the gate; the second stop came with `stop_hook_active: true` and the hook let it go | Docs above; runs 1 and 2 |
| B. Same checks as a step at the top of story-finish § 1 | Catches a bad report only after the worker is gone, so the fix needs a relaunch (`story-start --continue`) | Works, but later and costlier than A | `docs/DESIGN.md` › D9, Risks |

## Decision

R4 builds the hook (option A): `foreman/hooks/report-gate.sh`, registered in `hooks.json` under `SubagentStop`
with matcher `^foreman:story-worker$`, blocking once (only when `stop_hook_active` is `false`). The docs and the
live run both show the hook can tell a story-worker apart and block it exactly once; the design's rule was
"use the hook unless the input can't identify the agent type".

## Consequences

- **R4 finds the story from `cwd`.** With `isolation: "worktree"` the hook's `cwd` is the worker's worktree, so
  `git -C "$cwd"` gives the story branch (`story/<ID>-<slug>`), the head and the status; the main checkout comes
  from `--git-common-dir`, as `worker-guard.sh` does. The report file is
  `<main>/.claude/worktrees/handoffs/<ID>.md` (D8), and `agent_id` can be matched against the header's agent id.
- **R4 reads the report file, not `last_assistant_message`.** Story-workers hand back through `SubagentHandback`,
  and then `last_assistant_message` is not the report (docs quote above).
- **A worker that never renamed its branch** (blocked during setup) has no story ID. The hook should let it stop.
- **Keep the matcher anchored** (`^...$`): a plugin-scoped name with a colon is read as a regular expression.
- **Untested: block after `SubagentHandback`.** If a worker hands back and then gets blocked, the docs don't say
  whether the parent already has the report. R4's test plan should include one interactive run that checks this.
  If the report is already delivered, the block's message should only ask the worker to fix the file, and
  story-finish § 1 should still read the file rather than trust the hand-back line.
- **Revisit** if a Claude Code release drops `agent_type` or `stop_hook_active` from the `SubagentStop` input, or
  changes the plugin-scoped name format. Then fall back to option B.
- Cost of the runs: about $0.03 in all on Haiku (run 2: $0.0070, run 3: $0.0099, from `total_cost_usd`; run 1
  wasn't measured and is of the same size).
